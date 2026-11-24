"""기록 설명서: 모델 하나를 새 기록 화면(/app/r/<app>/<model>/<id>)으로 여는 데 필요한 것을 모은다(REC-01).

설명서를 SPECS에 등록하면 records API·기록 화면·record_url 링크가 함께 따라온다. 등록되지 않은 모델은 404.
core는 qms 모델을 import하지 않는다('app.model' 라벨만). 삭제·잠금 규칙은 core/records.py에 있다(건드리지 않는다).
"""
import datetime
import decimal
import json
from typing import Callable, NamedTuple

from django.apps import apps
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
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
    # 기록 화면에서 고칠 수 있는 칸(fields의 부분집합, 외래키 가능). 서명·처분·보류 인터록 칸, 자동 번호, 붙어 있는 부모(문서·심사·PPAP 등),
    # 출하·실적의 LOT(보류 인터록), 정체를 바꾸는 칸(LOT·작업지시의 품번, 코드값·부서·거래처 코드), 파일·JSON 칸은 넣지 않는다. 규칙은 모델 clean/save가 막는다
    edit: tuple = ()
    sign: tuple = ()  # 이 기록에서만 서명 칸인 것(SIGN_FIELDS에 더한다)
    close: bool = False  # 「종결」 버튼(POST …/close/): 서버가 종결일을 넣고 모델 clean 규칙이 막는다(REC-09)
    lock_parent: str = ''  # 이 부모가 승인되면 잠긴다(예: PPAP 요소). 기록 화면에서는 시스템 관리자도 못 고친다(REC-10)
    create: tuple = ()  # 기록 화면 「새로 만들기」 칸(외래키 가능). 비면 관리 화면 추가 폼. 규칙은 모델 clean/save가 막는다
    hidden: tuple = ()  # create 중 화면에 안 보이고 주소(?키=값)로만 채우는 칸(예: CAPA 출처 기록)
    groups: tuple = ()  # (이름, 예/아니오 칸들): 한 줄에 체크 상자로 모아 보인다
    body: str = ''  # 긴 본문 칸: 칸 표가 아니라 아래 「본문」 구역(편집·이전 개정과 비교, 모델 previous), 양식지 본문(W7)


# 승인 서명·판정 경로로만 바뀌는 칸. 범용 저장(PATCH)은 이 칸을 받지 않는다(REC-06).
# 보류 해제는 처분으로만, 종결은 「종결」 API로만 바뀐다(REC-08·09). 기록별 서명 칸은 설명서 sign에 둔다
SIGN_FIELDS = frozenset({'approved_by', 'approved_at', 'judgment', 'result', 'decided_by', 'decided_at', 'closed_at',
                         'released_at'})
# verbose_name이 없는 모델 칸·속성의 화면 이름 (마이그레이션 없이)
LABELS = {'core.hold': {'lot': 'LOT', 'nonconformance': '부적합', 'created_at': '보류 일시', 'released_at': '해제 일시'},
          'qms.capa': {'source_record': '출처 기록', 'status': '상태'},
          'qms.customerclaim': {'current_step': '현재 단계', 'containment_due': '봉쇄(D3) 기한', 'root_cause_due': '원인(D4) 기한',
                                'corrective_due': '대책(D5) 기한', 'closure_due': '종결(D8) 기한', 'step_status': '단계별 기한',
                                'delay': '지연'},
          'qms.changerequest': {'first_article_state': '초품 합격'},
          'qms.ppapelement': {'record': '증적 기록'},
          'qms.evidence': {'record': '증적 기록'},
          'core.workorder': {'progress': '진도율(%)'}}


# 여러 줄 표 칸(JSON 목록): 열 (키, 이름). 기록 화면에서 줄을 더하고 뺀다. 검사는 모델 clean이 한다
# 증적 기록으로 고를 수 있는 기록(W4) → 품목을 가리키는 경로. 개인·인증 기록은 넣지 않는다.
EVIDENCE_RECORDS = {'qms.controlplan': 'item', 'qms.inspectionspec': 'item', 'qms.inspection': 'lot__item',
                    'qms.changerequest': 'item'}
EVIDENCE_LIMIT = 50  # 종류마다 최근 기록만 고를 수 있게 보인다

