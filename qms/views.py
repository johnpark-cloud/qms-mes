from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from core.models import Lot, is_approver

from . import kpi, spc
from .due import due_items
from .memo import ATTACHABLE, TARGETS, MemoForm, box_context, resolve_target, target_url, todays_audit
from .models import Characteristic, ExcelTemplate, Gauge, Inspection, InspectionSpec, Measurement, Memo, MemoPhoto


@staff_member_required
def excel_report(request, template_id, pk):
    tpl = get_object_or_404(ExcelTemplate, pk=template_id)
    model = tpl.target.model_class()
    if not request.user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}'):
        raise PermissionDenied
    obj = get_object_or_404(model, pk=pk)
    resp = HttpResponse(tpl.fill(obj), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f"attachment; filename*=UTF-8''{tpl.name}_{pk}.xlsx".replace(' ', '_')
    return resp


@staff_member_required
def todo(request):
    """내 할 일: 기한 임박·초과 항목, 승인 대기, 열린 부적합, 보류 LOT (계산은 qms.due)."""
    d = due_items(approver=is_approver(request.user))
    d['claims_overdue'] = sum(c.overdue for c in d['claims'])
    d['capas_late'] = sum(c.status == '기한 초과' for c in d['capas'])
    return render(request, 'qms/todo.html', {'title': '내 할 일', **d})


def _months(request):
    try:
        return min(max(int(request.GET.get('months', 6)), 1), 36)
    except ValueError:
        return 6


@staff_member_required
def kpi_view(request):
    months = _months(request)
    rows = kpi.monthly(months)
    for key in ('ppm', 'copq'):  # 막대 길이(%)는 기간 내 최댓값 기준
        top = max((float(r[key] or 0) for r in rows), default=0) or 1
        for r in rows:
            r[f'{key}_bar'] = float(r[key] or 0) / top * 100
    return render(request, 'qms/kpi.html', {'title': '품질 KPI', 'months': months, 'rows': rows,
                                             'pareto': kpi.pareto(months), 'yields': kpi.process_yield(months)})


@staff_member_required
def suppliers_view(request):
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


@staff_member_required
def inspect_lot(request):
    """LOT 스캔 → 품번·보류 상태와 검사할 수 있는 검사구분(승인된 현재 기준)."""
    _can_inspect(request)
    lot = Lot.objects.filter(number=request.GET.get('lot', '').strip()).select_related('item').first()
    specs = [s for t, _ in InspectionSpec.TYPES if (s := InspectionSpec.current(lot.item, t))] if lot else []
    return render(request, 'qms/inspect_lot.html', {'lot': lot, 'specs': specs, 'number': request.GET.get('lot', '')})


@staff_member_required
def inspect_form(request, lot_id, spec_id):
    _can_inspect(request)
    lot, spec = get_object_or_404(Lot, pk=lot_id), get_object_or_404(InspectionSpec, pk=spec_id, approved_at__isnull=False)
    gauges = [g for g in Gauge.objects.filter(active=True) if g.usable_on(timezone.localdate())]
    return render(request, 'qms/inspect_form.html', {'lot': lot, 'spec': spec, 'chars': spec.characteristics.all(),
                                                     'gauges': gauges})


def _measurement(char, raw):
    """입력칸 값 → 저장 전 측정값. 계량형은 숫자, 계수형은 OK/NG."""
    if char.is_variable:
        try:
            return Measurement(characteristic=char, value=Decimal(raw.strip()))
        except (InvalidOperation, AttributeError):
            return None
    return Measurement(characteristic=char, ok={'OK': True, 'NG': False}.get(raw)) if raw in ('OK', 'NG') else None


@staff_member_required
def inspect_check(request, char_id):
    """값을 입력하는 즉시 항목별 합부를 보여준다 (저장하지 않음)."""
    _can_inspect(request)
    char = get_object_or_404(Characteristic, pk=char_id)
    m = _measurement(char, request.POST.get(f'c{char.pk}', ''))
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
    error = None
    try:
        with transaction.atomic():
            insp = Inspection.objects.create(lot=lot, spec=spec, inspector=request.user)
            for char in spec.characteristics.all():
                m = _measurement(char, request.POST.get(f'c{char.pk}', ''))
                if m is None:
                    raise ValidationError(f'{char.name}: 값을 입력하세요.')
                m.inspection = insp
                m.gauge = gauge if char.is_variable else None
                m.save()
            insp.finalize()
    except ValidationError as e:
        error, insp = ' '.join(e.messages), None
    return render(request, 'qms/inspect_result.html', {'insp': insp, 'error': error, 'lot': lot})


@staff_member_required
def spc_view(request, char_id):
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
