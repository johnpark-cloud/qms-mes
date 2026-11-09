from django.db import migrations

SIMPLE = {
    'category': [('1', '완제품', 'FIN'), ('2', '반제품', 'SEMI'), ('3', '원자재', 'RAW')],
    'industry': [('A', '모든 제품 적용 가능'), ('B', 'BUS, 버스용 축전지'), ('T', 'Train/Tram, 철차/트램용 축전지'),
                 ('G', 'Golfcart, 골프카트 축전지'), ('E', 'ESS, 축전지'), ('M', 'Mobility, 전기스쿠터·전기바이크·전동퀵보드'),
                 ('C', 'Construction Machinery, 건설 중장비 축전지'), ('V', 'Vehicle, 전기자동차(소형자동차 이상)'),
                 ('S', '선박용 배터리'), ('D', '무인기체(드론 등 무인 비행체)'), ('F', '농기계'), ('P', '유인기체(항공기 등)'),
                 ('N', '전력공급용')],
    'customer': [('BG', '비긴스'), ('CJ', 'CJ'), ('DC', '디피코'), ('DD', '대동모빌리티'), ('DP', '대풍모터스'), ('DS', '다원시스'),
                 ('EM', '에디슨 모터스'), ('GM', 'GM사업본부'), ('KM', 'KIA 자동차'), ('KR', '코레일'), ('NC', 'NC Clubcar'),
                 ('RT', '현대로템'), ('SA', '새안모터스'), ('SW', '성우하이텍'), ('US', '언맨드솔루션'), ('WJ', '우진산전'),
                 ('CE', '씨에스에너텍'), ('SM', '서울교통공사'), ('MB', 'MBI'), ('MS', '명신'), ('HD', '한화디펜스'),
                 ('TH', '써멀마스터'), ('KA', '한국자동차연구원'), ('ER', '이래오토모티브(이래AMS)'), ('FE', '퓨쳐EV'),
                 ('GR', '그리너지'), ('KI', '한국항공산업'), ('SB', '삼보모터스'), ('UN', '우나스텔라'),
                 ('JR', '제이알배터리시스템'), ('HA', '한화에어로스페이스'), ('GB', '그린모빌리티 사업부')],
    'doc_kind': [('M', '매뉴얼'), ('P', '절차서'), ('F', '플로우차트'), ('G', '지침서')],
    'dept': [('A', '관리'), ('O', '구매자재'), ('D', '연구소'), ('P', '생산'), ('M', '마케팅'), ('Q', '품질'), ('S', '고객지원')],
    'design': [('SP', '규격서'), ('TP', '시험절차서'), ('BA', '반제품 보드'), ('CD', '회로도면'), ('PD', 'PCB 도면'),
               ('BD', '블록도'), ('AS', '기구 조립도면'), ('BM', 'BOM'), ('AP', '부품승인원'), ('TR', '시험성적서'),
               ('MT', '회의록'), ('SD', '소프트웨어 품질문서'), ('IR', '원인분석보고서'), ('UM', '사용자매뉴얼'),
               ('EC', '설계변경 요청/통보서'), ('DD', '상세설계서'), ('TN', '기술보고서'), ('SW', '소프트웨어'),
               ('SU', '기구 부분 조립도면'), ('DT', '기구 상세도면'), ('IL', 'IC Layout'), ('JF', '작업지도서'),
               ('PE', '설계점검기준표'), ('IC', '시정 및 예방조치'), ('IQ', '수입검사기준서'), ('FQ', '최종검사기준서'),
               ('MF', '제조/QC공정도'), ('PA', '단품도면'), ('HD', '하드웨어문서'), ('ED', '일반기술문서'),
               ('MN', '매뉴얼'), ('CP', 'Control Plan'), ('DM', 'D-FMEA'), ('FM', 'P-FMEA')],
}
DESIGN_TYPES = {'AS': 'SEMI', 'SU': 'SEMI', 'BA': 'SEMI', 'DT': 'RAW', 'PA': 'RAW'}  # 도면 품번 기본 구분
NONE = [('0', '해당 없음')]  # GD-02 '0으로 지정'
SIZE_A = [(str(i), f'size {s}') for i, s in enumerate(['1005', '1608', '2012', '3216', '3225', '4532', '5750'], 1)]
SIZE_B = [(str(i), f'size {s}') for i, s in enumerate(['1005', '1608', '2012', '3216', '3225', '5025', '6432'], 1)]
MATERIAL = [('0', 'Cell'), ('1', 'PBA, 회로자재'), ('2', 'Connector'), ('3', 'Cable'), ('4', '전장품'), ('5', '기구'), ('6', '기타')]
# 키 = 부모 코드 체인(자재분류[대분류[중분류]])
LARGE = {'0': NONE, '1': [('1', 'Capacitor'), ('2', 'Inductor'), ('3', 'Resistor'), ('4', 'BEAD'), ('5', '기타 회로 자재'), ('6', 'PCB')],
         '2': [('1', 'Connector')], '3': [('1', 'Cable')], '4': [('1', '전장품')],
         '5': [('1', '모듈부'), ('2', '구매품'), ('3', '함체부')], '6': [('1', '포장재')]}
MIDDLE = {'00': NONE, '11': [('1', 'Chip'), ('2', 'Elec'), ('3', 'Tantal')], '12': NONE,
          '13': [('1', 'Chip'), ('2', 'DIP, 특수저항')], '14': [('1', 'Chip')], '15': NONE, '16': NONE,
          '21': NONE, '31': NONE, '41': NONE, '51': NONE, '52': NONE, '53': NONE, '61': NONE}
SMALL = {'000': NONE, '111': SIZE_A, '112': NONE, '113': NONE, '120': NONE, '131': SIZE_B, '132': NONE,
         '141': NONE, '150': NONE, '160': NONE, '210': NONE, '310': NONE, '410': NONE,
         '510': NONE, '520': NONE, '530': NONE, '610': NONE}


def seed(apps, schema_editor):
    CodeValue = apps.get_model('core', 'CodeValue')

    def put(group, code, name, parent=None, item_type='', sort=0):
        # 이미 있는 행은 건드리지 않는다(추가만)
        row = CodeValue.objects.filter(group=group, parent=parent, code=code).first()
        return row or CodeValue.objects.create(group=group, parent=parent, code=code, name=name,
                                               item_type=item_type, sort=sort)

    for group, rows in SIMPLE.items():
        for n, row in enumerate(rows, 1):
            code, name = row[:2]
            item_type = row[2] if group == 'category' else DESIGN_TYPES.get(code, '') if group == 'design' else ''
            put(group, code, name, item_type=item_type, sort=n)
    chain = {'': None}
    for n, (code, name) in enumerate(MATERIAL, 1):
        chain[code] = put('material', code, name, sort=n)
    for table, group, parent_len in ((LARGE, 'mat_l', 1), (MIDDLE, 'mat_m', 2), (SMALL, 'mat_s', 3)):
        parents = {k: v for k, v in chain.items() if len(k) == parent_len}
        for key, rows in table.items():
            for n, (code, name) in enumerate(rows, 1):
                chain[key + code] = put(group, code, name, parent=parents[key], sort=n)


class Migration(migrations.Migration):

    dependencies = [('core', '0010_codevalue')]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
