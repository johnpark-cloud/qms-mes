"""첫 화면 위젯. 계산은 qms.due·qms.kpi·personal.leave를 그대로 쓰고, 여기서는 고르고 배치만 한다."""
from dataclasses import dataclass
from typing import Callable

from django.urls import reverse
from django.utils import timezone

from core.models import Hold, is_approver
from personal.leave import balance
from personal.models import LeaveUse

from . import kpi
from .models import DashboardLayout, Memo

SIZES = ('normal', 'wide')
COLS, ROWS = 4, 10  # 넓은 화면 격자: 4칸 × 최대 10줄. 보통은 1×1, 넓게는 2×2를 차지한다
DETAIL_ROWS = 6  # 넓게 볼 때 타일 아래 목록 줄 수


@dataclass
class Widget:
    key: str
    title: str
    template: str
    context: Callable  # (request, due_items 결과, size) -> 추가 문맥
    allowed: Callable  # (user) -> bool


def everyone(user):
    return True


def kpi_allowed(area):
    """KPI 위젯: /kpi/ 화면 권한(클레임 보기)이 있고 소속 부서의 KPI일 때만 (qms.kpi.can_see)."""
    return lambda user: user.has_perm('qms.view_customerclaim') and kpi.can_see(user, area)


def tile(count, sub, href, bad='critical', rows=None, more=None):
    """숫자 타일 문맥. href는 URL 이름 또는 '#앵커'. 넓게 보면 rows(request, d)의 앞 몇 줄과 '전체 보기'(more 또는 href)를 붙인다."""
    def context(request, d, size):
        n = count(d)
        url = href if href.startswith('#') else reverse(href)
        out = {'value': n, 'sub': sub, 'href': url, 'more': reverse(more) if more else url,
               'tone': (bad(d) if callable(bad) else bad) if n else 'positive'}
        if size == 'wide' and rows:
            out['rows'] = rows(request, d)[:DETAIL_ROWS]
        return out
    return context


def row(label, href=None, meta='', tone=None):
    """넓은 타일 목록 한 줄: 링크 + 값 하나(tone이 있으면 상태 배지)."""
    return {'label': label, 'href': href, 'meta': meta, 'tone': tone}


def change(name, obj):
    return reverse(f'admin:{name}_change', args=[obj.pk])


def held_rows(request, d):
    holds = Hold.objects.filter(released_at__isnull=True).select_related('lot', 'nonconformance').order_by('-created_at')
    seen, out = set(), []
    for h in holds[:50]:  # 같은 LOT의 보류가 여러 건이면 최신 한 줄만
        if h.lot_id not in seen:
            seen.add(h.lot_id)
            out.append(row(str(h.lot), f"{reverse('trace')}?lot={h.lot.number}", str(h.nonconformance)))
    return out


def nc_rows(key, meta):
    return lambda request, d: [row(str(n), change('core_nonconformance', n), meta(n)) for n in d[key]]


def approval_rows(request, d):
    kinds = [('pending_specs', '검사기준', 'inspectionspec'), ('pending_docs', '문서', 'documentrevision'),
             ('pending_plans', '관리계획서', 'controlplan'), ('pending_changes', '4M 변경', 'changerequest')]
    out = [row(str(o), reverse('approve', args=['qms', model, o.pk]), kind) for key, kind, model in kinds for o in d[key]]
    return out + [row(str(p), change('qms_ppapsubmission', p), 'PSW') for p in d['pending_ppaps']]


def capa_tone(status):
    return 'negative' if status == '기한 초과' else 'info' if status == '유효성 확인 대기' else 'critical'


def memo_rows(request, d):
    if not request.user.has_perm('qms.view_memo'):  # 메모 내용은 수신함을 볼 수 있는 사람에게만
        return []
    url = reverse('memo_inbox')
    return [row(m.body[:30], url, f'{timezone.localtime(m.created_at):%m-%d}')
            for m in Memo.objects.filter(content_type__isnull=True).order_by('-created_at')[:DETAIL_ROWS]]


def this_month(d):
    if 'kpi_month' not in d:  # PPM·초도 합격률 위젯이 같은 계산을 나눠 쓴다
        d['kpi_month'] = kpi.monthly(1)[-1]
    return d['kpi_month']


def kpi_tile(field, fmt, sub):
    def show(v):
        return '-' if v is None else fmt.format(v)

    def context(request, d, size):
        url = reverse('kpi')
        out = {'value': show(this_month(d)[field]), 'sub': sub, 'href': url, 'more': url, 'tone': 'neutral'}
        if size == 'wide':
            if 'kpi_months' not in d:
                d['kpi_months'] = kpi.monthly(DETAIL_ROWS)
            out['rows'] = [row(f"{r['month']:%Y-%m}", meta=show(r[field])) for r in reversed(d['kpi_months'])]
        return out
    return context


