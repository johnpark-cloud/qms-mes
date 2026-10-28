"""기한·대기 항목 계산. '내 할 일' 화면과 알림(manage.py notify)이 같은 기준을 쓴다."""
import datetime

from django.db.models import Exists, OuterRef
from django.utils import timezone

from core.models import EditRequest, Hold, Nonconformance

from . import spc
from .models import (AuditFinding, Capa, ChangeRequest, Characteristic, ControlPlan, CustomerClaim, DocumentRevision, Gauge,
                     Inspection, InspectionSpec, InternalAudit, Memo, PpapSubmission, Scar)


def due_items(approver=False, user=None):
    now, today = timezone.now(), timezone.localdate()
    soon = now + datetime.timedelta(days=2)
    claims = []
    for c in CustomerClaim.objects.filter(closed_at__isnull=True).select_related('lot'):
        c.due_label, c.due = ('대책', c.corrective_due) if c.d3_containment else ('봉쇄', c.containment_due)
        if c.due <= soon:
            c.overdue = c.due < now
            claims.append(c)
    capas = [c for c in Capa.objects.filter(closed_at__isnull=True).select_related('owner')
             if c.status in ('기한 초과', '유효성 확인 대기') or c.due_date <= today + datetime.timedelta(days=3)]
    open_ncs = list(Nonconformance.objects.filter(closed_at__isnull=True).select_related('lot'))
    admin = user is None or user.is_superuser  # notify(user=None)는 관리자용 목록을 쓴다
    return {
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
        'audits': list(InternalAudit.objects.filter(performed_at__isnull=True, planned_date__lte=today + datetime.timedelta(days=14))),
        'findings': list(AuditFinding.objects.filter(grade__in=AuditFinding.NEEDS_CAPA, capa__isnull=True).select_related('audit')),
        'ppaps': list(PpapSubmission.objects.filter(submitted_at__isnull=True, due_date__lte=today + datetime.timedelta(days=14))
                      .select_related('item')),
        'gauges': [g for g in Gauge.objects.filter(active=True) if g.next_due <= today + datetime.timedelta(days=14)],
        'first_articles': list(ChangeRequest.objects.filter(approved_at__isnull=False, effective_at__lte=now).annotate(
            fa=Exists(Inspection.objects.filter(lot__item=OuterRef('item'), result=Inspection.PASS,
                                                inspected_at__gte=OuterRef('effective_at')))).filter(fa=False)
                               .select_related('item')),  # ChangeRequest.awaiting_first_article과 같은 기준
        'spc_alarms': recent_spc_alarms(now),
        'pending_specs': list(InspectionSpec.objects.filter(approved_at__isnull=True)) if approver else [],
        'pending_docs': list(DocumentRevision.objects.filter(approved_at__isnull=True)) if approver else [],
        'pending_plans': list(ControlPlan.objects.filter(approved_at__isnull=True)) if approver else [],
        'pending_changes': list(ChangeRequest.objects.filter(approved_at__isnull=True)) if approver else [],
        'pending_ppaps': list(PpapSubmission.objects.filter(approved_at__isnull=True)) if approver else [],
    }


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
        ('4M 초품 미확인 (출하 차단 중)', [str(c) for c in d['first_articles']]),
        ('내부심사 예정', [str(a) for a in d['audits']]),
        ('CAPA 미연결 심사 지적', [str(f) for f in d['findings']]),
        ('PPAP 제출 기한', [f'{p} · 기한 {p.due_date}' for p in d['ppaps']]),
        ('부적합 보완 필요', [f'{n} · 없는 항목: {", ".join(n.missing_fields())}' for n in d['nc_incomplete']]),
        ('메일 발송 대기', [str(n) for n in d['nc_mail_pending']]),
        ('고객 통보 미처리', [str(n) for n in d['nc_notify_pending']]),
        ('삭제·수정 요청 대기', [f'{r} · {r.requested_by}' for r in d['edit_requests']]),
        ('SPC 경보', [f'{a["char"].spec.item.code} {a["char"].name} · {a["lot"]} · {", ".join(a["alarms"])}'
                    for a in d['spc_alarms']]),
    ]
    return [(title, lines) for title, lines in groups if lines]
