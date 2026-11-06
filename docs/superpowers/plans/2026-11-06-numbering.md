# 번호 부여 체계 (품번·문서번호) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 품번(완제품·반제품·원자재)과 문서번호(관리표준·양식·기술문서)를 드롭다운으로 고르면 일련번호가 자동으로 붙고, 번호의 각 자리 뜻을 풀어 보여 준다.

**Architecture:** 코드값은 새 모델 `core.CodeValue` 하나에 묶음(group)별로 저장하고 관리 화면에서 편집한다. 번호 모양 7가지와 일련번호 계산·풀이는 새 파일 `core/numbering.py` 한 곳에 둔다. 품번은 React 새 화면 등록 창과 `/api/core/items/` POST가, 문서번호는 Django 관리 화면의 문서 추가 폼이 이 모듈을 부른다.

**Tech Stack:** Django 6.1, DRF, django-simple-history, SQLite, React 19 + TypeScript + Vite + antd 6.

**Spec:** `docs/superpowers/specs/2026-11-05-numbering-design.md`

## Global Constraints

- 새 의존성 금지(`requirements.txt`, `package.json` 변경 금지). 오프라인 동작.
- 화면 문구·오류·커밋 메시지는 한국어. 커밋은 한국어 Conventional Commits, 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 기존 행을 바꾸거나 지우는 마이그레이션 금지. 이번 마이그레이션은 테이블 추가, `DocumentRevision.revision`에 `blank=True` 추가, 코드값 **추가만** 하는 데이터 마이그레이션뿐이다.
- `Item` 모델·`Item.TYPES`는 바꾸지 않는다. `Document`에 컬럼을 추가하지 않는다.
- 직접 입력한 번호의 모양은 검사하지 않는다. 엑셀 일괄 등록(`core/importer.py`)은 손대지 않는다.
- 비활성(`active=False`) 코드값으로는 새 번호를 받을 수 없다(서버에서 거부). 풀이에는 비활성 코드도 쓴다.
- 오류 문구(그대로 쓴다): 끝 번호 초과 `일련번호가 다 찼습니다.`, 동시 저장 충돌 `같은 번호가 방금 사용되었습니다. 다시 시도하세요.`, 코드표에 없는 글자 풀이 `미등록`.
- `core` → `qms`는 모듈 수준에서 import하지 않는다. 함수 안에서 `apps.get_model('qms', 'Document')`로만 참조한다(`docs/architecture.md` 의존 방향).
- `data/`, `.superpowers/`, `.venv/`는 커밋하지 않는다. 사용자 미커밋 변경은 건드리지 않고 내 파일만 `git add`한다.
- 테스트 명령: `.\.venv\Scripts\python manage.py test` (Bash에서는 `./.venv/Scripts/python manage.py test`), `./.venv/Scripts/python manage.py makemigrations --check --dry-run`.

## Review Focus

1. 같은 앞자리를 가진 **모양이 다른 번호**(예: `KEN-PQ-01-01`이 `KEN-PQ-` 일련번호 계산에, `1VDC001A`가 `1VDC` 계산에)가 섞여도 최댓값 계산에 들어가지 않아야 한다 → Task 2 `test_serial_ignores_other_shapes`.
2. 코드값을 **사용 중지**한 뒤에도 예전 번호 풀이가 그대로 나와야 하고, 새 번호는 거부돼야 한다 → Task 2 `test_inactive_code_rejected_but_described`.
3. 자재 분류 체인에서 **다른 부모 아래 같은 코드**(예: 중분류 `1`이 311과 313 아래 둘 다)를 고를 때 엉뚱한 부모의 값이 잡히면 안 된다 → Task 2 `test_raw_code_uses_parent_chain`.
4. 미리보기 뒤 **다른 사람이 같은 번호를 먼저 저장**하면 저장 때 다시 계산해 다음 번호를 받는다 → Task 3 `test_auto_code_recomputed_on_save`.
5. 개정 칸을 비웠을 때 **문자 개정(`A`)·`Rev.1` 표기가 섞인** 기존 개정이 있어도 숫자 최댓값 + 1이 나와야 한다 → Task 2 `test_next_revision`, Task 5 `test_blank_revision_filled`.
6. **도면 품번은 도면 문서번호와 같은 번호를 쓴다.** 도면 문서만 먼저 등록된 번호(`Document 1TRT038-AS105`)가 있으면 품번 일련번호가 그 뒤를 이어야 한다 → Task 2 `test_drawing_part_counts_documents`.

---

### Task 1: 코드표 모델 `CodeValue`, 관리 화면, 초기 코드값

**Files:**
- Modify: `core/models.py` (`Item` 아래에 `CodeValue` 추가)
- Create: `core/migrations/0010_codevalue.py` (`makemigrations core`로 생성: 모델 + historical 모델)
- Create: `core/migrations/0011_seed_codevalue.py` (데이터 마이그레이션, 직접 작성)
- Modify: `core/admin.py` (`CodeValueAdmin(BaseAdmin)` 등록)
- Modify: `core/nav.py:63-68` (기준정보 묶음에 `('번호 코드표', 'admin:core_codevalue_changelist', 'core.view_codevalue')`를 '공정' 다음에 추가)
- Test: `core/tests_numbering.py` (새 파일)

