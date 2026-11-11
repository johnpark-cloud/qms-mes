"""현장 메모 API. 옛 htmx 화면(qms/views.py memo_*)과 같은 규칙·폼(qms.memo)을 쓴다."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import require_perm
from qms.memo import TARGETS, MemoForm, resolve_target, todays_audit
from qms.models import Memo, MemoPhoto
from qms.views import _memo_target

from .specs import BAD_BODY, _bad, _who


def _memo(m, user):
    return {'id': m.pk, 'body': m.body, 'speaker_kind': m.speaker_kind, 'speaker': m.get_speaker_kind_display(),
            'speaker_name': m.speaker_name, 'author': _who(m.author),
            'created_at': timezone.localtime(m.created_at).isoformat(), 'audit': str(m.audit) if m.audit else '',
            'photos': [{'id': p.pk, 'url': p.file.url} for p in m.photos.all()],
            'can_edit': m.author_id == user.pk,
            'can_link': m.author_id == user.pk or user.has_perm('qms.change_memo')}


def _save(request, memo, target):
    """폼 검증 → 저장. 심사는 화면에서 받지 않는다: 새 메모는 오늘 심사, 수정은 원래 값."""
    data = request.POST.copy()
    audit = memo.audit if memo else todays_audit(timezone.localdate())
    data['audit'] = audit.pk if audit else ''
    form = MemoForm(data, request.FILES, instance=memo)
    if not form.is_valid():
        errors = {k: [str(e) for e in v] for k, v in form.errors.items()}
        return Response({'detail': ' '.join(m for v in errors.values() for m in v), 'fields': errors}, status=400)
    with transaction.atomic():
        saved = form.save(commit=False)
        if not saved.pk:
            saved.author, saved.target = request.user, target
        saved.save()
        for f in form.cleaned_data['photos']:
            MemoPhoto.objects.create(memo=saved, file=f)
    return Response(_memo(saved, request.user), status=200 if memo else 201)


class MemoListView(APIView):
    """?ct=app.model&id=pk 면 그 기록의 메모, 없으면 미분류 메모."""
    schema = None

    def get(self, request):
        target = _memo_target(request)  # 붙일 수 없는 종류는 404, 그 기록을 볼 권한이 없으면 403
        if target is None:
            require_perm(request.user, 'qms.view_memo')
            qs = Memo.objects.filter(content_type__isnull=True)
        else:
            qs = Memo.objects.filter(content_type__app_label=target._meta.app_label,
                                     content_type__model=target._meta.model_name, object_id=target.pk)
        return Response({
            'results': [_memo(m, request.user) for m in qs.select_related('author', 'audit').prefetch_related('photos')],
            'can_add': request.user.has_perm('qms.add_memo'),
            'speakers': [{'value': v, 'label': label} for v, label in Memo.SPEAKERS], 'kinds': list(TARGETS),
        })

    def post(self, request):
        require_perm(request.user, 'qms.add_memo')
        return _save(request, None, _memo_target(request))


class MemoEditView(APIView):
    schema = None

    def post(self, request, pk):
        memo = get_object_or_404(Memo, pk=pk)
        if memo.author_id != request.user.pk:
            raise PermissionDenied('메모는 작성자만 수정할 수 있습니다.')
        return _save(request, memo, memo.target)


class MemoLinkView(APIView):
    """미분류 메모를 종류 + 번호로 찾은 기록에 연결한다 (작성자 또는 메모 수정 권한자)."""
    schema = None

    def post(self, request, pk):
        require_perm(request.user, 'qms.view_memo')
        memo = get_object_or_404(Memo, pk=pk, content_type__isnull=True)
        if memo.author_id != request.user.pk and not request.user.has_perm('qms.change_memo'):
            raise PermissionDenied('메모는 작성자나 메모 수정 권한자만 연결할 수 있습니다.')
        if not isinstance(request.data, dict):
            return _bad(BAD_BODY)
        kind, number = request.data.get('kind'), request.data.get('number')
        if not isinstance(kind, str) or not isinstance(number, str):
            return _bad(BAD_BODY)
        target = resolve_target(kind, number, request.user)
        if target is None:
            return _bad(f'{kind} "{number.strip()}": 찾을 수 없습니다. 종류와 번호를 확인하세요.', 'number')
        memo.target = target
        memo.save()
        return Response({'detail': f'{kind} {target}에 연결했습니다.'})
