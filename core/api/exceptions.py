from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError
from rest_framework.exceptions import PermissionDenied as DrfPermissionDenied
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.rules import LOCKED_MSG, Locked

CSRF_MSG = '보안 토큰이 없거나 만료되었습니다. 새로고침 후 다시 시도하세요.'


def handler(exc, context):
    """오류 형식(spec 6.6). DRF 자체 예외는 기본 처리를 그대로 쓴다."""
    if isinstance(exc, Locked):  # ValidationError의 하위 클래스라 먼저 본다
        return Response({'detail': LOCKED_MSG}, status=409)
    if isinstance(exc, ValidationError):
        fields = exc.message_dict if hasattr(exc, 'error_dict') else {}
        return Response({'detail': ' '.join(exc.messages), 'fields': fields}, status=400)
    if isinstance(exc, PermissionDenied):
        return Response({'detail': str(exc) or '권한이 없습니다.'}, status=403)
    if isinstance(exc, ProtectedError):
        blockers = [f'{o._meta.verbose_name}: {o}' for o in exc.protected_objects]
        return Response({'detail': '먼저 지워야 할 기록: ' + ', '.join(blockers), 'blockers': blockers}, status=409)
    if isinstance(exc, DrfPermissionDenied) and str(exc.detail).startswith('CSRF Failed'):
        return Response({'detail': CSRF_MSG}, status=403)
    return exception_handler(exc, context)