**Interfaces:**
- Produces:
  - `CodeValue.CATEGORY='category'`(품목분류), `INDUSTRY='industry'`(산업분류), `CUSTOMER='customer'`(고객사), `MATERIAL='material'`(자재분류), `MAT_L='mat_l'`(자재 대분류), `MAT_M='mat_m'`(자재 중분류), `MAT_S='mat_s'`(자재 소분류), `DOC_KIND='doc_kind'`(관리표준 문서구분), `DEPT='dept'`(부서), `DESIGN='design'`(설계자료분류). `CodeValue.GROUPS` = 이 순서의 choices.
  - 필드: `group` CharField(10, choices), `code` CharField(2), `name` CharField(100), `parent` FK self `null=True, blank=True, on_delete=PROTECT, related_name='children'`, `item_type` CharField(4, `choices=Item.TYPES`, blank=True), `active` Boolean(default True), `sort` PositiveIntegerField(default 0), `history = HistoricalRecords()`. verbose_name `'번호 코드값'`, ordering `['group', 'parent_id', 'sort', 'code']`. `__str__` → `f'{code} {name}'`.
  - `CodeValue.PARENT_GROUP = {MAT_L: MATERIAL, MAT_M: MAT_L, MAT_S: MAT_M}`.
  - `CodeValue.FORMATS`: `CATEGORY/MATERIAL/MAT_L/MAT_M/MAT_S → r'\d'`, `INDUSTRY/DOC_KIND/DEPT → r'[A-Z]'`, `CUSTOMER/DESIGN → r'[A-Z]{2}'`.
  - 제약 2개: `UniqueConstraint(fields=['group','code'], condition=Q(parent__isnull=True), name='uniq_codevalue_root')`, `UniqueConstraint(fields=['parent','code'], condition=Q(parent__isnull=False), name='uniq_codevalue_child')`.

- [ ] **Step 1: 실패하는 테스트 작성** — `core/tests_numbering.py`에 `CodeValueTest(TestCase)`:
  - `test_format_checked`: `CodeValue(group='customer', code='D', name='x').full_clean()` → `ValidationError`(`code` 필드). `industry`에 `'VV'`, `category`에 `'A'`도 각각 오류.
  - `test_parent_rules`: `mat_m` 행의 parent가 `material` 행이면 오류(부모는 `mat_l`이어야 함). `mat_l`에 parent 없음 → 오류. `industry`에 parent 있음 → 오류.
  - `test_item_type_only_category`: `category` 행에 `item_type=''` → 오류, `industry` 행에 `item_type='FIN'` → 오류.
  - `test_unique_within_parent`: 같은 부모 아래 같은 code 두 번째 `full_clean()` → 오류. 부모가 다르면 허용.
  - `test_seed_rows_valid`: 마이그레이션으로 들어간 모든 행이 `full_clean()`을 통과한다. 개수 확인: `category` 3, `industry` 13, `customer` 32, `material` 7, `doc_kind` 4, `dept` 7, `design` 34. `category` `1`/`2`/`3`의 `item_type`은 `FIN`/`SEMI`/`RAW`. 체인 확인: `material 1 → mat_l 1 → mat_m 1 → mat_s 1`의 이름이 `size 1005`.
  - `test_admin_delete_superuser_only`: 품질엔지니어 역할 사용자(`ensure_roles` 후 그룹 부여)는 `core.add_codevalue`·`core.change_codevalue` 권한이 있고 관리 목록 200, `CodeValueAdmin.has_delete_permission`은 False. 검사원 그룹 사용자는 `core.view_codevalue` 없음.

- [ ] **Step 2: 실행해 실패 확인** — `./.venv/Scripts/python manage.py test core.tests_numbering` → `ImportError`/`no such table` 류로 실패.

- [ ] **Step 3: 모델 구현** — `CodeValue.clean()`에서 `FORMATS[group]`을 `re.fullmatch`로 검사, `PARENT_GROUP`대로 부모 묶음 검사(해당 없는 묶음은 parent가 없어야 함), `item_type`은 `CATEGORY`일 때만 필수·그 외 금지. 오류는 필드별 `ValidationError({'code': ...})` 형식, 한국어. 같은 부모 중복은 제약이 `validate_constraints`로 잡는다.

- [ ] **Step 4: 스키마 마이그레이션** — `./.venv/Scripts/python manage.py makemigrations core -n codevalue` 실행 후 결과 파일을 읽어 `CreateModel` 2개(모델·historical)만 있는지 확인.

- [ ] **Step 5: 데이터 마이그레이션 작성** — `0011_seed_codevalue.py`, `RunPython(seed, migrations.RunPython.noop)`. `seed`는 historical 모델로 `(group, parent, code)`가 이미 있으면 건너뛰고 없으면 만든다(추가만). `sort`는 아래 순서대로 1부터. historical 레코드는 데이터 마이그레이션에서 만들지 않는다(기존 마이그레이션 관례). 값은 그대로 쓴다:

