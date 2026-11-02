from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import is_approver
from core.nav import NAV, nav_url


def me_payload(user):
    # 사이드바(core/context_processors.py shell)와 같은 규칙: 권한이 없는 항목은 빼고, 빈 묶음은 감춘다
    nav = []
    for name, items in NAV:
        links = [{'label': label, 'href': nav_url(url)} for label, url, perm in items
                 if perm is None or user.has_perm(perm)]
        if links:
            nav.append({'group': name, 'items': links})
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


# 로그인은 익명 요청이라 SessionAuthentication이 CSRF를 검사하지 않는다. 직접 검사한다.
@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    schema = None
    permission_classes = [AllowAny]

    def post(self, request):
        user = authenticate(request, username=request.data.get('username'), password=request.data.get('password'))
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
