# A단계 기준정보·관계 레지스트리 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사업장·부서·직원·거래처(담당자·인증)·사용자 정의 칸·공통 첨부를 기준정보로 만들고, 기존 글자 칸(공급처·고객사·심사 대상)을 새 기준정보에 연결하며, 어느 기록에서나 "연결" 패널로 관련 기록을 본다.

**Architecture:** 새 모델은 모두 `core/models.py`에 두고 공통 칸은 추상 모델 `MasterModel`로 묶는다. 기존 표에는 null 가능한 외래키만 더하고(글자 칸은 그대로), 관리 명령 `link_masters`가 글자 값으로 외래키를 채운다. 관계 목록은 새 파일 `core/relations.py`가 `_meta`에서 만들고 `/api/relations/…`로 내보내며, React `RelationsPanel`·`AttachmentPanel`이 기존 `RecordPage` 오른쪽 탭에 붙는다.

**Tech Stack:** Django 6.1, DRF, django-simple-history, SQLite, React 19 + TypeScript + Vite + antd 6.

**Spec:** `docs/superpowers/specs/2026-11-11-data-model-detail.md` (1~3절), `docs/superpowers/specs/2026-11-11-ux-relations-design.md` (U1, U2, 5절 접근성)

**이번 계획 범위 밖:** U1 지도 API(`graph/`), U3~U9, B단계 이후 표. U2의 "+ 연결" 단추와 Shift+누르기 미리보기는 U5·P2가 생긴 뒤 붙인다.

## Global Constraints

- 새 의존성 금지(`requirements.txt`, `package.json` 변경 금지). 오프라인 동작.
- 화면 문구·오류·커밋 메시지는 한국어. 커밋은 한국어 Conventional Commits, 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 마이그레이션은 **추가만** 한다: 새 표, 기존 표에 null 가능한 외래키. 기존 칸 삭제·변경·데이터 수정 마이그레이션 금지. 기존 글자 칸(`Lot.supplier`, `Shipment.customer`, `Scar.supplier`, `CustomerRule.customer`, `CustomerClaim.customer`, `PpapSubmission.customer`, `InternalAudit.auditor/auditee`)은 지우지 않고 필수 여부도 바꾸지 않는다.
- 새 모델은 모두 `history = HistoricalRecords()`, 한국어 `verbose_name`, 관리 화면은 `BaseAdmin`(삭제는 시스템 관리자만).
- 기준정보 행은 지우지 않고 `active=False`로 사용 중지한다.
- `core` → `qms`는 모듈 수준에서 import하지 않는다. 함수 안에서 `apps.get_model` 또는 지역 import만 쓴다.
- 권한(사용자 승인 사항): 사업장·부서·직원·거래처·사용자 정의 칸의 추가·수정은 **품질팀장 그룹과 시스템 관리자만**. 품질엔지니어는 보기만. 거래처 담당자·인증은 엔지니어도 추가·수정.
- 첨부 파일은 `DATA_DIR/'attachments'`(MEDIA 밖)에 두고 서버 뷰로만 내려준다. `personal` 앱 기록(`qms.models.PRIVATE_APPS`)에는 붙일 수 없다.
- `link_masters --apply`는 쓰기 전에 반드시 `backup`을 실행한다. 기존 외래키 값이 있으면 덮어쓰지 않는다. 글자 칸은 바꾸지 않는다.
- 오류 문구(그대로 쓴다): 부서 순환 `상위 부서가 자기 자신이나 하위 부서일 수 없습니다.`, 거래처 구분 없음 `협력사·고객사·외주처·교정기관 중 하나 이상을 고르세요.`, 사용자 정의 칸 키 잠금 `저장된 칸의 키·대상은 바꿀 수 없습니다.`, 선택 목록 없음 `종류가 "선택"이면 선택지를 입력하세요.`, 개인 기록 첨부 `개인 기록에는 첨부할 수 없습니다.`, 백업 폴더 없음 `백업 폴더를 --backup-dir이나 QMS_BACKUP_DIR로 지정하세요.`
- `data/`, `.superpowers/`, `.venv/`는 커밋하지 않는다. 사용자 미커밋 변경은 건드리지 않고 내 파일만 `git add`한다.
- 테스트 명령(Bash): `./.venv/Scripts/python manage.py test`, `./.venv/Scripts/python manage.py makemigrations --check --dry-run`, `./.venv/Scripts/python scripts/e2e_check.py`, `cd frontend && npm run build`, `python scripts/e2e_browser.py`(시스템 Python).

## Review Focus

