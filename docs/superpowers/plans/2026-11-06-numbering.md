# 번호 부여 체계 (품번·문서번호) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리 화면에서 정한 번호 규칙(틀 문자열)대로 품번·문서번호를 드롭다운으로 받고 일련번호가 자동으로 붙으며, 번호의 각 자리 뜻을 풀어 보여 준다.

**Architecture:** 코드값은 `core.CodeValue`, 번호 모양은 `core.NumberRule`(틀 문자열)에 저장하고 둘 다 관리 화면에서 편집한다. 틀 해석·일련번호 계산·풀이는 새 파일 `core/numbering.py` 한 곳에 둔다. 품번은 React 새 화면 등록 창과 `/api/core/items/` POST가, 문서번호는 Django 관리 화면의 문서 추가 폼이 이 모듈을 부른다.

**Tech Stack:** Django 6.1, DRF, django-simple-history, SQLite, React 19 + TypeScript + Vite + antd 6.

**Spec:** `docs/superpowers/specs/2026-11-05-numbering-design.md`

## Global Constraints

- 새 의존성 금지(`requirements.txt`, `package.json` 변경 금지). 오프라인 동작.
- 화면 문구·오류·커밋 메시지는 한국어. 커밋은 한국어 Conventional Commits, 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 기존 행을 바꾸거나 지우는 마이그레이션 금지. 이번 마이그레이션은 테이블 추가, `DocumentRevision.revision`에 `blank=True` 추가, 코드값·규칙을 **추가만** 하는 데이터 마이그레이션뿐이다.
- `Item` 모델·`Item.TYPES`는 바꾸지 않는다. `Document`에 컬럼을 추가하지 않는다.
- 직접 입력한 번호의 모양은 검사하지 않는다. 엑셀 일괄 등록(`core/importer.py`)은 손대지 않는다.
- 비활성(`active=False`) 코드값·규칙으로는 새 번호를 받을 수 없다(서버에서 거부). 풀이에는 비활성 코드값·규칙도 쓴다.
- 오류 문구(그대로 쓴다): 끝 번호 초과 `일련번호가 다 찼습니다.`, 동시 저장 충돌 `같은 번호가 방금 사용되었습니다. 다시 시도하세요.`, 코드표에 없는 글자 풀이 `미등록`, 비활성 규칙 `사용 중지된 규칙입니다.`, 규칙 잠금 `저장된 규칙의 이름·대상·틀은 바꿀 수 없습니다. 새 규칙을 만드세요.`
- `core` → `qms`는 모듈 수준에서 import하지 않는다. 함수 안에서 `apps.get_model('qms', 'Document')`로만 참조한다(`docs/architecture.md` 의존 방향).
- `data/`, `.superpowers/`, `.venv/`는 커밋하지 않는다. 사용자 미커밋 변경은 건드리지 않고 내 파일만 `git add`한다.
- 테스트 명령: `.\.venv\Scripts\python manage.py test` (Bash에서는 `./.venv/Scripts/python manage.py test`), `./.venv/Scripts/python manage.py makemigrations --check --dry-run`.

## Review Focus

1. **틀을 고쳐 옛 번호 풀이가 깨지는 것:** 저장된 규칙의 이름·대상·틀 수정은 거부되고, 사용 중지만 된다 → Task 2 `test_pattern_locked`.
2. **규칙을 사용 중지한 뒤:** 옛 번호 풀이는 그대로, 새 번호는 거부 → Task 3 `test_inactive_rule_still_describes`.
3. **회사 약칭 변경(KEN → ABC):** 새 규칙의 번호는 1번부터, KEN 번호 풀이는 유지 → Task 3 `test_company_prefix_change`.
4. **도면 품번 = 도면 문서번호:** 도면 문서만 먼저 등록된 번호(`Document 1TRT038-AS105`)가 있으면 품번 일련번호가 그 뒤를 잇는다 → Task 3 `test_drawing_part_counts_documents`.
5. **잘못된 틀:** 순환 참조, 일련번호 위치·개수 오류, 경계에 안 맞는 `뒤N`, 부모 없는 하위 분류는 저장 거부 → Task 2 `test_rule_validation`.
6. **다른 부모 아래 같은 코드**(중분류 `1`이 311과 313 아래 둘 다): 엉뚱한 부모의 값이 잡히면 안 된다 → Task 3 `test_parent_chain`.
7. **같은 앞자리를 가진 모양이 다른 번호**(`KEN-PQ-01-01`이 `KEN-PQ-` 계산에, `1VDC001A`가 `1VDC` 계산에)는 최댓값 계산에 들어가지 않는다 → Task 2 `test_serial_ignores_other_shapes`.
8. **미리보기 뒤 다른 사람이 같은 번호를 먼저 저장:** 저장 때 다시 계산해 다음 번호를 받는다 → Task 4 `test_auto_code_recomputed_on_save`.

---

### Task 1: 코드표 모델 `CodeValue`, 관리 화면, 초기 코드값

**Files:**
- Modify: `core/models.py` (`Item` 아래에 `CodeValue` 추가)
- Create: `core/migrations/0010_codevalue.py` (`makemigrations core`로 생성: 모델 + historical 모델)
- Create: `core/migrations/0011_seed_codevalue.py` (데이터 마이그레이션, 직접 작성)
- Modify: `core/admin.py` (`CodeValueAdmin(BaseAdmin)` 등록)
- Modify: `core/nav.py:63-68` (기준정보 묶음에 `('번호 코드값', 'admin:core_codevalue_changelist', 'core.view_codevalue')`를 '공정' 다음에 추가)
- Test: `core/tests_numbering.py` (새 파일)

