"""기한·대기 항목 계산. '내 할 일' 화면과 알림(manage.py notify)이 같은 기준을 쓴다."""
import datetime

from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, OuterRef
from django.utils import timezone

from core.models import EditRequest, Hold, Nonconformance, PartnerCertificate
from core.modules import active_set

from . import spc
from .models import (AuditFinding, Capa, ChangeRequest, Characteristic, ControlPlan, CustomerClaim, DocumentRevision, Gauge,
                     Inspection, InspectionSpec, InternalAudit, Memo, PpapSubmission, Qualification, Scar)


# due_items 키 → 모듈. 꺼진 모듈의 묶음은 할 일·위젯·알림 메일에서 빈 목록이 된다(MOD-10). 나머지 키는 기본 플랫폼
DUE_MODULE = {
    'claims': 'qms_claim', 'scars': 'qms_supplier', 'capas': 'qms_capa', 'audits': 'qms_audit', 'findings': 'qms_audit',
    'ppaps': 'qms_ppap', 'pending_ppaps': 'qms_ppap', 'gauges': 'qms_inspection', 'qualifications': 'qms_inspection', 'spc_alarms': 'qms_inspection',
    'pending_specs': 'qms_inspection', 'pending_plans': 'qms_inspection', 'first_articles': 'qms_change',
    'pending_changes': 'qms_change', 'pending_docs': 'qms_document', 'repeat_ncs': 'qms_capa',
}
REPEAT_COUNT, REPEAT_DAYS = 3, 90  # 같은 품번·같은 부적합 유형이 90일 안에 CAPA 없이 3건이면 CAPA를 제안한다



def due_items(approver=False, user=None):
    now, today = timezone.now(), timezone.localdate()
    soon = now + datetime.timedelta(days=2)
    claims = []
    for c in CustomerClaim.objects.filter(closed_at__isnull=True).select_related('lot'):
        if not c.current_due:
            continue
        c.due_label, c.due = c.current_due  # 지금 단계가 따르는 기한(봉쇄·원인·대책·종결)
        if c.due <= soon:
            c.overdue = c.due < now
            claims.append(c)
    capas = [c for c in Capa.objects.filter(closed_at__isnull=True).select_related('owner')
             if c.status in ('기한 초과', '유효성 확인 대기') or c.due_date <= today + datetime.timedelta(days=3)]
    open_ncs = list(Nonconformance.objects.filter(closed_at__isnull=True).select_related('lot'))
    admin = user is None or user.is_superuser  # notify(user=None)는 관리자용 목록을 쓴다
    d = {
        'now': now,
        'today': today,
        'claims': claims,
        'scars': list(Scar.objects.filter(responded_at__isnull=True, response_due__lte=soon.date())),
        'open_ncs': open_ncs,
        'nc_incomplete': [n for n in open_ncs if n.missing_fields()],
        'nc_mail_pending': list(Nonconformance.objects.filter(approved_at__isnull=False, mailed_at__isnull=True).select_related('lot')),
        'nc_notify_pending': list(Nonconformance.objects.filter(customer_notify=True, customer_notified_on__isnull=True)
                                  .select_related('lot')),
        'edit_requests': list(EditRequest.objects.filter(status=EditRequest.PENDING)) if admin else [],
        'my_rejected': list(EditRequest.objects.filter(requested_by=user, status=EditRequest.REJECTED,
                                                       decided_at__gte=now - datetime.timedelta(days=7)))
                       if user is not None else [],
        'memos_unsorted': Memo.objects.filter(content_type__isnull=True).count(),
        'held_lots': Hold.objects.filter(released_at__isnull=True).values('lot').distinct().count(),
        'capas': capas,
        'repeat_ncs': repeat_ncs(now),
        'audits': list(InternalAudit.objects.filter(performed_at__isnull=True, planned_date__lte=today + datetime.timedelta(days=14))),
        'findings': list(AuditFinding.objects.filter(grade__in=AuditFinding.NEEDS_CAPA, capa__isnull=True).select_related('audit')),
        'ppaps': list(PpapSubmission.objects.filter(submitted_at__isnull=True, due_date__lte=today + datetime.timedelta(days=14))
                      .select_related('item')),
        'gauges': [g for g in Gauge.objects.filter(active=True) if g.next_due <= today + datetime.timedelta(days=14)],
        'partner_certs': list(PartnerCertificate.objects.filter(partner__active=True, valid_until__lte=today + datetime.timedelta(days=30))
                              .select_related('partner')),
        'qualifications': expiring_qualifications(today),
        'first_articles': list(ChangeRequest.objects.filter(approved_at__isnull=False, effective_at__lte=now).annotate(
            fa=Exists(Inspection.objects.filter(lot__item=OuterRef('item'), result=Inspection.PASS,
                                                inspected_at__gte=OuterRef('effective_at')))).filter(fa=False)
                               .select_related('item')),  # ChangeRequest.awaiting_first_article과 같은 기준
        'spc_alarms': recent_spc_alarms(now),
        'pending_specs': list(InspectionSpec.objects.filter(approved_at__isnull=True)) if approver else [],
        'pending_docs': list(DocumentRevision.objects.filter(approved_at__isnull=True)) if approver else [],
        'pending_plans': list(ControlPlan.objects.filter(approved_at__isnull=True)) if approver else [],
        'pending_changes': list(ChangeRequest.objects.filter(approved_at__isnull=True).exclude(stage__in=(ChangeRequest.HOLD, ChangeRequest.REJECTED))) if approver else [],
        'pending_ppaps': list(PpapSubmission.objects.filter(approved_at__isnull=True)) if approver else [],
    }
    on = active_set()
    return d | {key: [] for key, module in DUE_MODULE.items() if module not in on}


