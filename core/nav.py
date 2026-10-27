"""사이드바 메뉴. (그룹명, [(라벨, url 이름, 필요 권한 또는 None)]) — 새 화면은 여기에 한 줄만 추가한다."""
NAV = [
    ('홈', [('내 할 일', 'todo', None)]),
    ('MES', [('LOT 이력', 'trace', None)]),
    ('QMS', [('검사 입력', 'inspect', 'qms.add_inspection'),
             ('품질 KPI', 'kpi', None),
             ('협력사', 'suppliers', None)]),
]