def leave_context(request, d, size):
    b = balance(request.user, timezone.localdate())  # 본인 것만
    me = reverse('me')
    if b is None:
        return {'value': '-', 'sub': '연차 정보 없음', 'href': me, 'more': me, 'tone': 'neutral'}
    out = {'value': b['remaining'], 'sub': f"잔여일 · 사용 {b['used']}일", 'href': me, 'more': me, 'tone': 'neutral'}
    if size == 'wide':  # 최근 사용일 (본인 것만)
        out['rows'] = [row(f'{u.used_on:%Y-%m-%d}', meta=f'{u.days.normalize()}일')
                       for u in LeaveUse.objects.filter(owner=request.user)[:DETAIL_ROWS]]
    return out


TODO_SECTIONS = [  # (todo_lists.html 구역 id, 이름, due_items 키): 보통 크기에서 건수만 보여 주는 줄
    ('claims', '8D 기한', 'claims'), ('ncs', '열린 부적합', 'open_ncs'), ('capas', 'CAPA', 'capas'), ('scars', 'SCAR 회신', 'scars'),
    ('nc-incomplete', '보완 필요', 'nc_incomplete'), ('nc-mail', '메일 대기', 'nc_mail_pending'),
    ('nc-notify', '고객 통보', 'nc_notify_pending'), ('edit-requests', '삭제·수정 요청', 'edit_requests'),
    ('my-rejected', '거절된 내 요청', 'my_rejected'), ('memos-unsorted', '미분류 메모', 'memos_unsorted'),
    ('fa', '초품 미확인', 'first_articles'), ('gauges', '계측기 교정', 'gauges'), ('ppaps', 'PPAP 제출', 'ppaps'),
]


def todo_context(request, d, size):
    if size == 'wide':
        return {}
    lines = [(i, name, d[k] if isinstance(d[k], int) else len(d[k])) for i, name, k in TODO_SECTIONS]
    lines.append(('approvals', '승인 대기', sum(len(d[k]) for k in PENDING)))
    lines = [x for x in lines if x[2]]
    return {'summary': lines, 'total': sum(n for _, _, n in lines)}


def yield_context(request, d, size):
    ys = kpi.process_yield(6)
    known = [y for y in ys if y['yield'] is not None]
    inp = sum(float(y['input']) for y in known)
    return {'yields': ys, 'overall': 100 * sum(float(y['good']) for y in known) / inp if inp else None,
            'lowest': min(known, key=lambda y: y['yield'], default=None)}


TILE = 'qms/widgets/tile.html'
PENDING = ('pending_specs', 'pending_docs', 'pending_plans', 'pending_changes', 'pending_ppaps')  # due_items의 승인 대기 묶음
NC_LIST = 'admin:core_nonconformance_changelist'
WIDGETS = {w.key: w for w in [
    Widget('held_lots', '보류 LOT', TILE, tile(lambda d: d['held_lots'], '출하·투입 차단 중', 'admin:core_hold_changelist', 'negative',
                                            held_rows), everyone),
    Widget('nc_incomplete', '부적합 보완 필요', TILE, tile(lambda d: len(d['nc_incomplete']), '필수 항목 미입력', '#nc-incomplete',
                                                     rows=nc_rows('nc_incomplete', lambda n: ', '.join(n.missing_fields())),
                                                     more=NC_LIST), everyone),
    Widget('nc_open', '열린 부적합', TILE, tile(lambda d: len(d['open_ncs']), 'MRB 처분 대기', '#ncs',
                                           rows=nc_rows('open_ncs', lambda n: f'{timezone.localtime(n.detected_at):%m-%d}'),
                                           more=NC_LIST), everyone),
    Widget('nc_mail_pending', '메일 발송 대기', TILE, tile(
        lambda d: len(d['nc_mail_pending']), '승인 후 미발송', '#nc-mail', more=NC_LIST,
        rows=lambda request, d: [row(str(n), reverse('nc_mail', args=[n.pk]), f'{timezone.localtime(n.approved_at):%m-%d} 승인')
                                 for n in d['nc_mail_pending']]), everyone),
    Widget('edit_requests', '삭제·수정 요청', TILE, tile(
        lambda d: len(d['edit_requests']), '관리자 처리 대기', '#edit-requests',
        rows=lambda request, d: [row(str(r), reverse('edit_request_decide', args=[r.pk]), str(r.requested_by))
                                 for r in d['edit_requests']]), lambda u: u.is_superuser),
    Widget('approvals', '승인 대기', TILE, tile(lambda d: sum(len(d[k]) for k in PENDING), '품질팀장 서명', '#approvals',
                                           rows=approval_rows), is_approver),
    Widget('memos_unsorted', '미분류 메모', TILE, tile(lambda d: d['memos_unsorted'], '수신함에서 분류', 'memo_inbox', rows=memo_rows),
           everyone),
    Widget('capa', 'CAPA', TILE, tile(lambda d: len(d['capas']), '지연·임박·확인 대기', 'admin:qms_capa_changelist',
                                       lambda d: 'negative' if d['capas_late'] else 'critical',
                                       lambda request, d: [row(str(c), change('qms_capa', c), c.status, capa_tone(c.status))
                                                           for c in d['capas']]), everyone),
    Widget('gauges', '계측기 교정', TILE, tile(
        lambda d: len(d['gauges']), '14일 이내·초과', 'admin:qms_gauge_changelist',
        rows=lambda request, d: [row(str(g), change('qms_gauge', g), f'{g.next_due:%Y-%m-%d}',
                                     'negative' if g.next_due < d['today'] else 'critical')
                                 for g in sorted(d['gauges'], key=lambda g: g.next_due)]), everyone),
    Widget('todo_lists', '할 일 목록', 'qms/widgets/todo_lists.html', todo_context,
           lambda u: u.has_perm('core.view_nonconformance')),
    Widget('spc_alarms', 'SPC 경보', 'qms/widgets/spc_alarms.html', lambda request, d, size: {}, everyone),
    Widget('audits', '내부심사', 'qms/widgets/audits.html', lambda request, d, size: {}, everyone),
    Widget('kpi_ppm', '고객 PPM', TILE, kpi_tile('ppm', '{:,.0f}', '이번 달 · 클레임 수량 기준'), kpi_allowed('quality')),
    Widget('kpi_fpy', '초도 합격률', TILE, kpi_tile('fpy', '{:.1f}%', '이번 달 · 첫 판정 합격'), kpi_allowed('quality')),
    Widget('kpi_yield', '공정 수율', 'qms/widgets/kpi_yield.html', yield_context, kpi_allowed('yield')),
    Widget('leave', '연차 잔여', TILE, leave_context, everyone),
]}


