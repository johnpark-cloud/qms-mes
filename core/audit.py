"""감사 기록: simple-history 이력을 화면용으로 읽는다. 개인정보 앱(PRIVATE_APPS)은 보여 주지 않는다."""
from django.apps import apps

TYPES = {'+': '생성', '~': '변경', '-': '삭제'}
SECRET_FIELDS = {'password'}  # 지금 감사 대상 모델에는 없다. 생기면 값을 보여 주지 않는다.


def audited_models():
    from qms.models import PRIVATE_APPS  # core → qms는 함수 안에서만 가져온다
    return {f'{m._meta.app_label}.{m._meta.model_name}': m for m in apps.get_models()
            if hasattr(m, 'history') and m._meta.app_label not in PRIVATE_APPS}


def rows(model, object_id=None):
    qs = model.history.select_related('history_user').order_by('-history_date', '-history_id')
    return qs.filter(**{model._meta.pk.attname: object_id}) if object_id is not None else qs


def _who(u):
    return (u.get_full_name() or u.username) if u else ''


def row_payload(h):
    model = h.instance_type
    pk = model._meta.pk.attname
    changes = []
    if h.history_type == '~' and h.prev_record:
        for c in h.diff_against(h.prev_record).changes:
            if c.field in SECRET_FIELDS:
                continue
            changes.append({'field': str(model._meta.get_field(c.field).verbose_name),
                            'old': '' if c.old is None else str(c.old), 'new': '' if c.new is None else str(c.new)})
    try:
        repr_ = str(h.instance)
    except Exception:  # 지워진 관계 등으로 글자를 만들 수 없는 옛 기록
        repr_ = f'#{getattr(h, pk)}'
    return {'history_id': h.history_id, 'date': h.history_date.isoformat(), 'user': _who(h.history_user),
            'type': TYPES[h.history_type], 'object_id': getattr(h, pk), 'object_repr': repr_, 'changes': changes}
