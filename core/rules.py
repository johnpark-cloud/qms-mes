"""admin·기존 뷰·API가 함께 쓰는 업무 규칙. 본문은 기존 admin·뷰 코드를 옮긴 것이다(docs/architecture-migration-plan.md 3.2)."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import Nonconformance
from .records import can_edit_locked, delete_record, edit_unlocked, is_locked

LOCKED_MSG = '잠긴 기록입니다. 수정 요청 후 승인받아야 수정할 수 있습니다.'


class Locked(ValidationError):
    """잠금 때문에 막힌 저장. API는 409로 바꾼다."""


def begin_edit(obj, user):
    """obj의 잠금 해제 여부(_edit_unlocked)를 정하고, 이번 저장이 쓸 수정 승인을 돌려준다 (새 기록이면 None)."""
    unlock = edit_unlocked(obj, user) if obj.pk else None
    obj._edit_unlocked = bool(unlock) or user.is_superuser
    return unlock


def finish_edit(unlock):
    if unlock:  # 저장이 성공했을 때만 잠금 해제를 소모한다
        unlock.status = unlock.USED
        unlock.save()


@transaction.atomic
def save_with_lock(obj, user, children=()):
    unlock = begin_edit(obj, user)
    # 폼이 없으므로 admin의 '폼 변경 없음' 판정 대신, 잠기고 해제되지 않은 저장은 항상 막는다
    if obj.pk and is_locked(obj) and not obj._edit_unlocked:
        raise Locked(LOCKED_MSG)
    obj.save()
    for child in children:
        child._edit_unlocked = obj._edit_unlocked
        child.save()
    finish_edit(unlock)


def delete_as(obj, user):
    if not user.is_superuser:
        raise PermissionDenied('시스템 관리자만 삭제할 수 있습니다.')
    delete_record(obj)


def child_editable(parent, user):
    """하위 항목(검사항목·사진 등)을 고칠 수 있는가. 부적합은 종결 여부, 그 밖은 승인 잠금 기준이다."""
    if parent is None:
        return True
    locked = bool(parent.closed_at) if isinstance(parent, Nonconformance) else is_locked(parent)
    return not locked or can_edit_locked(parent, user)