# 승인 서명만 넣는 선택지: 수정 드롭다운에서 뺀다(모델 clean도 막는다)
SIGN_CHOICES = {'qms.changerequest': {'stage': {'APPROVED'}}}
# 양식지 끝에 변경 이력(simple-history)을 「개정 이력」 표로 붙이는 기록
HISTORY_DOCS = {'qms.changerequest'}

ROWS = {'core.partner': {'contacts': (('role', '업무'), ('name', '이름'), ('phone', '전화'), ('email', '이메일'))}}


def groups_of(spec):
    return [{'label': label, 'keys': list(keys)} for label, keys in spec.groups]


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
        edit=('number', 'title', 'doc_type'),
        create=('number', 'title', 'doc_type')),
    'qms.documentrevision': Spec(
        fields=('document', 'revision', 'file', 'change_note', 'created_at', 'approved_by', 'approved_at', 'body'),
        columns=('document', 'revision', 'created_at', 'approved_at'),
        search=('document__number', 'document__title', 'revision'),
        tabs=(ALL, ('draft', '초안', lambda qs: qs.filter(approved_at__isnull=True)),
              ('approved', '승인됨', lambda qs: qs.filter(approved_at__isnull=False))),
        side=('relations', 'files', 'history'),
        order=('-created_at', '-pk'),
        edit=('revision', 'change_note', 'body'),
        create=('document', 'revision', 'file', 'change_note', 'body'),
        body='body'),
    'qms.gauge': Spec(
        fields=('number', 'name', 'kind', 'maker', 'model_no', 'serial_no', 'measuring_range', 'resolution',
                'department', 'location', 'owner', 'cal_type', 'cal_agency', 'interval_months', 'last_calibrated', 'next_due',
                'certificate', 'active'),
        columns=('number', 'name', 'kind', 'location', 'last_calibrated', 'next_due', 'active'),
        search=('number', 'name', 'kind', 'maker', 'model_no', 'serial_no', 'location'),
        tabs=(('active', '사용', lambda qs: qs.filter(active=True)), ALL,
              ('inactive', '사용 중지', lambda qs: qs.filter(active=False))),
        children=(Child('calibrations', '교정 이력', ('calibrated_on', 'cal_type', 'agency', 'result', 'cert_no', 'certificate', 'note'),
                        ('-calibrated_on', '-pk')),),
        side=('relations', 'files', 'history'),
        order=('number',),
        # 최근 교정일은 교정 이력(합격)으로 바뀌는 것이 원칙이나, 이력 없이 쓰던 대장을 위해 직접 고치는 칸도 둔다
        edit=('number', 'name', 'kind', 'maker', 'model_no', 'serial_no', 'measuring_range', 'resolution', 'department', 'location',
              'owner', 'cal_type', 'cal_agency', 'interval_months', 'last_calibrated', 'active'),
        create=('number', 'name', 'kind', 'maker', 'model_no', 'serial_no', 'measuring_range', 'resolution', 'department',
                'location', 'owner', 'cal_type', 'cal_agency', 'interval_months', 'last_calibrated', 'active')),
    'qms.gaugecalibration': Spec(
        fields=('gauge', 'calibrated_on', 'cal_type', 'agency', 'result', 'cert_no', 'certificate', 'note'),
        columns=('gauge', 'calibrated_on', 'cal_type', 'agency', 'result', 'cert_no'),
        search=('gauge__number', 'gauge__name', 'agency', 'cert_no'),
        tabs=(ALL, ('fail', '불합격', lambda qs: qs.filter(result='FAIL'))),
        side=('relations', 'files', 'history'),
        order=('-calibrated_on', '-pk'),
        # 결과·교정일은 계측기 대장을 바꾸므로 등록 후 고치지 않는다(잘못 넣었으면 새 이력으로 바로잡는다)
        edit=('agency', 'cert_no', 'note'),
        create=('gauge', 'calibrated_on', 'cal_type', 'agency', 'result', 'cert_no', 'note')),
    'qms.qualification': Spec(
        fields=('user', 'inspection_type', 'valid_until', 'basis', 'record'),
        columns=('user', 'inspection_type', 'valid_until', 'basis'),
        search=('user__username', 'user__first_name', 'user__last_name', 'basis'),
        tabs=(('valid', '유효', lambda qs: qs.filter(valid_until__gte=_today())), ALL,
              ('expired', '만료', lambda qs: qs.filter(valid_until__lt=_today()))),
        side=('relations', 'files', 'history'),
        order=('-valid_until', '-pk'),
        edit=('inspection_type', 'valid_until', 'basis', 'user'),
        create=('user', 'inspection_type', 'valid_until', 'basis')),
    'core.lot': Spec(
        fields=('number', 'item', 'work_order', 'is_serial', 'qty', 'supplier', 'partner', 'created_at'),
        columns=('number', 'item', 'qty', 'supplier', 'created_at'),
        search=('number', 'item__code', 'supplier'),
        tabs=(ALL, ('hold', '보류 중', lambda qs: qs.filter(holds__released_at__isnull=True).distinct())),
        children=(Child('nonconformances', '부적합', ('number', 'defect_type', 'disposition', 'closed_at'), ('-detected_at', '-pk')),
                  Child('holds', '보류', ('nonconformance', 'created_at', 'released_at'), ('-created_at', '-pk'))),
        order=('-created_at', '-pk'),
        edit=('number', 'is_serial', 'qty', 'supplier', 'work_order', 'partner'),
        create=('number', 'item', 'qty', 'supplier', 'partner', 'work_order', 'is_serial')),
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
        # LOT·발견 일시는 보류 인터록 칸, 비용은 처분 칸이라 넣지 않는다 (종결 뒤에는 모델이 막는다)
        edit=('origin', 'defect_type', 'defect_qty', 'inspected_qty', 'description', 'measured_value', 'special_char',
              'contained_qty', 'sorting_result', 'customer_notify', 'customer_notified_on', 'process', 'detected_by', 'capa_required')),
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
        edit=('title', 'source', 'root_cause', 'action', 'due_date', 'done_at', 'verified_at', 'verification_note', 'owner', 'effective', 'verified_by'),
        close=True,
        create=('title', 'source', 'owner', 'due_date', 'action', 'root_cause', 'source_type', 'source_id'),
        hidden=('source_type', 'source_id')),
    'qms.customerclaim': Spec(
        fields=('number', 'customer', 'partner', 'lot', 'description', 'defect_qty', 'received_at', 'nonconformance',
                'current_step', 'delay', 'containment_due', 'root_cause_due', 'corrective_due', 'closure_due', 'step_status', 'd1_team', 'd2_problem', 'd3_containment', 'd4_root_cause',
                'd5_corrective', 'd6_verification', 'd7_prevention', 'd8_closure', 'closed_at'),
        columns=('number', 'customer', 'lot', 'received_at', 'current_step', 'delay', 'closed_at'),
        search=('number', 'customer', 'lot__number'),
        tabs=(('open', '진행', lambda qs: qs.filter(closed_at__isnull=True)), ALL,
              ('closed', '종결', lambda qs: qs.filter(closed_at__isnull=False))),
        order=('-received_at', '-pk'),
        edit=('customer', 'description', 'defect_qty', 'd1_team', 'd2_problem', 'd3_containment', 'd4_root_cause',
              'd5_corrective', 'd6_verification', 'd7_prevention', 'd8_closure', 'partner', 'lot', 'received_at'),
        close=True,
        create=('number', 'customer', 'partner', 'lot', 'description', 'defect_qty', 'received_at')),
    'qms.customerrule': Spec(
        fields=('customer', 'partner', 'containment_hours', 'root_cause_days', 'corrective_days', 'closure_days'),
        columns=('customer', 'containment_hours', 'root_cause_days', 'corrective_days', 'closure_days'),
        search=('customer',),
        side=('relations', 'history'),
        order=('customer',),
        edit=('customer', 'containment_hours', 'root_cause_days', 'corrective_days', 'closure_days', 'partner'),
        create=('customer', 'partner', 'containment_hours', 'root_cause_days', 'corrective_days', 'closure_days')),
    'qms.scar': Spec(
        fields=('number', 'supplier', 'partner', 'lot', 'nonconformance', 'request', 'issued_at', 'response_due', 'response',
                'responded_at', 'closed_at'),
        columns=('number', 'supplier', 'lot', 'issued_at', 'response_due', 'responded_at', 'closed_at'),
        search=('number', 'supplier', 'lot__number'),
        tabs=(('open', '진행', lambda qs: qs.filter(closed_at__isnull=True)), ALL,
              ('closed', '종결', lambda qs: qs.filter(closed_at__isnull=False))),
        order=('-issued_at', '-pk'),
        edit=('supplier', 'request', 'issued_at', 'response_due', 'response', 'responded_at', 'partner', 'lot', 'nonconformance'),
        close=True,
        create=('number', 'supplier', 'partner', 'lot', 'nonconformance', 'request', 'issued_at', 'response_due')),
    'qms.changerequest': Spec(  # 출하 차단(초품 합격 전)은 Shipment.clean 그대로. 단계·고객 승인 규칙은 ChangeRequest.clean(W6)
        fields=('number', 'item', 'category', 'stage', 'effective_at', 'description', 'customer_notice', 'customer_status',
                'customer_approval_ref', 'reviewer', 'reviewed_at', 'review_comment', 'approved_by', 'approved_at',
                'first_article_state'),
        columns=('number', 'item', 'category', 'stage', 'customer_status', 'effective_at', 'approved_at'),
        search=('number', 'item__code', 'description'),
        tabs=(ALL, ('draft', '진행 중', lambda qs: qs.filter(approved_at__isnull=True).exclude(stage__in=('HOLD', 'REJECTED'))),
              ('hold', '보류·반려', lambda qs: qs.filter(approved_at__isnull=True, stage__in=('HOLD', 'REJECTED'))),
              ('approved', '승인됨', lambda qs: qs.filter(approved_at__isnull=False))),
        order=('-effective_at', '-pk'),
        edit=('category', 'stage', 'description', 'customer_notice', 'customer_status', 'customer_approval_ref', 'item',
              'effective_at', 'reviewer', 'reviewed_at', 'review_comment'),
        create=('number', 'item', 'category', 'description', 'customer_notice', 'customer_approval_ref', 'effective_at',
                'reviewer')),
    'qms.internalaudit': Spec(  # 종결 규칙(실시일, CAPA 없는 중·경부적합)은 InternalAudit.clean 그대로
        fields=('name', 'kind', 'scope', 'checklist', 'planned_date', 'auditor', 'auditee', 'auditor_user', 'auditee_dept',
                'performed_at', 'closed_at'),
        columns=('name', 'kind', 'planned_date', 'auditor', 'performed_at', 'closed_at'),
        search=('name', 'auditor', 'auditee'),
        tabs=(('open', '진행', lambda qs: qs.filter(closed_at__isnull=True)), ALL,
              ('closed', '종결', lambda qs: qs.filter(closed_at__isnull=False))),
        children=(Child('findings', '발견사항', ('clause', 'grade', 'description', 'capa'), ('pk',)),),
        order=('-planned_date', '-pk'),
        edit=('name', 'kind', 'scope', 'planned_date', 'auditor', 'auditee', 'performed_at', 'checklist', 'auditor_user', 'auditee_dept'),
        close=True,
        create=('name', 'kind', 'scope', 'checklist', 'planned_date', 'auditor', 'auditee', 'auditor_user', 'auditee_dept')),
    'qms.auditfinding': Spec(  # CAPA 연결은 「CAPA 만들기」 → Capa.save가 지적에 건다
        fields=('audit', 'clause', 'grade', 'description', 'capa'),
        columns=('audit', 'clause', 'grade', 'capa'),
        search=('clause', 'description', 'audit__name'),
        edit=('clause', 'grade', 'description', 'capa'),
        create=('audit', 'clause', 'grade', 'description')),
    'qms.auditchecklist': Spec(
        fields=('name', 'standard'),
        columns=('name', 'standard'),
        search=('name', 'standard'),
        children=(Child('items', '심사 항목', ('clause', 'requirement'), ('clause', 'pk')),),
        side=('relations', 'files', 'history'),
        order=('name',),
        edit=('name', 'standard'),
        create=('name', 'standard')),
    'qms.audititem': Spec(
        fields=('checklist', 'clause', 'requirement'),
        columns=('checklist', 'clause', 'requirement'),
        search=('clause', 'requirement', 'checklist__name'),
        children=(Child('evidences', '증적', ('document', 'record', 'note'), ('pk',)),),
        side=('relations', 'files', 'history'),
        order=('checklist', 'clause'),
        edit=('clause', 'requirement'),
        create=('checklist', 'clause', 'requirement')),
    # 제출일·고객 승인일(PSW 승인 후 기록 칸)은 승인 후 잠금 때문에 승인 뒤에는 관리 화면에서
    'qms.ppapsubmission': Spec(
        fields=('item', 'customer', 'partner', 'level', 'reason', 'due_date', 'submitted_at', 'customer_approved_at',
                'approved_by', 'approved_at'),
        columns=('item', 'customer', 'level', 'due_date', 'submitted_at', 'approved_at'),
        search=('item__code', 'customer', 'reason'),
        tabs=(ALL, ('draft', '초안', lambda qs: qs.filter(approved_at__isnull=True)),
              ('approved', '승인됨', lambda qs: qs.filter(approved_at__isnull=False))),
        children=(Child('elements', 'PPAP 요소', ('number', 'name', 'requirement', 'document', 'record', 'note'), ('number',)),),
        edit=('customer', 'reason', 'due_date', 'submitted_at', 'customer_approved_at', 'item', 'partner', 'level'),
        create=('item', 'customer', 'partner', 'level', 'reason', 'due_date')),
    'qms.ppapelement': Spec(  # 증적 기록(일반 연결)은 EVIDENCE_RECORDS 안에서 고른다(W4)
        fields=('submission', 'number', 'name', 'requirement', 'document', 'record', 'note'),
        columns=('submission', 'number', 'name', 'requirement'),
        search=('name', 'submission__customer', 'submission__item__code'),
        side=('relations', 'history'),
        order=('submission', 'number'),
        edit=('requirement', 'note', 'document', 'record'),
        lock_parent='submission'),
    # 작업지시·실적·출하(REC-11): LOT·작업지시·공정 같은 외래키는 관리 화면에서만 — 보류·4M 인터록(모델 clean/save)이 그대로 막는다.
    # 새 등록도 관리 화면 추가 폼. 기록 화면은 수량·납기 정정만(모델 clean: 양품+불량 ≤ 투입, 이전 공정 실적)
    'core.workorder': Spec(
        fields=('number', 'item', 'process', 'planned_qty', 'due_date', 'status', 'progress'),
        columns=('number', 'item', 'planned_qty', 'due_date', 'status'),
        search=('number', 'item__code', 'item__name'),
        tabs=(('open', '진행', lambda qs: qs.exclude(status='DONE')), ALL, ('done', '완료', lambda qs: qs.filter(status='DONE'))),
        children=(Child('results', '작업 실적', ('step', 'lot', 'input_qty', 'good_qty', 'defect_qty', 'started_at'),
                        ('step__seq', 'started_at')),
                  Child('lots', 'LOT', ('number', 'qty', 'created_at'), ('-created_at', '-pk'))),
        edit=('planned_qty', 'due_date', 'status', 'process'),
        create=('number', 'item', 'process', 'planned_qty', 'due_date')),
    'core.workresult': Spec(
        fields=('work_order', 'step', 'lot', 'input_qty', 'good_qty', 'defect_qty', 'operator', 'started_at', 'ended_at'),
        columns=('work_order', 'step', 'lot', 'good_qty', 'defect_qty', 'started_at'),
        search=('work_order__number', 'lot__number'),
        order=('-started_at', '-pk'),
        edit=('input_qty', 'good_qty', 'defect_qty', 'operator', 'started_at', 'ended_at'),
        create=('work_order', 'step', 'lot', 'input_qty', 'good_qty', 'defect_qty')),
    'core.shipment': Spec(
        fields=('lot', 'customer', 'partner', 'qty', 'shipped_at'),
        columns=('lot', 'customer', 'qty', 'shipped_at'),
        search=('lot__number', 'customer'),
        order=('-shipped_at', '-pk'),
        edit=('customer', 'qty', 'partner', 'shipped_at'),
        create=('lot', 'partner', 'customer', 'qty')),
    # 기준정보: 코드·대상처럼 다른 기록이 가리키는 칸, 외래키, JSON(선택지·매핑)은 관리 화면에서
    'core.partner': Spec(
        fields=('code', 'name', 'is_customer', 'is_supplier', 'is_outsource', 'is_calibrator', 'contacts',
                'status', 'grade', 'evaluated_on', 'active', 'note'),
        columns=('code', 'name', 'is_customer', 'is_supplier', 'status', 'grade'),
        search=('code', 'name', 'contacts'),
        tabs=(ALL, ('customer', '고객', lambda qs: qs.filter(is_customer=True)),
              ('supplier', '공급', lambda qs: qs.filter(is_supplier=True))),
        children=(Child('certificates', '인증', ('standard', 'cert_no', 'valid_until', 'file'), ('valid_until',)),
                  Child('projects', '프로젝트', ('code', 'name', 'program', 'status'), ('code',))),
        order=('code',),
        edit=('name', 'is_customer', 'is_supplier', 'is_outsource', 'is_calibrator', 'contacts',
              'status', 'grade', 'evaluated_on', 'active', 'note'),
        create=('name', 'is_customer', 'is_supplier', 'is_outsource', 'is_calibrator', 'contacts', 'note'),  # 코드는 모델이 매긴다
        groups=(('구분', ('is_customer', 'is_supplier', 'is_outsource', 'is_calibrator')),)),
    'core.project': Spec(
        fields=('code', 'name', 'customer', 'program', 'status', 'start_date', 'end_date', 'active', 'note'),
        columns=('code', 'name', 'customer', 'program', 'status', 'start_date', 'end_date'),
        search=('code', 'name', 'program', 'customer__name'),
        tabs=(('open', '진행 중', lambda qs: qs.exclude(status='closed').filter(active=True)), ALL,
              ('closed', '종료', lambda qs: qs.filter(status='closed'))),
        children=(Child('items', '품목', ('code', 'name', 'item_type'), ('code',)),),
        order=('code',),
        edit=('name', 'customer', 'program', 'status', 'start_date', 'end_date', 'active', 'note'),
        create=('name', 'customer', 'program', 'status', 'start_date', 'end_date', 'note')),  # 코드는 모델이 매긴다
    'core.department': Spec(
        fields=('code', 'name', 'parent', 'manager', 'sort', 'active', 'note'),
        columns=('code', 'name', 'parent', 'manager', 'active'),
        search=('code', 'name'),
        children=(Child('children', '하위 부서', ('code', 'name', 'manager'), ('sort', 'code')),),
        order=('sort', 'code'),
        edit=('name', 'sort', 'active', 'note', 'parent', 'manager'),
        create=('code', 'name', 'parent', 'manager', 'sort', 'note')),
    'core.codevalue': Spec(
        fields=('group', 'code', 'name', 'parent', 'item_type', 'sort', 'active'),
        columns=('group', 'code', 'name', 'parent', 'active'),
        search=('code', 'name'),
        children=(Child('children', '하위 코드', ('code', 'name', 'active'), ('sort', 'code')),),
        side=('relations', 'history'),
        order=('group', 'sort', 'code'),
        edit=('name', 'item_type', 'sort', 'active', 'parent'),
        create=('group', 'code', 'name', 'parent', 'item_type', 'sort')),
    'core.numberrule': Spec(
        fields=('name', 'target', 'pattern', 'sort', 'active'),
        columns=('name', 'target', 'pattern', 'active'),
        search=('name', 'pattern'),
        side=('relations', 'history'),
        order=('target', 'sort'),
        edit=('name', 'pattern', 'sort', 'active'),
        create=('name', 'target', 'pattern', 'sort')),
    'core.fielddef': Spec(
        fields=('target', 'key', 'label', 'kind', 'choices', 'required', 'sort', 'active'),
        columns=('target', 'key', 'label', 'kind', 'active'),
        search=('key', 'label'),
        side=('relations', 'history'),
        order=('target', 'sort'),
        edit=('label', 'choices', 'required', 'sort', 'active'),  # 키·대상은 저장 후 못 바꾼다(모델 clean)
        create=('target', 'key', 'label', 'kind', 'choices', 'required', 'sort')),
    'qms.exceltemplate': Spec(
        fields=('name', 'target', 'file', 'mapping'),
        columns=('name', 'target', 'file'),
        search=('name',),
        side=('relations', 'history'),
        order=('name',),
        edit=('name',),
        create=('name', 'target', 'file', 'mapping')),
    'core.importprofile': Spec(
        fields=('name', 'target', 'header_row', 'mapping'),
        columns=('name', 'target', 'header_row'),
        search=('name',),
        side=('relations', 'history'),
        order=('name',),
        edit=('name', 'header_row'),
        create=('name', 'target', 'header_row', 'mapping')),
}