def repeat_ncs(now, item_id=None):
    """반복 부적합 묶음 [{item, defect_type, ncs, latest}] (4단계 개선 1). 묶음 = 최근 REPEAT_DAYS일의 같은 품번·같은 유형
    (앞뒤 공백 무시, 빈 유형 제외). CAPA를 만든 부적합까지는 그 CAPA가 다루므로 그 뒤 건만 센다."""
    ncs = Nonconformance.objects.filter(detected_at__gte=now - datetime.timedelta(days=REPEAT_DAYS)).exclude(defect_type='')
    if item_id:
        ncs = ncs.filter(lot__item_id=item_id)
    ncs = list(ncs.select_related('lot__item').order_by('detected_at', 'pk'))
    with_capa = set(Capa.objects.filter(source_type=ContentType.objects.get_for_model(Nonconformance),
                                        source_id__in=[n.pk for n in ncs]).values_list('source_id', flat=True))
    groups = {}
    for n in ncs:
        key = (n.lot.item_id, n.defect_type.strip())
        if not key[1]:
            continue
        groups[key] = [] if n.pk in with_capa else groups.get(key, []) + [n]
    return [{'item': g[0].lot.item, 'defect_type': key[1], 'ncs': g, 'latest': g[-1]}
            for key, g in groups.items() if len(g) >= REPEAT_COUNT]


def repeat_group_of(nc):
    """이 부적합이 든 반복 묶음, 없으면 None."""
    return next((g for g in repeat_ncs(timezone.now(), nc.lot.item_id) if nc in g['ncs']), None)


def recent_spc_alarms(now):
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


def expiring_qualifications(today):
    """30일 이내·만료된 검사원 자격. 같은 검사원·구분에 더 늦게 끝나는 자격(갱신)이 있으면 뺀다."""
    limit = today + datetime.timedelta(days=30)
    renewed = Qualification.objects.filter(user=OuterRef('user'), inspection_type=OuterRef('inspection_type'),
                                           valid_until__gt=limit)
    return list(Qualification.objects.filter(user__is_active=True, valid_until__lte=limit).exclude(Exists(renewed))
                .select_related('user').order_by('valid_until', 'pk'))


def digest(d):
    """알림용 요약: [(제목, [줄...])]. 비어 있는 묶음은 뺀다."""
    def when(x):
        return timezone.localtime(x).strftime('%m-%d %H:%M')
    groups = [
        ('8D 기한 임박·초과', [f'{c} · {c.current_step} · {c.due_label} {when(c.due)}{" (초과)" if c.overdue else ""}'
                           for c in d['claims']]),
        ('SCAR 회신 기한', [f'{s} · 기한 {s.response_due}' for s in d['scars']]),
        ('CAPA', [f'{c} · {c.owner} · {c.status} · 기한 {c.due_date}' for c in d['capas']]),
        ('계측기 교정', [f'{g} · 교정 기한 {g.next_due}' for g in d['gauges']]),
        ('공급자 인증 만료', [f'{c.partner} · {c.get_standard_display()} · {c.valid_until}' for c in d['partner_certs']]),
        ('검사원 자격 만료', [f'{q.user} · {q.get_inspection_type_display()} · {q.valid_until}' for q in d['qualifications']]),
        ('4M 초품 미확인 (출하 차단 중)', [str(c) for c in d['first_articles']]),
        ('심사 예정', [str(a) for a in d['audits']]),
        ('CAPA 미연결 심사 발견사항', [str(f) for f in d['findings']]),
        ('반복 부적합 (CAPA 제안)', [f"{g['item']} · {g['defect_type']} · 최근 {REPEAT_DAYS}일 {len(g['ncs'])}건"
                              for g in d['repeat_ncs']]),
        ('PPAP 제출 기한', [f'{p} · 기한 {p.due_date}' for p in d['ppaps']]),
        ('부적합 보완 필요', [f'{n} · 없는 항목: {", ".join(n.missing_fields())}' for n in d['nc_incomplete']]),
        ('메일 발송 대기', [str(n) for n in d['nc_mail_pending']]),
        ('고객 통보 미처리', [str(n) for n in d['nc_notify_pending']]),
        ('삭제·수정 요청 대기', [f'{r} · {r.requested_by}' for r in d['edit_requests']]),
        ('SPC 경보', [f'{a["char"].spec.item.code} {a["char"].name} · {a["lot"]} · {", ".join(a["alarms"])}'
                    for a in d['spc_alarms']]),
    ]
    return [(title, lines) for title, lines in groups if lines]
