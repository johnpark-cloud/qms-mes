"""admin·기존 뷰·API가 함께 쓰는 업무 규칙. 본문은 기존 admin·뷰 코드를 옮긴 것이다(docs/architecture-migration-plan.md 3.2)."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, models, transaction
from django.http import Http404
from django.utils import timezone

from .grid import collect_rows, record_version, table_version
from .models import BomLine, EditRequest, Hold, Nonconformance, RevisionLog, RoutingStep, is_approver
from .records import can_edit_locked, delete_record, edit_unlocked, is_locked

LOCKED_MSG = '잠긴 기록입니다. 수정 요청 후 승인받아야 수정할 수 있습니다.'


class Locked(ValidationError):
    """잠금 때문에 막힌 저장. API는 409로 바꾼다."""


class Stale(Exception):
    """다른 사람이 먼저 저장했다. API는 409로 바꾼다."""

    def __init__(self, msg='다른 사람이 먼저 고쳤습니다. 다시 불러오세요.'):
        super().__init__(msg)


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
    """잠금 규칙을 지키며 저장한다(승인 후 잠금·수정 승인 소모). 종결된 부적합도 모델 save 가드가 막는다."""
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
    """MRB 처분: data(DISPOSE_FIELDS)를 넣고 서명한 뒤 저장한다. 종결되면 보류 해제는 모델 save가 한다.
    비밀번호 오류와 필수칸 누락이 함께 있으면 admin처럼 두 문구를 함께 담아 낸다.
    admin보다 엄격한 점: 허용 외 칸 거부, 빈 처분('처분을 선택하세요.') 거부, full_clean 검사.
    실패해도 메모리의 nc 속성은 바뀐 채 남으므로 호출자는 다시 조회해야 한다."""
    if nc.closed_at:
        raise Locked(LOCKED_MSG)
    if extra := set(data) - set(DISPOSE_FIELDS):
        raise ValidationError('처분에서 바꿀 수 없는 칸: ' + ', '.join(sorted(extra)))
    if not data.get('disposition'):  # 처분 없는 서명은 admin 폼도 받지 않는다
        raise ValidationError('처분을 선택하세요.')
    for name, value in data.items():
        setattr(nc, name, value)
    errors = []
    try:
        sign_disposition(nc, user, password)
    except ValidationError as e:
        errors += e.messages
    if msg := missing_message(nc):
        errors.append(msg)
    if errors:  # admin 순서: 비밀번호, 보완 필요
        raise ValidationError(errors)
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


def check_edit_request(obj, kind, user):
    """수정·삭제 요청 대상인지 본다: 관리 화면 기록만, 보류(부적합과 함께만 삭제) 제외, 수정 요청은 잠긴 기록만, view_ 권한."""
    from django.contrib import admin
    model = type(obj)
    if not admin.site.is_registered(model) or model is Hold or kind not in (EditRequest.DELETE, EditRequest.EDIT):
        raise Http404
    if kind == EditRequest.EDIT and not is_locked(obj):
        raise Http404
    if not user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}'):
        raise PermissionDenied


def submit_edit_request(obj, user, kind, reason, password):
    """사유와 본인 비밀번호로 요청을 남긴다. 시스템 관리자는 요청과 동시에 승인·실행된다.
    돌려주는 값: (요청, 즉시 승인 실패 문구 또는 None). 예: 다른 기록이 참조 중이라 삭제 불가."""
    reason = reason.strip() if isinstance(reason, str) else ''
    if not reason:
        raise ValidationError('사유를 입력하세요.')
    if not user.check_password(password if isinstance(password, str) else ''):
        raise ValidationError('비밀번호가 맞지 않습니다.')
    req = EditRequest.objects.create(kind=kind, target=obj, object_repr=str(obj)[:200], reason=reason, requested_by=user)
    if user.is_superuser:
        try:
            req.decide(user, True)
        except ValidationError as e:
            return req, ' '.join(e.messages)
    return req, None


def _clean_texts(changes, reason):
    if not all(isinstance(v, str) or v is None for v in (changes, reason)):
        raise ValidationError('변경 내용과 사유는 글이어야 합니다.')
    changes, reason = (changes or '').strip(), (reason or '').strip()
    if not changes:
        raise ValidationError('변경 내용을 입력하세요.')
    if not reason:
        raise ValidationError('사유를 입력하세요.')
    return changes, reason


def _new_log(obj, user, label, changes, reason, **extra):
    changes, reason = _clean_texts(changes, reason)
    return RevisionLog.objects.create(
        content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk, object_repr=str(obj)[:200],
        label=label, changes=changes, reason=reason, requested_by=user, **extra)


def request_revision_log(obj, user, label, changes, reason):
    """개정 이력 신청(대기). 변경 내용과 사유는 비워 둘 수 없다."""
    return _new_log(obj, user, label, changes, reason)


@transaction.atomic
def confirm_revision_log(log, user, password):
    """승인자가 비밀번호를 다시 입력해 개정 이력을 확정한다. 확정 뒤에는 모델이 수정을 막는다."""
    if not is_approver(user):
        raise PermissionDenied('품질팀장만 승인할 수 있습니다.')
    if log.status == RevisionLog.CONFIRMED:
        raise ValidationError('이미 확정된 개정 이력입니다.')
    if not user.check_password(password):
        raise ValidationError('비밀번호가 맞지 않습니다.')
    log.status, log.approved_by, log.approved_at = RevisionLog.CONFIRMED, user, timezone.now()
    log.save()
    return log


@transaction.atomic
def approve_and_log(obj, user, password, label, changes, reason):
    """승인 서명과 확정 개정 이력을 한 트랜잭션으로 처리한다. 어느 쪽이 실패해도 둘 다 취소된다."""
    changes, reason = _clean_texts(changes, reason)  # 서명(승인)보다 먼저 검사해 obj를 건드리지 않는다
    approve(obj, user, password)
    return _new_log(obj, user, label, changes, reason, status=RevisionLog.CONFIRMED,
                    approved_by=user, approved_at=obj.approved_at)


ITEM_CHILDREN = [(BomLine, 'parent'), (RoutingStep, 'item')]


def item_version(item):
    return record_version(item, ITEM_CHILDREN)


def save_item(item, user, data, bom, routing, version):
    """품번 속성과 BOM·라우팅 줄을 한꺼번에 저장한다. 하나라도 잘못이면 아무것도 저장하지 않는다.
    오류 키는 bom.{줄}.{칸}, routing.{줄}.{칸}. 품번은 승인 대상이 아니어서 잠금이 없다."""
    with transaction.atomic():
        if version is not None and version != item_version(item):
            raise Stale()
        b_new, b_chg, b_del, errors = collect_rows(
            bom, {r.pk: r for r in item.bom_lines.all()}, lambda: BomLine(parent=item),
            {'component': 'fk', 'qty': 'number'}, 'bom', exclude=['parent'], unique=['component'])
        r_new, r_chg, r_del, e2 = collect_rows(
            routing, {r.pk: r for r in item.routing.all()}, lambda: RoutingStep(item=item),
            {'seq': 'int', 'process': 'fk'}, 'routing', exclude=['item'], unique=['seq'])
        errors.update(e2)

        perms = ['change_item']
        for model, new, chg, dele in (('bomline', b_new, b_chg, b_del), ('routingstep', r_new, r_chg, r_del)):
            perms += ['add_' + model] * bool(new) + ['change_' + model] * bool(chg) + ['delete_' + model] * bool(dele)
        if not all(user.has_perm(f'core.{p}') for p in perms):
            raise PermissionDenied('이 작업을 할 권한이 없습니다.')

        for f in ('code', 'name', 'item_type'):
            if f in data:
                if not isinstance(data[f], str):
                    errors[f] = ['글이어야 합니다.']
                else:
                    setattr(item, f, data[f].strip())
        if not any(k in errors for k in ('code', 'name', 'item_type')):
            try:
                item.full_clean()
            except ValidationError as e:
                errors.update(e.message_dict)
        if errors:
            raise ValidationError(errors)

        for r in b_del + r_del:
            r.delete()
        save_with_lock(item, user)
        # shortcut: 순서를 맞바꾸는 저장은 DB 고유 제약에 걸려 오류로 돌려준다(줄을 임시 값으로 옮기지 않음). 필요해지면 두 단계로 저장한다.
        for key, rows, msg in (('bom', b_chg + b_new, '같은 자품번이 이미 있습니다.'),
                               ('routing', r_chg + r_new, '순서를 맞바꿀 때는 두 번에 나눠 저장하세요.')):
            try:
                with transaction.atomic():  # 오류 뒤에도 바깥 트랜잭션이 깨끗이 되돌아가도록 세이브포인트로 감싼다
                    for r in rows:
                        r.save()
            except IntegrityError:
                raise ValidationError({key: [msg]})
    return item


def save_table(model, user, rows, fields, unique, version):
    """모델 전체를 한 표로 저장한다(공정·고객사별 기한). 오류 키는 rows.{줄}.{칸}. 하나라도 잘못이면 아무것도 바꾸지 않는다."""
    name = model._meta.model_name
    with transaction.atomic():
        new, chg, dele, errors = collect_rows(
            rows, {o.pk: o for o in model.objects.all()}, model, fields, 'rows', unique=unique)
        perms = ['add_' + name] * bool(new) + ['change_' + name] * bool(chg)
        if not all(user.has_perm(f'{model._meta.app_label}.{p}') for p in perms):
            raise PermissionDenied('이 작업을 할 권한이 없습니다.')
        if dele and not user.is_superuser:
            raise PermissionDenied('시스템 관리자만 삭제할 수 있습니다.')
        if version is not None and version != table_version(model):
            raise Stale()
        if errors:
            raise ValidationError(errors)
        for o in dele:
            delete_as(o, user)
        try:
            with transaction.atomic():
                for o in chg + new:
                    o.save()
        except IntegrityError:
            raise ValidationError({'rows': ['같은 값이 이미 있습니다. 값을 맞바꿀 때는 두 번에 나눠 저장하세요.']})


def close_record(obj, user):
    """「종결」(REC-09): 종결일을 서버가 넣고 모델 clean 규칙(8D 전 단계·SCAR 회신·CAPA 유효)이 같은 문구로 막는다."""
    if obj.closed_at:
        raise ValidationError('이미 종결된 기록입니다.')
    field = obj._meta.get_field('closed_at')
    obj.closed_at = timezone.now() if isinstance(field, models.DateTimeField) else timezone.localdate()
    try:
        save_with_lock(obj, user)
    except ValidationError:
        obj.closed_at = None
        raise
