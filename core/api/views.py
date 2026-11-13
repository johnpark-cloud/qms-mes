from django.apps import apps
from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import PermissionDenied
from django.db.models import Q, prefetch_related_objects
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core import audit, relations
from core.api.permissions import require_perm
from core.models import Hold, Item, Lot, RevisionLog, is_approver
from core.modules import MODULES, active_set
from core.nav import visible_nav
from core.rules import confirm_revision_log
from core.search import search
from core.timeline import lot_actions, lot_timeline


def me_payload(user):
    on = active_set()
    nav = [{'group': name, 'items': [{'label': label, 'href': href} for label, href in items]}
           for name, items in visible_nav(user)]  # 사이드바(core/context_processors.py)와 같은 필터
    return {'username': user.get_username(), 'name': user.get_full_name() or user.get_username(),
            'is_superuser': user.is_superuser, 'is_approver': is_approver(user),
            'groups': sorted(user.groups.values_list('name', flat=True)),
            'perms': sorted(user.get_all_permissions()), 'nav': nav,
            'modules': {key: key in on for key in MODULES}}  # 꺼진 모듈 경로는 React가 「비활성 모듈」로 안내한다


@method_decorator(ensure_csrf_cookie, name='dispatch')
class CsrfView(APIView):
    schema = None  # 인증 API는 OpenAPI 문서에 넣지 않는다 (직렬화기가 없다)
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({})


class LoginView(APIView):
    schema = None
    permission_classes = [AllowAny]

    def post(self, request):
        # 로그인은 익명 요청이라 SessionAuthentication이 CSRF를 검사하지 않는다. 직접 검사한다 (실패는 DRF 403 JSON).
        SessionAuthentication().enforce_csrf(request)
        data = request.data if isinstance(request.data, dict) else {}
        user = authenticate(request, username=data.get('username'), password=data.get('password'))
        if user is None or not user.is_staff:  # 틀린 비밀번호와 같은 응답 (계정 존재 여부를 알려 주지 않는다)
            return Response({'detail': '아이디 또는 비밀번호가 맞지 않습니다.'}, status=400)
        login(request, user)
        return Response(me_payload(user))


class LogoutView(APIView):
    schema = None

    def post(self, request):
        logout(request)
        return Response(status=204)


class MeView(APIView):
    schema = None

    def get(self, request):
        return Response(me_payload(request.user))


class SearchView(APIView):
    schema = None

    def get(self, request):
        return Response({'results': search(request.user, request.query_params.get('q', ''))})


class ItemLookupView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'core.view_item')
        q = request.query_params.get('q', '').strip()
        qs = Item.objects.filter(Q(code__icontains=q) | Q(name__icontains=q)).order_by('code')[:20]
        return Response([{'id': i.pk, 'code': i.code, 'name': i.name} for i in qs])


class RevisionLogApproveView(APIView):
    schema = None

    def post(self, request, pk):
        from qms.api.specs import _log  # 같은 줄 모양을 쓴다. core → qms는 함수 안에서만 가져온다
        log = get_object_or_404(RevisionLog, pk=pk)
        data = request.data if isinstance(request.data, dict) else {}
        return Response(_log(confirm_revision_log(log, request.user, data.get('password'))))


class AuditLogView(APIView):
    schema = None
    PAGE_SIZE = 50

    def get(self, request):
        if not is_approver(request.user):
            raise PermissionDenied('품질팀장만 볼 수 있습니다.')
        models = audit.audited_models()
        key = request.query_params.get('model')
        if not key:
            return Response({'models': [{'key': k, 'label': str(m._meta.verbose_name)} for k, m in models.items()]})
        if key not in models:
            raise Http404
        try:
            object_id = int(request.query_params['id']) if request.query_params.get('id') else None
            page = min(max(int(request.query_params.get('page', 1)), 1), 10**6)
        except ValueError:
            return Response({'detail': 'id와 page는 숫자여야 합니다.', 'fields': {}}, status=400)
        qs = audit.rows(models[key], object_id)
        start = (page - 1) * self.PAGE_SIZE
        chunk = list(qs[start:start + self.PAGE_SIZE + 1])
        return Response({'count': qs.count(), 'page': page, 'has_more': len(chunk) > self.PAGE_SIZE,
                         'results': [audit.row_payload(h) for h in chunk[:self.PAGE_SIZE]]})


