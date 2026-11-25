"""메뉴 묶음 한눈에 보기(허브) 요약: 묶음 안 기록 목록마다 탭별 건수·지연·7일 안 기한과 「주의 필요」 목록(P3)."""
import datetime

from django.core.exceptions import PermissionDenied
from django.http import Http404, QueryDict
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core import recordspec
from core.nav import app_href, visible_nav
from core.relations import record_url

from . import listing
from .records import _model, _new_url

ATTENTION = 8  # 「주의 필요」 최대 줄 수
SOON = 7  # 이 날수 안에 오는 기한


def _due_field(model, spec):
    """기한 칸(DB 칸이어야 7일 안 기한을 센다). 없으면 None."""
    names = {f.name for f in model._meta.concrete_fields}
    return next((n for n in spec.fields if n in recordspec.DUE_NAMES and n in names), None)


def _days(obj, spec):
    return next((d for n in spec.fields if (d := recordspec.due_of(obj, n)) is not None), None)


def _module(user, label, href):
    path, _, query = href.partition('?')
    ct = '.'.join(path.split('/')[3:5])
    try:
        model, spec = _model(user, ct)
    except (Http404, PermissionDenied):
        return None, []
    base = model.objects.all()
    if query:  # 메뉴 주소의 거름(예: 검사 구분)은 목록 화면과 같은 방식으로
        sorts, filters = listing.field_controls(model, spec.columns, base)
        base = listing.apply(base, QueryDict(query), sorts, filters, spec.order)
    tabs = [{'key': k, 'label': n, 'count': (fn(base) if fn else base).count()} for k, n, fn in spec.tabs]
    rows, soon = [], 0
    if spec.overdue:
        late = dict((k, fn) for k, _, fn in spec.tabs)[spec.overdue](base)
        rows += [(o, _days(o, spec)) for o in late.order_by(*spec.order)[:ATTENTION]]
    if field := _due_field(model, spec):
        today = timezone.localdate()
        near = [(o, d) for o in base.filter(**{f'{field}__range': (today, today + datetime.timedelta(days=SOON))})
                if (d := recordspec.due_of(o, field)) is not None]
        soon = len(near)
        rows += near[:ATTENTION]
    meta = model._meta
    return ({'label': label, 'href': href, 'ct': ct, 'count': base.count(), 'tabs': tabs,
             'overdue': {'tab': spec.overdue, 'count': next(t['count'] for t in tabs if t['key'] == spec.overdue)} if spec.overdue else None,
             'soon': soon, 'can_add': user.has_perm(f'{meta.app_label}.add_{meta.model_name}'), 'new_url': _new_url(model, spec)},
            [{'module': label, 'title': str(o), 'url': record_url(o), 'days': d} for o, d in rows])


class HubView(APIView):
    schema = None

    def get(self, request):
        group = request.query_params.get('group', '')
        items = next((items for name, items in visible_nav(request.user) if name == group), None)
        if items is None:  # 없거나 볼 권한이 없는 묶음
            raise Http404
        modules, attention, others = [], [], []
        for label, href in items:
            href = app_href(href)
            module, rows = _module(request.user, label, href) if href.startswith('/app/r/') else (None, [])
            if module:
                modules.append(module)
                attention += rows
            else:
                others.append({'label': label, 'href': href})
        seen = set()
        attention = [a for a in sorted(attention, key=lambda a: (a['days'] is None, a['days'] or 0))
                     if not (a['url'] in seen or seen.add(a['url']))]  # 지연이면서 7일 안 기한인 건은 한 번만
        return Response({'group': group, 'modules': modules, 'others': others, 'attention': attention[:ATTENTION]})
