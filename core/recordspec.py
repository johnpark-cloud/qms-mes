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
    edit: tuple = ()  # 기록 화면에서 고칠 수 있는 칸(fields의 부분집합). 서명 칸은 넣지 않는다


# 승인 서명·판정 경로로만 바뀌는 칸. 범용 저장(PATCH)은 이 칸을 받지 않는다(REC-06).
# 부적합 처분은 MRB 서명(rules.dispose_nc)으로만, 보류 해제는 처분으로만 바뀐다(REC-08)
SIGN_FIELDS = frozenset({'approved_by', 'approved_at', 'judgment', 'result', 'decided_by', 'decided_at', 'closed_at',
                         'disposition', 'customer_approval_ref', 'released_at'})
# verbose_name이 없는 모델 칸의 화면 이름 (마이그레이션 없이)
LABELS = {'core.hold': {'lot': 'LOT', 'nonconformance': '부적합', 'created_at': '보류 일시', 'released_at': '해제 일시'}}


def _today():
    return timezone.localdate()


SPECS = {
    'qms.document': Spec(
        fields=('number', 'title', 'doc_type', 'current_revision'),
        columns=('number', 'title', 'doc_type'),
        search=('number', 'title', 'doc_type'),
        children=(Child('revisions', '개정 이력', ('revision', 'change_note', 'approved_at', 'file'), ('-created_at', '-pk')),),
        order=('number',),
        edit=('number', 'title', 'doc_type')),
    'qms.documentrevision': Spec(
        fields=('document', 'revision', 'file', 'change_note', 'created_at', 'approved_by', 'approved_at'),
        columns=('document', 'revision', 'created_at', 'approved_at'),
        search=('document__number', 'document__title', 'revision'),
        tabs=(ALL, ('draft', '초안', lambda qs: qs.filter(approved_at__isnull=True)),
              ('approved', '승인됨', lambda qs: qs.filter(approved_at__isnull=False))),
        side=('relations', 'files', 'history'),
        order=('-created_at', '-pk'),
        edit=('revision', 'change_note')),
    'qms.gauge': Spec(
        fields=('number', 'name', 'interval_days', 'last_calibrated', 'next_due', 'certificate', 'active'),
        columns=('number', 'name', 'last_calibrated', 'next_due', 'active'),
        search=('number', 'name'),
        tabs=(('active', '사용', lambda qs: qs.filter(active=True)), ALL,
              ('inactive', '사용 중지', lambda qs: qs.filter(active=False))),
        side=('relations', 'files', 'history'),
        order=('number',),
        edit=('number', 'name', 'interval_days', 'last_calibrated', 'active')),
    'qms.qualification': Spec(
        fields=('user', 'inspection_type', 'valid_until', 'basis', 'record'),
        columns=('user', 'inspection_type', 'valid_until', 'basis'),
        search=('user__username', 'user__first_name', 'user__last_name', 'basis'),
        tabs=(('valid', '유효', lambda qs: qs.filter(valid_until__gte=_today())), ALL,
              ('expired', '만료', lambda qs: qs.filter(valid_until__lt=_today()))),
        side=('relations', 'files', 'history'),
        order=('-valid_until', '-pk'),
        edit=('inspection_type', 'valid_until', 'basis')),
    'core.lot': Spec(
        fields=('number', 'item', 'work_order', 'is_serial', 'qty', 'supplier', 'partner', 'created_at'),
        columns=('number', 'item', 'qty', 'supplier', 'created_at'),
        search=('number', 'item__code', 'supplier'),
        tabs=(ALL, ('hold', '보류 중', lambda qs: qs.filter(holds__released_at__isnull=True).distinct())),
        children=(Child('nonconformances', '부적합', ('number', 'defect_type', 'disposition', 'closed_at'), ('-detected_at', '-pk')),
                  Child('holds', '보류', ('nonconformance', 'created_at', 'released_at'), ('-created_at', '-pk'))),
        order=('-created_at', '-pk'),
        edit=('number', 'is_serial', 'qty', 'supplier')),
    'core.nonconformance': Spec(
        fields=('number', 'origin', 'lot', 'process', 'detected_by', 'detected_at', 'defect_type', 'defect_qty', 'inspected_qty',
                'description', 'measured_value', 'special_char', 'contained_qty', 'sorting_result', 'customer_notify',
                'customer_notified_on', 'disposition', 'customer_approval_ref', 'cost', 'capa_required', 'approved_by',
                'approved_at', 'closed_at'),
        columns=('number', 'origin', 'lot', 'defect_type', 'detected_at', 'disposition', 'closed_at'),
        search=('number', 'lot__number', 'description', 'defect_type'),
        tabs=(('open', '진행', lambda qs: qs.filter(closed_at__isnull=True)), ALL,
              ('closed', '종결', lambda qs: qs.filter(closed_at__isnull=False))),
        children=(Child('holds', '보류', ('lot', 'created_at', 'released_at'), ('-created_at', '-pk')),
                  Child('photos', '사진', ('caption', 'file', 'uploaded_at'), ('pk',))),
        order=('-detected_at', '-pk'),
        # LOT·발견 일시는 보류 인터록 칸이라 관리 화면에서만 (종결 뒤에는 모델이 막는다)
        edit=('origin', 'defect_type', 'defect_qty', 'inspected_qty', 'description', 'measured_value', 'special_char',
              'contained_qty', 'sorting_result', 'customer_notify', 'customer_notified_on')),
    'core.hold': Spec(  # 읽기 전용: 부적합 등록으로 생기고 처분으로만 풀린다
        fields=('lot', 'nonconformance', 'created_at', 'released_at'),
        columns=('lot', 'nonconformance', 'created_at', 'released_at'),
        search=('lot__number', 'nonconformance__number'),
        tabs=(('active', '보류 중', lambda qs: qs.filter(released_at__isnull=True)), ALL,
              ('released', '해제', lambda qs: qs.filter(released_at__isnull=False))),
        side=('relations', 'history'),
        order=('-created_at', '-pk')),
}


def spec_of(label):
    return SPECS.get(label.lower())


def url_for(obj):
    """설명서가 있는 기록의 새 화면 주소, 없으면 None."""
    meta = obj._meta
    return f'/app/r/{meta.app_label}/{meta.model_name}/{obj.pk}' if meta.label_lower in SPECS else None


def label_of(model, name):
    if name in LABELS.get(model._meta.label_lower, {}):
        return LABELS[model._meta.label_lower][name]
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


def editor(obj, name):
    """수정 칸 하나의 입력 종류와 원래 값."""
    f = obj._meta.get_field(name)
    v = getattr(obj, name)
    if f.choices:
        kind = 'choice'
    elif isinstance(f, models.BooleanField):
        kind = 'bool'
    elif isinstance(f, models.DateField) and not isinstance(f, models.DateTimeField):
        kind, v = 'date', v.isoformat() if v else None
    elif isinstance(f, (models.IntegerField, models.DecimalField)):
        kind = 'int'  # 숫자 입력(소수 포함)
    elif isinstance(f, models.TextField):
        kind = 'text'
    else:
        kind = 'str'
    return {'key': name, 'label': str(f.verbose_name), 'type': kind, 'value': v, 'required': not f.blank,
            'choices': [{'value': k, 'label': str(n)} for k, n in f.choices] if f.choices else None}


def cells(obj, names):
    return {n: value_of(obj, n)[0] for n in names}