**Interfaces:**
- Produces:
  - `CodeValue.CATEGORY='category'`(품목분류), `INDUSTRY='industry'`(산업분류), `CUSTOMER='customer'`(고객사), `MATERIAL='material'`(자재분류), `MAT_L='mat_l'`(자재 대분류), `MAT_M='mat_m'`(자재 중분류), `MAT_S='mat_s'`(자재 소분류), `DOC_KIND='doc_kind'`(관리표준 문서구분), `DEPT='dept'`(부서), `DESIGN='design'`(설계자료분류). `CodeValue.GROUPS` = 이 순서의 choices. 괄호 안 한국어 이름이 choices 라벨이며, Task 2 틀 문법의 묶음 이름이다.
  - 필드: `group` CharField(10, choices), `code` CharField(2), `name` CharField(100), `parent` FK self `null=True, blank=True, on_delete=PROTECT, related_name='children'`, `item_type` CharField(4, `choices=Item.TYPES`, blank=True), `active` Boolean(default True), `sort` PositiveIntegerField(default 0), `history = HistoricalRecords()`. verbose_name `'번호 코드값'`, ordering `['group', 'parent_id', 'sort', 'code']`. `__str__` → `f'{code} {name}'`.
  - `CodeValue.PARENT_GROUP = {MAT_L: MATERIAL, MAT_M: MAT_L, MAT_S: MAT_M}`.
  - `CodeValue.FORMATS`: `CATEGORY/MATERIAL/MAT_L/MAT_M/MAT_S → r'\d'`, `INDUSTRY/DOC_KIND/DEPT → r'[A-Z]'`, `CUSTOMER/DESIGN → r'[A-Z]{2}'`. 묶음별 자릿수는 이 정규식에서 나온다(1 또는 2).
  - 제약 2개: `UniqueConstraint(fields=['group','code'], condition=Q(parent__isnull=True), name='uniq_codevalue_root')`, `UniqueConstraint(fields=['parent','code'], condition=Q(parent__isnull=False), name='uniq_codevalue_child')`.

- [ ] **Step 1: 실패하는 테스트 작성** — `core/tests_numbering.py`에 `CodeValueTest(TestCase)`:
  - `test_format_checked`: `CodeValue(group='customer', code='D', name='x').full_clean()` → `ValidationError`(`code` 필드). `industry`에 `'VV'`, `category`에 `'A'`도 각각 오류.
  - `test_parent_rules`: `mat_m` 행의 parent가 `material` 행이면 오류(부모는 `mat_l`이어야 함). `mat_l`에 parent 없음 → 오류. `industry`에 parent 있음 → 오류.
  - `test_item_type_rules`: `category` 행에 `item_type=''` → 오류. `industry` 행에 `item_type='FIN'` → 오류. `design` 행은 `item_type=''`·`'RAW'` 둘 다 허용.
  - `test_unique_within_parent`: 같은 부모 아래 같은 code 두 번째 `full_clean()` → 오류. 부모가 다르면 허용.
  - `test_seed_rows_valid`: 마이그레이션으로 들어간 모든 행이 `full_clean()`을 통과한다. 개수: `category` 3, `industry` 13, `customer` 32, `material` 7, `doc_kind` 4, `dept` 7, `design` 34. `category` `1`/`2`/`3`의 `item_type`은 `FIN`/`SEMI`/`RAW`. `design`의 `AS`·`SU`·`BA`는 `SEMI`, `DT`·`PA`는 `RAW`, `BM`은 `''`. 체인: `material 1 → mat_l 1 → mat_m 1 → mat_s 1`의 이름이 `size 1005`.
  - `test_admin_delete_superuser_only`: 품질엔지니어 역할 사용자(`ensure_roles` 후 그룹 부여)는 `core.add_codevalue`·`core.change_codevalue` 권한이 있고 관리 목록 200, `CodeValueAdmin.has_delete_permission`은 False. 검사원 그룹 사용자는 `core.view_codevalue` 없음.

- [ ] **Step 2: 실행해 실패 확인** — `./.venv/Scripts/python manage.py test core.tests_numbering` → `ImportError`/`no such table` 류로 실패.

