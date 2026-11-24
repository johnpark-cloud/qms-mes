"""경영검토 입력 자동 요약(ISO 9001 9.3.2 c·a). 등록할 때 한 번 글로 채우고, 그 뒤에는 사람이 고친다."""
import datetime

from django.utils import timezone

from core import modules
from core.models import Nonconformance, Partner

from .models import AuditFinding, Capa, CustomerClaim, Gauge, Inspection, InternalAudit, ManagementReview


def _aware(day, end=False):
    t = datetime.datetime.combine(day + datetime.timedelta(days=1) if end else day, datetime.time())
    return timezone.make_aware(t)


def performance(start, end):
    """검토 기간(start~end, 양 끝 포함)의 품질 성과 요약. 꺼진 모듈 줄은 뺀다. 미종결·기한 초과는 지금 기준."""
    since, until = _aware(start), _aware(end, end=True)
    judged = Inspection.objects.filter(inspected_at__gte=since, inspected_at__lt=until).exclude(result='')
    n, ok = judged.count(), judged.filter(result=Inspection.PASS).count()
    rate = f'({ok / n * 100:.1f}%)' if n else ''
    ncs = Nonconformance.objects.filter(detected_at__gte=since, detected_at__lt=until)
    lines = [f'검토 기간 {start} ~ {end}',
             f'· 검사: 판정 {n}건, 합격 {ok}건{rate}',
             f'· 부적합: 발생 {ncs.count()}건, 미종결 {Nonconformance.objects.filter(closed_at__isnull=True).count()}건(현재)']
    if modules.active('qms_claim'):
        claims = CustomerClaim.objects.filter(received_at__gte=since, received_at__lt=until)
        lines.append(f'· 고객 클레임: 접수 {claims.count()}건, 미종결 {CustomerClaim.objects.filter(closed_at__isnull=True).count()}건(현재)')
    if modules.active('qms_capa'):
        open_capas = list(Capa.objects.filter(closed_at__isnull=True))
        late = sum(c.status == '기한 초과' for c in open_capas)
        lines.append(f'· CAPA: 미종결 {len(open_capas)}건, 기한 초과 {late}건(현재)')
    if modules.active('qms_audit'):
        audits = InternalAudit.objects.filter(performed_at__gte=start, performed_at__lte=end)
        found = AuditFinding.objects.filter(audit__in=audits).count()
        lines.append(f'· 심사: 실시 {audits.count()}건, 발견사항 {found}건')
    watch = Partner.objects.filter(is_supplier=True, active=True, grade__in=Partner.WATCH_GRADES).count()
    lines.append(f'· 공급자: 평가 등급 C·D {watch}곳(현재)')
    if modules.active('qms_inspection'):
        today = timezone.localdate()
        late = sum(g.next_due < today for g in Gauge.objects.filter(active=True))
        lines.append(f'· 계측기: 교정 기한 지남 {late}대(현재)')
    return '\n'.join(lines)


def previous_actions(before):
    """직전 경영검토(검토일이 before보다 앞선 것)의 조치 사항 상태. 없으면 빈 글."""
    prev = ManagementReview.objects.filter(held_on__lt=before).order_by('-held_on', '-pk').first()
    acts = list(prev.actions.select_related('owner')) if prev else []
    if not acts:
        return ''
    done = sum(a.done_on is not None for a in acts)
    lines = [f'직전 검토({prev.held_on}) 조치 {len(acts)}건 중 완료 {done}건']
    lines += [f'· 미완료: {a.task} (담당 {a.owner.get_full_name() or a.owner.username}, 기한 {a.due_date})'
              for a in acts if a.done_on is None]
    return '\n'.join(lines)
