"""관계 레지스트리: 어느 기록이든 그 기록을 가리키는 것(incoming)과 그 기록이 가리키는 것(outgoing)을 묶음으로 모은다.

모델 `_meta`에서 만들므로 새 표·새 외래키를 더해도 따로 등록하지 않는다.
core는 qms를 모듈 수준에서 import하지 않는다 (함수 안 import, apps.get_model).
"""
import math
from functools import cache
from typing import NamedTuple

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.urls import NoReverseMatch, reverse
from django.utils.http import urlencode

from .modules import active_set, module_of_model
from .recordspec import url_for

APPS = ('core', 'qms')
EXCLUDE = {'core.importprofile', 'qms.dashboardlayout'}
OPEN_FIRST = ['core.nonconformance', 'qms.capa', 'core.hold']
# 일반 연결(ContentType + id). (모델, 종류 칸, id 칸, 붙을 수 있는 대상 — None이면 모두)
GENERIC = [
    ('core.attachment', 'content_type', 'object_id', None),
    ('qms.memo', 'content_type', 'object_id', None),
    ('qms.evidence', 'record_type', 'record_id', None),
    ('qms.ppapelement', 'record_type', 'record_id', None),
    ('qms.capa', 'source_type', 'source_id',
     {'qms.customerclaim', 'qms.scar', 'qms.auditfinding', 'core.nonconformance'}),
]
FIRST, PAGE = 5, 20


class Relation(NamedTuple):
    key: str  # '<app.model>:<field>' (정방향은 뒤에 ':out')
    label: str
    model: type
    field: str
    direction: str  # 'in' | 'out'
    kind: str  # 'fk' | 'm2m' | 'generic'


def is_registered(label):
    """'app.model'이 연결·첨부를 붙일 수 있는 업무 모델인가. 개인 앱·이력·설정 표는 아니다."""
    try:
        app_label, name = label.lower().split('.')
        model = apps.get_model(app_label, name)
    except (ValueError, LookupError):
        return False
    return app_label in APPS and not model.__name__.startswith('Historical') and label.lower() not in EXCLUDE


def _label(model):
    return model._meta.label_lower


@cache
def relations_for(model):
    me = _label(model)
    rels = []
    incoming = [r for r in model._meta.related_objects
                if r.related_model is not None and is_registered(_label(r.related_model))]
    per_model = {}
    for r in incoming:
        per_model[r.related_model] = per_model.get(r.related_model, 0) + 1
    for r in incoming:
        other = r.related_model
        label = str(other._meta.verbose_name)
        if per_model[other] > 1:  # 같은 표에서 이 기록을 가리키는 칸이 둘 이상이면 칸 이름을 붙인다
            label = f'{label}({r.field.verbose_name})'
        rels.append(Relation(f'{_label(other)}:{r.field.name}', label, other, r.field.name, 'in',
                             'm2m' if r.many_to_many else 'fk'))
    for g_label, ct_field, _id, targets in GENERIC:
        if g_label != me and (targets is None or me in targets):
            other = apps.get_model(g_label)
            rels.append(Relation(f'{g_label}:{ct_field}', str(other._meta.verbose_name), other, ct_field, 'in', 'generic'))
    for f in model._meta.get_fields():
        if (f.is_relation and f.concrete and not f.auto_created and f.related_model is not None
                and (f.many_to_one or f.one_to_one or f.many_to_many) and is_registered(_label(f.related_model))):
            rels.append(Relation(f'{me}:{f.name}:out', str(f.verbose_name), f.related_model, f.name, 'out',
                                 'm2m' if f.many_to_many else 'fk'))
    return rels


def record_url(obj):
    """기록 상세 주소의 유일한 기준(REC-04): 전용 React 화면 → 기록 설명서 화면 → LOT 이력 → 관리 화면."""
    pages = {'core.item': 'items', 'qms.inspectionspec': 'specs', 'qms.controlplan': 'plans', 'qms.inspection': 'inspections'}
    label = _label(obj)
    if label in pages:
        return f'/app/{pages[label]}/{obj.pk}'
    url = url_for(obj)
    if url:
        return url
    if label == 'core.lot':
        return f"{reverse('trace')}?{urlencode({'lot': obj.number})}"
    try:
        return reverse(f'admin:{obj._meta.app_label}_{obj._meta.model_name}_change', args=[obj.pk])
    except NoReverseMatch:  # 관리 화면이 없는 표(측정값 등)는 링크 없이 글자만
        return None


def status_of(obj):
    names = {f.name for f in obj._meta.concrete_fields}
    if 'closed_at' in names:  # 부적합은 처분 승인과 종결이 함께라 종결·진행으로 보인다
        return '종결' if obj.closed_at else '진행'
    if 'approved_at' in names:
        return '승인됨' if obj.approved_at else '초안'
    if 'result' in names and hasattr(obj, 'get_result_display'):
        return obj.get_result_display() or '미판정'
    if 'released_at' in names:
        return '해제' if obj.released_at else '보류'
    if 'active' in names and not obj.active:
        return '사용 중지'
    return ''


def item_payload(obj):
    return {'id': obj.pk, 'text': str(obj), 'status': status_of(obj), 'url': record_url(obj)}


def _queryset(obj, rel):
    if rel.direction == 'out':
        if rel.kind == 'm2m':
            return getattr(obj, rel.field).all()
        target_id = getattr(obj, obj._meta.get_field(rel.field).attname)
        return rel.model._default_manager.filter(pk=target_id) if target_id else rel.model._default_manager.none()
    if rel.kind == 'generic':
        id_field = next(g[2] for g in GENERIC if g[0] == _label(rel.model))
        ct = ContentType.objects.get_for_model(obj)
        return rel.model._default_manager.filter(**{rel.field: ct, id_field: obj.pk})
    return rel.model._default_manager.filter(**{rel.field: obj.pk})


def group_payload(user, obj, rel, page=None, on=None):
    """묶음 하나. 사용자가 그 표를 볼 권한이 없으면 None (개수도 알리지 않는다)."""
    meta = rel.model._meta
    if not user.has_perm(f'{meta.app_label}.view_{meta.model_name}'):
        return None
    qs = _queryset(obj, rel).select_related().order_by('-pk')
    count = qs.count()
    if module_of_model(_label(rel.model)) not in (on if on is not None else active_set()):  # 꺼진 모듈: 건수만, 목록은 열지 않는다(MOD-11)
        return {'key': rel.key, 'label': rel.label, 'model': _label(rel.model), 'field': rel.field,
                'direction': rel.direction, 'count': count, 'items': [], 'inactive': True}
    rows = qs[:FIRST] if page is None else qs[(page - 1) * PAGE:page * PAGE]
    return {'key': rel.key, 'label': rel.label, 'model': _label(rel.model), 'field': rel.field,
            'direction': rel.direction, 'count': count, 'items': [item_payload(o) for o in rows]}


def pages(count):
    return max(1, math.ceil(count / PAGE))


def relations_payload(user, obj):
    groups, inactive, on = {'in': [], 'out': []}, 0, active_set()  # 묶음마다 조회하지 않는다
    for rel in relations_for(type(obj)):
        g = group_payload(user, obj, rel, on=on)
        if g and g.get('inactive'):
            inactive += g['count']
        elif g and g['count']:
            groups[rel.direction].append(g)
    first = {m: i for i, m in enumerate(OPEN_FIRST)}
    groups['in'].sort(key=lambda g: (first.get(g['model'], len(first)), -g['count']))
    return {'record': {'model': _label(obj), **item_payload(obj)}, 'incoming': groups['in'], 'outgoing': groups['out'],
            'inactive': inactive}