def span(size):
    return 2 if size == 'wide' else 1


def place(items):
    """목록 순서대로 격자에 자리를 잡는다 (core/static/qms/dashboard.js의 place와 같은 규칙).
    지정 위치(x, y)를 칸 안으로 당긴 뒤 비어 있으면 그대로, 아니면 위→아래·왼→오른쪽 첫 빈자리에 둔다.
    넓게(2×2) 놓을 자리가 없으면 보통으로 줄이고, 그래도 없으면 뺀다. 결과는 (y, x) 순."""
    taken, out = set(), []

    def cells(x, y, n):
        return {(x + i, y + j) for i in range(n) for j in range(n)}

    def first_free(n):
        return next(((x, y) for y in range(ROWS - n + 1) for x in range(COLS - n + 1) if not cells(x, y, n) & taken), None)

    for it in items:
        size, x, y = it['size'], it.get('x'), it.get('y')
        n, spot = span(size), None
        if type(x) is int and type(y) is int:
            x, y = min(max(x, 0), COLS - n), min(max(y, 0), ROWS - n)
            spot = None if cells(x, y, n) & taken else (x, y)
        spot = spot or first_free(n)
        if spot is None and n == 2:
            size, n = 'normal', 1
            spot = first_free(1)
        if spot is None:
            continue
        taken |= cells(*spot, n)
        out.append({**it, 'size': size, 'x': spot[0], 'y': spot[1]})
    return sorted(out, key=lambda w: (w['y'], w['x']))


def _layout(*keys):
    """역할별 기본 배치: 첫 줄에 숫자 타일 4개, 그 아래 할 일 목록(넓게) 옆에 타일이 둘씩 쌓인다."""
    return place([{'key': k, 'size': 'wide' if k == 'todo_lists' else 'normal'} for k in keys])


DEFAULT_LAYOUTS = {
    'inspector': _layout('held_lots', 'nc_open', 'nc_incomplete', 'gauges', 'todo_lists', 'memos_unsorted', 'leave', 'spc_alarms',
                         'capa'),
    'approver': _layout('held_lots', 'approvals', 'nc_open', 'capa', 'todo_lists', 'nc_mail_pending', 'kpi_ppm', 'audits',
                        'kpi_fpy'),
    'admin': _layout('held_lots', 'approvals', 'nc_open', 'edit_requests', 'todo_lists', 'nc_mail_pending', 'capa', 'kpi_ppm',
                     'kpi_fpy', 'gauges', 'kpi_yield'),
}


def role(user):
    return 'admin' if user.is_superuser else 'approver' if is_approver(user) else 'inspector'


def layout_for(user):
    """저장된 배치에서 없어졌거나 권한이 사라진 위젯은 뺀다. 저장값이 없거나 깨졌으면 역할별 기본 배치. 위치는 place로 정리한다."""
    saved = DashboardLayout.objects.filter(user=user).values_list('widgets', flat=True).first()
    if isinstance(saved, list):
        out = [{'key': w['key'], 'size': w.get('size') if w.get('size') in SIZES else 'normal',
                **{k: w[k] for k in ('x', 'y') if k in w}} for w in saved
               if isinstance(w, dict) and isinstance(w.get('key'), str) and w['key'] in WIDGETS and WIDGETS[w['key']].allowed(user)]
        if out:
            return place(out)
    return place([w for w in DEFAULT_LAYOUTS[role(user)] if WIDGETS[w['key']].allowed(user)])