- [ ] **Step 3: 모델 구현** — `CodeValue.clean()`에서 `FORMATS[group]`을 `re.fullmatch`로 검사, `PARENT_GROUP`대로 부모 묶음 검사(해당 없는 묶음은 parent가 없어야 함), `item_type`은 `CATEGORY`면 필수, `DESIGN`이면 선택, 그 외 금지. 오류는 필드별 `ValidationError({'code': ...})` 형식, 한국어. 같은 부모 중복은 제약이 `validate_constraints`로 잡는다.

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
```

- [ ] **Step 6: 관리 화면** — `@admin.register(CodeValue) class CodeValueAdmin(BaseAdmin)`: `list_display=['group','code','name','parent','item_type','active','sort']`, `list_filter=['group','active']`, `search_fields=['code','name']`, `list_editable`는 쓰지 않는다. `core/nav.py` 기준정보 묶음에 항목 추가.

- [ ] **Step 7: 통과 확인** — `./.venv/Scripts/python manage.py test core.tests_numbering` PASS, `./.venv/Scripts/python manage.py makemigrations --check --dry-run` → `No changes detected`, 전체 `manage.py test` PASS(메뉴 개수를 세는 기존 테스트가 깨지면 기대값을 새 항목만큼 고친다).

- [ ] **Step 8: 커밋** — `git add core/models.py core/migrations/0010_codevalue.py core/migrations/0011_seed_codevalue.py core/admin.py core/nav.py core/tests_numbering.py` → `feat: 번호 코드표(CodeValue)와 초기 코드값을 더한다`

---

### Task 2: 번호 규칙 모델 `NumberRule`, 틀 해석·검사, 초기 규칙

**Files:**
- Modify: `core/models.py` (`CodeValue` 아래에 `NumberRule`)
- Create: `core/numbering.py`
- Create: `core/migrations/0012_numberrule.py` (`makemigrations core -n numberrule`)
- Create: `core/migrations/0013_seed_numberrule.py` (데이터 마이그레이션, 직접 작성)
- Modify: `core/admin.py` (`NumberRuleAdmin(BaseAdmin)`)
- Modify: `core/nav.py` (기준정보 묶음, '번호 코드값' 다음에 `('번호 규칙', 'admin:core_numberrule_changelist', 'core.view_numberrule')`)
- Test: `core/tests_numbering.py` (`NumberRuleTest` 추가)

**Interfaces:**
- Consumes: Task 1의 `CodeValue` 상수·`GROUPS` 라벨·`FORMATS`·`PARENT_GROUP`.
- Produces:
  - `NumberRule`: `name` CharField(50, unique), `target` CharField(4, choices `ITEM='ITEM'` 품번 / `DOC='DOC'` 문서), `pattern` CharField(200), `active` Boolean(default True), `sort` PositiveIntegerField(default 0), `history = HistoricalRecords()`. verbose_name `'번호 규칙'`, ordering `['sort', 'id']`. `__str__` → `name`.
  - `NumberRule.clean()`: 저장된 행이면 DB 값과 비교해 `name`·`target`·`pattern` 중 바뀐 필드에 `ValidationError({필드: '저장된 규칙의 이름·대상·틀은 바꿀 수 없습니다. 새 규칙을 만드세요.'})`. 그다음 `check_rule(...)`의 `NumberingError`를 `ValidationError({'pattern': str(e)})`로.
  - `core/numbering.py`:
    - `class NumberingError(ValueError)` — 메시지는 사용자에게 그대로 보이는 한국어.
    - `@dataclass(frozen=True) class Token`: `kind: str`(`'text'|'code'|'ref'|'serial'`), `text: str = ''`, `group: str = ''`(CodeValue 상수), `allowed: tuple[str, ...] = ()`, `target: str = ''`(`'ITEM'|'DOC'`), `rule: str = ''`, `tail: int = 0`, `width: int = 0`.
    - `parse_pattern(pattern: str) -> list[Token]` — 문법 오류만 검사(중괄호 짝, 알 수 없는 묶음 라벨, `{일련N}`이 정확히 1개이고 맨 끝, `뒤N`은 ref에만). 토큰: `{묶음 라벨}`·`{묶음 라벨:A,B}` → code(`width`는 `FORMATS` 자릿수), `{품번:규칙}`·`{문서:규칙}`·`{품번:규칙:뒤N}` → ref, `{일련N}` → serial(`width=N`), 나머지 글자 → text.
    - `rulebook() -> dict[str, NumberRule]` — 전체 규칙(비활성 포함), 이름 → 규칙. 쿼리 1번.
    - `width(rule: NumberRule, rules: dict) -> int` — 번호 전체 글자 수(ref는 참조 규칙 너비 또는 `tail`). 모든 토큰 너비가 고정이다.
    - `check_rule(name: str, target: str, pattern: str, rules: dict | None = None) -> None` — `parse_pattern` + 의미 검사: 허용 값이 해당 묶음 코드표에 있고 `FORMATS`에 맞음, 부모 묶음 토큰은 바로 앞 code 토큰이 `PARENT_GROUP`의 부모 묶음, ref 규칙이 있고 그 `target`이 토큰의 `품번/문서`와 같음, 자기 참조·순환 없음(`rules`에 이 이름의 새 틀을 넣어 따라감), `tail`이 참조 규칙 뒤쪽 토큰 경계(뒤에서부터 토큰 너비 누적합 중 하나)와 같음. `rules` 기본값은 `rulebook()`.

- [ ] **Step 1: 실패하는 테스트 작성** — `NumberRuleTest(TestCase)`:
  - `test_parse_pattern`: `parse_pattern('{품목분류:1,2}{산업분류}{고객사}{일련3}')`의 `kind` 열 = `['code','code','code','serial']`, 첫 토큰 `group='category'`, `allowed=('1','2')`, 마지막 `width=3`. `parse_pattern('{품목분류:3}{품번:제품코드:뒤6}-{일련4}')`의 두 번째 토큰 `kind='ref'`, `target='ITEM'`, `rule='제품코드'`, `tail=6`; 세 번째 `kind='text'`, `text='-'`.
  - `test_seed_rules_valid`: 마이그레이션으로 들어간 규칙 7개, 이름·대상·틀·sort가 설계 4.2절 표와 같고 모두 `full_clean()` 통과.
  - `test_rule_validation`: 아래 각각 `check_rule(...)` → `NumberingError`:
    - 일련 위치·개수: `'X{일련3}-A'`, `'{일련2}{일련2}'`, `'KEN-{부서}'`.
    - 없는 묶음 `'{공장}{일련2}'`, 코드표에 없는 허용 값 `'{품목분류:9}{일련2}'`.
    - 없는 규칙 `'{품번:없음}-{일련2}'`, 대상 불일치 `'{문서:제품코드}-{일련2}'`(제품코드는 품번 규칙).
    - 자기 참조: 이름 `'자기'`, 틀 `'{품번:자기}-{일련2}'`.
    - 순환: `rules={**rulebook(), 'B': NumberRule(name='B', target='ITEM', pattern='{품번:A}-{일련2}')}`에서 `check_rule('A', 'ITEM', '{품번:B}-{일련2}', rules)`.
    - 경계: `'{품번:제품코드:뒤4}-{일련2}'`. 반대로 `뒤5`·`뒤6`은 통과.
    - 부모 없는 하위 분류: `'{자재 중분류}{일련2}'`, `'{자재분류}{자재 중분류}{일련2}'`.
  - `test_pattern_locked`: 규칙 `제품코드`의 `pattern`을 바꾸고 `full_clean()` → `ValidationError`, 오류 키 `pattern`, 메시지 `저장된 규칙의 이름·대상·틀은 바꿀 수 없습니다. 새 규칙을 만드세요.` `name` 변경도 같은 오류(키 `name`). `active=False`만 바꾸면 통과.
  - `test_rule_admin`: 품질엔지니어 역할 사용자는 `core.add_numberrule`·`core.change_numberrule` 권한이 있고 규칙 수정 화면에서 `name`·`target`·`pattern`이 읽기 전용(폼에 입력 칸 없음), `has_delete_permission`은 False. 추가 화면에서는 세 칸 모두 입력 가능.

- [ ] **Step 2: 실행해 실패 확인** — `./.venv/Scripts/python manage.py test core.tests_numbering.NumberRuleTest` → 실패.

- [ ] **Step 3: 구현** — 위 Interfaces 그대로. 묶음 라벨 → 상수는 `CodeValue.GROUPS`의 라벨에서 만든다(라벨 표를 따로 두지 않는다). `NumberRule.clean()`은 `check_rule`에 `rulebook()`을 넘기되 자기 자신의 옛 행은 새 값으로 바꿔 넣는다.

- [ ] **Step 4: 마이그레이션** — `makemigrations core -n numberrule` 결과가 `CreateModel` 2개뿐인지 읽어 확인. `0013_seed_numberrule.py`: `RunPython(seed, noop)`, 이름이 이미 있으면 건너뛰고 아래 7행을 추가만 한다(`check_rule`은 부르지 않는다 — 테스트가 검증):

```python
RULES = [  # (sort, name, target, pattern)
    (1, '관리표준', 'DOC', 'KEN-{관리표준 문서구분}{부서}-{일련2}'),
    (2, '양식', 'DOC', '{문서:관리표준}-{일련2}'),
    (3, '제품코드', 'ITEM', '{품목분류:1,2}{산업분류}{고객사}{일련3}'),
    (4, '원자재', 'ITEM', '{품목분류:3}{자재분류}{자재 대분류}{자재 중분류}{자재 소분류}-{일련5}'),
    (5, '기술문서', 'DOC', '{품번:제품코드}-{설계자료분류}{일련3}'),
    (6, '도면 품번', 'ITEM', '{품번:제품코드}-{설계자료분류:AS,SU,DT,PA,BA}{일련3}'),
    (7, '표준품', 'ITEM', '{품목분류:3}{품번:제품코드:뒤6}-{일련4}'),
]
```

- [ ] **Step 5: 관리 화면** — `@admin.register(NumberRule) class NumberRuleAdmin(BaseAdmin)`: `list_display=['sort','name','target','pattern','active']`, `list_filter=['target','active']`, `get_readonly_fields`는 수정 화면(`obj`가 있음)에서 `['name','target','pattern']`을 더한다. `pattern` 도움말에 문법 한 줄 요약: `예: KEN-{관리표준 문서구분}{부서}-{일련2}. 코드 {묶음}, 허용 값 {묶음:A,B}, 기존 번호 {품번:규칙}/{문서:규칙}, 뒤 N자리 {품번:규칙:뒤N}, 일련번호 {일련N}(맨 끝 1개).` nav 항목 추가.

- [ ] **Step 6: 통과 확인** — `./.venv/Scripts/python manage.py test core.tests_numbering` PASS, `makemigrations --check --dry-run` → `No changes detected`.

- [ ] **Step 7: 커밋** — `git add core/models.py core/numbering.py core/migrations/0012_numberrule.py core/migrations/0013_seed_numberrule.py core/admin.py core/nav.py core/tests_numbering.py` → `feat: 번호 규칙(NumberRule)과 틀 문자열 해석을 더한다`

---

### Task 3: 번호 계산·풀이

**Files:**
- Modify: `core/numbering.py`
- Test: `core/tests_numbering.py` (`NumberingTest` 추가)

**Interfaces:**
- Consumes: Task 1 `CodeValue`, Task 2 `NumberRule`, `Token`, `parse_pattern`, `rulebook`, `width`, `NumberingError`.
- Produces (모두 `core/numbering.py`):
  - `next_serial(numbers: Iterable[str], prefix: str, width: int) -> str` — 순수 함수. `^{re.escape(prefix)}(\d{width})$`에 맞는 것의 최댓값 + 1을 `width`자리 0 채움으로. 없으면 1. `10**width - 1`을 넘으면 `NumberingError('일련번호가 다 찼습니다.')`.
  - `fields(rule: NumberRule) -> list[Token]` — 사용자가 고를 토큰(code·ref)만, 틀 순서대로.
  - `codebook() -> dict[tuple[str, int | None, str], CodeValue]` — 전체 코드값(비활성 포함)을 `(group, parent_id, code)`로. 쿼리 1번.
  - `matches(rule: NumberRule, number: str, rules: dict | None = None) -> bool` — 모양만 본다(코드값 존재 여부는 안 봄): 길이가 `width`와 같고, text는 글자 그대로, code는 `FORMATS`와 `allowed`에 맞고, ref는 참조 규칙에 재귀로 맞고(`tail`이면 참조 규칙 뒤쪽 토큰만), serial은 숫자.
  - `next_number(rule: NumberRule, values: list[str]) -> str` — `values`는 `fields(rule)`와 같은 길이. 규칙이 비활성이면 `NumberingError('사용 중지된 규칙입니다.')`. code 값은 `allowed`에 있고, 활성이고, 부모 묶음이면 바로 앞 code 값의 자식이어야 한다(아니면 `NumberingError(f'{묶음 라벨} {code}: 없거나 사용 중지된 코드입니다.')`). ref 값은 참조 대상 표(`ITEM`→`Item.code`, `DOC`→`qms.Document.number`)에 있고 `matches(참조 규칙, 값)`이어야 한다(참조 규칙은 비활성이어도 됨). `tail`이면 값의 뒤 N글자를 쓴다. prefix = 일련 토큰 앞까지 이은 글자. 후보 번호는 `Item.code`와 `Document.number` **둘 다**에서 `__startswith=prefix`로 모아 `next_serial`에 넘긴다.
  - `default_item_type(rule: NumberRule, values: list[str]) -> str` — 고른 code 값 중 `item_type`이 비지 않은 마지막 값의 것. 없으면 `''`.
  - `candidates(token: Token, rules: dict | None = None) -> list[str]` — ref 토큰의 후보: 참조 대상 표의 번호 중 `matches(참조 규칙, 번호)`인 것, 정렬. `# shortcut: 표 전체를 읽어 파이썬에서 거른다, 품번·문서가 수만 건이 되면 prefix 조건을 DB로 내린다.`
  - `describe(number: str, target: str | None = None, book: dict | None = None, rules: list[NumberRule] | None = None) -> list[tuple[str, str]]` — 규칙을 `target`이 같은 것 먼저, 그 안에서 `sort` 순으로 맞춰 보고(비활성 포함, 틀을 해석할 수 없거나 참조 규칙이 지워진 규칙은 건너뜀 — 설계 10절), 처음 맞는 규칙으로 `[(자리 글자, 뜻), ...]`. text는 넣지 않는다. code는 코드표 이름(부모 묶음은 바로 앞 code의 행을 부모로 찾음, 없으면 `'미등록'`). ref는 참조 규칙으로 펼치고 그 안의 serial 뜻은 `f'{참조 규칙 이름} 일련번호'`. 자기 serial은 `'일련번호'`. 안 맞으면 `[]`.
  - `describe_text(number: str, target: str | None = None, book: dict | None = None, rules: list | None = None) -> str` — `' · '.join(f'{c} {n}')`. 빈 풀이면 `''`.
  - `next_revision(values: Iterable[str]) -> str` — 앞의 `Rev.`/`Rev`(대소문자 무시, 공백 허용)를 떼고 숫자만인 값의 최댓값 + 1. 숫자 값이 없으면 `'0'`.

