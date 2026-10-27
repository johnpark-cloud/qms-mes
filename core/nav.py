"""사이드바 메뉴. (그룹명, [(라벨, url 이름, 필요 권한 또는 None)]) — 새 화면은 여기에 한 줄만 추가한다."""
NAV = [
    ('홈', [('내 할 일', 'todo', None)]),
    ('MES', [('LOT 이력', 'trace', None)]),
    ('QMS', [('검사 입력', 'inspect', 'qms.add_inspection'),
             ('부적합 등록', 'nc_quick', 'core.add_nonconformance'),
             ('품질 KPI', 'kpi', None),
             ('협력사', 'suppliers', None),
             ('심사 묶음', 'audit_pack', 'core.view_nonconformance'),
             ('미분류 메모', 'memo_inbox', 'qms.view_memo')]),
    ('개인', [('연차·급여', 'me', None)]),
]