1. **개인 기록에 첨부·연결:** `personal` 기록에 첨부를 붙이거나 연결 패널로 개인 기록이 보이면 안 된다 → Task 4 `test_attachment_rejects_personal`, Task 6 `test_registry_excludes_personal`.
2. **권한 없는 묶음:** 검사원이 볼 권한이 없는 표(예: CAPA)는 연결 패널에서 개수까지 숨긴다 → Task 6 `test_group_hidden_without_permission`.
3. **승인된 기록 정제:** 승인 잠긴 `PpapSubmission`·보류 LOT의 `Shipment`도 `link_masters`가 외래키를 채우고, 잠금·출하 인터록 검사로 실패하지 않으며 변경 이력이 남는다 → Task 5 `test_link_approved_ppap_keeps_history`.
4. **이름이 겹치는 거래처:** 같은 글자 값에 맞는 거래처가 둘 이상이면 연결하지 않고 보고한다 → Task 5 `test_ambiguous_name_not_linked`.
5. **부서 순환:** A의 상위를 A의 하위로 바꾸면 거부 → Task 1 `test_department_cycle_rejected`.
6. **첨부 내려받기 권한:** 대상 기록을 볼 권한이 없는 사용자가 파일 주소를 알아도 403 → Task 4 `test_download_requires_target_view`.
7. **엔지니어의 기준정보 수정:** 품질엔지니어가 관리 화면에서 거래처를 고치면 403, 품질팀장은 허용 → Task 1 `test_master_edit_team_lead_only`.

---

### Task 1: 공통 추상 모델, 사업장·부서·직원, 역할 권한, 관리 화면

**Files:**
- Modify: `core/models.py` (끝에 추가)
- Modify: `core/admin.py`, `core/nav.py`, `qms/apps.py`
- Create: `core/migrations/0014_masters.py` (makemigrations로 생성; Task 2~4의 모델도 같은 작업 중이면 각 Task마다 새 번호 마이그레이션을 만들어도 된다)
- Create: `core/tests_masters.py`

**Interfaces:**
- Produces:
  - `class MasterModel(models.Model)` (abstract): `created_at`(auto_now_add), `created_by`(FK User, null, `editable=False`, `related_name='+'`), `updated_at`(auto_now), `active`(기본 True), `note`(TextField, blank), `extra`(JSONField, 기본 `dict`, blank). `clean()`은 Task 3에서 `validate_extra(self)`를 부른다(Task 1에서는 빈 훅).
  - `Site(MasterModel)`: `code`(10, unique), `name`(60), `address`(200, blank), `phone`(30, blank). `__str__` = name.
  - `Department(MasterModel)`: `code`(10, unique), `name`(60), `site`(FK Site, PROTECT), `parent`(FK self, null, PROTECT, `related_name='children'`), `manager`(FK User, null, SET_NULL, `related_name='+'`), `doc_code`(FK CodeValue, null, PROTECT, `limit_choices_to={'group': 'dept'}`), `sort`(int, 0). `clean()`: parent 사슬을 따라가 self가 나오면 순환 오류.
  - `Employee(MasterModel)`: `user`(OneToOne User, CASCADE 아님 → PROTECT, `related_name='employee'`), `emp_no`(20, blank; 값이 있으면 고유 → `UniqueConstraint(fields=['emp_no'], condition=~Q(emp_no=''), name='uniq_emp_no')`), `department`(FK Department, PROTECT), `position`(30, blank), `job`(60, blank), `phone_ext`·`mobile`(30, blank), `signature`(ImageField, `upload_to='signature/'`, blank, `validators=[validate_photo]`).
  - 각 모델 `history = HistoricalRecords()`.
  - `qms/apps.py`: 상수 `TEAM_LEAD_ONLY = ['site', 'department', 'employee', 'partner', 'fielddef']` (모델 이름). 품질엔지니어 = 기존 engineer에서 이 모델들의 `add_`·`change_` 권한 제외. 품질팀장 = 기존 engineer 그대로.
  - `core/admin.py`: `SiteAdmin`, `DepartmentAdmin`, `EmployeeAdmin` (모두 `BaseAdmin`), `MasterModel`의 `created_by`는 `save_model`에서 새 행일 때 `request.user`로 채운다.
  - `core/nav.py`: '기준정보 및 시스템 관리' 묶음 맨 앞에 `('사업장', 'admin:core_site_changelist', 'core.view_site')`, `('부서', 'admin:core_department_changelist', 'core.view_department')`, `('직원', 'admin:core_employee_changelist', 'core.view_employee')`.

- [ ] **Step 1: 실패하는 테스트 작성** (`core/tests_masters.py`, `class MasterTest(TestCase)`)

```python
def test_department_cycle_rejected(self):
    a = Department.objects.create(code='A', name='품질', site=self.site)
    b = Department.objects.create(code='B', name='품질보증', site=self.site, parent=a)
    a.parent = b
    with self.assertRaisesMessage(ValidationError, '상위 부서가 자기 자신이나 하위 부서일 수 없습니다.'):
        a.full_clean()

def test_emp_no_unique_only_when_filled(self):
    # emp_no '' 두 명은 허용, 같은 'E001' 두 명은 IntegrityError(또는 full_clean ValidationError)

def test_master_edit_team_lead_only(self):
    # 품질엔지니어 그룹 사용자: POST admin:core_site_add → 403, 품질팀장: 302
    # 품질엔지니어도 admin:core_site_changelist GET → 200

def test_created_by_set_on_admin_add(self):
    # 품질팀장이 관리 화면으로 Site 추가 → created_by == 그 사용자
```

