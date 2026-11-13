"""재발 방지: 새 부적합·클레임과 비슷한 과거 종결 사례를 찾는다."""
import re

from django.utils.html import format_html, format_html_join

from core.models import Nonconformance
from core.relations import record_url

SCAN = 500  # shortcut: 최근 종결 500건만 훑는다, 이력이 많아져 놓치는 사례가 생기면 전문 검색(FTS)으로 교체


def _words(text):
    return set(re.findall(r'\w{2,}', text or ''))


def similar(record, limit=10):
    """record: 부적합(Nonconformance) 또는 고객 클레임. 점수 = 같은 품번(계보 포함) 2 + 같은 불량유형 2 + 겹치는 단어 수."""
    nc = record if isinstance(record, Nonconformance) else record.nonconformance
    if nc is None:
        return []
    items = {nc.lot.item_id} | {lot.item_id for lot in nc.lot.ancestors()}
    words = _words(nc.description) | _words(getattr(record, 'description', ''))
    found = []
    for past in (Nonconformance.objects.filter(closed_at__isnull=False).exclude(pk=nc.pk)
                 .select_related('lot', 'claim').order_by('-closed_at')[:SCAN]):
        claim = getattr(past, 'claim', None)
        overlap = len(words & (_words(past.description) | _words(claim.description if claim else '')))
        score = 2 * (past.lot.item_id in items) + 2 * bool(nc.defect_type and past.defect_type == nc.defect_type) + overlap
        if score >= 2:
            found.append((score, past, claim))
    found.sort(key=lambda x: (-x[0], -x[1].closed_at.timestamp()))
    return found[:limit]


def similar_html(record):
    rows = similar(record)
    if not rows:
        return '비슷한 과거 종결 사례 없음'
    return format_html('<ul style="margin:0;padding-left:1.2em">{}</ul>', format_html_join('', (
        '<li><a href="{}" target="_blank">{}</a> · {} · 처분 {}{}</li>'), (
        (record_url(c or p),
         c or p, p.description[:60], p.get_disposition_display(),
         format_html('<br>D4 근본 원인: {}<br>D7 재발 방지: {}', c.d4_root_cause[:120], c.d7_prevention[:120]) if c else '')
        for _, p, c in rows)))
