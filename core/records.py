"""기록 삭제·잠금 규칙. 삭제·수정 요청(EditRequest)과 관리 화면(BaseAdmin)이 함께 쓴다."""
from django.contrib.admin.utils import NestedObjects
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .models import EditRequest, Hold, Nonconformance


@transaction.atomic
def delete_record(obj):
    if isinstance(obj, Nonconformance):
        # 이 부적합이 만든 보류만 지운다. 같은 LOT의 다른 부적합 보류는 그대로 남는다.
        Hold.objects.filter(nonconformance=obj).delete()
    obj.delete()


def blockers(obj):
    """삭제를 막는 PROTECT 참조 기록 (Django 삭제 확인 화면의 수집기 재사용). delete_record가 먼저 지우는 보류는 뺀다."""
    collector = NestedObjects(using='default')
    collector.collect([obj])
    own = set(Hold.objects.filter(nonconformance=obj)) if isinstance(obj, Nonconformance) else set()
    return [o for o in collector.protected if o not in own]


def edit_unlocked(obj, user):
    return EditRequest.objects.filter(kind=EditRequest.EDIT, status=EditRequest.APPROVED, requested_by=user,
                                      content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk).first()


def is_locked(obj):
    # Approvable과 (Task 4 이후) 부적합 모두 is_approved로 잠긴다
    return bool(getattr(obj, 'is_approved', False))
