"""사이드바 메뉴. (그룹명 또는 None, [(라벨, url 이름, 필요 권한 또는 None)]) — 새 화면은 여기에 한 줄만 추가한다.
QMS·MES 구분 대신 하는 일 순서로 묶는다. 그룹명이 None이면 제목 없이 맨 위에 둔다."""
NAV = [
    (None, [('전체 메뉴', 'admin:index', None),
            ('내 할 일', 'todo', None)]),
    ('현장 기록', [('검사 입력', 'inspect', 'qms.add_inspection'),
               ('부적합 등록', 'nc_quick', 'core.add_nonconformance'),
               ('LOT 이력', 'trace', None)]),
    ('품질 관리', [('품질 KPI', 'kpi', 'qms.view_customerclaim'),
               ('협력사', 'suppliers', 'qms.view_scar'),
               ('미분류 메모', 'memo_inbox', 'qms.view_memo')]),
    ('심사 대응', [('심사 묶음', 'audit_pack', 'core.view_nonconformance')]),
    ('개인', [('연차·급여', 'me', None)]),
]
