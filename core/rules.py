"""admin·기존 뷰·API가 함께 쓰는 업무 규칙. 본문은 기존 admin·뷰 코드를 옮긴 것이다(docs/architecture-migration-plan.md 3.2)."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Nonconformance, is_approver
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
    locked = bool(obj.pk) and is_locked(obj)
    unlock = begin_edit(obj, user)
    try:  # 승인 후에도 어떤 칸이 열려 있는지는 모델의 save 가드가 정한다
        obj.save()
        for child in children:
            child._edit_unlocked = obj._edit_unlocked
            child.save()
    except ValidationError as e:
        if locked and not obj._edit_unlocked:
            raise Locked(LOCKED_MSG) from e
        raise
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


DISPOSE_FIELDS = ('disposition', 'customer_approval_ref', 'cost')


def sign_disposition(nc, user, password):
    """MRB 승인 서명: 본인 비밀번호를 다시 확인하고 승인자·승인 시각을 기록한다 (승인자 자격은 모델 clean이 본다)."""
    if not user.check_password(password):
        raise ValidationError('MRB 승인 비밀번호가 맞지 않습니다.')
    nc.approved_by, nc.approved_at = user, timezone.now()


def missing_message(nc):
    if missing := nc.missing_fields():
        return '보완 필요: ' + ', '.join(missing)


@transaction.atomic
def dispose_nc(nc, user, password, data):
    if nc.closed_at:
        raise Locked(LOCKED_MSG)
    if extra := set(data) - set(DISPOSE_FIELDS):
        raise ValidationError('처분에서 바꿀 수 없는 칸: ' + ', '.join(sorted(extra)))
    if not data.get('disposition'):  # 처분 없는 서명은 admin 폼도 받지 않는다
        raise ValidationError('처분을 선택하세요.')
    for name, value in data.items():
        setattr(nc, name, value)
    sign_disposition(nc, user, password)
    if msg := missing_message(nc):
        raise ValidationError(msg)
    nc.full_clean()
    nc.save()


def nc_locked_fields(nc, user):
    """종결된 부적합에서 읽기 전용인 모델 칸. 보류 인터록 칸은 관리자·수정 승인으로도 못 바꾼다."""
    if not nc or not nc.closed_at:
        return []
    if can_edit_locked(nc, user):
        return list(Nonconformance.INTERLOCK)
    return [f.name for f in nc._meta.fields if f.name not in Nonconformance.AFTER_APPROVAL]


def approve(obj, user, password):
    """승인 서명: 승인자가 비밀번호를 다시 입력해야 승인된다. Approvable 여부는 부르는 쪽이 먼저 본다."""
    if not is_approver(user):
        raise PermissionDenied('품질팀장만 승인할 수 있습니다.')
    if obj.is_approved:
        raise ValidationError('이미 승인된 기록입니다.')
    if not user.check_password(password):
        raise ValidationError('비밀번호가 맞지 않습니다.')
    prev = obj.approved_by, obj.approved_at
    obj.approved_by, obj.approved_at = user, timezone.now()
    try:
        obj.save()
    except ValidationError:  # 예: 고객 승인번호 없는 4M 변경
        obj.approved_by, obj.approved_at = prev
        raise