- [ ] **Step 1: 실패하는 테스트 작성** — `NumberingTest(TestCase)` (시드 코드값·규칙은 마이그레이션으로 이미 있음, `R = lambda n: NumberRule.objects.get(name=n)`):
  - `test_next_serial`: `next_serial([], 'X', 3) == '001'`, `next_serial(['X001','X007'], 'X', 3) == '008'`, `next_serial(['X999'], 'X', 3)` → `NumberingError` 메시지 `일련번호가 다 찼습니다.`
  - `test_serial_ignores_other_shapes`: `next_serial(['KEN-PQ-01-01','KEN-PQ-03'], 'KEN-PQ-', 2) == '04'`, `next_serial(['1VDC001A','1VDC002'], '1VDC', 3) == '003'`, `next_serial(['1VDC1000'], '1VDC', 3) == '001'`.
  - `test_item_code`: 빈 DB에서 `next_number(R('제품코드'), ['1','V','DC']) == '1VDC001'`. `Item(code='1VDC005')` 저장 후 `'1VDC006'`. `['3','V','DC']` → `NumberingError`(허용 값 아님). `default_item_type(R('제품코드'), ['2','V','DC']) == 'SEMI'`.
  - `test_parent_chain`: `next_number(R('원자재'), ['3','1','1','1','1']) == '31111-00001'`, `['3','1','3','2','0'] → '31320-00001'`, `['3','1','2','2','0']` → `NumberingError`(312 아래 중분류 2 없음). `default_item_type(R('원자재'), ['3','1','1','1','1']) == 'RAW'`.
  - `test_doc_numbers`: `Document(number='KEN-PQ-01')`·`'KEN-PQ-01-01'` 저장 후 `next_number(R('관리표준'), ['P','Q']) == 'KEN-PQ-02'`, `next_number(R('양식'), ['KEN-PQ-01']) == 'KEN-PQ-01-02'`, `next_number(R('양식'), ['KEN-PQ-09'])` → 오류(없는 문서). `Item(code='1TDS001')` 저장 후 `next_number(R('기술문서'), ['1TDS001','BM']) == '1TDS001-BM001'`. `candidates(fields(R('양식'))[0]) == ['KEN-PQ-01']`.
  - `test_drawing_part_counts_documents`: `Item(code='1TRT038')`, `Item(code='1TRT038-AS101')`, `Document(number='1TRT038-AS105')` 저장 후 `next_number(R('도면 품번'), ['1TRT038','AS']) == '1TRT038-AS106'`, `['1TRT038','DT'] → '1TRT038-DT001'`, `['1TRT038','BM']` → `NumberingError`, `['1TRT099','AS']` → `NumberingError`(없는 제품). `default_item_type(R('도면 품번'), ['1TRT038','DT']) == 'RAW'`, `'AS'`면 `'SEMI'`.
  - `test_std_part`: `Item(code='1TRT038')` 저장 후 `next_number(R('표준품'), ['3','1TRT038']) == '3TRT038-0001'`. `Item(code='3TRT038-0014')` 저장 후 `'3TRT038-0015'`. `describe('3TRT038-0001') == [('3','원자재'), ('T','Train/Tram, 철차/트램용 축전지'), ('RT','현대로템'), ('038','제품코드 일련번호'), ('0001','일련번호')]`. `describe('1TRT38-DT302') == []`.
  - `test_describe`: `describe('1VZZ001')`의 세 번째 항목 `('ZZ','미등록')`. `describe('31111-00001')`의 뜻 열 = `['원자재','PBA, 회로자재','Capacitor','Chip','size 1005','일련번호']`. `describe('1TDS001-BM001')` 마지막 두 항목 `('BM','BOM')`, `('001','일련번호')`. `describe('KEN-PQ-01-01') == [('P','절차서'), ('Q','품질'), ('01','관리표준 일련번호'), ('01','일련번호')]`. `describe('ABC') == []`. `describe('1TRT038-AS001', target='ITEM')`은 도면 품번 규칙으로 풀린다(마지막 항목 `('001','일련번호')`, 앞에 `('038','제품코드 일련번호')`).
  - `test_inactive_rule_still_describes`: `customer DC`를 `active=False`로 바꾼 뒤 `next_number(R('제품코드'), ['1','V','DC'])` → `NumberingError`, `describe_text('1VDC001') == '1 완제품 · V Vehicle, 전기자동차(소형자동차 이상) · DC 디피코 · 001 일련번호'`. 규칙 `제품코드`를 `active=False`로 바꾸면 `next_number(...)` → `NumberingError('사용 중지된 규칙입니다.')`, 풀이는 같은 문자열 그대로.
  - `test_company_prefix_change`: `Document(number='KEN-PQ-01')` 저장. `NumberRule(name='관리표준2', target='DOC', pattern='ABC-{관리표준 문서구분}{부서}-{일련2}', sort=8)`을 `full_clean()` 후 저장, `관리표준`은 `active=False`. `next_number(R('관리표준2'), ['P','Q']) == 'ABC-PQ-01'`. `next_number(R('관리표준'), ['P','Q'])` → `NumberingError`. `describe('KEN-PQ-01') == describe('ABC-PQ-01') == [('P','절차서'), ('Q','품질'), ('01','일련번호')]`. `NumberRule(name='양식2', target='DOC', pattern='{문서:관리표준2}-{일련2}')` `full_clean()` 통과.
  - `test_next_revision`: `next_revision([]) == '0'`, `next_revision(['0','1']) == '2'`, `next_revision(['Rev.3','A','rev 1']) == '4'`, `next_revision(['A','B']) == '0'`.