def _lot_row(lot, held):
    return {'id': lot.pk, 'number': lot.number, 'item_code': lot.item.code, 'item_name': lot.item.name,
            'supplier': lot.supplier, 'qty': format(lot.qty.normalize(), 'f'), 'on_hold': held}


class LotSearchView(APIView):
    """LOT 고르기 목록: 번호·품번·품명·협력사 일부로 찾는다. 검색어가 없으면 최근 LOT."""
    schema = None

    def get(self, request):
        # LOT 번호를 이미 다루는 두 화면(검사 입력, LOT 이력)의 권한 중 하나가 있으면 된다
        if not (request.user.has_perm('qms.add_inspection') or request.user.has_perm('core.view_lot')):
            raise PermissionDenied
        q = request.query_params.get('q', '').strip()
        qs = Lot.objects.select_related('item').order_by('-created_at', '-pk')
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(item__code__icontains=q) | Q(item__name__icontains=q)
                           | Q(supplier__icontains=q))
        lots = list(qs[:20])
        held = set(Hold.objects.filter(lot__in=lots, released_at__isnull=True).values_list('lot_id', flat=True))
        return Response({'results': [_lot_row(x, x.pk in held) for x in lots]})


class TraceView(APIView):
    """LOT 이력: 상태, 시간순 흐름, 상위·하위 계보. 옛 화면(core.views.trace)과 같은 함수를 쓴다."""
    schema = None

    def get(self, request):
        require_perm(request.user, 'core.view_lot')
        number = request.query_params.get('lot', '').strip()
        lot = Lot.objects.filter(number=number).select_related('item').first() if number else None
        if not lot:
            return Response({'detail': '등록되지 않은 LOT입니다.'}, status=404)
        ancestors, descendants = lot.ancestors(), lot.descendants()
        # 계보 LOT마다 조회하지 않도록 출하·투입 계보·보류를 한꺼번에 읽는다
        prefetch_related_objects([lot] + ancestors + descendants, 'shipments', 'parent_links')
        held = set(Hold.objects.filter(lot__in=[lot] + ancestors + descendants, released_at__isnull=True)
                   .values_list('lot_id', flat=True))

        def row(x):
            return {**_lot_row(x, x.pk in held), 'lineage_gap': x.lineage_gap,
                    'shipments': [{'customer': str(s.customer), 'shipped_at': s.shipped_at.isoformat()}
                                  for s in x.shipments.all()]}

        return Response({
            'lot': {**row(lot), 'created_at': lot.created_at.isoformat()},
            'timeline': [{**e, 'at': e['at'].isoformat()} for e in lot_timeline(lot)],
            'actions': [{'label': label, 'url': url} for label, url in lot_actions(lot, request.user)],
            'ancestors': [row(x) for x in ancestors], 'descendants': [row(x) for x in descendants],
        })


class RelationsView(APIView):
    """GET /api/relations/<app.model>/<pk>/ → 이 기록과 연결된 기록 묶음. ?key=&page=n 이면 묶음 하나의 n쪽."""
    schema = None

    def get(self, request, label, pk):
        if not relations.is_registered(label):
            raise Http404
        model = apps.get_model(label)
        require_perm(request.user, f'{model._meta.app_label}.view_{model._meta.model_name}')
        obj = get_object_or_404(model, pk=pk)
        key = request.query_params.get('key')
        if not key:
            return Response(relations.relations_payload(request.user, obj))
        rel = next((r for r in relations.relations_for(model) if r.key == key), None)
        if rel is None:
            raise Http404
        try:
            page = max(1, int(request.query_params.get('page', 1)))
        except ValueError:
            page = 1
        group = relations.group_payload(request.user, obj, rel, page=page)
        if group is None:
            raise PermissionDenied
        return Response({**group, 'page': page, 'pages': relations.pages(group['count'])})