`setUp`: `call_command`로 역할을 다시 만들 필요 없음(테스트 DB migrate 때 `ensure_roles`가 돈다). 사용자는 `is_staff=True` + `groups.add(Group.objects.get(name=...))`.

- [ ] **Step 2: 실행해서 실패 확인**
Run: `./.venv/Scripts/python manage.py test core.tests_masters`
Expected: ImportError(`Department` 없음)

- [ ] **Step 3: 모델·admin·nav·권한 구현, `makemigrations core` 후 마이그레이션 내용 확인(CreateModel만 있어야 한다)**

- [ ] **Step 4: 통과 확인**
Run: `./.venv/Scripts/python manage.py test core.tests_masters && ./.venv/Scripts/python manage.py test`
Expected: 전부 OK (기존 테스트 포함 — 엔지니어 권한 축소가 기존 테스트를 깨면 그 테스트가 새 모델이 아닌 다른 것을 쓰는지 확인)

- [ ] **Step 5: 커밋** `feat: 사업장·부서·직원 기준정보와 품질팀장 전용 편집 권한을 추가한다`

---

### Task 2: 거래처·담당자·인증, 인증 만료 할 일

**Files:**
- Modify: `core/models.py`, `core/admin.py`, `core/nav.py`
- Modify: `qms/due.py`, `qms/widgets.py`
- Create: 새 core 마이그레이션
- Test: `core/tests_masters.py` (`PartnerTest`), `qms/tests.py` 또는 `qms/api/tests.py`의 할 일 테스트 옆

**Interfaces:**
- Consumes: `MasterModel` (Task 1)
- Produces:
  - `Partner(MasterModel)`: `code`(20, unique), `name`(100), `name_en`(100, blank), `is_supplier`·`is_customer`·`is_outsource`·`is_calibrator`(bool, False), `biz_no`(12, blank, 값 있으면 고유 — `uniq_biz_no` 조건부 제약), `ceo`(30, blank), `address`(200, blank), `phone`(30, blank), `email`(blank), `status` 선택 `NEW='new'`/`APPROVED='approved'`/`CONDITIONAL='conditional'`/`SUSPENDED='suspended'` (표시 `신규 평가`/`승인`/`조건부 승인`/`거래 중지`, 기본 NEW), `grade` 선택 A~D(blank), `evaluated_on`(date, null), `payment_terms`(60, blank), `currency`(3, 기본 `'KRW'`), `customer_code_prefix`(FK CodeValue, null, PROTECT, `limit_choices_to={'group': 'customer'}`, `related_name='+'`). `clean()`: 구분 4개가 모두 거짓이면 오류. `__str__` = name.
  - `PartnerContact(models.Model)`: `partner`(FK, CASCADE, `related_name='contacts'`), `name`(30), `role` 선택 `영업/품질/구매/기술/기타`(값 `sales/quality/purchase/tech/etc`), `phone`(30, blank), `email`(blank), `primary`(bool). history.
  - `PartnerCertificate(models.Model)`: `partner`(FK, CASCADE, `related_name='certificates'`), `standard` 선택 `ISO 9001, IATF 16949, AS9100, ISO 17025, ISO 14001, NADCAP, 기타`, `cert_no`(60, blank), `issuer`(100, blank), `scope`(200, blank), `valid_until`(date), `file`(FileField, `upload_to='partner_cert/%Y/'`, blank). history. — 협력사 인증서는 기밀이 아니므로 MEDIA에 둔다 **[내 판단]**.
  - `PartnerAdmin(BaseAdmin)`: 인라인 `PartnerContactInline`, `PartnerCertificateInline`; `list_display = ('code','name','status','grade', 구분 4개, 'active')`, `list_filter = ('status','is_supplier','is_customer','active')`, `search_fields = ('code','name','name_en','biz_no')`.
  - nav: '고객 및 협력사' 묶음 맨 앞에 `('거래처', 'admin:core_partner_changelist', 'core.view_partner')`.
  - `due_items()` 새 키 `'partner_certs'`: `PartnerCertificate.objects.filter(partner__active=True, valid_until__lte=today + 30일).select_related('partner')` 리스트.
  - `qms/widgets.py`: `TODO_SECTIONS`에 `('partner-certs', '협력사 인증 만료', 'partner_certs')`, `todo_lists_data`에 `'partner_certs': _lines(..., str, lambda c: change('core_partner', c.partner), valid_until=..., overdue=lambda c: c.valid_until < d['today'])`. `todo_lists.html`에 그 구역을 기존 `gauges` 구역과 같은 모양으로 추가. `digest()`에 `('협력사 인증 만료', [f'{c.partner} · {c.get_standard_display()} · {c.valid_until}' ...])`.
  - `PartnerCertificate.__str__` = `f'{partner} {standard 표시}'`.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_partner_needs_a_role(self):
    p = Partner(code='P1', name='대한정밀')
    with self.assertRaisesMessage(ValidationError, '협력사·고객사·외주처·교정기관 중 하나 이상을 고르세요.'):
        p.full_clean()

