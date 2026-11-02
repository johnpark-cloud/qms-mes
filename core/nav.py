"""사이드바 메뉴. (그룹명, [(라벨, url 이름, 필요 권한 또는 None)]) — 새 화면은 여기에 한 줄만 추가한다.
묶음은 업무 흐름 순서다(docs/ux-improvement-plan.md): 홈 → 생산(MES) → 품질(QMS) → 품질보증·개선 → 고객·협력사 → 분석 → 기준정보·관리.
한 기능은 한 묶음에만 둔다.
url 이름 뒤에 '?조건'을 붙이면 관리 목록을 그 조건으로 걸러 연다. 전체 메뉴(관리 첫 화면)도 이 묶음대로 보인다(core/admin.py)."""
from django.urls import reverse


def nav_url(name):
    """'url 이름?조건' → 실제 주소."""
    name, _, query = name.partition('?')
    return reverse(name) + (f'?{query}' if query else '')


def _inspections(kind):
    return f'admin:qms_inspection_changelist?spec__inspection_type__exact={kind}'


HOME = '통합 업무 홈'  # 늘 펼쳐 두는 묶음

NAV = [
    ('통합 업무 홈', [('내 할 일', 'todo', None),
                ('공장 종합현황', 'overview', None),
                ('미분류 메모', 'memo_inbox', 'qms.view_memo'),
                ('연차·급여', 'me', None)]),
    ('생산관리 (MES)', [('작업지시', 'admin:core_workorder_changelist', 'core.view_workorder'),
                   ('작업 실적', 'admin:core_workresult_changelist', 'core.view_workresult'),
                   ('LOT', 'admin:core_lot_changelist', 'core.view_lot'),
                   ('LOT 이력 조회', 'trace', None),
                   ('출하', 'admin:core_shipment_changelist', 'core.view_shipment')]),
    ('품질관리 (QMS)', [('검사 입력', 'inspect', 'qms.add_inspection'),
                   ('수입검사', _inspections('INCOMING'), 'qms.view_inspection'),
                   ('공정검사', _inspections('PROCESS'), 'qms.view_inspection'),
                   ('출하검사', _inspections('OUTGOING'), 'qms.view_inspection'),
                   ('계측기·교정', 'admin:qms_gauge_changelist', 'qms.view_gauge'),
                   ('검사원 자격', 'admin:qms_qualification_changelist', 'qms.view_qualification')]),
    ('품질보증 및 개선', [('부적합 등록', 'nc_quick', 'core.add_nonconformance'),
                    ('부적합', 'admin:core_nonconformance_changelist', 'core.view_nonconformance'),
                    ('보류', 'admin:core_hold_changelist', 'core.view_hold'),
                    ('CAPA(시정조치)', 'admin:qms_capa_changelist', 'qms.view_capa'),
                    ('4M 변경', 'admin:qms_changerequest_changelist', 'qms.view_changerequest'),
                    ('문서', 'admin:qms_document_changelist', 'qms.view_document'),
                    ('내부심사', 'admin:qms_internalaudit_changelist', 'qms.view_internalaudit'),
                    ('심사 체크리스트·증적', 'admin:qms_auditchecklist_changelist', 'qms.view_auditchecklist'),
                    ('심사 자료 출력', 'audit_pack', 'core.view_nonconformance')]),
    ('고객 및 협력사', [('고객 클레임(8D)', 'admin:qms_customerclaim_changelist', 'qms.view_customerclaim'),
                  ('협력사 시정요구(SCAR)', 'admin:qms_scar_changelist', 'qms.view_scar'),
                  ('PPAP', 'admin:qms_ppapsubmission_changelist', 'qms.view_ppapsubmission'),
                  ('협력사 평가', 'suppliers', 'qms.view_scar')]),
    ('분석 및 보고서', [('품질 KPI', 'kpi', 'qms.view_customerclaim'),
                  ('엑셀 보고서 양식', 'admin:qms_exceltemplate_changelist', 'qms.view_exceltemplate')]),
    ('기준정보 및 시스템 관리', [('품번·BOM·라우팅', 'admin:core_item_changelist', 'core.view_item'),
                       ('공정', 'admin:core_process_changelist', 'core.view_process'),
                       ('검사기준', 'admin:qms_inspectionspec_changelist', 'qms.view_inspectionspec'),
                       ('관리계획서', 'admin:qms_controlplan_changelist', 'qms.view_controlplan'),
                       ('고객사별 8D 기한', 'admin:qms_customerrule_changelist', 'qms.view_customerrule'),
                       ('엑셀 일괄 등록', 'import', 'core.view_importprofile'),
                       ('사용자', 'admin:auth_user_changelist', 'auth.view_user'),
                       ('전체 메뉴', 'admin:index', None)]),
]
