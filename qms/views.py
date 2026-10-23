import datetime
from urllib.parse import urlencode

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from core.models import Hold, Nonconformance, is_approver

from . import spc
from .models import Characteristic, CustomerClaim, DocumentRevision, ExcelTemplate, InspectionSpec, Measurement, Scar


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
    }
    return render(request, 'qms/todo.html', ctx)


@staff_member_required
def spc_view(request, char_id):
    char = get_object_or_404(Characteristic.objects.select_related('spec__item'), pk=char_id)
    # 같은 품번·검사구분·항목명이면 기준 개정이 달라도 같은 특성으로 본다
    ms = (Measurement.objects
          .filter(characteristic__spec__item=char.spec.item, characteristic__spec__inspection_type=char.spec.inspection_type,
                  characteristic__name=char.name, value__isnull=False, inspection__result__in=['PASS', 'FAIL'])
          .select_related('inspection__lot').order_by('inspection__inspected_at', 'pk'))
    groups = {}
    for m in ms:
        groups.setdefault(m.inspection, []).append(m.value)
    ctx = {'title': f'SPC · {char.spec.item.code} {char.name}', 'char': char}
    try:
        res = spc.xbar_r([(insp, v) for insp, v in groups.items()], char.lsl, char.usl)
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