def test_biz_no_unique_only_when_filled(self): ...

def test_engineer_can_edit_certificate_not_partner(self):
    # 품질엔지니어: add_partnercertificate 권한 있음, change_partner 권한 없음 (user.has_perm으로)

def test_expiring_cert_in_due_items(self):
    # valid_until = 오늘+29 → due_items(...)['partner_certs']에 있음, 오늘+31 → 없음, 거래처 active=False → 없음
```

- [ ] **Step 2: 실패 확인** `./.venv/Scripts/python manage.py test core.tests_masters` → ImportError
- [ ] **Step 3: 구현 + makemigrations(CreateModel만)**
- [ ] **Step 4: 전체 테스트 통과 확인** `./.venv/Scripts/python manage.py test`
- [ ] **Step 5: 커밋** `feat: 거래처·담당자·인증 기준정보와 인증 만료 할 일을 추가한다`

---

### Task 3: 사용자 정의 칸 `FieldDef`

**Files:**
- Modify: `core/models.py`, `core/admin.py`, `core/nav.py`
- Test: `core/tests_masters.py` (`FieldDefTest`)

**Interfaces:**
- Consumes: `MasterModel` (Task 1), `Partner`, `Employee`
- Produces:
  - `FieldDef(models.Model)`: `target`(FK ContentType, PROTECT, `limit_choices_to=extra_targets` 함수 — `MasterModel` 하위 모델의 ContentType만), `key`(40, 정규식 `^[a-z][a-z0-9_]*$`), `label`(60), `kind` 선택 `text/number/date/bool/choice/partner/employee` (표시 `글/수/날짜/예·아니오/선택/거래처/직원`), `choices`(JSON 목록, 기본 `list`, blank), `required`(bool), `sort`(int), `active`(bool, True). `UniqueConstraint(['target','key'])`. history. `clean()`: 저장된 행의 key·target이 바뀌면 `저장된 칸의 키·대상은 바꿀 수 없습니다.`; kind=choice인데 choices 비면 `종류가 "선택"이면 선택지를 입력하세요.`
  - `validate_extra(obj) -> None` (core/models.py 모듈 함수): 그 모델의 활성 FieldDef로 `obj.extra` 검사. 오류는 `ValidationError({'extra': [...]})`, 문구 `'{label}: 값을 입력하세요.'`, `'{label}: 숫자가 아닙니다.'`, `'{label}: 날짜 형식(YYYY-MM-DD)이 아닙니다.'`, `'{label}: 선택지에 없는 값입니다.'`, `'{label}: 없는 거래처입니다.'`, `'{label}: 없는 직원입니다.'`. 값 저장 형식: number는 숫자, date는 `'YYYY-MM-DD'` 문자열, bool은 true/false, partner·employee는 pk 정수. 정의에 없는 키는 그대로 둔다(칸을 사용 중지해도 값이 지워지지 않게).
  - `MasterModel.clean()`이 `validate_extra(self)`를 부른다.
  - `ExtraFieldsMixin` (core/admin.py): `get_form`에서 그 모델의 활성 FieldDef마다 폼 칸 `extra__<key>`를 만든다(text→CharField, number→DecimalField, date→DateField, bool→BooleanField, choice→ChoiceField, partner/employee→ModelChoiceField). 초기값은 `instance.extra`, `save_model` 전에 `obj.extra`에 합친다. `fieldsets`가 있는 Admin이면 끝에 `('사용자 정의 칸', {'fields': [...]})`. Site·Department·Employee·Partner Admin이 이 믹스인을 쓴다.
  - nav '기준정보 및 시스템 관리'에 `('사용자 정의 칸', 'admin:core_fielddef_changelist', 'core.view_fielddef')`.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_fielddef_key_locked(self): ...  # key 바꾸고 full_clean → 잠금 문구
def test_choice_needs_choices(self): ...
def test_extra_validated(self):
    FieldDef.objects.create(target=ct(Partner), key='bank', label='주거래 은행', kind='choice', choices=['국민', '신한'], required=True)
    p = Partner(code='P1', name='대한정밀', is_supplier=True, extra={})
    # full_clean → '주거래 은행: 값을 입력하세요.'
    p.extra = {'bank': '하나'}  # → '주거래 은행: 선택지에 없는 값입니다.'
    p.extra = {'bank': '국민'}; p.full_clean()  # 통과
def test_inactive_def_keeps_value(self): ...  # 칸 사용 중지 뒤 저장해도 extra['bank'] 유지
def test_admin_form_shows_extra_field(self):
    # 품질팀장이 admin:core_partner_add GET → 응답에 'extra__bank' 있음; POST로 저장 → extra == {'bank': '국민'}
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현 + makemigrations**
- [ ] **Step 4: 전체 테스트 통과**
- [ ] **Step 5: 커밋** `feat: 관리 화면에서 기준정보에 사용자 정의 칸을 더할 수 있게 한다`

---

### Task 4: 공통 첨부 `Attachment`, 내려받기, API, 백업

**Files:**
- Modify: `core/models.py`, `core/admin.py`, `core/views.py`, `config/urls.py`(내려받기 경로), `core/api/urls.py`, `core/api/views.py`
- Modify: `core/management/commands/backup.py`, `core/management/commands/restore.py`, `qms/apps.py`(검사원 권한)
- Test: `core/tests_masters.py` (`AttachmentTest`), `core/api/tests_master.py` 또는 새 `core/api/tests_attachments.py`, `qms/tests.py`의 백업 테스트 옆

**Interfaces:**
- Produces:
  - `attachment_storage()` (core/models.py): `FileSystemStorage(location=settings.DATA_DIR / 'attachments')` — `personal.models.private_storage`와 같은 모양.
  - `Attachment(models.Model)`: `content_type`(FK ContentType, PROTECT), `object_id`(PositiveBigIntegerField), `target`(GenericForeignKey), `kind` 선택 `photo/spec/drawing/manual/purchase/report/warranty/cert/etc` (표시 `사진/사양서/도면/매뉴얼/구매서류/성적서/보증서/인증서/기타`), `file`(FileField, `storage=attachment_storage`, `upload_to='%Y/%m/'`), `title`(100, blank — 비면 `save()`에서 파일 이름), `uploaded_by`(FK User, null, SET_NULL, `editable=False`), `uploaded_at`(auto_now_add). `Index(fields=['content_type','object_id'])`. history. `clean()`: `content_type.app_label in PRIVATE_APPS`면 `개인 기록에는 첨부할 수 없습니다.` (PRIVATE_APPS는 qms에 있으므로 core 안에 같은 목록을 지역 import로 읽는다: 함수 안 `from qms.models import PRIVATE_APPS`).
  - `can_view_target(user, obj) -> bool` (core/models.py 또는 core/views.py): `user.has_perm(f'{app}.view_{model}')`. LOT 등 추가 규칙 없음.
  - 내려받기 뷰 `attachment_download(request, pk)` (`core/views.py`, `staff_member_required`): 대상 볼 권한 없으면 `PermissionDenied`, 있으면 `FileResponse(as_attachment=False)`. URL 이름 `attachment_download`, 경로 `attachments/<int:pk>/`.
  - API `AttachmentListView` (`core/api/views.py`, `GET/POST /api/attachments/?ct=app.model&id=pk`): ct 해석·권한은 `qms.views._memo_target`과 같은 규칙이되 허용 대상은 `ATTACHABLE`이 아니라 "core·qms의 모델 중 relations 제외 목록에 없는 것"(Task 6 전에는 `app_label in ('core','qms')`로 검사). GET은 `core.view_attachment` + 대상 view 권한, POST는 `core.add_attachment` + 대상 view 권한. 응답 행 `{id, title, kind, kind_label, url(=reverse('attachment_download')), uploaded_by, uploaded_at, size}`, 목록 응답 `{'results': [...], 'can_add': bool, 'kinds': [{value,label}]}`. POST는 multipart `file`, `kind`, `title`.
  - `AttachmentAdmin(BaseAdmin)`: 목록에서 대상·종류·제목. 추가는 API·인라인으로만 하고 관리 화면 add는 `has_add_permission=False` **[내 판단]**.
  - `qms/apps.py` 검사원 목록에 `'view_attachment', 'add_attachment'` 추가.
  - `backup`: `DATA_DIR/'attachments'`가 있으면 `target/'attachments'`로 복사. `restore`: `private`와 같은 방식으로 옮기고 복사(옛 백업에 폴더가 없으면 현재 것을 그대로 둔다), 점검 출력에 `첨부 보관 폴더: 있음/없음` 추가.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_attachment_rejects_personal(self):
    a = Attachment(content_type=ContentType.objects.get_for_model(LeaveProfile), object_id=1, kind='etc', file=SimpleUploadedFile('a.txt', b'x'))
    with self.assertRaisesMessage(ValidationError, '개인 기록에는 첨부할 수 없습니다.'):
        a.full_clean()

def test_download_requires_target_view(self):
    # Nonconformance에 첨부; view_nonconformance 없는 staff 사용자 → 403, 품질엔지니어 → 200 + 파일 내용
    # (테스트는 override_settings(DATA_DIR=임시폴더)로 파일을 임시 폴더에 쓴다)

def test_api_upload_and_list(self):
    # 검사원: POST /api/attachments/?ct=qms.inspection&id=… (file, kind='photo') → 201, GET → results 1개, title == 파일 이름

def test_api_rejects_unknown_ct(self):  # ct=personal.leaveprofile → 404

def test_backup_copies_attachments(self):  # 기존 백업 테스트 모양 그대로, 결과 폴더에 attachments/ 있음
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현 + makemigrations**
- [ ] **Step 4: 전체 테스트 통과**
- [ ] **Step 5: 커밋** `feat: 어느 기록에나 붙는 공통 첨부와 권한 검사 내려받기를 추가한다`

---

### Task 5: 기존 표의 연결 칸과 정제 명령 `link_masters`

**Files:**
- Modify: `core/models.py` (`Lot.partner`, `Shipment.partner`)
- Modify: `qms/models.py` (`Scar.partner`, `CustomerRule.partner`, `CustomerClaim.partner`, `PpapSubmission.partner`, `InternalAudit.auditee_dept`, `InternalAudit.auditor_user`)
- Modify: `core/admin.py`, `qms/admin.py` (새 칸을 폼에 보이게, `autocomplete_fields` 또는 기본 선택)
- Create: 새 core 마이그레이션, `qms/migrations/0011_link_masters.py`
- Create: `core/management/commands/link_masters.py`
- Test: `core/tests_masters.py` (`LinkMastersTest`)

**Interfaces:**
- Consumes: `Partner`, `Department` (Task 1~2)
- Produces:
  - 새 칸 모두 `null=True, blank=True, on_delete=PROTECT, related_name='+'`가 아닌 **역방향 이름이 있는** 형태(연결 패널이 쓴다): `Lot.partner`(`related_name='lots'`, `limit_choices_to={'is_supplier': True}`), `Shipment.partner`(`'shipments'`, `{'is_customer': True}`), `Scar.partner`(`'scars'`, 협력사), `CustomerRule.partner`(`'customer_rules'`, 고객사), `CustomerClaim.partner`(`'claims'`, 고객사), `PpapSubmission.partner`(`'ppaps'`, 고객사), `InternalAudit.auditee_dept`(FK Department, `'audits'`), `InternalAudit.auditor_user`(FK User, `related_name='+'`). verbose_name: `거래처`, `심사 대상 부서`, `심사원(사용자)`.
  - 명령 `link_masters [--apply] [--backup-dir PATH]`:
    - 표 정의 `LINKS = [(app_label, model, text_field, fk_field, matcher)]`, 위 8개.
    - 거래처 매칭: 글자 값을 `strip()` 뒤 대소문자 무시로 `code`·`name`·`name_en` 중 하나와 같고, 해당 구분 플래그(협력사/고객사)가 참인 거래처. 후보가 정확히 1개일 때만 연결.
    - 부서 매칭: `code` 또는 `name`. 사용자 매칭: `username` 또는 `get_full_name()`(공백 제거 비교).
    - 이미 외래키가 있는 행, 글자 값이 빈 행은 건너뛴다.
    - 기본(드라이런): 표마다 `연결 가능 N`, `이미 연결 N`, `못 찾음: 값(건수)…`, `여러 후보: 값 → 후보 코드…`, `구분 불일치: 값 → 거래처 코드(협력사 아님)`를 출력하고 아무것도 쓰지 않는다.
    - `--apply`: 먼저 `call_command('backup', backup_dir or env QMS_BACKUP_DIR)`; 없으면 `CommandError('백업 폴더를 --backup-dir이나 QMS_BACKUP_DIR로 지정하세요.')`. 그 뒤 `transaction.atomic()` 안에서 표마다 `bulk_update_with_history(objs, Model, [fk_field], default_change_reason='기준정보 연결(link_masters)')` — `save()`/`clean()`을 거치지 않으므로 승인 잠금·출하 인터록에 막히지 않고 이력은 남는다. 끝에 `연결함 N건` 출력.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_dry_run_writes_nothing(self):
    # Lot.supplier='대한정밀', Partner(name='대한정밀', is_supplier=True) → call_command('link_masters', stdout=out)
    # Lot.partner is None, 출력에 '연결 가능 1'

def test_apply_links_and_backs_up(self):
    # call_command('link_masters', apply=True, backup_dir=tmp) → tmp 아래 qms-* 폴더 있음, lot.partner == p

def test_ambiguous_name_not_linked(self):
    # 같은 name_en 'DH'를 가진 협력사 둘 → 연결 안 됨, 출력에 '여러 후보'

def test_role_mismatch_not_linked(self):
    # Shipment.customer='대한정밀', 그 거래처가 is_customer=False → 연결 안 됨, '구분 불일치'

def test_existing_fk_not_overwritten(self): ...

def test_link_approved_ppap_keeps_history(self):
    # 승인된(approved_at 채움) PpapSubmission, 출하 보류 중 LOT의 Shipment → --apply 성공,
    # ppap.partner == p, ppap.history.count() 가 1 늘어남, 글자 칸 customer 값 그대로

def test_auditor_matched_by_full_name(self): ...  # auditor='홍 길동' ↔ User(first_name='길동', last_name='홍') 공백 무시
```

