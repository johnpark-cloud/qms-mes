from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core import audit
from core.api.permissions import require_perm
from core.models import Item, RevisionLog, is_approver
from core.nav import visible_nav
from core.rules import confirm_revision_log
from core.search import search


def me_payload(user):
    nav = [{'group': name, 'items': [{'label': label, 'href': href} for label, href in items]}
           for name, items in visible_nav(user)]  # 사이드바(core/context_processors.py)와 같은 필터
    return {'username': user.get_username(), 'name': user.get_full_name() or user.get_username(),
            'is_superuser': user.is_superuser, 'is_approver': is_approver(user),
            'groups': sorted(user.groups.values_list('name', flat=True)),
            'perms': sorted(user.get_all_permissions()), 'nav': nav}


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
            page = max(int(request.query_params.get('page', 1)), 1)
        except ValueError:
            return Response({'detail': 'id와 page는 숫자여야 합니다.', 'fields': {}}, status=400)
        qs = audit.rows(models[key], object_id)
        start = (page - 1) * self.PAGE_SIZE
        chunk = list(qs[start:start + self.PAGE_SIZE + 1])
        return Response({'count': qs.count(), 'page': page, 'has_more': len(chunk) > self.PAGE_SIZE,
                         'results': [audit.row_payload(h) for h in chunk[:self.PAGE_SIZE]]})
