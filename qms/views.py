import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from core.models import Hold, Lot, Nonconformance, is_approver

from . import spc
from .models import (ChangeRequest, Characteristic, ControlPlan, CustomerClaim, DocumentRevision, ExcelTemplate, Gauge,
                     Inspection, InspectionSpec, Measurement, Scar)


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
    """내 할 일: 기한 임박·초과 8D와 SCAR, 승인 대기, 열린 부적합, 보류 LOT."""
    now = timezone.now()
    soon = now + datetime.timedelta(days=2)
    claims = []
    for c in CustomerClaim.objects.filter(closed_at__isnull=True).select_related('lot'):
        c.due_label, c.due = ('대책', c.corrective_due) if c.d3_containment else ('봉쇄', c.containment_due)
        if c.due <= soon:
            c.overdue = c.due < now
            claims.append(c)
    ctx = {
        'title': '내 할 일',
        'now': now,
        'claims': claims,
        'scars': Scar.objects.filter(responded_at__isnull=True, response_due__lte=soon.date()),
        'open_ncs': Nonconformance.objects.filter(closed_at__isnull=True).select_related('lot'),
        'held_lots': Hold.objects.filter(released_at__isnull=True).values('lot').distinct().count(),
        'pending_specs': InspectionSpec.objects.filter(approved_at__isnull=True) if is_approver(request.user) else [],
        'pending_docs': DocumentRevision.objects.filter(approved_at__isnull=True) if is_approver(request.user) else [],
        'pending_plans': ControlPlan.objects.filter(approved_at__isnull=True) if is_approver(request.user) else [],
        'pending_changes': ChangeRequest.objects.filter(approved_at__isnull=True) if is_approver(request.user) else [],
        'today': timezone.localdate(),
        'gauges': [g for g in Gauge.objects.filter(active=True)
                   if g.next_due <= timezone.localdate() + datetime.timedelta(days=14)],
        'first_articles': [c for c in ChangeRequest.objects.filter(approved_at__isnull=False).select_related('item')
                           if not c.first_article],
        'spc_alarms': _recent_spc_alarms(now),
    }
    return render(request, 'qms/todo.html', ctx)


def _recent_spc_alarms(now):
    """최근 7일 측정된 계량형 항목 중 마지막 점에 경보가 있는 것 (특별특성은 이미 부적합이 자동 등록됨)."""
    seen, out = set(), []
    recent = (Characteristic.objects.filter(measurements__inspection__inspected_at__gte=now - datetime.timedelta(days=7))
              .select_related('spec__item').distinct())
    for c in recent:
        key = (c.spec.item_id, c.spec.inspection_type, c.name)
        if key in seen or not c.is_variable:
            continue
        seen.add(key)
        try:
            last = spc.control_chart(c.spc_series(), c.lsl, c.usl)['points'][-1]
        except ValueError:
            continue
        if last['alarms']:
            out.append({'char': c, 'lot': last['label'].lot, 'alarms': last['alarms']})
    return out


# ---------- 검사원 전용 입력 화면 (htmx: 화면 일부만 서버에서 다시 그린다) ----------

def _can_inspect(request):
    if not request.user.has_perm('qms.add_inspection'):
        raise PermissionDenied


@staff_member_required
def inspect_home(request):
    _can_inspect(request)
    return render(request, 'qms/inspect.html', {'title': '검사 입력'})


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
    return HttpResponse(format_html('<span class="{}">{}</span>', 'ok' if m.passed else 'ng', '합격' if m.passed else '규격 이탈'))


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
