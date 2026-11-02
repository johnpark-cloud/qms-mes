import datetime
import io
import json
import logging
import os
import zipfile
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from core.models import Item, Lot, Nonconformance, is_approver
from core.views import _get_record

from . import kpi, spc
from .due import due_items
from .memo import ATTACHABLE, TARGETS, MemoForm, box_context, resolve_target, target_url, todays_audit
from .models import Capa, Characteristic, DashboardLayout, ExcelTemplate, Gauge, Inspection, InspectionSpec, Memo, MemoPhoto
from .overview import sections as overview_sections
from .rules import RECEIVE_MSG, measurement, receive_lot, submit_inspection
from .widgets import COLS, ROWS, SIZES, WIDGETS, layout_for


@staff_member_required
def excel_report(request, template_id, pk):
    tpl = get_object_or_404(ExcelTemplate, pk=template_id)
    model, obj = _get_record(tpl.target.app_label, tpl.target.model, pk)  # 개인 자료(급여·연차)는 막는다
    if not request.user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}'):
        raise PermissionDenied
    resp = HttpResponse(tpl.fill(obj), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = content_disposition_header(True, f'{tpl.name}_{pk}.xlsx')
    return resp


@staff_member_required
def todo(request):
    """내 할 일: 사용자별 위젯 배치(qms.widgets). 계산은 qms.due 한 번을 위젯이 나눠 쓴다."""
    d = due_items(approver=is_approver(request.user), user=request.user)
    d['claims_overdue'] = sum(c.overdue for c in d['claims'])
    d['capas_late'] = sum(c.status == '기한 초과' for c in d['capas'])
    widgets = []
    for w in layout_for(request.user):
        widget = WIDGETS[w['key']]
        try:
            html = render_to_string(widget.template, {**d, 'title': widget.title, 'size': w['size'],
                                                      **widget.context(request, d, w['size'])})
        except Exception:  # 위젯 하나가 깨져도 첫 화면은 떠야 한다
            logging.getLogger('qms').exception('위젯 불러오기 실패: %s', widget.key)
            html = None
        widgets.append({**w, 'title': widget.title, 'html': html})
    available = [(k, w.title) for k, w in WIDGETS.items() if w.allowed(request.user)]
    return render(request, 'qms/todo.html', {'title': '내 할 일', 'widgets': widgets, 'available': available})


@staff_member_required
def overview(request):
    return render(request, 'qms/overview.html', {'title': '공장 종합현황', 'sections': overview_sections(request.user)})


@staff_member_required
@require_POST
def dashboard_save(request):
    """본문 JSON [{key, size, x, y}]로 내 배치를 저장한다. x·y(격자 칸)는 없어도 된다. 빈 배열이면 저장값을 지워 기본 배치로 돌아간다."""
    try:
        items = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest('배치 형식이 올바르지 않습니다.')
    ok = isinstance(items, list) and all(
        isinstance(w, dict) and isinstance(w.get('key'), str) and w['key'] in WIDGETS
        and WIDGETS[w['key']].allowed(request.user) and w.get('size') in SIZES
        and all(k not in w or (type(w[k]) is int and 0 <= w[k] < n) for k, n in (('x', COLS), ('y', ROWS))) for w in items)
    if not ok or len({w['key'] for w in items}) != len(items):
        return HttpResponseBadRequest('저장할 수 없는 위젯 배치입니다.')
    if items:
        DashboardLayout.objects.update_or_create(user=request.user, defaults={
            'widgets': [{'key': w['key'], 'size': w['size'], **{k: w[k] for k in ('x', 'y') if k in w}} for w in items]})
    else:
        DashboardLayout.objects.filter(user=request.user).delete()
    return JsonResponse({'ok': True})


def _months(request):
    try:
        return min(max(int(request.GET.get('months', 6)), 1), 36)
    except ValueError:
        return 6


def _need(request, perm):
    if not request.user.has_perm(perm):
        raise PermissionDenied


@staff_member_required
def kpi_view(request):
    # shortcut: 화면 권한이 클레임 보기 하나라 수율만 볼 부서도 이 권한이 필요하다, 생산 부서를 추가할 때 영역별 권한으로 나눈다
    _need(request, 'qms.view_customerclaim')  # PPM·COPQ는 클레임·비용 자료라 검사원에게는 보이지 않는다
    months = _months(request)
    show = {area: kpi.can_see(request.user, area) for area in kpi.KPI_DEPARTMENTS}  # 소속 부서 KPI만
    rows, pareto = (kpi.monthly(months), kpi.pareto(months)) if show['quality'] else ([], [])
    for key in ('ppm', 'copq'):  # 막대 길이(%)는 기간 내 최댓값 기준
        top = max((float(r[key] or 0) for r in rows), default=0) or 1
        for r in rows:
            r[f'{key}_bar'] = float(r[key] or 0) / top * 100
    return render(request, 'qms/kpi.html', {'title': '품질 KPI', 'months': months, 'rows': rows, 'show': show,
                                             'pareto': pareto, 'yields': kpi.process_yield(months) if show['yield'] else []})


@staff_member_required
def suppliers_view(request):
    _need(request, 'qms.view_scar')
    months = _months(request)
    return render(request, 'qms/suppliers.html', {'title': '협력사 성적표', 'months': months,
                                                   'rows': kpi.suppliers(months)})


# ---------- 검사원 전용 입력 화면 (htmx: 화면 일부만 서버에서 다시 그린다) ----------

def _can_inspect(request):
    if not request.user.has_perm('qms.add_inspection'):
        raise PermissionDenied


@staff_member_required
def inspect_home(request):
    _can_inspect(request)
    return render(request, 'qms/inspect.html', {'title': '검사 입력', 'number': request.GET.get('lot', '').strip()})


DEFECT_TYPES = ['파손', '찍힘·스크래치', '이물', '인쇄', 'Burr', '도장', '용접', '부품 누락', '납땜', '치수', '기능', '조립성', '기타']


def _lot_step(request, lot, number, error=None):
    """LOT 화면. 없는 LOT이면 그 자리에서 입고 등록할 수 있게 품목·협력사 목록을 준다."""
    ctx = {'lot': lot, 'number': number, 'error': error}
    if lot:
        ctx['specs'] = [s for t, _ in InspectionSpec.TYPES if (s := InspectionSpec.current(lot.item, t))]
    elif request.user.has_perm('core.add_lot'):
        with_spec = InspectionSpec.objects.filter(approved_at__isnull=False).values('item')
        ctx['items'] = Item.objects.filter(pk__in=with_spec).order_by('code')
        ctx['suppliers'] = (Lot.objects.exclude(supplier='').order_by('supplier')
                            .values_list('supplier', flat=True).distinct())
    return render(request, 'qms/inspect_lot.html', ctx)


@staff_member_required
def inspect_lot(request):
    """LOT 스캔 → 품번·보류 상태와 검사할 수 있는 검사구분(승인된 현재 기준)."""
    _can_inspect(request)
    number = request.GET.get('lot', '').strip()
    return _lot_step(request, Lot.objects.filter(number=number).select_related('item').first(), number)


@staff_member_required
@require_POST
def inspect_receive(request):
    """입고 등록: 처음 들어온 자재 LOT을 만들고 바로 검사 화면으로 잇는다."""
    _can_inspect(request)
    if not request.user.has_perm('core.add_lot'):
        raise PermissionDenied
    p = request.POST
    number = p.get('number', '').strip()
    item = Item.objects.filter(pk=p.get('item') or None).first()
    try:
        lot, created = receive_lot(number, item, p.get('qty', ''), p.get('supplier', ''))
    except ValidationError:
        return _lot_step(request, None, number, RECEIVE_MSG)
    return _lot_step(request, lot, number, None if created else '이미 등록된 LOT입니다. 기존 LOT으로 검사합니다.')


@staff_member_required
def inspect_form(request, lot_id, spec_id):
    _can_inspect(request)
    lot, spec = get_object_or_404(Lot, pk=lot_id), get_object_or_404(InspectionSpec, pk=spec_id, approved_at__isnull=False)
    gauges = [g for g in Gauge.objects.filter(active=True) if g.usable_on(timezone.localdate())]
    return render(request, 'qms/inspect_form.html', {'lot': lot, 'spec': spec, 'chars': spec.characteristics.all(),
                                                     'gauges': gauges, 'defect_types': DEFECT_TYPES})


@staff_member_required
def inspect_check(request, char_id):
    """값을 입력하는 즉시 항목별 합부를 보여준다 (저장하지 않음)."""
    _can_inspect(request)
    char = get_object_or_404(Characteristic, pk=char_id)
    m = measurement(char, request.POST.get(f'c{char.pk}', ''))
    if m is None:
        return HttpResponse('')
    return HttpResponse(format_html('<span class="status status--{}">{}</span>',
                                    'positive' if m.passed else 'negative', '합격' if m.passed else '규격 이탈'))


@staff_member_required
def inspect_submit(request, lot_id, spec_id):
    """판정: 검사·측정값을 만들고 finalize()로 판정한다. 하나라도 거부되면 전부 되돌린다."""
    _can_inspect(request)
    if request.method != 'POST':
        raise PermissionDenied
    lot, spec = get_object_or_404(Lot, pk=lot_id), get_object_or_404(InspectionSpec, pk=spec_id)
    gauge = Gauge.objects.filter(pk=request.POST.get('gauge') or None).first()
    values = {c.pk: request.POST.get(f'c{c.pk}', '') for c in spec.characteristics.all()}
    error = None
    try:
        insp = submit_inspection(lot, spec, request.user, gauge, values,
                                 request.POST.get('defect_type', ''), request.POST.get('defect_qty'))
    except ValidationError as e:
        error, insp = ' '.join(e.messages), None
    return render(request, 'qms/inspect_result.html', {'insp': insp, 'error': error, 'lot': lot})


@staff_member_required
def spc_view(request, char_id):
    _need(request, 'qms.view_measurement')
    char = get_object_or_404(Characteristic.objects.select_related('spec__item'), pk=char_id)
    ctx = {'title': f'SPC · {char.spec.item.code} {char.name}', 'char': char}
    try:
        res = spc.control_chart(char.spc_series(limit=100), char.lsl, char.usl)
    except ValueError as e:
        ctx['error'] = str(e)
        return render(request, 'qms/spc.html', ctx)
    lim, pts = res['limits'], res['points']
    lo = min([lim['lcl']] + [p['xbar'] for p in pts])
    hi = max([lim['ucl']] + [p['xbar'] for p in pts])
    span = (hi - lo) or 1
    W, H, PAD = 720, 240, 30
    y = lambda v: PAD + (hi - v) / span * (H - 2 * PAD)
    x = lambda i: PAD + i * (W - 2 * PAD) / max(len(pts) - 1, 1)
    for i, p in enumerate(pts):
        p['x'], p['y'] = x(i), y(p['xbar'])
        if p['alarms']:
            insp = p['label']
            p['nc_url'] = reverse('admin:core_nonconformance_add') + '?' + urlencode({
                'lot': insp.lot_id, 'description': f'SPC 경보 {char.name}: {", ".join(p["alarms"])} (검사 {insp.pk})'})
    ctx.update(res=res, W=W, H=H, polyline=' '.join(f"{p['x']:.1f},{p['y']:.1f}" for p in pts),
               lines=[(name, y(lim[key])) for name, key in (('UCL', 'ucl'), ('CL', 'cl'), ('LCL', 'lcl'))])
    return render(request, 'qms/spc.html', ctx)


# ---------- 현장 메모 ----------

def _memo_target(request):
    """?ct=app_label.model&id=pk → 대상 기록. ct가 없으면 미분류(None)."""
    key = request.GET.get('ct')
    if not key:
        return None
    try:
        app_label, model = key.split('.')
        ct = ContentType.objects.get_by_natural_key(app_label, model)
        pk = int(request.GET.get('id', ''))
    except (ValueError, ContentType.DoesNotExist):
        raise Http404
    if key not in ATTACHABLE or ct.model_class() is None:
        raise Http404
    if not request.user.has_perm(f'{app_label}.view_{model}'):
        raise PermissionDenied
    return get_object_or_404(ct.model_class(), pk=pk)


def _memo_save(request, form, target):
    """저장 후 htmx면 메모 상자를 다시 그리고, 미분류면 미분류함으로 보낸다."""
    with transaction.atomic():
        memo = form.save(commit=False)
        if not memo.pk:
            memo.author, memo.target = request.user, target
        memo.save()
        for f in form.cleaned_data['photos']:
            MemoPhoto.objects.create(memo=memo, file=f)
    if memo.target is None or not request.headers.get('HX-Request'):
        messages.success(request, '메모를 저장했습니다.')
        return redirect(target_url(memo.target) if memo.target else 'memo_inbox')
    resp = render(request, 'qms/memo_list.html', box_context(memo.target, request.user))
    resp['HX-Retarget'], resp['HX-Reswap'] = '#memo-box', 'outerHTML'
    return resp


def _memo_form(request, form):
    hx = bool(request.headers.get('HX-Request'))
    ctx = {'form': form, 'action': request.get_full_path(), 'hx': hx, 'title': '메모'}
    return render(request, 'qms/memo_form.html#form' if hx else 'qms/memo_form.html', ctx)


@staff_member_required
def memo_new(request):
    if not request.user.has_perm('qms.add_memo'):
        raise PermissionDenied
    target = _memo_target(request)
    form = MemoForm(request.POST or None, request.FILES or None, initial={'audit': todays_audit(timezone.localdate())})
    if request.method == 'POST' and form.is_valid():
        return _memo_save(request, form, target)
    return _memo_form(request, form)


@staff_member_required
def memo_edit(request, pk):
    memo = get_object_or_404(Memo, pk=pk)
    if memo.author_id != request.user.pk:
        raise PermissionDenied('메모는 작성자만 수정할 수 있습니다.')
    form = MemoForm(request.POST or None, request.FILES or None, instance=memo)
    if request.method == 'POST' and form.is_valid():
        return _memo_save(request, form, memo.target)
    return _memo_form(request, form)


@staff_member_required
def memo_inbox(request):
    """미분류 메모: 종류 + 번호로 대상 기록을 찾아 연결한다 (작성자 또는 메모 수정 권한자)."""
    if not request.user.has_perm('qms.view_memo'):
        raise PermissionDenied
    if request.method == 'POST':
        memo_id = request.POST.get('memo', '')
        if not memo_id.isdigit():
            raise Http404
        memo = get_object_or_404(Memo, pk=memo_id, content_type__isnull=True)
        if memo.author_id != request.user.pk and not request.user.has_perm('qms.change_memo'):
            raise PermissionDenied('메모는 작성자나 메모 수정 권한자만 연결할 수 있습니다.')
        kind, number = request.POST.get('kind', ''), request.POST.get('number', '').strip()
        target = resolve_target(kind, number, request.user)
        if target is None:
            messages.error(request, f'{kind} "{number}": 찾을 수 없습니다. 종류와 번호를 확인하세요.')
        else:
            memo.target = target
            memo.save()
            messages.success(request, f'{kind} {target}에 연결했습니다.')
        return redirect('memo_inbox')
    memos = Memo.objects.filter(content_type__isnull=True).select_related('author', 'audit').prefetch_related('photos')
    return render(request, 'qms/memo_inbox.html', {'title': '미분류 메모', 'memos': memos, 'kinds': TARGETS})



# ---------- 심사 자료 출력 ----------

PACK_LIMIT = 500


def _pack_data(request):
    """품번·기간 조건으로 묶음에 들어갈 기록을 모은다. 보는 권한이 없는 절은 None으로 둔다."""
    from core.models import Item, Nonconformance
    from .models import Capa, ChangeRequest, ControlPlan, CustomerClaim, PpapElement, Scar
    u, today, errors = request.user, timezone.localdate(), []
    base = {'from': today - datetime.timedelta(days=90), 'to': today}
    day = {}
    for key, default in base.items():
        raw = (request.GET.get(key) or '').strip()
        try:
            day[key] = datetime.date.fromisoformat(raw) if raw else default
        except ValueError:
            errors.append(f'날짜 형식이 올바르지 않습니다: {raw} (예: 2026-10-27)')
            day[key] = default
    if day['from'] > day['to']:
        errors.append('시작일이 종료일보다 늦습니다. 기본 기간(최근 90일)으로 보여 줍니다.')
        day = base
    pk = request.GET.get('item') or ''
    item = Item.objects.filter(pk=pk).first() if pk.isdigit() else None
    d = {'items': Item.objects.order_by('code'), 'item': item, 'from': day['from'], 'to': day['to'],
         'errors': errors, 'limit': PACK_LIMIT, 'truncated': False}
    if item is None:
        return d

    def cap(qs):
        rows = list(qs[:PACK_LIMIT + 1])  # shortcut: 앞 500건만, 기간을 줄여 다시 조회하게 한다
        d['truncated'] |= len(rows) > PACK_LIMIT
        return rows[:PACK_LIMIT]

    def between(field):
        return {f'{field}__date__gte': day['from'], f'{field}__date__lte': day['to']}

    types = dict(InspectionSpec.TYPES)
    summary = {}
    for t, result in Inspection.objects.filter(lot__item=item, **between('inspected_at')) \
            .values_list('spec__inspection_type', 'result'):
        s = summary.setdefault(t, {'label': types.get(t, t), 'total': 0, 'passed': 0})
        s['total'] += 1
        s['passed'] += result == Inspection.PASS
    for s in summary.values():
        s['rate'] = round(s['passed'] * 100 / s['total'], 1)
    d['summary'] = list(summary.values())
    ncs = cap(Nonconformance.objects.filter(lot__item=item, **between('detected_at'))
              .select_related('lot', 'approved_by').prefetch_related('photos').order_by('detected_at'))
    d['ncs'] = ncs
    nc_ids = [n.pk for n in ncs]
    can = lambda m: u.has_perm(f'qms.view_{m}')
    ct = ContentType.objects.get_for_model
    d['claims'] = list(CustomerClaim.objects.filter(nonconformance_id__in=nc_ids)) if can('customerclaim') else None
    d['scars'] = list(Scar.objects.filter(nonconformance_id__in=nc_ids)) if can('scar') else None
    if can('capa'):
        q = Q(source_type=ct(Nonconformance), source_id__in=nc_ids)
        if d['claims']:
            q |= Q(source_type=ct(CustomerClaim), source_id__in=[c.pk for c in d['claims']])
        d['capas'] = list(Capa.objects.filter(q))
    else:
        d['capas'] = None
    d['changes'] = cap(ChangeRequest.objects.filter(item=item, **between('effective_at'))
                       .order_by('effective_at')) if can('changerequest') else None
    d['plan'], d['plan_lines'], d['can_plan'] = None, [], can('controlplan')
    if can('controlplan'):
        d['plan'] = ControlPlan.objects.filter(item=item, approved_at__isnull=False).order_by('-approved_at').first()
        d['plan_lines'] = list(d['plan'].lines.select_related('process')) if d['plan'] else []
    # 문서는 품번에 직접 묶이지 않아, 이 품번 PPAP 요소가 인용한 문서의 유효본만 모은다
    d['doc_revisions'] = []
    if can('documentrevision'):
        docs = {e.document for e in PpapElement.objects.filter(submission__item=item, document__isnull=False)
                .select_related('document')}
        d['doc_revisions'] = [r for r in (doc.current_revision for doc in docs) if r]
    d['memos'] = None
    if can('memo'):
        pairs = [(Nonconformance, nc_ids), (Lot, {n.lot_id for n in ncs}), (Item, [item.pk]),
                 (Capa, [c.pk for c in d['capas'] or []]), (CustomerClaim, [c.pk for c in d['claims'] or []]),
                 (Scar, [s.pk for s in d['scars'] or []])]
        q = Q(pk__in=[])
        for model, ids in pairs:
            q |= Q(content_type=ct(model), object_id__in=list(ids))
        d['memos'] = cap(Memo.objects.filter(q).select_related('author').prefetch_related('photos').order_by('created_at'))
    return d


def _pack_allowed(request):
    u = request.user
    if not (u.has_perm('core.view_nonconformance') and u.has_perm('qms.view_inspection')):
        raise PermissionDenied


@staff_member_required
def audit_pack(request):
    _pack_allowed(request)
    return render(request, 'qms/audit_pack.html', {'title': '심사 자료 출력', 'obj': '', **_pack_data(request)})


@staff_member_required
def audit_pack_zip(request):
    _pack_allowed(request)
    d = _pack_data(request)
    if d['item'] is None:
        raise Http404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:  # 사진은 이미 압축 포맷이라 저장만 한다
        def add(field, name):
            try:  # 디스크에서 사라진 파일은 건너뛴다. 이름은 기록 번호+순번으로만 만든다
                z.write(field.path, name + os.path.splitext(field.name)[1].lower())
            except (OSError, ValueError):
                pass
        for n in d['ncs']:
            for i, p in enumerate(n.photos.all(), 1):
                add(p.file, f'부적합/{n.number}_{i}')
        for m in d['memos'] or []:
            for i, p in enumerate(m.photos.all(), 1):
                add(p.file, f'메모/메모{m.pk}_{i}')
        for r in d['doc_revisions']:
            add(r.file, f'문서/{r.document.number}_Rev{r.revision}')
    name = f"audit_{d['item'].code}_{d['from']}_{d['to']}.zip"
    return HttpResponse(buf.getvalue(), content_type='application/zip',
                        headers={'Content-Disposition': f'attachment; filename="{name}"'})
