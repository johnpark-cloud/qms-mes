from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, DjangoModelPermissions


class IsStaff(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.is_staff)


class ModelPerms(DjangoModelPermissions):
    """조회도 view 권한을 요구하고, 삭제는 시스템 관리자만 한다 (관리 화면과 같은 규칙)."""
    perms_map = {**DjangoModelPermissions.perms_map,
                 'GET': ['%(app_label)s.view_%(model_name)s'],
                 'HEAD': ['%(app_label)s.view_%(model_name)s'],
                 'OPTIONS': ['%(app_label)s.view_%(model_name)s']}

    def has_permission(self, request, view):
        if not (request.user.is_authenticated and request.user.is_staff):
            return False
        if request.method == 'DELETE':
            return request.user.is_superuser
        return super().has_permission(request, view)


def require_perm(user, perm):
    """qms/views.py _need와 같다: 권한이 없으면 PermissionDenied."""
    if not user.has_perm(perm):
        raise PermissionDenied