- [ ] **Step 2: 실행해 실패 확인** — `./.venv/Scripts/python manage.py test core.tests_numbering.NumberingTest` → `ImportError`(없는 함수).

- [ ] **Step 3: 구현** — 위 Interfaces 그대로. 토큰 너비가 모두 고정이므로 `matches`·`describe`는 정규식 대신 위치로 잘라 맞춘다. `Document`는 함수 안에서 `apps.get_model('qms', 'Document')`.

- [ ] **Step 4: 통과 확인** — `./.venv/Scripts/python manage.py test core.tests_numbering` PASS.

- [ ] **Step 5: 커밋** — `git add core/numbering.py core/tests_numbering.py` → `feat: 규칙 기반 번호 계산과 번호 풀이를 더한다`

---

### Task 4: 품번 자동 번호 API

**Files:**
- Modify: `core/api/master.py` (`_row`, `_detail`, `ItemListView.post`, 새 뷰 2개)
- Modify: `core/api/urls.py` (경로 2개)
- Test: `core/api/tests.py` (`ItemApiTest`에 추가)

**Interfaces:**
- Consumes: Task 3의 `fields`, `candidates`, `next_number`, `default_item_type`, `codebook`, `rulebook`, `describe_text`, `NumberingError`; Task 2 `NumberRule`.
- Produces:
  - `GET /api/core/numbering/item-options/` (`require_perm(user, 'core.add_item')`) → 품번 대상 활성 규칙만(참조 규칙이 지워진 규칙은 뺀다), `sort` 순:
    `{"rules": [{"id", "name", "pattern", "fields": [{"kind": "code"|"ref", "label", "parent": <부모 묶음 field의 index> | null, "options": [...]}]}]}`
    - code field: `label`은 묶음 라벨, `options`는 활성 코드값(허용 값이 있으면 그것만) `{"id","code","name","item_type","parent_id"}`. 화면은 `parent`가 가리키는 field에서 고른 option의 `id`와 `parent_id`가 같은 것만 보인다.
    - ref field: `label`은 참조 규칙 이름, `options`는 `candidates`의 번호 `{"code": 번호, "name": 품명}`.
  - `GET /api/core/numbering/item-preview/?rule=<id>&v=..&v=..` (`core.add_item`) → `{"number": "1VDC001", "item_type": "FIN"}`. 규칙이 없거나 품번 대상이 아니거나 `NumberingError`·값 개수 불일치 → `_bad(msg)` 400.
  - `POST /api/core/items/` 본문에 `auto: {"rule": <id>, "values": [...]}`가 있으면 `code`를 무시하고 서버가 계산한다. `item_type`은 본문 값이 있으면 그것, 없으면 `default_item_type`; 둘 다 비면 `_bad('구분을 고르세요.', 'item_type')`. `auto`가 없으면 지금 동작 그대로.
  - `_row(i, book, rules)` 결과에 `"code_parts": describe_text(i.code, 'ITEM', book, rules)` 추가(목록은 `codebook()`·규칙 목록을 한 번만 불러 넘긴다). `_detail` 결과에도 `"code_parts"`.

