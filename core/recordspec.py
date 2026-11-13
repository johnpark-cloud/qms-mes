"""기록 설명서: 모델 하나를 새 기록 화면(/app/r/<app>/<model>/<id>)으로 여는 데 필요한 것을 모은다(REC-01).

설명서를 SPECS에 등록하면 records API·기록 화면·record_url 링크가 함께 따라온다. 등록되지 않은 모델은 404.
core는 qms 모델을 import하지 않는다('app.model' 라벨만). 삭제·잠금 규칙은 core/records.py에 있다(건드리지 않는다).
"""
import datetime
from typing import Callable, NamedTuple

from django.db import models
from django.utils import timezone

ALL = ('all', '전체', None)


class Child(NamedTuple):
    accessor: str  # 역참조 이름(예: 'revisions')
    label: str
    fields: tuple
    order: tuple = ('-pk',)


class Spec(NamedTuple):
    fields: tuple  # 상세 칸(모델 필드 또는 속성 이름)
    columns: tuple  # 목록 열
    search: tuple = ()  # 목록 검색(icontains)
    tabs: tuple = (ALL,)  # (키, 이름, qs → qs). 첫 탭이 기본
    children: tuple = ()
    side: tuple = ('relations', 'memo', 'files', 'history')
    order: tuple = ('-pk',)


def _today():
    return timezone.localdate()


SPECS = {
    'qms.document': Spec(
        fields=('number', 'title', 'doc_type', 'current_revision'),
        columns=('number', 'title', 'doc_type'),
        search=('number', 'title', 'doc_type'),
        children=(Child('revisions', '개정 이력', ('revision', 'change_note', 'approved_at', 'file'), ('-created_at', '-pk')),),
        order=('number',)),
    'qms.documentrevision': Spec(
        fields=('document', 'revision', 'file', 'change_note', 'created_at', 'approved_by', 'approved_at'),
        columns=('document', 'revision', 'created_at', 'approved_at'),
        search=('document__number', 'document__title', 'revision'),
        tabs=(ALL, ('draft', '초안', lambda qs: qs.filter(approved_at__isnull=True)),
              ('approved', '승인됨', lambda qs: qs.filter(approved_at__isnull=False))),
        side=('relations', 'files', 'history'),
        order=('-created_at', '-pk')),
    'qms.gauge': Spec(
        fields=('number', 'name', 'interval_days', 'last_calibrated', 'next_due', 'certificate', 'active'),
        columns=('number', 'name', 'last_calibrated', 'next_due', 'active'),
        search=('number', 'name'),
        tabs=(('active', '사용', lambda qs: qs.filter(active=True)), ALL,
              ('inactive', '사용 중지', lambda qs: qs.filter(active=False))),
        side=('relations', 'files', 'history'),
        order=('number',)),
    'qms.qualification': Spec(
        fields=('user', 'inspection_type', 'valid_until', 'basis', 'record'),
        columns=('user', 'inspection_type', 'valid_until', 'basis'),
        search=('user__username', 'user__first_name', 'user__last_name', 'basis'),
        tabs=(('valid', '유효', lambda qs: qs.filter(valid_until__gte=_today())), ALL,
              ('expired', '만료', lambda qs: qs.filter(valid_until__lt=_today()))),
        side=('relations', 'files', 'history'),
        order=('-valid_until', '-pk')),
}


def spec_of(label):
    return SPECS.get(label.lower())


def url_for(obj):
    """설명서가 있는 기록의 새 화면 주소, 없으면 None."""
    meta = obj._meta
    return f'/app/r/{meta.app_label}/{meta.model_name}/{obj.pk}' if meta.label_lower in SPECS else None


def label_of(model, name):
    try:
        return str(model._meta.get_field(name).verbose_name)
    except Exception:  # 속성(next_due 등)
        return {'next_due': '다음 교정 기한', 'current_revision': '유효본'}.get(name, name)


def value_of(obj, name):
    """화면용 (글자, 링크). 선택지는 표시 이름, 외래키는 그 기록 주소, 파일은 내려받기 주소."""
    from .relations import record_url
    try:
        field = obj._meta.get_field(name)
    except Exception:
        field = None
    if field is not None and field.choices:
        return getattr(obj, f'get_{name}_display')(), None
    v = getattr(obj, name)
    if v is None or v == '':
        return '', None
    if isinstance(v, models.Model):
        return str(v), record_url(v)
    if isinstance(field, models.FileField):
        return (v.name.rsplit('/', 1)[-1], v.url) if v else ('', None)
    if isinstance(v, bool):
        return ('예' if v else '아니오'), None
    if isinstance(v, datetime.datetime):
        return timezone.localtime(v).strftime('%Y-%m-%d %H:%M'), None
    if isinstance(v, datetime.date):
        return v.isoformat(), None
    return str(v), None


def cells(obj, names):
    return {n: value_of(obj, n)[0] for n in names}