# 양식지(W3): 기록 화면 「양식지」 → A4 한 장(core/api/records.py document_of). (제목, ((구역, 칸들), ...)).
# 여기 없는 기록은 상세 칸 전부를 머리말 표로 그린다. 부적합·출하·PPAP는 모델 print_table 표(①~⑦·성적서·PSW)를 쓴다
DOCS = {
    'qms.documentrevision': ('문서', (('문서 정보', ('document', 'revision', 'created_at', 'change_note', 'file')),)),
    'qms.capa': ('시정조치 보고서(CAPA)', (
        ('개요', ('number', 'title', 'source', 'source_record', 'status', 'owner', 'due_date')),
        ('원인·대책', ('root_cause', 'action', 'done_at')),
        ('유효성 확인', ('effective', 'verified_by', 'verified_at', 'verification_note', 'closed_at')))),
    'qms.customerclaim': ('8D 보고서', (
        ('클레임', ('number', 'customer', 'partner', 'lot', 'received_at', 'defect_qty', 'nonconformance', 'description')),
        ('기한', ('current_step', 'delay', 'containment_due', 'root_cause_due', 'corrective_due', 'closure_due')),
        ('8D', ('d1_team', 'd2_problem', 'd3_containment', 'd4_root_cause', 'd5_corrective', 'd6_verification',
                'd7_prevention', 'd8_closure', 'closed_at')))),
    'qms.scar': ('공급자 시정조치 요구서(SCAR)', (
        ('요구', ('number', 'supplier', 'partner', 'lot', 'nonconformance', 'issued_at', 'response_due', 'request')),
        ('회신', ('response', 'responded_at', 'closed_at')))),
    'qms.changerequest': ('4M 변경 신청서', (
        ('변경', ('number', 'item', 'category', 'stage', 'effective_at', 'description')),
        ('고객', ('customer_notice', 'customer_status', 'customer_approval_ref')),
        ('검토', ('reviewer', 'reviewed_at', 'review_comment')),
        ('승인·초품', ('approved_by', 'approved_at', 'first_article_state')))),
    'qms.internalaudit': ('내부심사 보고서', (
        ('심사', ('name', 'kind', 'scope', 'checklist', 'planned_date', 'performed_at', 'closed_at')),
        ('심사원·피심사', ('auditor', 'auditor_user', 'auditee', 'auditee_dept')))),
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
        return {'next_due': '다음 교정 기한', 'current_revision': '최신 승인본'}.get(name, name)


def shown(o):
    """기록 글자. 사람은 아이디가 아니라 이름(다른 화면·API와 같은 표기)."""
    if isinstance(o, AbstractBaseUser):
        return o.get_full_name() or o.get_username()
    return str(o)


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
    cols = ROWS.get(obj._meta.label_lower, {}).get(name)
    if cols:  # 한 줄에 한 사람: "업무 이름 · 전화 · 이메일"
        return '\n'.join(' · '.join(x for x in (f"{r.get('role', '')} {r.get('name', '')}".strip(),
                                                *(r.get(k, '') for k, _ in cols[2:])) if x) for r in v), None
    if isinstance(v, models.Model):
        return shown(v), record_url(v)
    if isinstance(v, list) and all(isinstance(x, str) for x in v):  # 선택지 목록
        return ', '.join(v), None
    if isinstance(field, models.FileField):
        return (v.name.rsplit('/', 1)[-1], v.url) if v else ('', None)
    if isinstance(v, bool):
        return ('예' if v else '아니오'), None
    if isinstance(v, datetime.datetime):
        return timezone.localtime(v).strftime('%Y-%m-%d %H:%M'), None
    if isinstance(v, datetime.date):
        return v.isoformat(), None
    if isinstance(v, decimal.Decimal):  # 2000.000 → 2,000 (0 꼬리를 떼고 천 단위 쉼표)
        return f'{v.normalize():,f}', None
    if isinstance(v, dict):  # 열 매핑 같은 JSON: 한 줄에 한 쌍
        return '\n'.join(f'{k}: {x}' for k, x in v.items()), None
    return str(v), None


def generic_value(v):
    return f'{v._meta.label_lower}:{v.pk}' if v is not None else None


def evidence_choices(obj, label):
    """증적 후보 한 종류. PPAP 요소는 그 제출 품목의 기록만."""
    qs = apps.get_model(label).objects.order_by('-pk')
    sub = getattr(obj, 'submission', None)
    return qs.filter(**{EVIDENCE_RECORDS[label]: sub.item_id}) if sub else qs


def generic_target(obj, name, value):
    """editor가 낸 'app.model:pk'를 기록으로. 빈 값은 None, 지금 값은 그대로, 그 밖은 후보 안에서만."""
    current = getattr(obj, name)
    if not value:
        return None
    if value == generic_value(current):
        return current
    label, _, pk = str(value).partition(':')
    found = label in EVIDENCE_RECORDS and pk.isdigit() and evidence_choices(obj, label).filter(pk=pk).first()
    if not found:
        raise ValidationError({name: ['고를 수 없는 기록입니다.']})
    return found


def editor(obj, name):
    """수정 칸 하나의 입력 종류와 원래 값. 외래키는 폼 queryset(limit_choices_to 반영) 앞 CHOICE_LIMIT개 + 지금 값."""
    f = obj._meta.get_field(name)
    v = getattr(obj, name)
    if isinstance(f, GenericForeignKey):  # 증적 기록: 'app.model:pk'
        objs = [o for label in EVIDENCE_RECORDS for o in evidence_choices(obj, label)[:EVIDENCE_LIMIT]]
        if v is not None and v not in objs:
            objs.insert(0, v)
        return {'key': name, 'label': label_of(type(obj), name), 'type': 'choice', 'value': generic_value(v),
                'required': False, 'choices': [{'value': generic_value(o), 'label': f'{o._meta.verbose_name} · {o}'}
                                               for o in objs]}
    if f.is_relation:
        from django.forms import modelform_factory
        objs = list(modelform_factory(type(obj), fields=[name])().fields[name].queryset[:CHOICE_LIMIT])
        if v is not None and v not in objs:
            objs.insert(0, v)
        return {'key': name, 'label': str(f.verbose_name), 'type': 'choice', 'value': str(v.pk) if v else None,
                'required': not f.blank, 'choices': [{'value': str(o.pk), 'label': shown(o)} for o in objs]}
    cols = ROWS.get(obj._meta.label_lower, {}).get(name)
    if cols:
        return {'key': name, 'label': str(f.verbose_name), 'type': 'rows', 'value': v or [], 'required': False,
                'choices': None, 'columns': [{'key': k, 'label': n} for k, n in cols]}
    if isinstance(f, models.JSONField) and f.default is list:  # 글 목록(사용자 정의 칸 선택지): 입력하고 Enter
        return {'key': name, 'label': str(f.verbose_name), 'type': 'tags', 'value': v or [], 'required': False, 'choices': None}
    if isinstance(f, models.JSONField):  # 사전(셀·열 매핑): JSON 글로 적는다. 예시는 help
        return {'key': name, 'label': str(f.verbose_name), 'type': 'json', 'required': not f.blank, 'choices': None,
                'value': json.dumps(v, ensure_ascii=False, indent=2) if v else '', 'help': str(f.help_text)}
    if isinstance(f, models.FileField):  # 새로 만들기에서만(파일은 multipart로 보낸다)
        return {'key': name, 'label': str(f.verbose_name), 'type': 'file', 'value': None, 'required': not f.blank, 'choices': None}
    if f.choices:
        kind = 'choice'
    elif isinstance(f, models.BooleanField):
        kind = 'bool'
    elif isinstance(f, models.DateTimeField):
        kind, v = 'datetime', timezone.localtime(v).strftime('%Y-%m-%dT%H:%M') if v else None
    elif isinstance(f, models.DateField):
        kind, v = 'date', v.isoformat() if v else None
    elif isinstance(f, (models.IntegerField, models.DecimalField)):
        kind = 'int'  # 숫자 입력(소수 포함)
    elif isinstance(f, models.TextField):
        kind = 'text'
    else:
        kind = 'str'
    skip = SIGN_CHOICES.get(obj._meta.label_lower, {}).get(name, ())
    return {'key': name, 'label': str(f.verbose_name), 'type': kind, 'value': v, 'required': not f.blank,
            'choices': [{'value': k, 'label': str(n)} for k, n in f.choices if k not in skip] if f.choices else None}


CHOICE_LIMIT = 500  # shortcut: 외래키 선택지는 앞 500개만 — 기록이 더 많아지면 검색 API로 바꾼다


def creator(model, name, form):
    """새로 만들기 칸 하나. 외래키는 폼 queryset(limit_choices_to 반영)을 선택지로."""
    f = model._meta.get_field(name)
    if not f.is_relation:
        return editor(model(), name)
    qs = form.fields[name].queryset[:CHOICE_LIMIT]
    return {'key': name, 'label': str(f.verbose_name), 'type': 'choice', 'value': None, 'required': not f.blank,
            'choices': [{'value': str(o.pk), 'label': shown(o)} for o in qs]}


def cells(obj, names):
    return {n: value_of(obj, n)[0] for n in names}
