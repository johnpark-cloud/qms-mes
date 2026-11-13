from urllib.parse import urlencode

from django.apps import apps
from django.urls import reverse

from .modules import active_set
from .relations import record_url

KIND_MODULE = {'inspection': 'qms_inspection', 'work': 'mes', 'shipment': 'mes'}  # 나머지 종류는 기본 플랫폼


def lot_timeline(lot):
    """LOT 하나의 생성·검사·공정·부적합·처분·출하를 시간 오름차순으로 모은다."""
    Inspection = apps.get_model('qms', 'Inspection')
    ev = [(lot.created_at, 'created', f'생성 · {lot.supplier or lot.item}', '', False, None)]
    for i in lot.inspections.select_related('spec').order_by('inspected_at'):
        bad = i.result == Inspection.FAIL
        label = f'검사 {i.spec.get_inspection_type_display()} {i.get_result_display() or "진행"}'
        ev.append((i.inspected_at, 'inspection', label, f'/app/inspections/{i.pk}', bad, None))
    for w in lot.work_results.select_related('step__process'):
        ev.append((w.started_at, 'work', f'공정 {w.step.process.name}', record_url(w), False, None))
    for nc in lot.nonconformances.prefetch_related('photos'):
        url = record_url(nc)
        photo = next(iter(nc.photos.all()), None)
        ev.append((nc.detected_at, 'nc', f'부적합 {nc.number}', url, True, photo.file.url if photo else None))
        if nc.closed_at:
            ev.append((nc.closed_at, 'disposition', f'처분 {nc.get_disposition_display()}', url, False, None))
    for s in lot.shipments.all():
        ev.append((s.shipped_at, 'shipment', f'출하 {s.customer}', record_url(s), False, None))
    ev.sort(key=lambda e: e[0])  # 안정 정렬: 같은 시각이면 위 순서 유지
    # 꺼진 모듈의 사건은 감추지 않고 건수 한 줄로 끝에 남긴다(MOD-11)
    on = active_set()
    hidden = [e for e in ev if KIND_MODULE.get(e[1], 'base') not in on]
    if hidden:
        ev = [e for e in ev if e not in hidden] + [(hidden[-1][0], 'inactive', f'비활성 모듈 기록 {len(hidden)}건', None, False, None)]
    return [dict(zip(('at', 'kind', 'label', 'url', 'bad', 'thumb'), e)) for e in ev]


def lot_actions(lot, user):
    """LOT 상태에 맞는 다음 동작 버튼. 권한 없는 동작은 뺀다."""
    Inspection = apps.get_model('qms', 'Inspection')
    out, on = [], active_set()
    q = urlencode({'lot': lot.number})
    Nc = apps.get_model('core', 'Nonconformance')
    # 자기 부적합이 열려 있거나, 상위 LOT 부적합 등으로 보류가 걸린 경우의 부적합
    open_nc = (lot.nonconformances.filter(closed_at__isnull=True).first()
               or Nc.objects.filter(holds__lot=lot, holds__released_at__isnull=True, closed_at__isnull=True)
               .order_by('detected_at', 'pk').first())
    if open_nc and user.has_perm('core.change_nonconformance'):
        out.append(('처분 입력', record_url(open_nc)))
    if 'qms_inspection' in on and not lot.inspections.exists() and user.has_perm('qms.add_inspection'):
        out.append(('검사 입력', f'{reverse("inspect")}?{q}'))
    if 'mes' in on and not lot.on_hold and lot.inspections.filter(result=Inspection.PASS).exists() and user.has_perm('core.add_shipment'):
        out.append(('출하 등록', f'{reverse("admin:core_shipment_add")}?lot={lot.pk}'))
    if user.has_perm('core.add_nonconformance'):
        out.append(('부적합 등록', f'{reverse("nc_quick")}?{q}'))
    return out