```python
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
```

- [ ] **Step 6: 관리 화면** — `@admin.register(CodeValue) class CodeValueAdmin(BaseAdmin)`: `list_display=['group','code','name','parent','item_type','active','sort']`, `list_filter=['group','active']`, `search_fields=['code','name']`, `list_editable`는 쓰지 않는다. `core/nav.py` 기준정보 묶음에 항목 추가.

- [ ] **Step 7: 통과 확인** — `./.venv/Scripts/python manage.py test core.tests_numbering` PASS, `./.venv/Scripts/python manage.py makemigrations --check --dry-run` → `No changes detected`, 전체 `manage.py test` PASS(메뉴 개수를 세는 기존 테스트가 깨지면 기대값을 새 항목만큼 고친다).

- [ ] **Step 8: 커밋** — `git add core/models.py core/migrations/0010_codevalue.py core/migrations/0011_seed_codevalue.py core/admin.py core/nav.py core/tests_numbering.py` → `feat: 번호 코드표(CodeValue)와 초기 코드값을 더한다`

---

### Task 2: 번호 계산·풀이 모듈 `core/numbering.py`

**Files:**
- Create: `core/numbering.py`
- Test: `core/tests_numbering.py` (`NumberingTest` 추가)

**Interfaces:**
- Consumes: Task 1의 `CodeValue` 상수·필드.
- Produces (모두 `core/numbering.py`):
  - `class NumberingError(ValueError)` — 메시지는 사용자에게 그대로 보이는 한국어.
  - 모양 정규식(이름 고정): `STD_DOC = r'^KEN-([A-Z])([A-Z])-(\d{2})$'`, `FORM = r'^(KEN-[A-Z][A-Z]-\d{2})-(\d{2})$'`, `PRODUCT = r'^(\d)([A-Z])([A-Z]{2})(\d{3})$'`, `RAW = r'^(\d)(\d)(\d)(\d)(\d)-(\d{5})$'`, `TECH = r'^(\d[A-Z][A-Z]{2}\d{3})-([A-Z]{2})(\d{3})$'`, `PART_DRAWING = r'^(\d[A-Z][A-Z]{2}\d{3})-(AS|SU|DT|PA|BA)(\d{3})$'`, `STD_PART = r'^3([A-Z][A-Z]{2}\d{3})-(\d{4})$'`.
  - 상수 `PART_DRAWING_TYPES = {'AS': 'SEMI', 'SU': 'SEMI', 'BA': 'SEMI', 'DT': 'RAW', 'PA': 'RAW'}` — 도면 품번에 쓸 수 있는 도면코드와 기본 `Item.item_type`.
  - `next_serial(numbers: Iterable[str], prefix: str, width: int) -> str` — 순수 함수. `^{re.escape(prefix)}(\d{width})$`에 맞는 것의 최댓값 + 1을 `width`자리 0 채움으로. 없으면 `1`. `10**width - 1`을 넘으면 `NumberingError('일련번호가 다 찼습니다.')`.
  - `next_item_code(category: str, industry: str, customer: str) -> str` — `Item.code`에서 계산. category의 `item_type`이 `FIN`·`SEMI`가 아니면 `NumberingError`.
  - `next_raw_code(category: str, material: str, large: str, middle: str, small: str) -> str` — prefix `f'{category}{material}{large}{middle}{small}-'`, width 5. category `item_type`이 `RAW`가 아니면 오류. large는 material 행의 자식, middle은 large 행의 자식, small은 middle 행의 자식에서 찾는다.
  - `next_std_doc(kind: str, dept: str) -> str` — prefix `f'KEN-{kind}{dept}-'`, width 2, `qms.Document.number`에서.
  - `next_form(parent_number: str) -> str` — parent가 `STD_DOC` 모양이고 `Document`에 있어야 함. prefix `f'{parent}-'`, width 2.
  - `next_tech_doc(product_code: str, design: str) -> str` — product가 `PRODUCT` 모양이고 `Item`에 있어야 함. prefix `f'{product}-{design}'`, width 3.
  - `next_drawing_part(product_code: str, design: str) -> str` — design이 `PART_DRAWING_TYPES`에 없으면 `NumberingError`. product는 `PRODUCT` 모양, `Item`에 있고 첫 자리 품목분류의 `item_type`이 `FIN`이어야 함. prefix `f'{product}-{design}'`, width 3. 후보 번호는 `Item.code`와 `qms.Document.number` **둘 다**에서 모은다(도면 품번 = 도면 문서번호).
  - `next_std_part(product_code: str) -> str` — product 조건은 `next_drawing_part`와 같다. prefix `f'3{product[1:]}-'`, width 4, `Item.code`에서.
  - `next_revision(values: Iterable[str]) -> str` — 앞의 `Rev.`/`Rev`(대소문자 무시, 공백 허용)를 떼고 숫자만인 값의 최댓값 + 1. 숫자 값이 없으면 `'0'`.
  - `codebook() -> dict[tuple[str, int | None, str], CodeValue]` — 전체 코드값(비활성 포함)을 `(group, parent_id, code)`로. 쿼리 1번.
  - `describe(number: str, book: dict | None = None) -> list[tuple[str, str]]` — 7가지 모양 중 맞는 것으로 `[(자리 글자, 뜻), ...]`. 도면 품번은 `TECH` 풀이와 같다(모양이 `TECH`의 부분집합). 표준품은 `[('3','원자재'), (산업 글자, 뜻), (고객사 글자, 뜻), (NNN, '프로젝트 일련번호'), (NNNN, '일련번호')]` — `'원자재'`는 품목분류 `3`의 코드표 이름. 뜻이 없으면 `'미등록'`, 일련번호 자리는 `(serial, '일련번호')`. 기술문서는 앞 7자리를 `PRODUCT` 풀이로 펼친 뒤 설계자료분류·일련번호를 잇는다. 양식은 상위 관리표준 풀이 뒤에 `(NN, '양식 일련번호')`. 모양에 안 맞으면 `[]`.
  - `describe_text(number: str, book: dict | None = None) -> str` — `' · '.join(f'{c} {n}')`. 빈 풀이면 `''`.
  - 활성 코드값 조회는 내부 함수 하나로: 없거나 `active=False`면 `NumberingError(f'{묶음 이름} {code}: 없거나 사용 중지된 코드입니다.')`.