- [ ] **Step 1: 실패하는 테스트 작성** (`ItemApiTest`, 기존 클래스의 사용자·로그인 준비를 그대로 쓴다):
  - `test_item_options`: 200, 규칙 이름 `['제품코드','원자재','도면 품번','표준품']`. 제품코드 첫 field의 option 코드 `['1','2']`. 원자재 field 3개째(`자재 대분류`)의 `parent == 1`. `customer DC`를 끄면 고객사 option에서 빠진다. 규칙 `표준품`을 끄면 규칙 목록에서 빠진다.
  - `test_item_preview`: `?rule=<제품코드 id>&v=1&v=V&v=DC` → `{"number":"1VDC001","item_type":"FIN"}`. `v=3&v=V&v=DC` → 400. 문서 규칙(`관리표준`) id → 400.
  - `test_auto_code_recomputed_on_save`: preview로 `1VDC001`을 본 뒤 `Item.objects.create(code='1VDC001', ...)`, 그 다음 `auto={"rule": 제품코드 id, "values": ["1","V","DC"]}`로 POST → 201, 응답 `code == '1VDC002'`, `item_type == 'FIN'`.
  - `test_auto_raw`: 원자재 `["3","1","1","1","1"]` → `code == '31111-00001'`, `item_type == 'RAW'`.
  - `test_auto_drawing_part`: `Item(code='1TRT038', item_type='FIN')` 준비. 도면 품번 `["1TRT038","AS"]` → 201, `code == '1TRT038-AS001'`, `item_type == 'SEMI'`. 같은 값 + 본문 `item_type='RAW'` → `code == '1TRT038-AS002'`, `item_type == 'RAW'`. `["1TRT038","BM"]` → 400. options 도면 품번 첫 field의 option 코드에 `1TRT038`.
  - `test_auto_std_part`: 같은 준비, 표준품 `["3","1TRT038"]` → `code == '3TRT038-0001'`, `item_type == 'RAW'`.
  - `test_auto_inactive_rejected`: `industry V`를 끄고 POST → 400, `detail`에 `사용 중지`.
  - `test_auto_integrity_retry_message`: `core.api.master.next_number`를 이미 있는 품번을 돌려주도록 `unittest.mock.patch`하고 POST → 400, `detail == '같은 번호가 방금 사용되었습니다. 다시 시도하세요.'`, 품번 개수 변화 없음.
  - `test_manual_code_unchanged`: `auto` 없이 `code='ABC-1'` POST → 201(모양 검사 없음).
  - `test_code_parts`: `Item(code='1VDC001')` 목록 행 `code_parts`가 `'1 완제품 · '`로 시작, `code='ABC-1'` 행은 `''`. 상세도 `code_parts` 있음.
  - `test_numbering_requires_add_item`: `core.add_item` 없는 사용자(검사원) → options·preview 403.

- [ ] **Step 2: 실행해 실패 확인** — `./.venv/Scripts/python manage.py test core.api.tests.ItemApiTest` → 404·KeyError로 실패.

- [ ] **Step 3: 구현** — `auto.rule`은 정수, `auto.values`는 문자열 목록이어야 한다(아니면 `_bad`). 저장은 `with transaction.atomic():` 안에서 `next_number` → `item.full_clean()` → `item.save()`. `full_clean`의 품번 중복 `ValidationError`와 `IntegrityError` 둘 다 `_bad('같은 번호가 방금 사용되었습니다. 다시 시도하세요.', 'code')`로 바꾼다(자동 번호일 때만; 직접 입력의 중복 오류는 지금처럼). `NumberingError`는 `_bad(str(e))`. `core/api/master.py`는 `from core.numbering import next_number`처럼 이름으로 import한다(테스트가 그 이름을 patch). URL 이름은 `numbering-item-options`, `numbering-item-preview`.

- [ ] **Step 4: 통과 확인** — `./.venv/Scripts/python manage.py test core.api` PASS.

- [ ] **Step 5: 커밋** — `git add core/api/master.py core/api/urls.py core/api/tests.py` → `feat: 규칙 기반 품번 자동 번호 API와 품번 풀이를 더한다`

---

### Task 5: React 품번 등록 창 자동 번호와 풀이 표시

**Files:**
- Modify: `frontend/src/api/master.ts` (`ItemRow.code_parts: string`, `ItemDetail.code_parts: string`, 새 타입)
- Modify: `frontend/src/pages/items/ItemList.tsx` (`NewItem`, 품번 열)
- Modify: `frontend/src/pages/items/ItemPage.tsx` (품번 아래 풀이)
- Modify: `frontend/dist/` (빌드 결과)
- Modify: `scripts/e2e_browser.py` (기준정보 구역에 자동 번호 확인 추가)

**Interfaces:**
- Consumes: Task 4의 두 GET 경로와 POST `auto` 본문, `code_parts`.
- Produces: 없음(화면).

- [ ] **Step 1: 타입** — `NumberOption = {id?: number; code: string; name: string; item_type?: string; parent_id?: number | null}`, `NumberField = {kind: 'code' | 'ref'; label: string; parent: number | null; options: NumberOption[]}`, `NumberRuleOptions = {id: number; name: string; pattern: string; fields: NumberField[]}`, `ItemNumberOptions = {rules: NumberRuleOptions[]}`.

