from urllib.parse import urlencode

from django.apps import apps
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .modules import active_set
from .nav import app_href
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
    return [(label, app_href(url)) for label, url in out]  # 옛 서버 화면 주소 → 새 화면


def _at(dt):
    return timezone.localtime(dt).isoformat() if dt else None


def _num(d):
    return format(d.normalize(), 'f')


def _inspection_rows(insp):
    """특성별 [이름, 규격, n, 최소, 최대, 판정]. 계수형은 최소·최대 자리에 OK 수·NG 수."""
    by = {}
    for m in insp.measurements.select_related('characteristic').order_by('characteristic_id', 'pk'):
        by.setdefault(m.characteristic, []).append(m)
    rows = []
    for c, ms in by.items():
        ok = all(m.passed for m in ms)
        if c.is_variable:
            vals = [m.value for m in ms if m.value is not None]
            lo, hi = (_num(min(vals)), _num(max(vals))) if vals else ('', '')
        else:
            ng = sum(1 for m in ms if not m.passed)
            lo, hi = 'OK', f'NG {ng}' if ng else ''
        rows.append([c.name, c.spec_text(), len(ms), lo, hi, '합격' if ok else '불합격'])
    return rows


def shipment_trace(ship):
    """출하 이력서: LOT 생성→작업→검사→출하 단계, 검사 근거, 투입 LOT 수입검사, 부적합, 4M, 전체 타임라인."""
    from .models import Nonconformance, result_text
    Inspection = apps.get_model('qms', 'Inspection')
    ChangeRequest = apps.get_model('qms', 'ChangeRequest')
    lot = ship.lot
    works = list(lot.work_results.all())
    started = min((w.started_at for w in works if w.started_at), default=None)
    ended = max((w.ended_at for w in works if w.ended_at), default=None) if works and all(w.ended_at for w in works) else None

    def insp_step(label, itype):
        i = lot.latest_inspection(itype)
        return {'label': label, 'at': _at(i.inspected_at) if i else None, 'text': result_text(i),
                'url': f'/app/inspections/{i.pk}' if i else None, 'bad': bool(i and i.result == Inspection.FAIL) or i is None}

    steps = [
        {'label': 'LOT 생성', 'at': _at(lot.created_at), 'text': lot.number, 'url': record_url(lot), 'bad': False},
        {'label': '작업 시작', 'at': _at(started), 'text': '' if started else '없음', 'url': None, 'bad': False},
        {'label': '작업 완료', 'at': _at(ended), 'text': '' if ended else ('진행 중' if works else '없음'), 'url': None, 'bad': False},
        insp_step('공정검사', 'PROCESS'),
        insp_step('출하검사', 'OUTGOING'),
        {'label': '출하', 'at': _at(ship.shipped_at), 'text': f'{ship.customer} {_num(ship.qty)}', 'url': None, 'bad': False},
    ]
    steps[3]['bad'] = steps[3]['text'] == '불합격'  # 공정검사는 없어도 정상(품목에 따라 없음)
    inspections = [{
        'type': i.spec.get_inspection_type_display(), 'result': result_text(i), 'bad': i.result == Inspection.FAIL,
        'at': _at(i.inspected_at), 'inspector': (i.inspector.get_full_name() or i.inspector.username) if i.inspector else '',
        'url': f'/app/inspections/{i.pk}', 'rows': _inspection_rows(i),
    } for i in lot.inspections.select_related('spec', 'inspector').order_by('-inspected_at', '-pk')]
    ancestors = sorted(lot.ancestors(), key=lambda a: a.number)
    inputs = []
    for a in ancestors:
        iqc = a.latest_inspection('INCOMING')
        inputs.append({'lot': a.number, 'url': record_url(a), 'item': f'{a.item.code} {a.item.name}',
                       'supplier': a.supplier or (a.partner.name if a.partner_id else ''), 'iqc': result_text(iqc),
                       'iqc_url': f'/app/inspections/{iqc.pk}' if iqc else None, 'bad': bool(iqc and iqc.result == Inspection.FAIL)})
    ncs = (Nonconformance.objects.filter(Q(lot_id__in=[lot.pk] + [a.pk for a in ancestors]) | Q(holds__lot=lot))
           .select_related('lot').distinct().order_by('-detected_at'))
    changes = ChangeRequest.objects.filter(item=lot.item_id, approved_at__isnull=False, effective_at__lte=ship.shipped_at)
    return {
        'steps': steps, 'inspections': inspections, 'inputs': inputs, 'on_hold': lot.on_hold,
        'ncs': [{'number': n.number, 'url': record_url(n), 'lot': n.lot.number if n.lot_id else '', 'open': not n.closed_at,
                 'text': n.get_disposition_display() or '처분 대기', 'at': _at(n.detected_at)} for n in ncs],
        'changes': [{'number': c.number, 'url': record_url(c), 'text': c.get_category_display(),
                     'first_article': bool(c.first_article)} for c in changes.order_by('-effective_at')],
        'timeline': lot_timeline(lot),
    }