`backup` 테스트처럼 `override_settings`로 DB 경로를 건드리지 않는다: 테스트 DB는 SQLite 메모리일 수 있으므로 `apply` 테스트에서는 `unittest.mock.patch('core.management.commands.link_masters.call_command')`로 backup 호출만 확인해도 된다 **[내 판단]**.

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 칸 추가 → `makemigrations core qms` → 생성된 파일에 `AddField`만 있는지 읽어서 확인 → 명령 구현**
- [ ] **Step 4: 전체 테스트 통과 + `makemigrations --check --dry-run` → `No changes detected`**
- [ ] **Step 5: 커밋** `feat: 기존 공급처·고객사·심사 대상 글자를 기준정보에 연결하는 칸과 정제 명령을 추가한다`

---

### Task 6: 관계 레지스트리 `core/relations.py`와 API

**Files:**
- Create: `core/relations.py`
- Modify: `core/api/urls.py`, `core/api/views.py`
- Test: `core/api/tests_relations.py`

**Interfaces:**
- Consumes: 모든 core·qms 모델, `Attachment`(Task 4), `qms.models.Memo`·`Evidence`, `qms.memo.target_url`
- Produces:
  - `EXCLUDE = {'core.importprofile', 'qms.dashboardlayout'}` + 이름이 `Historical`로 시작하는 모델 + app_label이 core·qms가 아닌 모델.
  - `Relation` (NamedTuple): `key`(str, `'<app.model>:<field>'`), `label`(str), `model`(모델 클래스), `field`(str — 상대 모델에서 이 기록을 가리키는 칸 이름, 또는 정방향일 때 이 모델의 칸 이름), `direction`(`'in'`|`'out'`), `kind`(`'fk'`|`'m2m'`|`'generic'`).
  - `relations_for(model) -> list[Relation]` (`functools.cache`): 역방향 FK·M2M(`_meta.related_objects`), 정방향 FK·M2M(`_meta.get_fields()`의 `many_to_one`/`many_to_many`/`one_to_one` 중 대상이 EXCLUDE 아닌 것; ContentType·User 대상은 제외 — User는 `auditor_user` 같은 담당자 칸이라 연결 묶음에 넣지 않는다 **[내 판단]**), 일반 연결 3개(`core.Attachment`, `qms.Memo`, `qms.Evidence`(`record_type`/`record_id`)). label = 역방향은 상대 모델 `verbose_name`, 정방향은 칸 `verbose_name`.
  - `record_url(obj) -> str`: `core.item` → `/app/items/<id>`, `qms.inspectionspec` → `/app/specs/<id>`, `qms.controlplan` → `/app/plans/<id>`, `qms.inspection` → `/app/inspections/<id>`, 그 밖은 `qms.memo.target_url(obj)`(함수 안 import).
  - `status_of(obj) -> str`: `approved_at` 칸이 있으면 `승인됨`/`초안`; `result` 칸이 있으면 `get_result_display()`; `closed_at` 칸이 있으면 `종결`/`진행`; `active` 칸이 있고 False면 `사용 중지`; 아니면 `''`.
  - `OPEN_FIRST = ['core.nonconformance', 'qms.capa', 'core.hold']` — 이 모델 묶음을 먼저, 나머지는 개수 내림차순.
  - `group_payload(user, obj, rel, page=None) -> dict | None`: 사용자가 `rel.model`의 view 권한이 없으면 `None`. 일반 연결 `Attachment`는 `core.view_attachment`. 반환 `{key, label, model: 'app.model', field, direction, count, items: [{id, text, status, url}]}`; page가 없으면 앞 5개, 있으면 20개씩.
  - API `RelationsView` `GET /api/relations/<str:label>/<int:pk>/` (이름 `relations`): label이 레지스트리에 없거나 EXCLUDE·개인 앱이면 404, 대상 view 권한 없으면 403. 응답 `{record: {model, id, text, status, url}, incoming: [...], outgoing: [...]}`. 0건 묶음과 `None` 묶음은 뺀다. `?key=<Relation.key>&page=n`이면 그 묶음 하나만 `{…group, page, pages}`.
  - Task 4의 첨부 API의 대상 허용 검사를 `relations.is_registered(label) -> bool`로 바꾼다.