- [ ] **Step 1: 실패하는 테스트 작성** — `NumberingTest(TestCase)` (시드 데이터는 마이그레이션으로 이미 있음):
  - `test_next_serial`: `next_serial([], 'X', 3) == '001'`, `next_serial(['X001','X007'], 'X', 3) == '008'`, `next_serial(['X999'], 'X', 3)` → `NumberingError` 메시지 `일련번호가 다 찼습니다.`
  - `test_serial_ignores_other_shapes`: `next_serial(['KEN-PQ-01-01','KEN-PQ-03'], 'KEN-PQ-', 2) == '04'`, `next_serial(['1VDC001A','1VDC002'], '1VDC', 3) == '003'`, `next_serial(['1VDC1000'], '1VDC', 3) == '001'`.
  - `test_item_code`: 빈 DB에서 `next_item_code('1','V','DC') == '1VDC001'`. `Item(code='1VDC005')` 저장 후 `'1VDC006'`. `next_item_code('3','V','DC')` → `NumberingError`.
  - `test_raw_code_uses_parent_chain`: `next_raw_code('3','1','1','1','1') == '31111-00001'`, `next_raw_code('3','1','3','2','0') == '31320-00001'`, `next_raw_code('3','1','2','2','0')` → `NumberingError`(312 아래 중분류 2 없음).
  - `test_doc_numbers`: `Document(number='KEN-PQ-01')`·`'KEN-PQ-01-01'` 저장 후 `next_std_doc('P','Q') == 'KEN-PQ-02'`, `next_form('KEN-PQ-01') == 'KEN-PQ-01-02'`, `next_form('KEN-PQ-09')` → 오류(없는 문서). `Item(code='1TDS001')` 저장 후 `next_tech_doc('1TDS001','BM') == '1TDS001-BM001'`.
  - `test_inactive_code_rejected_but_described`: `customer DC`를 `active=False`로 바꾼 뒤 `next_item_code('1','V','DC')` → `NumberingError`. `describe_text('1VDC001') == '1 완제품 · V Vehicle, 전기자동차(소형자동차 이상) · DC 디피코 · 001 일련번호'`.
  - `test_describe`: `describe('1VZZ001')`의 세 번째 항목 `('ZZ','미등록')`. `describe('31111-00001')`의 뜻 열 = `['원자재','PBA, 회로자재','Capacitor','Chip','size 1005','일련번호']`. `describe('1TDS001-BM001')` 마지막 두 항목 `('BM','BOM')`, `('001','일련번호')`. `describe('KEN-PQ-01-01')` 앞 두 항목 `('P','절차서')`, `('Q','품질')`. `describe('ABC') == []`.
  - `test_drawing_part_counts_documents`: `Item(code='1TRT038')`, `Item(code='1TRT038-AS101')`, `Document(number='1TRT038-AS105')` 저장 후 `next_drawing_part('1TRT038','AS') == '1TRT038-AS106'`. `next_drawing_part('1TRT038','DT') == '1TRT038-DT001'`. `next_drawing_part('1TRT038','BM')` → `NumberingError`. `next_drawing_part('1TRT099','AS')` → `NumberingError`(없는 제품).
  - `test_std_part`: `Item(code='1TRT038')` 저장 후 `next_std_part('1TRT038') == '3TRT038-0001'`. `Item(code='3TRT038-0014')` 저장 후 `'3TRT038-0015'`. `describe('3TRT038-0001')`의 첫 항목 `('3','원자재')`, 마지막 두 항목 `('038','프로젝트 일련번호')`, `('0001','일련번호')`. `describe('1TRT38-DT302') == []`.
  - `test_next_revision`: `next_revision([]) == '0'`, `next_revision(['0','1']) == '2'`, `next_revision(['Rev.3','A','rev 1']) == '4'`, `next_revision(['A','B']) == '0'`.

