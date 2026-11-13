"""첨부파일 API. ?ct=app_label.model&id=pk 기록에 붙은 파일 목록·올리기. 내려받기는 core.views.attachment_download."""
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Attachment
from core.modules import check_label
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


def _row(a):
    try:
        size = a.file.size
    except OSError:  # 디스크에서 사라진 파일
        size = None
    return {'id': a.pk, 'title': a.title, 'kind': a.kind, 'kind_label': a.get_kind_display(),
            'url': reverse('attachment_download', args=[a.pk]),
            'uploaded_by': (a.uploaded_by.get_full_name() or a.uploaded_by.username) if a.uploaded_by else '',
            'uploaded_at': timezone.localtime(a.uploaded_at).isoformat(), 'size': size}


class AttachmentListView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'core.view_attachment')
        ct, pk = _target(request, request.GET)
        qs = Attachment.objects.filter(content_type=ct, object_id=pk).select_related('uploaded_by')
        return Response({'results': [_row(a) for a in qs],
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
        return Response(_row(a), status=201)
