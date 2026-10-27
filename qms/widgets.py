"""첫 화면 위젯. 계산은 qms.due·qms.kpi·personal.leave를 그대로 쓰고, 여기서는 고르고 배치만 한다."""
from dataclasses import dataclass
from typing import Callable

from django.urls import reverse
from django.utils import timezone

from core.models import is_approver
from personal.leave import balance

from . import kpi
from .models import DashboardLayout

SIZES = ('normal', 'wide')


@dataclass
class Widget:
    key: str
    title: str
    template: str
    context: Callable  # (request, due_items 결과) -> 추가 문맥
    allowed: Callable  # (user) -> bool


def everyone(user):
    return True


def tile(count, sub, href, bad='critical'):
    """숫자 타일 문맥. href는 URL 이름 또는 '#앵커'."""
    def context(request, d):
        n = count(d)
        return {'value': n, 'sub': sub, 'href': href if href.startswith('#') else reverse(href),
                'tone': (bad(d) if callable(bad) else bad) if n else 'positive'}
    return context


def this_month(d):
    if 'kpi_month' not in d:  # PPM·초도 합격률 위젯이 같은 계산을 나눠 쓴다
        d['kpi_month'] = kpi.monthly(1)[-1]
    return d['kpi_month']


def kpi_tile(field, fmt, sub):
    def context(request, d):
        v = this_month(d)[field]
        return {'value': '-' if v is None else fmt.format(v), 'sub': sub, 'href': reverse('kpi'), 'tone': 'neutral'}
    return context


def leave_context(request, d):
    b = balance(request.user, timezone.localdate())  # 본인 것만
    if b is None:
        return {'value': '-', 'sub': '연차 정보 없음', 'href': reverse('me'), 'tone': 'neutral'}
    return {'value': b['remaining'], 'sub': f"잔여일 · 사용 {b['used']}일", 'href': reverse('me'), 'tone': 'neutral'}


TILE = 'qms/widgets/tile.html'
PENDING = ('pending_specs', 'pending_docs', 'pending_plans', 'pending_changes', 'pending_ppaps')  # due_items의 승인 대기 묶음
WIDGETS = {w.key: w for w in [
    Widget('held_lots', '보류 LOT', TILE, tile(lambda d: d['held_lots'], '출하·투입 차단 중', 'admin:core_hold_changelist', 'negative'),
           everyone),
    Widget('nc_incomplete', '부적합 보완 필요', TILE, tile(lambda d: len(d['nc_incomplete']), '필수 항목 미입력', '#nc-incomplete'),
           everyone),
    Widget('nc_open', '열린 부적합', TILE, tile(lambda d: len(d['open_ncs']), 'MRB 처분 대기', '#ncs'), everyone),
    Widget('nc_mail_pending', '메일 발송 대기', TILE, tile(lambda d: len(d['nc_mail_pending']), '승인 후 미발송', '#nc-mail'),
           everyone),
    Widget('edit_requests', '삭제·수정 요청', TILE, tile(lambda d: len(d['edit_requests']), '관리자 처리 대기', '#edit-requests'),
           lambda u: u.is_superuser),
    Widget('approvals', '승인 대기', TILE, tile(lambda d: sum(len(d[k]) for k in PENDING), '품질팀장 서명', '#approvals'),
           is_approver),
    Widget('memos_unsorted', '미분류 메모', TILE, tile(lambda d: d['memos_unsorted'], '수신함에서 분류', 'memo_inbox'), everyone),
    Widget('capa', 'CAPA', TILE, tile(lambda d: len(d['capas']), '지연·임박·확인 대기', 'admin:qms_capa_changelist',
                                       lambda d: 'negative' if d['capas_late'] else 'critical'), everyone),
    Widget('gauges', '계측기 교정', TILE, tile(lambda d: len(d['gauges']), '14일 이내·초과', 'admin:qms_gauge_changelist'),
           everyone),
    Widget('todo_lists', '할 일 목록', 'qms/widgets/todo_lists.html', lambda request, d: {}, everyone),
    Widget('spc_alarms', 'SPC 경보', 'qms/widgets/spc_alarms.html', lambda request, d: {}, everyone),
    Widget('audits', '내부심사', 'qms/widgets/audits.html', lambda request, d: {}, everyone),
    Widget('kpi_ppm', '고객 PPM', TILE, kpi_tile('ppm', '{:,.0f}', '이번 달 · 클레임 수량 기준'), everyone),
    Widget('kpi_fpy', '초도 합격률', TILE, kpi_tile('fpy', '{:.1f}%', '이번 달 · 첫 판정 합격'), everyone),
    Widget('kpi_yield', '공정 수율', 'qms/widgets/kpi_yield.html',
           lambda request, d: {'yields': kpi.process_yield(6)}, everyone),
    Widget('leave', '연차 잔여', TILE, leave_context, everyone),
]}


def _layout(*keys):
    return [{'key': k, 'size': 'wide' if k == 'todo_lists' else 'normal'} for k in keys]


DEFAULT_LAYOUTS = {
    'inspector': _layout('held_lots', 'nc_open', 'nc_incomplete', 'memos_unsorted', 'gauges', 'leave', 'todo_lists', 'spc_alarms'),
    'approver': _layout('held_lots', 'approvals', 'nc_open', 'nc_mail_pending', 'capa', 'kpi_ppm', 'kpi_fpy', 'todo_lists', 'audits'),
    'admin': _layout('held_lots', 'approvals', 'nc_open', 'edit_requests', 'nc_mail_pending', 'capa', 'gauges', 'kpi_ppm', 'kpi_fpy',
                     'todo_lists', 'kpi_yield'),
}


def role(user):
    return 'admin' if user.is_superuser else 'approver' if is_approver(user) else 'inspector'


def layout_for(user):
    """저장된 배치에서 없어졌거나 권한이 사라진 위젯은 뺀다. 저장값이 없거나 깨졌으면 역할별 기본 배치."""
    saved = DashboardLayout.objects.filter(user=user).values_list('widgets', flat=True).first()
    if isinstance(saved, list):
        out = [{'key': w['key'], 'size': w.get('size') if w.get('size') in SIZES else 'normal'} for w in saved
               if isinstance(w, dict) and isinstance(w.get('key'), str) and w['key'] in WIDGETS and WIDGETS[w['key']].allowed(user)]
        if out:
            return out
    return DEFAULT_LAYOUTS[role(user)]