- [ ] **Step 2: 실행해 실패 확인** — `./.venv/Scripts/python manage.py test core.tests_numbering.NumberingTest` → `ModuleNotFoundError: core.numbering`.

- [ ] **Step 3: 구현** — 위 Interfaces 그대로. `Document`는 함수 안에서 `apps.get_model('qms', 'Document')`. DB 조회는 `filter(<field>__startswith=prefix).values_list(<field>, flat=True)`를 `next_serial`에 넘긴다.

- [ ] **Step 4: 통과 확인** — `./.venv/Scripts/python manage.py test core.tests_numbering` PASS.

- [ ] **Step 5: 커밋** — `git add core/numbering.py core/tests_numbering.py` → `feat: 품번·문서번호 계산과 번호 풀이 모듈을 더한다`

---

### Task 3: 품번 자동 번호 API

**Files:**
- Modify: `core/api/master.py` (`_row`, `_detail`, `ItemListView.post`, 새 뷰 2개)
- Modify: `core/api/urls.py` (경로 2개)
- Test: `core/api/tests.py` (`ItemApiTest`에 추가)

**Interfaces:**
- Consumes: Task 2의 `next_item_code`, `next_raw_code`, `next_drawing_part`, `next_std_part`, `PART_DRAWING_TYPES`, `PRODUCT`, `NumberingError`, `codebook`, `describe_text`.
- Produces:
  - `GET /api/core/numbering/item-options/` (`require_perm(user, 'core.add_item')`) → 활성 코드값만, `sort` 순:
    `{"category": [{"code","name","item_type"}], "industry": [{"code","name"}], "customer": [...], "material": [{"code","name","children":[{"code","name","children":[{"code","name","children":[{"code","name"}]}]}]}], "drawing_codes": [{"code","name","item_type"}], "products": [{"code","name"}]}`
    - `drawing_codes`: `PART_DRAWING_TYPES` 순서대로, `name`은 설계자료분류 코드표 이름.
    - `products`: `PRODUCT` 모양이고 첫 자리 품목분류의 `item_type`이 `FIN`인 `Item`, 품번 순.
  - `GET /api/core/numbering/item-preview/` (`core.add_item`) → `{"number": "1VDC001"}`. 쿼리 묶음 4개: `?category=&industry=&customer=`, `?category=&material=&large=&middle=&small=`, `?product=&design=`(도면 품번), `?product=&std=1`(표준품). `NumberingError`·빠진 값 → `_bad(msg)` 400.
  - `POST /api/core/items/` 본문에 `auto` 객체가 있으면 `code`를 무시하고 서버가 계산한다. `auto` 키 묶음 4개: `{"category","industry","customer"}`, 원자재 5개 키, `{"product","design"}`, `{"product","std": true}`. `item_type`: 앞의 둘은 품목분류 행의 `item_type`; 도면 품번은 본문 `item_type`이 있으면 그것, 없으면 `PART_DRAWING_TYPES[design]`; 표준품은 `RAW`. `auto`가 없으면 지금 동작 그대로.
  - `_row(i, book)` 결과에 `"code_parts": describe_text(i.code, book)` 추가(목록은 `codebook()`을 한 번만 불러 넘긴다). `_detail` 결과에도 `"code_parts"`.

- [ ] **Step 1: 실패하는 테스트 작성** (`ItemApiTest`, 기존 클래스의 사용자·로그인 준비를 그대로 쓴다):
  - `test_item_options`: 200, `category` 코드 `['1','2','3']`, `material`의 `'1'` → 자식 `'1'` → 자식 `'1'` → 자식 이름 `size 1005`. `customer DC`를 끄면 목록에서 빠진다.
  - `test_item_preview`: `?category=1&industry=V&customer=DC` → `{"number":"1VDC001"}`. `?category=3&industry=V&customer=DC` → 400.
  - `test_auto_code_recomputed_on_save`: preview로 `1VDC001`을 본 뒤 `Item.objects.create(code='1VDC001', ...)`, 그 다음 `auto`로 POST → 201, 응답 `code == '1VDC002'`, `item_type == 'FIN'`.
  - `test_auto_raw`: `auto={"category":"3","material":"1","large":"1","middle":"1","small":"1"}` → `code == '31111-00001'`, `item_type == 'RAW'`.
  - `test_auto_drawing_part`: `Item(code='1TRT038', item_type='FIN')` 준비. `auto={"product":"1TRT038","design":"AS"}` → 201, `code == '1TRT038-AS001'`, `item_type == 'SEMI'`. 같은 묶음 + 본문 `item_type='RAW'` → `code == '1TRT038-AS002'`, `item_type == 'RAW'`. `design="BM"` → 400. options의 `products`에 `1TRT038`, `drawing_codes` 코드 `['AS','SU','BA','DT','PA']`(순서는 `PART_DRAWING_TYPES` 그대로).
  - `test_auto_std_part`: 같은 준비, `auto={"product":"1TRT038","std":true}` → `code == '3TRT038-0001'`, `item_type == 'RAW'`. preview `?product=1TRT038&std=1` → `{"number":"3TRT038-0002"}`.
  - `test_auto_inactive_rejected`: `industry V`를 끄고 POST → 400, `detail`에 `사용 중지`.
  - `test_auto_integrity_retry_message`: `core.api.master.next_item_code`를 이미 있는 품번을 돌려주도록 `unittest.mock.patch`하고 POST → 400, `detail == '같은 번호가 방금 사용되었습니다. 다시 시도하세요.'`, 품번 개수 변화 없음.
  - `test_manual_code_unchanged`: `auto` 없이 `code='ABC-1'` POST → 201(모양 검사 없음).
  - `test_code_parts`: `Item(code='1VDC001')` 목록 행 `code_parts`가 `'1 완제품 · '`로 시작, `code='ABC-1'` 행은 `''`. 상세도 `code_parts` 있음.
  - `test_numbering_requires_add_item`: `core.add_item` 없는 사용자(검사원) → options·preview 403.