- [ ] **Step 2: 등록 창** — `NewItem`에 antd `Switch` "자동 번호"(기본 켬). 켜면 창을 열 때 `item-options`를 한 번 받고:
  - "규칙" `Select`(규칙 이름, 첫 규칙 기본 선택). 규칙을 바꾸면 값 초기화.
  - field마다 `Select` 하나, 라벨은 field `label`, 옵션 라벨은 `` `${code} ${name}` ``, ref field는 검색 가능. `parent`가 있는 field는 부모 field에서 고른 option의 `id`와 `parent_id`가 같은 option만 보인다. 앞 field를 바꾸면 뒤 field 값 초기화.
  - 값이 다 차면 `item-preview`를 불러 "다음 번호: 1VDC001 (저장할 때 확정)"을 보이고, 구분 `Select`를 응답 `item_type`으로 채운다(바꿀 수 있음).
  - 자동일 때 품번 입력은 숨기고 `{name, item_type, auto: {rule, values}}`를 POST.
  - 미리보기 옆 "직접 고치기" 버튼: 자동을 끄고 품번 칸에 미리보기 번호를, 구분에 현재 값을 채운다(백 단위 묶음 `AS100` 등을 손으로 고치는 용도). 서버 변경 없음 — 기존 직접 입력 경로.
  - 끄면 지금 폼 그대로.

- [ ] **Step 3: 풀이 표시** — 목록 품번 열 `render`: `code_parts`가 있으면 antd `Tooltip title={code_parts}`로 감싼다. `ItemPage` 품번 입력 아래 `Typography.Text type="secondary"`로 `code_parts`(빈 값이면 표시 안 함).

- [ ] **Step 4: 빌드** — `cd frontend && npm run build` 성공(tsc 오류 0).

- [ ] **Step 5: e2e 추가** — `scripts/e2e_browser.py`의 기준정보(품번) 확인 근처에: 품번 목록에서 새 품번 → 자동 번호 켬 → 규칙 `제품코드`, 품목분류 `1`, 산업 `V`, 고객사 `DC` 선택 → 미리보기 텍스트가 `1VDC\d{3}` → 품명 입력 후 만들기 → 상세 품번 입력값이 미리보기 번호와 같고 풀이에 `디피코`가 보인다. 이어서 새 품번 → 규칙 `도면 품번` → 제품코드에 방금 만든 `1VDC…` 번호, 설계자료분류 `AS` → 만들기 → 상세 품번이 `^1VDC\d{3}-AS\d{3}$`에 맞는다.

- [ ] **Step 6: e2e 실행** — `./.venv/Scripts/python scripts/e2e_browser.py` 끝까지 통과(기존 확인 포함).

- [ ] **Step 7: 커밋** — `git add frontend/src/api/master.ts frontend/src/pages/items/ItemList.tsx frontend/src/pages/items/ItemPage.tsx frontend/dist scripts/e2e_browser.py` → `feat: 새 품번 창에 규칙 기반 자동 번호와 품번 풀이를 더한다`

---

### Task 6: 관리 화면 문서번호 자동 부여·개정 자동 채움·번호 풀이

**Files:**
- Modify: `qms/models.py:570` 부근 (`DocumentRevision.revision`에 `blank=True`, `clean()`/`save()`에서 빈 개정 채움)
- Create: `qms/migrations/0010_documentrevision_revision_blank.py` (`makemigrations qms`)
- Modify: `qms/admin.py:419-445` (`DocumentAdmin` 폼·목록, `RevisionInline`)
- Create: `core/static/qms/number_rule.js`
- Test: `qms/tests.py` (`DocumentNumberingTest` 새 클래스)

**Interfaces:**
- Consumes: Task 3의 `fields`, `candidates`, `next_number`, `next_revision`, `describe_text`, `codebook`, `NumberingError`; Task 2 `NumberRule`.
- Produces: 없음.

- [ ] **Step 1: 실패하는 테스트 작성** — `DocumentNumberingTest(TestCase)`, 슈퍼유저로 관리 화면 POST(인라인 관리폼 0개 포함):
  - `test_std_doc_auto`: `/admin/qms/document/add/?rule=<관리표준 id>`에 `number=''`, `number_rule=<관리표준 id>`, `v0='P'`, `v1='Q'`, `title='x'` → 302, `Document.objects.get(title='x').number == 'KEN-PQ-01'`.
  - `test_form_auto`: `KEN-PQ-01` 있을 때 양식 규칙, `v0='KEN-PQ-01'` → `KEN-PQ-01-01`.
  - `test_tech_auto`: `Item(code='1TDS001')` 있을 때 기술문서 규칙, `v0='1TDS001'`, `v1='BM'` → `1TDS001-BM001`.
  - `test_blank_number_needs_rule`: `number=''`, `number_rule=''` → 200(폼 다시 보임), 오류 문구 `문서번호를 입력하거나 번호 규칙을 고르세요.`
  - `test_manual_number_kept`: `number='OLD-001'` → 그대로 저장(모양 검사 없음).
  - `test_rule_fields_rendered`: `GET add/?rule=<양식 id>` HTML에 `name="v0"` 선택 칸, 선택지에 `KEN-PQ-01`은 있고 `KEN-PQ-01-01`은 없다. `GET add/` `number_rule` 선택지는 문서 대상 활성 규칙만(`관리표준`, `양식`, `기술문서`), 품번 규칙 `제품코드`는 없다. 비활성 `dept`는 관리표준 규칙의 `v1` 선택지에 없다. 페이지에 `number_rule.js`가 실려 있다.
  - `test_blank_revision_filled`: 개정 `'Rev.1'`, `'A'`가 있는 문서에 `DocumentRevision(document=d, revision='')`를 `full_clean()` 후 저장 → `revision == '2'`. 개정이 없는 문서는 `'0'`.
  - `test_list_shows_parts`: 문서 목록 HTML에 `title="` 속성으로 `P 절차서 · Q 품질`이 들어 있다.

- [ ] **Step 2: 실행해 실패 확인** — `./.venv/Scripts/python manage.py test qms.tests.DocumentNumberingTest` → 실패.

