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
    sign: tuple = ()  # 이 기록에서만 서명 칸인 것(SIGN_FIELDS에 더한다)
    close: bool = False  # 「종결」 버튼(POST …/close/): 서버가 종결일을 넣고 모델 clean 규칙이 막는다(REC-09)


# 승인 서명·판정 경로로만 바뀌는 칸. 범용 저장(PATCH)은 이 칸을 받지 않는다(REC-06).
# 보류 해제는 처분으로만, 종결은 「종결」 API로만 바뀐다(REC-08·09). 기록별 서명 칸은 설명서 sign에 둔다
SIGN_FIELDS = frozenset({'approved_by', 'approved_at', 'judgment', 'result', 'decided_by', 'decided_at', 'closed_at',
                         'released_at'})
# verbose_name이 없는 모델 칸·속성의 화면 이름 (마이그레이션 없이)
LABELS = {'core.hold': {'lot': 'LOT', 'nonconformance': '부적합', 'created_at': '보류 일시', 'released_at': '해제 일시'},
          'qms.capa': {'source_record': '출처 기록', 'status': '상태'},
          'qms.customerclaim': {'current_step': '현재 단계', 'containment_due': '봉쇄(D3) 기한', 'corrective_due': '대책(D5) 기한'},
          'qms.changerequest': {'first_article_state': '초품 합격'}}


def sign_fields(spec):
    return SIGN_FIELDS | set(spec.sign)


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
        sign=('disposition', 'customer_approval_ref'),  # MRB 처분(rules.dispose_nc)으로만
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
    # 외래키(담당자·확인자·LOT·부적합·거래처·품번)·날짜시간·비어 있을 수 있는 예/아니오(CAPA 유효성)는 관리 화면에서
    'qms.capa': Spec(
        fields=('number', 'title', 'source', 'source_record', 'status', 'owner', 'due_date', 'root_cause', 'action', 'done_at',
                'effective', 'verified_at', 'verified_by', 'verification_note', 'closed_at'),
        columns=('number', 'title', 'source', 'owner', 'due_date', 'closed_at'),
        search=('number', 'title', 'root_cause', 'action'),
        tabs=(('open', '진행', lambda qs: qs.filter(closed_at__isnull=True)), ALL,
              ('closed', '종결', lambda qs: qs.filter(closed_at__isnull=False))),
        edit=('title', 'source', 'root_cause', 'action', 'due_date', 'done_at', 'verified_at', 'verification_note'),
        close=True),
    'qms.customerclaim': Spec(
        fields=('number', 'customer', 'partner', 'lot', 'description', 'defect_qty', 'received_at', 'nonconformance',
                'current_step', 'containment_due', 'corrective_due', 'd1_team', 'd2_problem', 'd3_containment', 'd4_root_cause',
                'd5_corrective', 'd6_verification', 'd7_prevention', 'd8_closure', 'closed_at'),
        columns=('number', 'customer', 'lot', 'received_at', 'current_step', 'closed_at'),
        search=('number', 'customer', 'lot__number'),
        tabs=(('open', '진행', lambda qs: qs.filter(closed_at__isnull=True)), ALL,
              ('closed', '종결', lambda qs: qs.filter(closed_at__isnull=False))),
        order=('-received_at', '-pk'),
        edit=('customer', 'description', 'defect_qty', 'd1_team', 'd2_problem', 'd3_containment', 'd4_root_cause',
              'd5_corrective', 'd6_verification', 'd7_prevention', 'd8_closure'),
        close=True),
    'qms.customerrule': Spec(
        fields=('customer', 'partner', 'containment_hours', 'corrective_days'),
        columns=('customer', 'containment_hours', 'corrective_days'),
        search=('customer',),
        side=('relations', 'history'),
        order=('customer',),
        edit=('customer', 'containment_hours', 'corrective_days')),
    'qms.scar': Spec(
        fields=('number', 'supplier', 'partner', 'lot', 'nonconformance', 'request', 'issued_at', 'response_due', 'response',
                'responded_at', 'closed_at'),
        columns=('number', 'supplier', 'lot', 'issued_at', 'response_due', 'responded_at', 'closed_at'),
        search=('number', 'supplier', 'lot__number'),
        tabs=(('open', '진행', lambda qs: qs.filter(closed_at__isnull=True)), ALL,
              ('closed', '종결', lambda qs: qs.filter(closed_at__isnull=False))),
        order=('-issued_at', '-pk'),
        edit=('supplier', 'request', 'issued_at', 'response_due', 'response', 'responded_at'),
        close=True),
    'qms.changerequest': Spec(  # 출하 차단(초품 합격 전)은 Shipment.clean 그대로
        fields=('number', 'item', 'category', 'description', 'customer_notice', 'customer_approval_ref', 'effective_at',
                'approved_by', 'approved_at', 'first_article_state'),
        columns=('number', 'item', 'category', 'effective_at', 'approved_at'),
        search=('number', 'item__code', 'description'),
        tabs=(ALL, ('draft', '초안', lambda qs: qs.filter(approved_at__isnull=True)),
              ('approved', '승인됨', lambda qs: qs.filter(approved_at__isnull=False))),
        order=('-effective_at', '-pk'),
        edit=('category', 'description', 'customer_notice', 'customer_approval_ref')),
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
    if field is not None and getattr(field, 'choices', None):
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