- [ ] **Step 2: 실행해 실패 확인** — `./.venv/Scripts/python manage.py test core.api.tests.ItemApiTest` → 404·KeyError로 실패.

- [ ] **Step 3: 구현** — `auto`의 모든 값은 문자열이어야 하고(아니면 `_bad`), 키 묶음으로 완제품형/원자재형/도면 품번/표준품을 고른다(`std`만 불리언 `true`, 나머지는 문자열). 묶음에 안 맞으면 `_bad`. 저장은 `with transaction.atomic():` 안에서 `next_*` → `item.full_clean()` → `item.save()`. `full_clean`의 품번 중복 `ValidationError`와 `IntegrityError` 둘 다 `_bad('같은 번호가 방금 사용되었습니다. 다시 시도하세요.', 'code')`로 바꾼다(자동 번호일 때만; 직접 입력의 중복 오류는 지금처럼). `NumberingError`는 `_bad(str(e))`. URL 이름은 `numbering-item-options`, `numbering-item-preview`.

- [ ] **Step 4: 통과 확인** — `./.venv/Scripts/python manage.py test core.api` PASS.

- [ ] **Step 5: 커밋** — `git add core/api/master.py core/api/urls.py core/api/tests.py` → `feat: 품번 자동 번호 API와 품번 풀이를 더한다`

---

### Task 4: React 품번 등록 창 자동 번호와 풀이 표시

**Files:**
- Modify: `frontend/src/api/master.ts` (`ItemRow.code_parts: string`, `ItemDetail.code_parts: string`, 새 타입 `ItemNumberOptions`)
- Modify: `frontend/src/pages/items/ItemList.tsx` (`NewItem`, 품번 열)
- Modify: `frontend/src/pages/items/ItemPage.tsx` (품번 아래 풀이)
- Modify: `frontend/dist/` (빌드 결과)
- Modify: `scripts/e2e_browser.py` (기준정보 구역에 자동 번호 확인 추가)

**Interfaces:**
- Consumes: Task 3의 두 GET 경로와 POST `auto` 본문, `code_parts`.
- Produces: 없음(화면).

- [ ] **Step 1: 타입** — `ItemNumberOptions = { category: {code:string; name:string; item_type:string}[]; industry: Code[]; customer: Code[]; material: CodeNode[]; drawing_codes: {code:string; name:string; item_type:string}[]; products: Code[] }`, `Code = {code:string; name:string}`, `CodeNode = Code & { children?: CodeNode[] }`.

- [ ] **Step 2: 등록 창** — `NewItem`에 antd `Switch` "자동 번호"(기본 켬). 켜면 창을 열 때 `item-options`를 한 번 받고, antd `Segmented`로 번호 종류를 고른다: 제품코드 / 원자재 / 도면 품번 / 표준품.
  - 제품코드: 품목분류 `Select`(`item_type`이 `RAW`가 아닌 것) + 산업·고객사 `Select` 2개.
  - 원자재: 품목분류 `Select`(`RAW`인 것) + 자재분류→대→중→소 `Select` 4개(앞 값을 바꾸면 뒤 값 초기화).
  - 도면 품번: 기준 제품 `Select`(`products`, 검색 가능) + 도면코드 `Select`(`drawing_codes`) + 구분 `Select`(도면코드를 고르면 그 `item_type`으로 채움, 바꿀 수 있음).
  - 표준품: 기준 제품 `Select`만.
  - 옵션 라벨은 `` `${code} ${name}` ``. 값이 다 차면 `item-preview`를 불러 "다음 번호: 1VDC001 (저장할 때 확정)"을 보여 준다. 자동일 때 품번 입력은 숨기고 `{name, auto}`(도면 품번은 `item_type`도)를 POST.
  - 미리보기 옆 "직접 고치기" 버튼: 자동을 끄고 품번 칸에 미리보기 번호를, 구분에 현재 `item_type`을 채운다(백 단위 묶음 `AS100` 등을 손으로 고치는 용도). 서버 변경 없음 — 기존 직접 입력 경로.
  - 끄면 지금 폼 그대로.

