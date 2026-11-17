"""첨부파일 API. ?ct=app_label.model&id=pk 기록에 붙은 파일 목록·올리기, <id>/ 지우기. 내려받기는 core.views.attachment_download."""
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core import recordspec
from core.models import Attachment
from core.modules import check_label
from core.records import is_locked
from core.relations import is_registered
from core.views import can_view_target

from .permissions import require_perm


def _target(request, data):
    """ct·id → ContentType과 pk. 붙일 수 없는 종류·없는 기록은 404, 그 기록을 볼 권한이 없으면 403."""
    try:
        app_label, model = data.get('ct', '').split('.')
        ct = ContentType.objects.get_by_natural_key(app_label, model)
        pk = int(data.get('id', ''))
    except (ValueError, ContentType.DoesNotExist):
        raise Http404
    if not is_registered(f'{app_label}.{model}') or ct.model_class() is None:
        raise Http404
    check_label(request, f'{app_label}.{model}')
    if not request.user.has_perm(f'{app_label}.view_{model}'):
        raise PermissionDenied
    if not can_view_target(request.user, ct, pk):
        raise Http404
    return ct, pk


def _can_delete(user, a):
    """올린 사람(올리기 권한이 있을 때)과 시스템 관리자만 지운다(2026-11-16 사용자 결정)."""
    return user.is_superuser or (a.uploaded_by_id == user.pk and user.has_perm('core.add_attachment'))


def _locked(a):
    """붙은 기록이 승인돼 잠겼거나(설명서 lock_parent 포함) 이미 없는가."""
    obj = a.target
    if obj is None:
        return False
    spec = recordspec.spec_of(f'{a.content_type.app_label}.{a.content_type.model}')
    return is_locked(obj) or bool(spec and spec.lock_parent and is_locked(getattr(obj, spec.lock_parent)))


def _row(a, user):
    try:
        size = a.file.size
    except OSError:  # 디스크에서 사라진 파일
        size = None
    return {'id': a.pk, 'title': a.title, 'kind': a.kind, 'kind_label': a.get_kind_display(),
            'url': reverse('attachment_download', args=[a.pk]),
            'uploaded_by': (a.uploaded_by.get_full_name() or a.uploaded_by.username) if a.uploaded_by else '',
            'uploaded_at': timezone.localtime(a.uploaded_at).isoformat(), 'size': size, 'can_delete': _can_delete(user, a)}


class AttachmentListView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'core.view_attachment')
        ct, pk = _target(request, request.GET)
        qs = Attachment.objects.filter(content_type=ct, object_id=pk).select_related('uploaded_by')
        return Response({'results': [_row(a, request.user) for a in qs],
                         'can_add': request.user.has_perm('core.add_attachment'),
                         'kinds': [{'value': v, 'label': label} for v, label in Attachment.KIND_CHOICES]})

    def post(self, request):
        require_perm(request.user, 'core.add_attachment')
        ct, pk = _target(request, request.data)
        f = request.FILES.get('file')
        if not f:
            return Response({'detail': '파일을 고르세요.', 'fields': {'file': ['파일을 고르세요.']}}, status=400)
        a = Attachment(content_type=ct, object_id=pk, file=f, kind=request.data.get('kind') or 'etc',
                       title=(request.data.get('title') or '')[:200], uploaded_by=request.user)
        try:
            a.full_clean()
        except ValidationError as e:
            fields = {k: [str(m) for m in v] for k, v in e.message_dict.items()}
            return Response({'detail': ' '.join(m for v in fields.values() for m in v), 'fields': fields}, status=400)
        a.save()
        return Response(_row(a, request.user), status=201)


class AttachmentDetailView(APIView):
    schema = None

    def delete(self, request, pk):
        """파일까지 지운다(post_delete). 행은 simple-history에 파일 이름·지운 사람·시각으로 남는다."""
        a = get_object_or_404(Attachment.objects.select_related('content_type'), pk=pk)
        _target(request, {'ct': f'{a.content_type.app_label}.{a.content_type.model}', 'id': a.object_id})
        if not request.user.has_perm('core.view_attachment') or not _can_delete(request.user, a):
            raise PermissionDenied
        if _locked(a):
            return Response({'detail': '승인된 기록의 첨부는 지울 수 없습니다.'}, status=400)
        a.delete()
        return Response(status=204)