- [ ] **Step 1: 실패하는 테스트** (`class RelationsApiTest(TestCase)`)

```python
def test_lot_incoming_groups(self):
    # LOT 하나에 검사 2건, 부적합 1건, 출하 1건 → GET /api/relations/core.lot/<id>/ (품질팀장)
    # incoming 첫 묶음 model == 'core.nonconformance', 검사 묶음 count == 2, 항목 url 이 '/app/inspections/<id>'
def test_group_hidden_without_permission(self):
    # 검사원(view_capa 없음)으로 CAPA가 연결된 부적합 조회 → incoming에 'qms.capa' 묶음 없음(개수도 없음)
def test_outgoing_partner(self):
    # lot.partner 설정 → outgoing에 label '거래처' 묶음, items[0].text == 거래처 이름
def test_registry_excludes_personal(self):
    # /api/relations/personal.leaveprofile/1/ → 404; relations_for(User) 결과에 personal 모델 없음
def test_excluded_models(self):
    # relations_for(Item) 에 Historical*, dashboardlayout 없음
def test_paging(self):
    # 검사 25건 → ?key=...&page=2 → items 5개, pages == 2
def test_attachments_group(self):
    # 첨부 1건 → incoming에 'core.attachment' 묶음
def test_query_count(self):
    # assertNumQueries 상한: 묶음 수 × 2 + 5
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: 전체 테스트 통과**
- [ ] **Step 5: 커밋** `feat: 기록 사이 연결을 모아 보여 주는 관계 레지스트리와 API를 추가한다`

---

### Task 7: React 연결 패널과 첨부 패널

**Files:**
- Create: `frontend/src/components/RelationsPanel.tsx`, `frontend/src/components/AttachmentPanel.tsx`
- Modify: `frontend/src/api/`(타입 `RelationGroup`, `RelationsPayload`, `AttachmentRow`), `frontend/src/pages/items/ItemPage.tsx`, `frontend/src/pages/specs/SpecPage.tsx`, `frontend/src/pages/plans/PlanPage.tsx`, `frontend/src/pages/inspections/InspectionPage.tsx`
- Modify: `frontend/dist/` (빌드 결과), `scripts/e2e_browser.py`

**Interfaces:**
- Consumes: Task 6 API 응답 모양, Task 4 첨부 API
- Produces:
  - `<RelationsPanel ct="app.model" id={number} />`: `useQuery(['relations', ct, id])`. 바깥 `<section aria-label="연결">`, 머리 `연결 {총합}`. incoming 묶음마다 `<h3>{label} {count}</h3>`(접기는 antd `Collapse` 대신 `<details open>`가 아니라 버튼 + `aria-expanded`), 항목 `<a href={url}>{text}</a>` + 상태 `Tag`(색 + 글자; 승인됨·합격·종결=green, 초안·진행·미판정=orange, 불합격=red, 그 밖 default). 5개보다 많으면 `모두 보기 ({count})` 단추가 `?key=&page=` 로 다음 쪽을 이어 붙인다. 구분선 `이 기록이 가리키는 것` 아래 outgoing. 연결이 하나도 없으면 `연결된 기록이 없습니다.`. `/app/`로 시작하는 url은 react-router `Link`, 그 밖은 일반 `<a>`.
  - `<AttachmentPanel ct id />`: `MemoPanel`의 파일 선택 방식을 따른다. 목록(제목·종류·올린 사람·날짜, 제목은 내려받기 링크), `can_add`면 종류 `Select` + 파일 선택 + `올리기` 단추. 오류는 `ApiError` 메시지를 칸 아래에 쓴다.
  - 4개 페이지 `side` 배열 맨 앞에 `{ key: 'relations', label: '연결', node: <RelationsPanel …/> }`, 메모 뒤에 `{ key: 'files', label: '첨부', node: <AttachmentPanel …/> }`. ct는 각 페이지의 기존 메모 ct와 같다(`core.item`, `qms.inspectionspec`, `qms.controlplan`, `qms.inspection`).
  - e2e: 검사 기록 페이지에서 `연결` 탭 → LOT 묶음 보임; `첨부` 탭에서 파일 올리기 → 목록 1줄.

- [ ] **Step 1: e2e 단계 추가** (`scripts/e2e_browser.py`에 위 두 점검; 기존 검사 기록 페이지 점검 바로 뒤)
- [ ] **Step 2: 실패 확인** `python scripts/e2e_browser.py` → 새 두 줄 실패
- [ ] **Step 3: 컴포넌트·페이지 구현, `cd frontend && npm run build`(tsc 포함) 성공**
- [ ] **Step 4: e2e 통과** `python scripts/e2e_browser.py` → 전부 통과(390px 가로 스크롤 점검 포함)
- [ ] **Step 5: 커밋** `feat: 상세 화면 오른쪽에 연결·첨부 탭을 추가한다` (`frontend/dist/` 포함)

---

### Task 8: 문서 갱신과 전체 검증

**Files:**
- Modify: `README.md`(기준정보 메뉴, `link_masters` 사용법: 드라이런 → 결과 확인 → `--apply --backup-dir`), `docs/business-rules.md`(기준정보 편집 권한, 첨부 접근 규칙, 정제 규칙), `docs/architecture.md`(새 모델, `core/relations.py`, `data/attachments`), `docs/testing.md`(새 테스트 파일, 테스트 수)

- [ ] **Step 1: 문서 수정** — 실제 명령·경로만 적는다.
- [ ] **Step 2: 전체 검증**
  - `./.venv/Scripts/python manage.py test` → OK
  - `./.venv/Scripts/python manage.py makemigrations --check --dry-run` → `No changes detected`
  - `./.venv/Scripts/python manage.py check` → 문제 없음
  - `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python scripts/e2e_check.py` → 전부 통과
  - `PYTHONIOENCODING=utf-8 python scripts/e2e_browser.py` → 전부 통과
  - 운영 DB 사본에서 `migrate` 후 `link_masters`(드라이런) 실행해 출력 확인 (`docs/testing.md` "운영 DB 사본으로 미리 확인"). 운영 DB에는 적용하지 않는다.
- [ ] **Step 3: 커밋** `docs: A단계 기준정보·연결 패널 사용법과 규칙을 문서에 반영한다`