- [ ] **Step 3: 풀이 표시** — 목록 품번 열 `render`: `code_parts`가 있으면 antd `Tooltip title={code_parts}`로 감싼다. `ItemPage` 품번 입력 아래 `Typography.Text type="secondary"`로 `code_parts`(빈 값이면 표시 안 함).

- [ ] **Step 4: 빌드** — `cd frontend && npm run build` 성공(tsc 오류 0).

- [ ] **Step 5: e2e 추가** — `scripts/e2e_browser.py`의 기준정보(품번) 확인 근처에: 품번 목록에서 새 품번 → 자동 번호 켬 → 품목분류 `1`, 산업 `V`, 고객사 `DC` 선택 → 미리보기 텍스트가 `1VDC\d{3}` → 품명 입력 후 만들기 → 상세 품번 입력값이 미리보기 번호와 같고 풀이에 `디피코`가 보인다. 이어서 새 품번 → 도면 품번 → 기준 제품에 방금 만든 `1VDC…` 번호, 도면코드 `AS` → 만들기 → 상세 품번이 `^1VDC\d{3}-AS\d{3}$`에 맞는다.

- [ ] **Step 6: e2e 실행** — `./.venv/Scripts/python scripts/e2e_browser.py` 끝까지 통과(기존 확인 포함).

- [ ] **Step 7: 커밋** — `git add frontend/src/api/master.ts frontend/src/pages/items/ItemList.tsx frontend/src/pages/items/ItemPage.tsx frontend/dist scripts/e2e_browser.py` → `feat: 새 품번 창에 자동 번호와 품번 풀이를 더한다`

---

### Task 5: 관리 화면 문서번호 자동 부여·개정 자동 채움·번호 풀이

**Files:**
- Modify: `qms/models.py:570` 부근 (`DocumentRevision.revision`에 `blank=True`, `clean()`/`save()`에서 빈 개정 채움)
- Create: `qms/migrations/0010_documentrevision_revision_blank.py` (`makemigrations qms`)
- Modify: `qms/admin.py:419-445` (`DocumentAdmin` 폼·목록, `RevisionInline`)
- Test: `qms/tests.py` (`DocumentNumberingTest` 새 클래스)

**Interfaces:**
- Consumes: Task 2의 `next_std_doc`, `next_form`, `next_tech_doc`, `next_revision`, `describe_text`, `NumberingError`, 모양 정규식 `STD_DOC`, `PRODUCT`.
- Produces: 없음.

- [ ] **Step 1: 실패하는 테스트 작성** — `DocumentNumberingTest(TestCase)`, 슈퍼유저로 관리 화면 POST:
  - `test_std_doc_auto`: `/admin/qms/document/add/`에 `number=''`, `number_kind='std'`, `doc_kind='P'`, `dept='Q'`, `title='x'` (+ 인라인 관리폼 0개) → 302, `Document.objects.get(title='x').number == 'KEN-PQ-01'`.
  - `test_form_auto`: `KEN-PQ-01` 있을 때 `number_kind='form'`, `parent_doc='KEN-PQ-01'` → `KEN-PQ-01-01`.
  - `test_tech_auto`: `Item(code='1TDS001')` 있을 때 `number_kind='tech'`, `product='1TDS001'`, `design='BM'` → `1TDS001-BM001`.
  - `test_blank_number_needs_kind`: `number=''`, `number_kind=''` → 200(폼 다시 보임), 오류 문구 `문서번호를 입력하거나 번호 종류를 고르세요.`
  - `test_manual_number_kept`: `number='OLD-001'` → 그대로 저장(모양 검사 없음).
  - `test_choices_filtered`: 추가 폼의 `parent_doc` 선택지에 `KEN-PQ-01`은 있고 `KEN-PQ-01-01`은 없다. `product` 선택지에 `1TDS001`은 있고 `ABC-1`은 없다. 비활성 `dept`는 `dept` 선택지에 없다.
  - `test_blank_revision_filled`: 개정 `'Rev.1'`, `'A'`가 있는 문서에 `DocumentRevision(document=d, revision='')`를 `full_clean()` 후 저장 → `revision == '2'`. 개정이 없는 문서는 `'0'`.
  - `test_list_shows_parts`: 문서 목록 HTML에 `title="` 속성으로 `P 절차서 · Q 품질`이 들어 있다.

- [ ] **Step 2: 실행해 실패 확인** — `./.venv/Scripts/python manage.py test qms.tests.DocumentNumberingTest` → 실패.

- [ ] **Step 3: 개정 자동 채움** — `DocumentRevision.revision`에 `blank=True`. `clean()`(있으면 기존 내용 유지)과 `save()` 앞부분에서 `if not self.revision.strip(): self.revision = next_revision(같은 문서의 다른 개정 revision 값들)`. `makemigrations qms -n documentrevision_revision_blank` 결과가 `AlterField` 1개(+historical 1개)뿐인지 읽어 확인. `RevisionInline`과 `DocumentRevisionAdmin` 폼에서 개정 칸 도움말: `비워 두면 마지막 숫자 개정 + 1로 채웁니다.`