- [ ] **Step 3: 개정 자동 채움** — `DocumentRevision.revision`에 `blank=True`. `clean()`(있으면 기존 내용 유지)과 `save()` 앞부분에서 `if not self.revision.strip(): self.revision = next_revision(같은 문서의 다른 개정 revision 값들)`. `makemigrations qms -n documentrevision_revision_blank` 결과가 `AlterField` 1개(+historical 1개)뿐인지 읽어 확인. `RevisionInline`과 `DocumentRevisionAdmin` 폼에서 개정 칸 도움말: `비워 두면 마지막 숫자 개정 + 1로 채웁니다.`

- [ ] **Step 4: 문서 추가 폼** — `DocumentAdmin.get_form(request, obj=None)`: 추가 화면(`obj is None`)에서만 폼 클래스를 만들어 돌려준다:
  - 모델 필드 `number`는 `required=False`.
  - `number_rule` ChoiceField(`('', '직접 입력')` + 문서 대상 활성 규칙), 초기값은 `request.GET['rule']`.
  - 고른 규칙(`request.POST['number_rule']` 또는 `request.GET['rule']`)의 `fields(rule)`마다 `v0..vn` ChoiceField(`required=False`, 라벨은 묶음 라벨/참조 규칙 이름). code는 활성 코드값(허용 값이 있으면 그것만) `code name`, 부모 묶음이면 `code name (상위 code)`로 보이고 값은 code — 부모 일치는 `next_number`가 검사한다. ref는 `candidates(token)`.
  - `clean()`: 번호가 비었으면 `next_number(rule, [v0..vn])`로 `cleaned_data['number']`·`self.instance.number`를 채운다. `NumberingError`·빈 칸은 폼 오류. 번호도 규칙도 없으면 `문서번호를 입력하거나 번호 규칙을 고르세요.`
  - `get_fieldsets`로 추가 화면에만 "자동 번호" 묶음(`number_rule`, `v0..vn`)을 덧붙인다. 수정 화면은 지금 그대로.
  - `class Media: js = ['qms/number_rule.js']`(`core/admin.py:408`의 Media 방식). `number_rule.js`: `#id_number_rule`이 바뀌면 `location.search = '?rule=' + 값`으로 다시 연다(입력하던 제목은 사라진다 — 규칙을 먼저 고르는 안내를 `number_rule` 도움말에 적는다: `먼저 고르면 화면이 그 규칙의 칸으로 다시 열립니다.`).
  - 동시 저장: `DocumentAdmin.save_model`에서 자동 번호였으면 `with transaction.atomic(): obj.save()`를 `IntegrityError` 시 번호를 다시 계산해 한 번 더 시도한다. 그래도 실패하면 `IntegrityError`를 그대로 올린다 — `# shortcut: 두 번 연속 충돌은 500, 사용자가 몇 명뿐이라 충분. 사용자가 늘면 폼 오류로 돌린다.`

- [ ] **Step 5: 목록 풀이** — `list_display`의 `'number'`를 `number_display`로 바꾸고 `list_display_links=['number_display']`, `@admin.display(description='문서번호', ordering='number')`, `format_html('<span title="{}">{}</span>', describe_text(obj.number, 'DOC', ...), obj.number)`. 코드표·규칙은 `changelist_view`에서 한 번만 읽어 둔다(행마다 쿼리 금지).

- [ ] **Step 6: 통과 확인** — `./.venv/Scripts/python manage.py test qms` PASS, `makemigrations --check --dry-run` → `No changes detected`.

- [ ] **Step 7: 커밋** — `git add qms/models.py qms/migrations/0010_documentrevision_revision_blank.py qms/admin.py qms/tests.py core/static/qms/number_rule.js` → `feat: 규칙 기반 문서번호 자동 부여와 개정 자동 채움을 더한다`

---

### Task 7: 문서 갱신과 전체 검증

**Files:**
- Modify: `README.md` (`## 새 기능 사용법` 아래 "번호 자동 부여"와 "번호 체계 바꾸는 법" 소절; `#### 기준정보` 소절에 번호 코드값·번호 규칙 한 줄)
- Modify: `docs/business-rules.md` (새 절 `## 12. 번호 부여`)
- Modify: `docs/architecture.md` (`core` 모듈 표에 `numbering.py` 한 줄, API 설명에 `/api/core/numbering/item-options/`·`item-preview/`)
- Modify: `docs/testing.md` (테스트 파일 표에 `core/tests_numbering.py`, `DocumentNumberingTest`)

- [ ] **Step 1: business-rules 12절** — 틀 문법 표와 초기 규칙 7개 표(설계 4.1·4.2절 그대로, 도면 품번·표준품 "GD-02 미정의·현장 관행" 메모), 규칙 잠금(이름·대상·틀 수정 불가, 사용 중지만), "도면 품번 = 도면 문서번호"(일련번호는 `Item.code`·`Document.number` 양쪽 최댓값 + 1), 일련번호 규칙(빈 번호 재사용 안 함, 모양이 정확히 맞는 번호만 계산), 끝 번호 초과 오류, 사용 중지 규칙·코드 거부와 풀이 유지, 직접 입력 허용·모양 검사 없음, 개정 자동 채움 규칙, 코드 위치(`core/numbering.py`, `core/models.py` `CodeValue`·`NumberRule`, `core/api/master.py`, `qms/admin.py` `DocumentAdmin.get_form`, `qms/models.py` `DocumentRevision`).

- [ ] **Step 2: README "번호 체계 바꾸는 법"** — 설계 8절의 표와 KEN → ABC 예시를 그대로 옮긴다. README·architecture·testing에 적은 경로·명령이 실제로 있는지 `ls`·`grep`으로 확인.

- [ ] **Step 3: 전체 검증** — 아래를 실행하고 출력 그대로 기록:
  - `./.venv/Scripts/python manage.py test` → `OK` (기존 361개 + 새 테스트)
  - `./.venv/Scripts/python manage.py makemigrations --check --dry-run` → `No changes detected`
  - `./.venv/Scripts/python manage.py check` → 문제 없음
  - 운영 DB 사본에서 마이그레이션: `data/` DB를 스크래치 폴더로 복사하고 그 사본을 가리키게 해 `migrate`를 실행, 코드값 개수(`category` 3 … `design` 34)·규칙 7개와 기존 `Item`·`Document` 개수가 그대로인지 확인한다(`docs/testing.md`의 데이터 마이그레이션 절차를 따른다). 운영 DB 자체에는 적용하지 않는다.

- [ ] **Step 4: 커밋** — `git add README.md docs/business-rules.md docs/architecture.md docs/testing.md` → `docs: 번호 부여 규칙과 번호 체계 바꾸는 법을 문서에 더한다`
