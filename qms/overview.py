import datetime

from django.db.models import Count, Sum
from django.urls import reverse
from django.utils import timezone

from core.models import Hold, Nonconformance, RoutingStep, WorkOrder, WorkResult
from core.modules import active_set, module_of_model
from core.relations import record_url

from . import kpi
from .due import recent_spc_alarms
from .models import Capa, Gauge, Inspection, InspectionSpec


def _num(x):
    return f'{x:,.3f}'.rstrip('0').rstrip('.')  # 3500.000 → 3,500


def _pct(a, b):
    return f'{100 * float(a) / float(b):.0f}%' if b else '-'


def _admin_list(model, query=''):
    return reverse(f'admin:{model._meta.app_label}_{model._meta.model_name}_changelist') + (f'?{query}' if query else '')


def sections(user):
    """공장 종합현황: DB에 있는 생산·품질 기록만 집계한다(설비 실시간 값 없음).
    카드는 그 목록을 볼 권한이 있을 때만 보이고, 누르면 같은 조건으로 걸러진 관리 목록으로 간다."""
    u, now, today = user, timezone.now(), timezone.localdate()
    month = today.replace(day=1)
    next_month = (month + datetime.timedelta(days=32)).replace(day=1)
    since = timezone.make_aware(datetime.datetime.combine(month, datetime.time()))
    production, quality = [], []
    on = active_set()

    def can(perm):  # 볼 권한 + 그 기록의 모듈이 켜져 있음(MOD-10)
        return u.has_perm(perm) and module_of_model(perm.replace('.view_', '.')) in on

    if can('core.view_workorder'):
        by = dict(WorkOrder.objects.values_list('status').annotate(n=Count('id')))
        running = list(WorkOrder.objects.filter(status=WorkOrder.RUNNING).select_related('item').order_by('due_date', 'number')[:10])
        production.append({
            'title': '진행 중 작업지시', 'value': by.get(WorkOrder.RUNNING, 0),
            'sub': f"계획 {by.get(WorkOrder.PLANNED, 0)} · 완료 {by.get(WorkOrder.DONE, 0)}",
            'href': _admin_list(WorkOrder, 'status__exact=RUNNING'), 'more': _admin_list(WorkOrder),
            'rows': [{'label': f'{w} · {w.item.code}', 'href': record_url(w),
                      'meta': '-' if w.progress is None else f'{w.progress:.0f}%'} for w in running]})
        # 계획 대비 실적: 이번 달 납기 작업지시의 계획 수량 vs 마지막 공정 양품 (WorkOrder.progress와 같은 기준)
        wos = list(WorkOrder.objects.filter(due_date__gte=month, due_date__lt=next_month))
        last = {}
        for step in RoutingStep.objects.filter(item__in={w.item_id for w in wos}).order_by('item', '-seq'):
            last.setdefault(step.item_id, step.pk)
        good = {(r['work_order'], r['step']): r['s'] for r in WorkResult.objects.filter(work_order__in=wos, step__in=last.values())
                .values('work_order', 'step').annotate(s=Sum('good_qty'))}
        planned = sum(w.planned_qty for w in wos)
        done = sum(good.get((w.pk, last.get(w.item_id)), 0) for w in wos)
        production.append({
            'title': '계획 대비 실적', 'value': _pct(done, planned),
            'sub': f"{month:%Y-%m} 납기 작업지시 {len(wos)}건 · 계획 {_num(planned)} / 양품 {_num(done)}",
            'href': _admin_list(WorkOrder, f'due_date__gte={month}&due_date__lt={next_month}'), 'more': _admin_list(WorkOrder),
            'rows': [{'label': f'{w} · 납기 {w.due_date:%m-%d}', 'href': record_url(w),
                      'meta': _pct(good.get((w.pk, last.get(w.item_id)), 0), w.planned_qty)}
                     for w in sorted(wos, key=lambda w: w.due_date)[:5]]})
    if can('core.view_workresult'):
        ys = kpi.process_yield(1)
        inp, ok = sum(y['input'] or 0 for y in ys), sum(y['good'] or 0 for y in ys)
        production.append({
            'title': '생산 수율', 'value': _pct(ok, inp), 'sub': f'{month:%Y-%m} 작업 실적 · 양품 ÷ 투입',
            'href': _admin_list(WorkResult), 'more': _admin_list(WorkResult),
            'rows': [{'label': y['process'], 'meta': '-' if y['yield'] is None else f"{y['yield']:.1f}%"}
                     for y in sorted(ys, key=lambda y: 101 if y['yield'] is None else y['yield'])[:5]]})

    if can('qms.view_inspection'):
        insp = Inspection.objects.filter(inspected_at__gte=since).exclude(result='')
        by = {(r['spec__inspection_type'], r['result']): r['n']
              for r in insp.values('spec__inspection_type', 'result').annotate(n=Count('id'))}
        fails = sum(n for (_, res), n in by.items() if res == Inspection.FAIL)
        quality.append({
            'title': '검사 불합격', 'value': fails, 'tone': 'negative' if fails else '',
            'sub': f'{month:%Y-%m} 판정 {sum(by.values())}건', 'href': _admin_list(Inspection, 'result__exact=FAIL'),
            'more': _admin_list(Inspection),
            'rows': [{'label': name, 'href': _admin_list(Inspection, f'spec__inspection_type__exact={t}'),
                      'meta': f'불합격 {by.get((t, Inspection.FAIL), 0)} / {by.get((t, Inspection.PASS), 0) + by.get((t, Inspection.FAIL), 0)}건'}
                     for t, name in InspectionSpec.TYPES]})
    if can('core.view_hold'):
        holds = Hold.objects.filter(released_at__isnull=True)
        n = holds.values('lot').distinct().count()
        quality.append({'title': '보류 LOT', 'value': n, 'tone': 'negative' if n else '', 'sub': '투입·출하 차단 중',
                        'href': _admin_list(Hold, 'released_at__isnull=True'),
                        'rows': [{'label': str(h.lot), 'href': reverse('trace') + f'?lot={h.lot.number}', 'meta': h.nonconformance.number,
                                  'tone': 'negative'} for h in holds.select_related('lot', 'nonconformance').order_by('-created_at')[:5]]})
    if can('core.view_nonconformance'):
        ncs = list(Nonconformance.objects.filter(closed_at__isnull=True).select_related('lot').order_by('-detected_at'))
        quality.append({
            'title': '열린 부적합', 'value': len(ncs), 'tone': 'critical' if ncs else '', 'sub': '처분·종결 전',
            'href': _admin_list(Nonconformance, 'closed_at__isnull=True'), 'more': _admin_list(Nonconformance),
            'rows': [{'label': str(n), 'href': record_url(n),
                      'meta': f'{timezone.localtime(n.detected_at):%m-%d}'} for n in ncs[:5]]})
    if can('qms.view_capa'):
        capas = list(Capa.objects.filter(closed_at__isnull=True))
        late = [c for c in capas if c.status == '기한 초과']
        waiting = sum(c.status == '유효성 확인 대기' for c in capas)
        quality.append({
            'title': '진행 중 CAPA', 'value': len(capas), 'tone': 'critical' if late else '',
            'sub': f'기한 초과 {len(late)} · 유효성 확인 대기 {waiting}',
            'href': _admin_list(Capa, 'closed_at__isnull=True'), 'more': _admin_list(Capa),
            'rows': [{'label': str(c), 'href': record_url(c), 'meta': c.status, 'tone': 'negative'}
                     for c in late[:5]]})
    if can('qms.view_gauge'):
        gauges = sorted((g for g in Gauge.objects.filter(active=True) if g.next_due <= today + datetime.timedelta(days=14)),
                        key=lambda g: g.next_due)
        over = sum(g.next_due < today for g in gauges)
        quality.append({
            'title': '계측기 교정', 'value': len(gauges), 'tone': 'negative' if over else 'critical' if gauges else '',
            'sub': f'기한 초과 {over} · 14일 내 {len(gauges) - over}', 'href': _admin_list(Gauge), 'more': _admin_list(Gauge),
            'rows': [{'label': str(g), 'href': record_url(g), 'meta': f'{g.next_due:%m-%d}',
                      'tone': 'negative' if g.next_due < today else 'critical'} for g in gauges[:5]]})
    if can('qms.view_measurement'):
        alarms = recent_spc_alarms(now)
        quality.append({
            'title': 'SPC 경보', 'value': len(alarms), 'tone': 'negative' if alarms else '', 'sub': '최근 7일 · 마지막 점 기준',
            'href': reverse('spc', args=[alarms[0]['char'].pk]) if alarms else _admin_list(Inspection),
            'rows': [{'label': f"{a['char'].spec.item.code} {a['char'].name}", 'href': reverse('spc', args=[a['char'].pk]),
                      'meta': ', '.join(a['alarms']), 'tone': 'negative'} for a in alarms[:5]]})
    if can('qms.view_scar'):
        rows = [r for r in kpi.suppliers(3) if r['inspections'] or r['scars']]
        worst = sorted(rows, key=lambda r: -(r['fail_rate'] or 0))[:5]
        quality.append({
            'title': '협력사 품질', 'value': len(rows), 'sub': '최근 3개월 실적 있는 협력사 · 불합격률 높은 순',
            'href': reverse('suppliers') + '?months=3',
            'rows': [{'label': r['name'], 'meta': '-' if r['fail_rate'] is None else f"불합격 {r['fail_rate']:.1f}%",
                      'tone': 'negative' if r['fail_rate'] else ''} for r in worst]})

    return [(name, cards) for name, cards in (('생산 현황', production), ('품질 현황', quality)) if cards]
