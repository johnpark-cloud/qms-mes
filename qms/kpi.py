"""품질 KPI와 협력사 성적표 계산. 화면(views.kpi, views.suppliers)과 테스트가 함께 쓴다."""
import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from core.models import Lot, Nonconformance, Shipment, WorkResult, is_approver

from .models import CustomerClaim, Inspection, InspectionSpec, Scar

# 부서 = 역할 그룹 묶음. 부서를 늘릴 때 여기에 그룹을 더한다(예: '생산': ('생산팀',)).
DEPARTMENTS = {'품질': ('품질엔지니어', '품질팀장', '검사원')}
# KPI 영역 → 볼 수 있는 부서. quality = PPM·직행률·8D·실패비용·불량유형 파레토, yield = 공정별 수율
KPI_DEPARTMENTS = {'quality': ('품질',), 'yield': ('품질', '생산')}


def can_see(user, area):
    """소속 부서의 KPI만 본다. 품질팀장·시스템 관리자는 모든 부서 KPI를 본다(작은 조직은 타부서 품질 업무도 품질이 맡는다)."""
    if is_approver(user):
        return True
    groups = {g for dept in KPI_DEPARTMENTS[area] for g in DEPARTMENTS.get(dept, ())}
    return user.groups.filter(name__in=groups).exists()


def month_starts(months, today=None):
    """최근 months개월의 월초(현지 시각, 오래된 달부터)."""
    today = today or timezone.localdate()
    y, m = today.year, today.month
    out = []
    for _ in range(months):
        out.append(datetime.date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def _aware(d):
    return timezone.make_aware(datetime.datetime.combine(d, datetime.time()))


def _ppm(bad, total):
    return float(bad) / float(total) * 1e6 if total else None


def _first_pass():
    """(LOT, 검사구분)별 첫 판정 검사 → {월초: [합격 여부...]}."""
    # shortcut: 전체 판정 이력을 한 번에 읽는다, 검사가 수십만 건을 넘으면 기간으로 잘라 집계
    seen, by_month = set(), defaultdict(list)
    for lot_id, itype, at, result in (Inspection.objects.exclude(result='')
                                      .order_by('inspected_at', 'pk')
                                      .values_list('lot_id', 'spec__inspection_type', 'inspected_at', 'result')):
        if (lot_id, itype) in seen:
            continue
        seen.add((lot_id, itype))
        by_month[timezone.localtime(at).date().replace(day=1)].append(result == Inspection.PASS)
    return by_month


def _containment_on_time(claim):
    """D3 봉쇄 조치가 기한 안에 처음 기록됐는가. 기한 전이고 아직 미기록이면 None(집계 제외)."""
    first = (claim.history.exclude(d3_containment='').order_by('history_date').values_list('history_date', flat=True).first())
    if first:
        return first <= claim.containment_due
    return False if timezone.now() > claim.containment_due else None


def monthly(months=6):
    starts = month_starts(months)
    fpy = _first_pass()
    rows = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else (start + datetime.timedelta(days=32)).replace(day=1)
        lo, hi = _aware(start), _aware(end)
        shipped = Shipment.objects.filter(shipped_at__gte=lo, shipped_at__lt=hi).aggregate(s=Sum('qty'))['s'] or 0
        claims = list(CustomerClaim.objects.filter(received_at__gte=lo, received_at__lt=hi))
        claim_qty = sum((c.defect_qty for c in claims), Decimal(0))
        on_time = [x for x in map(_containment_on_time, claims) if x is not None]
        passes = fpy.get(start, [])
        rows.append({
            'month': start,
            'shipped': shipped,
            'claims': len(claims),
            'ppm': _ppm(claim_qty, shipped),
            'fpy': 100 * sum(passes) / len(passes) if passes else None,
            'copq': Nonconformance.objects.filter(detected_at__gte=lo, detected_at__lt=hi).aggregate(s=Sum('cost'))['s'] or 0,
            'd3_on_time': 100 * sum(on_time) / len(on_time) if on_time else None,
        })
    return rows


def pareto(months=6):
    since = _aware(month_starts(months)[0])
    data = (Nonconformance.objects.filter(detected_at__gte=since).exclude(defect_type='')
            .values('defect_type').annotate(qty=Sum('defect_qty'), n=Count('id')).order_by('-qty', '-n'))
    total = sum(d['qty'] for d in data) or 0
    cum, out = 0, []
    for d in data:
        cum += d['qty']
        out.append({**d, 'share': float(d['qty']) / float(total) * 100 if total else 0,
                    'cum': float(cum) / float(total) * 100 if total else 0})
    return out


def process_yield(months=6):
    """공정별 수율 = 양품 ÷ 투입 (작업 실적 기준)."""
    since = _aware(month_starts(months)[0])
    data = (WorkResult.objects.filter(started_at__gte=since)
            .values('step__process__code', 'step__process__name')
            .annotate(inp=Sum('input_qty'), good=Sum('good_qty'), bad=Sum('defect_qty'), n=Count('id'))
            .order_by('step__process__code'))
    return [{'process': f"{d['step__process__code']} {d['step__process__name']}", 'n': d['n'], 'input': d['inp'],
             'good': d['good'], 'defect': d['bad'], 'yield': 100 * float(d['good']) / float(d['inp']) if d['inp'] else None}
            for d in data]


def suppliers(months=6):
    since = _aware(month_starts(months)[0])
    names = set(Lot.objects.exclude(supplier='').values_list('supplier', flat=True))
    names |= set(Scar.objects.values_list('supplier', flat=True))
    today = timezone.localdate()
    out = []
    for name in sorted(names):
        lots = Lot.objects.filter(supplier=name, created_at__gte=since)
        insp = Inspection.objects.filter(lot__supplier=name, spec__inspection_type=InspectionSpec.INCOMING,
                                         inspected_at__gte=since).exclude(result='')
        n_insp, n_fail = insp.count(), insp.filter(result=Inspection.FAIL).count()
        received = lots.aggregate(s=Sum('qty'))['s'] or 0
        bad = Nonconformance.objects.filter(lot__supplier=name, detected_at__gte=since).aggregate(s=Sum('defect_qty'))['s'] or 0
        scars = Scar.objects.filter(supplier=name, issued_at__gte=since.date())
        judged = [s for s in scars if s.responded_at or s.response_due < today]
        on_time = [s for s in judged if s.responded_at and s.responded_at <= s.response_due]
        out.append({
            'name': name, 'lots': lots.count(), 'received': received,
            'inspections': n_insp, 'fail_rate': 100 * n_fail / n_insp if n_insp else None,
            'ppm': _ppm(bad, received), 'scars': scars.count(),
            'scar_on_time': 100 * len(on_time) / len(judged) if judged else None,
        })
    return out
