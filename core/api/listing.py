"""목록 정렬·필터(records 목록·검사 기록 목록 공통).

정렬: ?sort=열 또는 ?sort=-열. 필터: ?f_열=값(선택지), ?f_열_from=·?f_열_to=YYYY-MM-DD(날짜).
허용 목록에 없는 열·값은 무시한다(주소를 손으로 바꿔도 임의 조회식이 되지 않는다).
"""
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils.dateparse import parse_date

from core import recordspec

FK_OPTIONS = 200  # shortcut: 외래키 선택지는 목록에 있는 값 200개까지, 넘치면 검색으로 찾는다


def field_controls(model, names, base_qs):
    """모델의 실제 칸 → (정렬 식 dict, 필터 정의 list). 속성(next_due 등)은 뺀다."""
    sorts, filters = {}, []
    for n in names:
        try:
            f = model._meta.get_field(n)
        except FieldDoesNotExist:
            continue
        if not f.concrete or f.many_to_many:
            continue
        sorts[n] = n
        d = {'key': n, 'label': recordspec.label_of(model, n), 'type': 'choice', 'path': n}
        if f.choices:
            d['options'] = [{'value': str(v), 'label': str(lb)} for v, lb in f.flatchoices if v != '']
        elif isinstance(f, models.BooleanField):
            d['options'] = [{'value': '1', 'label': '예'}, {'value': '0', 'label': '아니오'}]
        elif f.is_relation:
            objs = f.related_model.objects.filter(pk__in=base_qs.values(n))[:FK_OPTIONS]
            d['options'] = [{'value': str(o.pk), 'label': str(o)} for o in objs]
        elif isinstance(f, models.DateField):  # DateTimeField 포함
            d.update(type='date', path=f'{n}__date' if isinstance(f, models.DateTimeField) else n)
        else:
            continue
        filters.append(d)
    return sorts, filters


def _day(s):
    try:
        return parse_date(s or '')
    except ValueError:  # 2026-13-01처럼 모양만 맞는 날짜
        return None


def apply(qs, params, sorts, filters, order):
    for d in filters:
        k = d['key']
        if d['type'] == 'choice':
            v = params.get(f'f_{k}')
            if v is not None and any(o['value'] == v for o in d['options']):
                qs = qs.filter(**{d['path']: v})
            continue
        for side, op in (('from', 'gte'), ('to', 'lte')):
            day = _day(params.get(f'f_{k}_{side}'))
            if day:
                qs = qs.filter(**{f"{d['path']}__{op}": day})
    s = params.get('sort', '')
    if s.lstrip('-') in sorts:
        qs = qs.order_by(('-' if s.startswith('-') else '') + sorts[s.lstrip('-')], *order)
    return qs


def public(filters):
    return [{k: d[k] for k in ('key', 'label', 'type') if k in d} | ({'options': d['options']} if 'options' in d else {})
            for d in filters]
