"""현장 메모: 오늘 심사 찾기, 미분류 메모의 대상 찾기, 입력 폼과 기록별 메모 목록."""
from django import forms
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils.http import urlencode

from core.views import MultiPhotoField

from .models import InternalAudit, Memo

# 미분류 메모를 연결할 대상 종류 → (모델 라벨, 번호 필드)
TARGETS = {
    'LOT': ('core.lot', 'number'),
    '부적합': ('core.nonconformance', 'number'),
    'CAPA': ('qms.capa', 'number'),
    '8D': ('qms.customerclaim', 'number'),
    'SCAR': ('qms.scar', 'number'),
    '문서': ('qms.document', 'number'),
    '품번': ('core.item', 'code'),
}

# 메모를 붙일 수 있는 기록: 연결 대상 + 메모 상자가 보이는 상세 화면
ATTACHABLE = {label for label, _ in TARGETS.values()} | {'qms.inspection', 'qms.internalaudit', 'qms.auditfinding'}


def target_url(obj):
    """기록 상세 화면 주소. LOT은 이력(타임라인) 화면."""
    if obj._meta.label_lower == 'core.lot':
        return f"{reverse('trace')}?{urlencode({'lot': obj.number})}"
    return reverse(f'admin:{obj._meta.app_label}_{obj._meta.model_name}_change', args=[obj.pk])


def todays_audit(today):
    """오늘 실시한 심사, 없으면 오늘 계획된 미실시 심사."""
    return (InternalAudit.objects.filter(performed_at=today).first()
            or InternalAudit.objects.filter(performed_at__isnull=True, planned_date=today).first())


def resolve_target(kind, number, user=None):
    """종류 + 번호 → 기록. user를 주면 그 사용자가 볼 수 없는 기록은 None."""
    if kind not in TARGETS:
        return None
    label, field = TARGETS[kind]
    n = (number or '').strip()  # 스캐너가 붙이는 공백·줄바꿈 제거
    if not n:
        return None
    model = apps.get_model(label)
    if user is not None and not user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}'):
        return None
    qs = model.objects
    return qs.filter(**{field: n}).first() or qs.filter(**{f'{field}__iexact': n}).first()


class MemoForm(forms.ModelForm):
    photos = MultiPhotoField(label='사진', required=False)

    class Meta:
        model = Memo
        fields = ['body', 'speaker_kind', 'speaker_name', 'audit']
        widgets = {'body': forms.Textarea(attrs={'rows': 3})}


def box_context(obj, user):
    """기록 상세 화면의 메모 상자: 붙은 메모(시간순)와 '메모' 버튼."""
    ct = ContentType.objects.get_for_model(obj)
    memos = (Memo.objects.filter(content_type=ct, object_id=obj.pk)
             .select_related('author', 'audit').prefetch_related('photos'))
    return {'obj': obj, 'ct': f'{ct.app_label}.{ct.model}', 'memos': memos, 'user': user,
            'can_add': user.has_perm('qms.add_memo')}