- [ ] **Step 4: 문서 추가 폼** — `DocumentAdmin.form`을 `DocumentForm(forms.ModelForm)`으로: 모델 필드 `number`는 `required=False`. 모델 밖 필드 `number_kind`(ChoiceField: `('', '직접 입력')`, `('std','관리표준')`, `('form','양식')`, `('tech','기술문서')`), `doc_kind`, `dept`, `design`(활성 코드값 choices), `parent_doc`(`STD_DOC` 모양 기존 문서번호), `product`(`PRODUCT` 모양 기존 품번) — 모두 `required=False`, choices는 폼 `__init__`에서 매번 만든다. 추가 화면에서만 이 필드들을 보이게 `get_fieldsets`로 "자동 번호" 묶음을 덧붙이고, 수정 화면은 지금 그대로. `clean()`: 번호가 비었으면 `number_kind`로 해당 `next_*`를 불러 `cleaned_data['number']`·`self.instance.number`에 넣는다. `NumberingError`와 필요한 칸이 빈 경우는 폼 오류. 번호도 종류도 없으면 `문서번호를 입력하거나 번호 종류를 고르세요.`
- 동시 저장: `DocumentAdmin.save_model`에서 자동 번호였으면 `with transaction.atomic(): obj.save()`를 `IntegrityError` 시 번호를 다시 계산해 한 번 더 시도한다. 그래도 실패하면 `IntegrityError`를 그대로 올린다 — `# shortcut: 두 번 연속 충돌은 500, 사용자가 몇 명뿐이라 충분. 사용자가 늘면 폼 오류로 돌린다.`

- [ ] **Step 5: 목록 풀이** — `list_display`의 `'number'`를 `number_display`로 바꾸고 `list_display_links=['number_display']`, `@admin.display(description='문서번호', ordering='number')`, `format_html('<span title="{}">{}</span>', describe_text(obj.number), obj.number)`.

- [ ] **Step 6: 통과 확인** — `./.venv/Scripts/python manage.py test qms` PASS, `makemigrations --check --dry-run` → `No changes detected`.

- [ ] **Step 7: 커밋** — `git add qms/models.py qms/migrations/0010_documentrevision_revision_blank.py qms/admin.py qms/tests.py` → `feat: 문서번호 자동 부여와 개정 자동 채움을 더한다`

---

### Task 6: 문서 갱신과 전체 검증

**Files:**
- Modify: `README.md` (`## 새 기능 사용법` 아래 "번호 자동 부여" 소절; `#### 기준정보` 소절에 자동 번호 한 줄)
- Modify: `docs/business-rules.md` (새 절 `## 12. 번호 부여`)
- Modify: `docs/architecture.md` (`core` 모듈 표에 `numbering.py` 한 줄, API 설명에 `/api/core/numbering/item-options/`·`item-preview/`)
- Modify: `docs/testing.md` (테스트 파일 표에 `core/tests_numbering.py`, `DocumentNumberingTest`)

- [ ] **Step 1: business-rules 12절** — 일곱 모양 표(설계 4절 표 그대로, 6 도면 품번·7 표준품 포함, "GD-02 미정의·현장 관행" 메모), "도면 품번 = 도면 문서번호" 규칙(일련번호는 `Item.code`·`Document.number` 양쪽 최댓값 + 1, 기준 완제품이 있어야 함), 일련번호 규칙(최댓값 + 1, 빈 번호 재사용 안 함, 모양 정규식에 정확히 맞는 번호만 계산), 끝 번호 초과 오류, 사용 중지 코드 거부, 직접 입력 허용·모양 검사 없음, 개정 자동 채움 규칙, 코드 위치(`core/numbering.py`, `core/models.py` `CodeValue`, `core/api/master.py`, `qms/admin.py` `DocumentForm`, `qms/models.py` `DocumentRevision`).

- [ ] **Step 2: README·architecture·testing** — 위 Files 대로. 적은 경로·명령이 실제로 있는지 `ls`·`grep`으로 확인.

- [ ] **Step 3: 전체 검증** — 아래를 실행하고 출력 그대로 기록:
  - `./.venv/Scripts/python manage.py test` → `OK` (기존 361개 + 새 테스트)
  - `./.venv/Scripts/python manage.py makemigrations --check --dry-run` → `No changes detected`
  - `./.venv/Scripts/python manage.py check` → 문제 없음
  - 운영 DB 사본에서 마이그레이션: `data/` DB를 스크래치 폴더로 복사하고 그 사본을 가리키게 해 `migrate`를 실행, 코드값 개수(`category` 3 … `design` 34)와 기존 `Item`·`Document` 개수가 그대로인지 확인한다(`docs/testing.md`의 데이터 마이그레이션 절차를 따른다). 운영 DB 자체에는 적용하지 않는다.

- [ ] **Step 4: 커밋** — `git add README.md docs/business-rules.md docs/architecture.md docs/testing.md` → `docs: 번호 부여 규칙과 사용법을 문서에 더한다`
