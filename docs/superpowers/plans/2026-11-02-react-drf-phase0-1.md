# React·DRF 전환 0~1단계 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** admin·뷰에만 있던 업무 규칙을 공용 함수로 옮기고(0단계), DRF API와 React 앱의 기반 위에 시범 화면 2개(공장 종합현황·내 할 일)를 `/app/` 아래에 띄운다(1단계).

**Architecture:** 같은 출처의 Django 하나가 DRF `/api/`(세션 + CSRF), 기존 화면, React 빌드 결과(`/static/app/`, whitenoise)를 함께 제공한다. 규칙은 `core/rules.py`·`qms/rules.py`에 두고 admin·기존 뷰·API가 같은 함수를 부른다. 기존 화면은 이 계획에서 하나도 지우지 않는다.

**Tech Stack:** Python 3.12, Django 6.1.2, djangorestframework, django-filter, drf-spectacular / React, TypeScript, Vite, antd, react-router-dom, @tanstack/react-query, dayjs

**Spec:** `docs/architecture-migration-plan.md` (특히 3.2, 6장, 7장 0~1단계, 9.2)

**범위 밖:** 2~5단계(업무 화면 묶음 전환, 현장·인쇄, PostgreSQL, 일괄 교체)는 이 계획이 끝난 뒤 단계마다 별도 계획을 쓴다. 사용자는 0~5단계 전체 진행을 승인했다(2026-11-02).

## Global Constraints

- 작업 브랜치: `react-drf`. master에 직접 커밋하지 않는다. push는 사용자 요청이 있을 때만 한다.
- 승인된 새 의존성(2026-11-02 사용자 승인 "필수 + 선택 전부"):
  - Python: `djangorestframework`, `django-filter`, `drf-spectacular`
  - npm: `react`, `react-dom`, `antd`, `@ant-design/icons`, `react-router-dom`, `@tanstack/react-query`, `dayjs`, `typescript`, `vite`, `@vitejs/plugin-react`
  - 이 목록 밖의 패키지는 추가하지 않는다.
- 버전은 설치 시점의 최신판으로 `requirements.txt`(`==`)와 `package-lock.json`에 고정한다.
- 빌드 결과물 배포는 (가) 방식이다: `frontend/dist/`를 Git에 커밋한다. `frontend/node_modules/`는 커밋하지 않는다(`.gitignore`).
- 외부 CDN·글꼴을 쓰지 않는다. 오프라인에서 동작해야 한다.
- Python Playwright는 시스템 Python에 이미 설치된 것을 쓴다. `requirements.txt`에 넣지 않는다.
- 화면 문구, 오류 메시지, 커밋 메시지는 한국어로 쓴다. 커밋은 Conventional Commits 형식이고 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`을 붙인다.
- **0단계에서는 기존 테스트를 한 줄도 고치지 않는다.** 기존 155개와 e2e 76개가 그대로 통과해야 한다(spec 7장 0단계 완료 기준).
- 규칙 함수의 본문은 지금 코드를 옮기기만 하고 동작과 메시지 문구를 바꾸지 않는다.
- 스키마를 바꾸지 않는다. 매 Task 끝에서 `makemigrations --check --dry-run`이 "No changes detected"여야 한다.
- `data/`를 건드리지 않는다. 테스트는 Django 테스트 DB만 쓴다.
- 명령은 PowerShell 기준이다: `.\.venv\Scripts\python manage.py …`. Git Bash에서는 `.venv/Scripts/python`을 쓰고, 한글이 깨지면 `PYTHONIOENCODING=utf-8`을 붙인다.

## Review Focus

1. **세션이 끝난 상태에서 React 화면을 쓰는 경우:** API가 403을 돌려주면 빈 화면이 아니라 로그인 화면으로 가야 한다. → Task 9 테스트
2. **CSRF 토큰 없이 쓰기 요청을 보내는 경우:** 403과 한국어 `detail`을 돌려주고, 아무것도 저장하지 않아야 한다. → Task 7 테스트
3. **수정 승인을 이미 한 번 쓴 기록을 다시 저장하는 경우:** 두 번째는 막혀야 한다(승인 1회 소모). → Task 2 테스트
4. **위젯 하나의 계산이 예외를 내는 경우:** 내 할 일 API는 나머지 위젯을 돌려주고, 깨진 위젯만 `error: true`로 표시해야 한다(기존 `todo` 뷰와 같은 동작). → Task 8 테스트
5. **모델 `ValidationError`가 필드별 dict인 경우:** 400 응답의 `fields`에 필드별 한국어 메시지가 그대로 들어가야 한다. → Task 7 테스트

---

## 0단계 — 공용 규칙 추출

### Task 1: LOT 이력 조회(`/trace/`)에 LOT 보기 권한 검사

사용자 승인 사항이다(2026-11-02). 지금은 그룹 없는 staff도 계보·고객사명·부적합 번호를 볼 수 있다.

**Files:**
- Modify: `core/views.py:47-59` (`trace`)
- Test: `core/tests.py` (새 클래스 `TracePermTest`를 파일 끝에 추가)

**Interfaces:**
- Produces: `trace`는 `core.view_lot` 권한이 없으면 `PermissionDenied`(403)를 낸다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
class TracePermTest(TestCase):
    def test_trace_needs_view_lot(self):
        item = Item.objects.create(code='T1', name='품목', item_type=Item.RAW)
        Lot.objects.create(number='T-1', item=item)
        nobody = User.objects.create_user('nobody', password='pw', is_staff=True)
        self.client.force_login(nobody)
        self.assertEqual(self.client.get('/trace/?lot=T-1').status_code, 403)
        inspector = User.objects.create_user('insp', password='pw', is_staff=True)
        inspector.groups.add(Group.objects.get(name='검사원'))
        self.client.force_login(inspector)
        self.assertEqual(self.client.get('/trace/?lot=T-1').status_code, 200)
```

테스트 클라이언트가 `DisallowedHost`를 내면 `self.client = Client(HTTP_HOST='127.0.0.1')`처럼 기존 테스트가 쓰는 방식을 따른다(`core/tests.py`의 `ShellTest` 참고).

- [ ] **Step 2: 실패 확인**

Run: `.\.venv\Scripts\python manage.py test core.tests.TracePermTest`
Expected: FAIL (`200 != 403`)

- [ ] **Step 3: `trace` 첫 줄에서 `if not request.user.has_perm('core.view_lot'): raise PermissionDenied`**

`PermissionDenied`는 이미 import되어 있다. 사이드바 `core/nav.py`의 `('LOT 이력 조회', 'trace', None)` 권한 칸도 `'core.view_lot'`로 바꿔서 메뉴가 권한과 맞게 한다.

- [ ] **Step 4: 통과 확인 + 전체 core 테스트**

Run: `.\.venv\Scripts\python manage.py test core`
Expected: OK

- [ ] **Step 5: 문서 갱신**

`docs/business-rules.md` 10장(권한)에 "LOT 이력 조회는 `core.view_lot` 권한이 필요하다(`core/views.py` `trace`)" 한 줄을 추가한다.

- [ ] **Step 6: 커밋**

```bash
git add core/views.py core/nav.py core/tests.py docs/business-rules.md
git commit -m "fix: LOT 이력 조회에 LOT 보기 권한 검사 추가"
```

---

### Task 2: 잠금·삭제 공용 함수 (`core/rules.py`)

**Files:**
- Create: `core/rules.py`
- Modify: `core/admin.py` (`LOCKED_MSG` 정의를 rules로 옮기고 import, `BaseAdmin.save_model`, `NcPhotoInline._open`)
- Modify: `qms/admin.py` (`LockedWhenApprovedInline._locked`)
- Test: `core/tests_rules.py` (새 파일)

**Interfaces:**
- Consumes: `core/records.py`의 `edit_unlocked`, `can_edit_locked`, `is_locked`, `delete_record`
- Produces (Task 3·7 이후가 쓴다):
  - `LOCKED_MSG: str` — 지금 `core/admin.py:51`의 문구 그대로
  - `class Locked(ValidationError)` — 잠금 때문에 막힌 저장. API는 409로 바꾼다
  - `begin_edit(obj, user) -> EditRequest | None` — `obj._edit_unlocked`를 `bool(승인) or user.is_superuser`로 켜고, 쓸 수정 승인(없으면 None)을 돌려준다. 새 기록(`obj.pk` 없음)이면 None
  - `finish_edit(unlock: EditRequest | None) -> None` — unlock이 있으면 `status=USED`로 저장
  - `save_with_lock(obj, user, children=()) -> None` — `transaction.atomic` 안에서 `begin_edit` → 하위 항목에 같은 `_edit_unlocked` 전달 → `obj.save()`·각 `child.save()` → `finish_edit`. 잠긴 기록인데 해제되지 않았고 모델이 `ValidationError`를 내면 `Locked(LOCKED_MSG)`를 낸다
  - `delete_as(obj, user) -> None` — superuser가 아니면 `PermissionDenied('시스템 관리자만 삭제할 수 있습니다.')`. 맞으면 `delete_record(obj)`. `ProtectedError`는 그대로 올린다
  - `child_editable(parent, user) -> bool` — 부적합은 `closed_at` 기준, 그 밖은 `is_locked(parent)` 기준. 잠기지 않았거나 `can_edit_locked(parent, user)`이면 True

- [ ] **Step 1: 실패하는 테스트 작성** (`core/tests_rules.py`, 클래스 `LockRulesTest`)

준비: `qms/tests.py`의 `approve(obj, user)` 헬퍼처럼 승인된 `InspectionSpec`을 하나 만든다. 사용자는 품질팀장 `boss`, 엔지니어 `eng`(품질엔지니어 그룹), superuser `root`.

```python
def test_locked_record_rejects_save(self):
    self.spec.note = '바꿈'
    with self.assertRaises(Locked):
        save_with_lock(self.spec, self.eng)

def test_edit_request_unlocks_once(self):
    req = EditRequest.objects.create(kind=EditRequest.EDIT, target=self.spec, object_repr='x', reason='r',
                                     requested_by=self.eng, status=EditRequest.APPROVED)
    self.spec.note = '1차'
    save_with_lock(self.spec, self.eng)
    req.refresh_from_db()
    self.assertEqual(req.status, EditRequest.USED)
    self.spec.note = '2차'
    with self.assertRaises(Locked):
        save_with_lock(self.spec, self.eng)

def test_superuser_edits_locked(self):
    self.spec.note = '관리자'
    save_with_lock(self.spec, self.root)
    self.spec.refresh_from_db()
    self.assertEqual(self.spec.note, '관리자')

def test_children_follow_parent_unlock(self):
    ch = self.spec.characteristics.first()
    ch.usl = ch.usl + 1
    with self.assertRaises(Locked):
        save_with_lock(self.spec, self.eng, children=[ch])
    save_with_lock(self.spec, self.root, children=[ch])

def test_delete_only_superuser(self):
    with self.assertRaises(PermissionDenied):
        delete_as(self.spec, self.boss)

def test_child_editable(self):
    self.assertFalse(child_editable(self.spec, self.eng))
    self.assertTrue(child_editable(self.spec, self.root))
    nc = Nonconformance.objects.create(lot=self.lot, description='x')
    self.assertTrue(child_editable(nc, self.eng))
```

`EditRequest`의 `target` 인자 이름은 `core/views.py:166`의 `EditRequest.objects.create(kind=kind, target=obj, …)`과 같다.

- [ ] **Step 2: 실패 확인**

Run: `.\.venv\Scripts\python manage.py test core.tests_rules`
Expected: FAIL (`ModuleNotFoundError: core.rules`)

- [ ] **Step 3: `core/rules.py` 작성** (위 Interfaces의 시그니처)

모듈 설명 한 줄: `"""admin·기존 뷰·API가 함께 쓰는 업무 규칙. 본문은 기존 admin·뷰 코드를 옮긴 것이다(docs/architecture-migration-plan.md 3.2)."""`

- [ ] **Step 4: admin이 새 함수를 부르게 고친다**
  - `BaseAdmin.save_model`: 첫 두 줄을 `unlock = begin_edit(obj, request.user) if change else None` / `obj._edit_unlocked = …`(begin_edit이 설정)로 바꾸고, 마지막 `if unlock:` 블록을 `finish_edit(unlock)`으로 바꾼다. `change=False`일 때도 superuser면 `_edit_unlocked=True`가 되어야 한다(지금 동작). 메시지·`_save_blocked` 처리는 admin에 그대로 둔다.
  - `NcPhotoInline._open`과 `LockedWhenApprovedInline._locked`는 `child_editable`을 부른다(`_locked`는 `not child_editable(obj, user)`이고, `obj is None`이면 False).
  - `LOCKED_MSG`는 `core/rules.py`에 두고 `core/admin.py`는 import한다.

- [ ] **Step 5: 새 테스트 + 기존 전체 테스트 통과 확인**

Run: `.\.venv\Scripts\python manage.py test`
Expected: OK. 기존 155개 + 새 테스트. 기존 테스트 파일은 고치지 않았다.

- [ ] **Step 6: 커밋**

```bash
git add core/rules.py core/admin.py qms/admin.py core/tests_rules.py
git commit -m "refactor: 잠금·삭제 규칙을 core/rules.py 공용 함수로 추출"
```

---

### Task 3: 부적합 처분 공용 함수

**Files:**
- Modify: `core/rules.py`
- Modify: `core/admin.py` (`NonconformanceForm.clean`·`_post_clean`, `NonconformanceAdmin.get_readonly_fields`)
- Test: `core/tests_rules.py` (클래스 `DisposeRulesTest`)

**Interfaces:**
- Consumes: Task 2의 `Locked`, `can_edit_locked`
- Produces:
  - `DISPOSE_FIELDS = ('disposition', 'customer_approval_ref', 'cost')`
  - `sign_disposition(nc, user, password: str) -> None` — 비밀번호가 틀리면 `ValidationError('MRB 승인 비밀번호가 맞지 않습니다.')`. 맞으면 `nc.approved_by, nc.approved_at = user, timezone.now()`
  - `missing_message(nc) -> str | None` — `nc.missing_fields()`가 있으면 `'보완 필요: ' + ', '.join(missing)`
  - `dispose_nc(nc, user, password: str, data: dict) -> None` — `nc.closed_at`이면 `Locked(LOCKED_MSG)`. `data`에서 `DISPOSE_FIELDS`만 적용하고, 다른 키가 있으면 `ValidationError('처분에서 바꿀 수 없는 칸: …')`. 그다음 `sign_disposition` → `missing_message`가 있으면 그 문구로 `ValidationError` → `nc.full_clean()` → `nc.save()`. 전체를 `transaction.atomic`으로 감싼다
  - `nc_locked_fields(nc, user) -> list[str]` — 모델 필드 이름만 돌려준다. 종결됐고 `can_edit_locked`가 아니면 `AFTER_APPROVAL` 밖의 모든 필드, 종결됐고 해제 가능하면 `Nonconformance.INTERLOCK`, 종결 전이면 `[]`

- [ ] **Step 1: 실패하는 테스트 작성**

준비: `InterlockTest.setUp`(`core/tests.py:33`)과 같은 LOT·품질팀장 `mrb`(비밀번호 `'pw'`)를 만든다. 부적합 `nc`는 `defect_type`, `sorting_result`, `contained_qty`를 채워 둔다.

```python
def test_wrong_password(self):
    with self.assertRaisesMessage(ValidationError, 'MRB 승인 비밀번호가 맞지 않습니다.'):
        dispose_nc(self.nc, self.mrb, 'bad', {'disposition': Nonconformance.SCRAP})
    self.nc.refresh_from_db()
    self.assertEqual(self.nc.disposition, '')

def test_missing_fields_block(self):
    self.nc.sorting_result = ''
    with self.assertRaisesMessage(ValidationError, '보완 필요:'):
        dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP})

def test_dispose_ok_keeps_hold_for_scrap(self):
    dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP})
    self.nc.refresh_from_db()
    self.assertEqual(self.nc.approved_by, self.mrb)
    self.assertTrue(self.lot.on_hold)

def test_other_fields_rejected(self):
    with self.assertRaises(ValidationError):
        dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP, 'lot': 99})

def test_closed_nc_locked_fields(self):
    dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP})
    self.nc.refresh_from_db()
    self.assertIn('lot', nc_locked_fields(self.nc, self.eng))
    self.assertNotIn('cost', nc_locked_fields(self.nc, self.eng))
    self.assertEqual(sorted(nc_locked_fields(self.nc, self.root)), sorted(Nonconformance.INTERLOCK))
    with self.assertRaises(Locked):
        dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.REWORK})
```

`closed_at`은 처분을 저장할 때 `Nonconformance.save`가 채운다(`core/models.py:373`).

- [ ] **Step 2: 실패 확인**

Run: `.\.venv\Scripts\python manage.py test core.tests_rules.DisposeRulesTest`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: `core/rules.py`에 함수 추가** (위 시그니처)

- [ ] **Step 4: admin이 새 함수를 부르게 고친다**
  - `NonconformanceForm.clean`: 비밀번호 확인과 승인자 기록을 `sign_disposition(self.instance, self.user, data.get('password') or '')`로 바꾸고, `ValidationError`를 `forms.ValidationError`로 다시 낸다(메시지 동일).
  - `_post_clean`: `missing_message(self.instance)`가 있으면 `add_error(None, msg)`.
  - `get_readonly_fields`: `self.AUTO + [f for f in nc_locked_fields(obj, request.user) if f not in self.AUTO]`. 종결 전이고 `obj`가 None이면 `self.AUTO`.

- [ ] **Step 5: 전체 테스트**

Run: `.\.venv\Scripts\python manage.py test`
Expected: OK

- [ ] **Step 6: 커밋**

```bash
git add core/rules.py core/admin.py core/tests_rules.py
git commit -m "refactor: 부적합 MRB 처분 규칙을 공용 함수로 추출"
```

---

### Task 4: 승인 서명 공용 함수

**Files:**
- Modify: `core/rules.py`, `core/views.py` (`approve`)
- Test: `core/tests_rules.py` (클래스 `ApproveRulesTest`)

**Interfaces:**
- Consumes: `core/models.py`의 `Approvable`, `is_approver`
- Produces: `approve(obj, user, password: str) -> None`
  - 승인자가 아니면 `PermissionDenied('품질팀장만 승인할 수 있습니다.')`
  - 이미 승인됐으면 `ValidationError('이미 승인된 기록입니다.')`
  - 비밀번호가 틀리면 `ValidationError('비밀번호가 맞지 않습니다.')`
  - 그 밖은 `approved_by`·`approved_at`을 넣고 `obj.save()`. 모델 `ValidationError`(예: 고객 승인번호 없는 4M)는 그대로 올리고, 이때 `approved_by`·`approved_at`을 원래 값(None)으로 되돌린다
  - `Approvable`인지는 호출하는 쪽(뷰·API)이 먼저 확인한다

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_non_approver(self):
    with self.assertRaisesMessage(PermissionDenied, '품질팀장만 승인할 수 있습니다.'):
        approve(self.spec, self.eng, 'pw')

def test_wrong_password(self):
    with self.assertRaisesMessage(ValidationError, '비밀번호가 맞지 않습니다.'):
        approve(self.spec, self.boss, 'bad')
    self.assertIsNone(self.spec.approved_at)

def test_model_rule_restores_fields(self):
    cr = ChangeRequest.objects.create(number='CR-1', item=self.item, category='MATERIAL',
                                      description='x', customer_notice=True)
    with self.assertRaises(ValidationError):
        approve(cr, self.boss, 'pw')
    self.assertIsNone(cr.approved_at)

def test_ok_then_already(self):
    approve(self.spec, self.boss, 'pw')
    self.spec.refresh_from_db()
    self.assertEqual(self.spec.approved_by, self.boss)
    with self.assertRaisesMessage(ValidationError, '이미 승인된 기록입니다.'):
        approve(self.spec, self.boss, 'pw')
```

`ChangeRequest.category`는 상수 없이 문자열 선택지다(`qms/models.py:326`).

- [ ] **Step 2: 실패 확인** — Run: `.\.venv\Scripts\python manage.py test core.tests_rules.ApproveRulesTest` / Expected: FAIL

- [ ] **Step 3: `approve` 구현, `core/views.py` `approve`가 부르게 고친다**

뷰는 `issubclass(model, Approvable)` 확인과 "이미 승인" 안내(`messages.info` + redirect)를 그대로 유지한다. POST 처리에서 `rules.approve(obj, request.user, request.POST.get('password', ''))`를 부르고, `ValidationError`는 `' '.join(e.messages)`를 `error`로 보여준다. 이름이 겹치므로 `from . import rules`로 가져와 `rules.approve`로 부른다.

- [ ] **Step 4: 전체 테스트** — Run: `.\.venv\Scripts\python manage.py test` / Expected: OK

- [ ] **Step 5: 커밋**

```bash
git add core/rules.py core/views.py core/tests_rules.py
git commit -m "refactor: 승인 서명 규칙을 공용 함수로 추출"
```

---

### Task 5: 검사 판정·입고 공용 함수 (`qms/rules.py`) + 0단계 검증

**Files:**
- Create: `qms/rules.py`
- Modify: `qms/views.py` (`_measurement` 삭제 후 `rules.measurement` 사용, `inspect_check`, `inspect_submit`, `inspect_receive`)
- Test: `qms/tests_rules.py` (새 파일)

**Interfaces:**
- Produces:
  - `measurement(char, raw) -> Measurement | None` — 지금 `qms/views.py:311` `_measurement`의 본문 그대로
  - `submit_inspection(lot, spec, user, gauge, values: dict[int, str], defect_type: str = '', defect_qty=None) -> Inspection` — 지금 `inspect_submit`의 `transaction.atomic` 블록 그대로. `values`의 키는 `Characteristic.pk`, 값은 입력 문자열. 빈 항목이면 `ValidationError(f'{char.name}: 값을 입력하세요.')`. `defect_qty`는 기존 `_qty` 규칙(숫자 아님·음수 → 0)을 따른다. `_qty`도 함께 옮긴다
  - `RECEIVE_MSG = '품목·LOT 번호·입고수량(0보다 큰 숫자)을 모두 입력하세요.'`
  - `receive_lot(number: str, item, qty_raw: str, supplier: str) -> tuple[Lot, bool]` — 지금 `inspect_receive`의 검증과 `get_or_create` 그대로. 검증에 실패하면 `ValidationError(RECEIVE_MSG)`. 권한 검사는 호출하는 쪽에 둔다

- [ ] **Step 1: 실패하는 테스트 작성** (`qms/tests_rules.py`, 클래스 `InspectionRulesTest`)

준비: `qms/tests.py`의 `QmsTest` 준비 코드를 참고해 승인된 검사기준(계량형 항목 1개: lsl 9, usl 11)·LOT·검사원 자격이 있는 사용자를 만든다.

```python
def test_pass(self):
    insp = submit_inspection(self.lot, self.spec, self.user, None, {self.char.pk: '10'})
    self.assertEqual(insp.result, Inspection.PASS)

def test_fail_creates_nc_with_defect(self):
    insp = submit_inspection(self.lot, self.spec, self.user, None, {self.char.pk: '12'}, '치수', '-3')
    self.assertEqual(insp.result, Inspection.FAIL)
    self.assertEqual(insp.nonconformance.defect_type, '치수')
    self.assertEqual(insp.nonconformance.defect_qty, 0)
    self.assertTrue(self.lot.on_hold)

def test_missing_value_rolls_back(self):
    with self.assertRaisesMessage(ValidationError, '값을 입력하세요'):
        submit_inspection(self.lot, self.spec, self.user, None, {})
    self.assertFalse(Inspection.objects.exists())

def test_nan_rejected(self):
    self.assertIsNone(measurement(self.char, 'nan'))

def test_receive(self):
    lot, created = receive_lot('NEW-1', self.item, '5', '협력사A')
    self.assertTrue(created)
    with self.assertRaisesMessage(ValidationError, RECEIVE_MSG):
        receive_lot('NEW-2', self.item, '0', '')
```

- [ ] **Step 2: 실패 확인** — Run: `.\.venv\Scripts\python manage.py test qms.tests_rules` / Expected: FAIL

- [ ] **Step 3: `qms/rules.py` 작성, 뷰가 부르게 고친다**

`inspect_submit`은 POST에서 `values = {c.pk: request.POST.get(f'c{c.pk}', '') for c in spec.characteristics.all()}`를 만들어 넘긴다. `inspect_receive`는 `receive_lot`의 `ValidationError`를 받아 지금과 같은 `_lot_step(..., RECEIVE_MSG)`로 보여준다.

- [ ] **Step 4: 0단계 전체 검증 (spec 7장 공통 검증)**

Run:
```
.\.venv\Scripts\python manage.py check
.\.venv\Scripts\python manage.py makemigrations --check --dry-run
.\.venv\Scripts\python manage.py test
.\.venv\Scripts\python scripts\e2e_check.py
```
Expected: check 문제 없음, "No changes detected", 테스트 OK, e2e 76개 전부 통과. 실제 출력 숫자를 ledger에 적는다.

- [ ] **Step 5: 커밋**

```bash
git add qms/rules.py qms/views.py qms/tests_rules.py
git commit -m "refactor: 검사 판정·입고 규칙을 qms/rules.py 공용 함수로 추출"
```

---

## 1단계 — DRF 기반과 시범 화면

### Task 6: 패키지 설치와 DRF 설정

**Files:**
- Modify: `requirements.txt`, `config/settings.py`, `config/urls.py`
- Create: `core/api/__init__.py`, `core/api/permissions.py`, `core/api/exceptions.py`, `core/api/views.py`, `core/api/urls.py`, `core/api/tests.py`

**Interfaces:**
- Consumes: Task 2의 `Locked`
- Produces (Task 7 이후가 쓴다):
  - `core.api.permissions.IsStaff` — `request.user.is_authenticated and request.user.is_staff`
  - `core.api.permissions.ModelPerms(DjangoModelPermissions)` — `GET`·`HEAD`·`OPTIONS`에도 `%(app_label)s.view_%(model_name)s`를 요구하고, `DELETE`는 superuser만 허용
  - `core.api.permissions.require_perm(user, perm: str) -> None` — 권한이 없으면 `PermissionDenied`. 기존 `qms/views.py` `_need`와 같은 동작
  - `core.api.exceptions.handler(exc, context)` — 오류 형식(spec 6.6):
    - Django `ValidationError` → 400 `{"detail": "…", "fields": {필드: [메시지]}}`. `message_dict`가 없으면 `fields`는 `{}`
    - `Locked` → 409 `{"detail": LOCKED_MSG}`
    - Django `PermissionDenied` → 403. 메시지가 있으면 `detail`에 그대로 넣고, 없으면 `'권한이 없습니다.'`
    - `ProtectedError` → 409 `{"detail": "먼저 지워야 할 기록: …", "blockers": ["모델명: 기록", …]}`
    - 나머지는 DRF 기본 처리
  - 인증 API (`core/api/views.py`):
    - `GET /api/auth/csrf/` — `ensure_csrf_cookie`. 응답 `{}`
    - `POST /api/auth/login/` `{username, password}` — 틀리면 400 `{"detail": "아이디 또는 비밀번호가 맞지 않습니다."}`. `is_staff`가 아니면 같은 400. 맞으면 `login()` 후 `me` 응답과 같은 본문
    - `POST /api/auth/logout/` — 204
    - `GET /api/auth/me/` — `{"username", "name", "is_superuser", "is_approver", "groups": [...], "perms": [정렬된 권한 코드], "nav": [{"group": 이름, "items": [{"label", "href"}]}]}`. `nav`는 `core/nav.py`의 `NAV`를 권한으로 거르고, `href`는 `nav_url()`이 만든 기존 화면 주소다
  - `/api/schema/`(drf-spectacular) — `IsStaff`만 허용

- [ ] **Step 1: 패키지 설치와 버전 고정**

Run:
```
.\.venv\Scripts\python -m pip install djangorestframework django-filter drf-spectacular
.\.venv\Scripts\python -m pip freeze
```
`requirements.txt`에는 위 3개를 `==버전`으로 추가하고, 이들이 끌고 온 의존성도 `pip freeze`에 새로 생긴 것만 `==버전`으로 추가한다. 각 패키지의 릴리스 노트에서 Django 6.1 지원 여부를 확인하고, 확인한 내용을 커밋 메시지 본문에 적는다. 지원이 명시되지 않았으면 Step 6의 전체 테스트 통과를 근거로 적는다.

- [ ] **Step 2: 설정**

`INSTALLED_APPS`에 `'rest_framework'`, `'django_filters'`, `'drf_spectacular'`를 추가한다. 설정 값:

```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['core.api.permissions.IsStaff'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend',
                                'rest_framework.filters.SearchFilter', 'rest_framework.filters.OrderingFilter'],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'EXCEPTION_HANDLER': 'core.api.exceptions.handler',
    'UNAUTHENTICATED_USER': 'django.contrib.auth.models.AnonymousUser',
}
SPECTACULAR_SETTINGS = {'TITLE': 'QMS+MES API', 'SERVE_INCLUDE_SCHEMA': False}
if DEBUG:  # Vite 개발 서버(5173)가 /api를 프록시할 때의 Origin
    CSRF_TRUSTED_ORIGINS = ['http://localhost:5173', 'http://127.0.0.1:5173']
```

`settings.py`에 `CSRF_TRUSTED_ORIGINS`가 이미 있으면 덮어쓰지 말고 목록에 더한다. `config/urls.py`에는 `path('api/', include('core.api.urls'))`를 추가한다. `core/api/urls.py`는 `auth/…`, `schema/`를 두고, 뒤 Task에서 `path('qms/', include('qms.api.urls'))`가 더해진다.

- [ ] **Step 3: 실패하는 테스트 작성** (`core/api/tests.py`, 클래스 `AuthApiTest`, `APIClient(enforce_csrf_checks=True)` 사용)

```python
def test_anonymous_forbidden(self):
    self.assertEqual(self.client.get('/api/auth/me/').status_code, 403)

def test_login_wrong_password(self):
    self.client.get('/api/auth/csrf/')
    r = self.client.post('/api/auth/login/', {'username': 'qe', 'password': 'bad'}, format='json',
                         HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
    self.assertEqual(r.status_code, 400)
    self.assertEqual(r.json()['detail'], '아이디 또는 비밀번호가 맞지 않습니다.')

def test_login_then_me(self):
    # 로그인 성공 → me의 perms에 'core.view_lot', nav에 '통합 업무 홈' 그룹
    ...

def test_post_without_csrf_rejected(self):
    self.client.force_login(self.qe)
    r = self.client.post('/api/auth/logout/')
    self.assertEqual(r.status_code, 403)
    self.assertIn('detail', r.json())

def test_non_staff_login_rejected(self):
    ...  # is_staff=False 사용자는 400
```

`ExceptionHandlerTest`도 같은 파일에 둔다. 테스트 전용 URL 없이 `handler`를 직접 부른다: `handler(ValidationError({'qty': ['수량 오류']}), {})` → 400, `fields == {'qty': ['수량 오류']}`. `Locked` → 409. `PermissionDenied('품질팀장만 승인할 수 있습니다.')` → 403이고 같은 detail. `ProtectedError` → 409이고 `blockers`가 있다.

- [ ] **Step 4: 실패 확인** — Run: `.\.venv\Scripts\python manage.py test core.api` / Expected: FAIL

- [ ] **Step 5: 구현** (위 Interfaces)

- [ ] **Step 6: 전체 검증** — Run: `check`, `makemigrations --check --dry-run`, `manage.py test` / Expected: 모두 통과

- [ ] **Step 7: 커밋**

```bash
git add requirements.txt config/settings.py config/urls.py core/api/
git commit -m "feat: DRF API 기반(세션 인증·권한·오류 형식·로그인 API) 추가"
```

---

### Task 7: 공장 종합현황 API

**Files:**
- Create: `qms/overview.py`, `qms/api/__init__.py`, `qms/api/views.py`, `qms/api/urls.py`, `qms/api/tests.py`
- Modify: `qms/views.py` (`overview` 본문을 `qms/overview.py`로 옮긴다), `core/api/urls.py`

**Interfaces:**
- Consumes: Task 6의 `IsStaff`
- Produces:
  - `qms.overview.sections(user) -> list[tuple[str, list[dict]]]` — 지금 `overview` 뷰의 계산 그대로. 카드 dict의 키(`title`, `value`, `sub`, `tone`, `href`, `more`, `rows`)와 값도 그대로다. `href`는 지금처럼 기존 화면 주소다
  - `GET /api/qms/overview/` → `{"sections": [{"name": 이름, "cards": [카드 dict]}]}`. `value`는 숫자 또는 문자열(`'95%'`) 그대로다

**결정(spec 1.5·7장 1단계와 다른 점):** spec은 1단계에서 집계 함수가 링크 대신 식별자를 돌려주게 하라고 적었다. 이 계획은 1단계에서 `href`(기존 화면 주소)를 그대로 돌려준다. React는 아직 옮기지 않은 화면을 기존 주소로 연다. 식별자로 바꾸는 일은 해당 화면을 React로 옮기는 2단계 묶음에서 한다. 이유: 1단계에는 React 쪽에 옮겨 갈 경로가 아직 없다. 지금 바꾸면 템플릿 쪽 변환 코드만 늘고 얻는 것이 없다. 이 결정이 틀렸을 때의 비용: 2단계에서 `href`를 식별자로 바꾸는 작업을 그때 한다.

- [ ] **Step 1: 실패하는 테스트 작성** (`qms/api/tests.py`, 클래스 `OverviewApiTest`)

준비: `qms/tests.py`의 `OverviewTest` 준비 코드를 참고한다(작업지시·검사·보류·CAPA가 각각 하나 이상). 사용자: 품질엔지니어 `qe`, 검사원 `insp`.

```python
def test_same_numbers_as_page(self):
    self.client.force_login(self.qe)
    api = self.client.get('/api/qms/overview/').json()
    page = sections(self.qe)
    self.assertEqual([(s['name'], [(c['title'], c['value']) for c in s['cards']]) for s in api['sections']],
                     [(name, [(c['title'], c['value']) for c in cards]) for name, cards in page])

def test_inspector_has_no_capa_card(self):
    self.client.force_login(self.insp)
    titles = [c['title'] for s in self.client.get('/api/qms/overview/').json()['sections'] for c in s['cards']]
    self.assertNotIn('진행 중 CAPA', titles)

def test_anonymous_forbidden(self):
    self.assertEqual(self.client.get('/api/qms/overview/').status_code, 403)
```

- [ ] **Step 2: 실패 확인** — Run: `.\.venv\Scripts\python manage.py test qms.api` / Expected: FAIL

- [ ] **Step 3: 구현**

`overview` 뷰는 `render(..., {'title': '공장 종합현황', 'sections': overview.sections(request.user)})`만 남는다. 응답 JSON은 DRF `Response`를 쓴다. Decimal·날짜 직렬화는 DRF 기본 JSON 인코더가 처리한다.

- [ ] **Step 4: 전체 테스트** — Run: `.\.venv\Scripts\python manage.py test` / Expected: OK. 기존 `OverviewTest`도 그대로 통과해야 한다.

- [ ] **Step 5: 커밋**

```bash
git add qms/overview.py qms/views.py qms/api/ core/api/urls.py
git commit -m "feat: 공장 종합현황 API 추가(기존 화면과 같은 집계 함수 사용)"
```

---

### Task 8: 내 할 일 API (위젯 데이터·배치 저장)

**Files:**
- Modify: `qms/views.py` (`dashboard_save`의 검증을 함수로 분리), `qms/widgets.py` (위젯별 JSON 데이터 함수 추가)
- Modify: `qms/api/views.py`, `qms/api/urls.py`, `qms/api/tests.py`

**Interfaces:**
- Consumes: Task 6의 `IsStaff`, 기존 `qms/widgets.py`의 `WIDGETS`·`layout_for`·`SIZES`·`COLS`·`ROWS`, `qms/due.py`의 `due_items`
- Produces:
  - `qms.widgets.valid_layout(user, items) -> bool` — 지금 `dashboard_save`의 `ok` 조건과 중복 키 검사 그대로
  - `qms.widgets.save_layout(user, items) -> None` — 지금 `dashboard_save`의 저장 부분 그대로(빈 배열이면 삭제)
  - `qms.widgets.widget_data(widget, request, d, size) -> dict` — JSON으로 보낼 수 있는 값만 담는다. 숫자 타일(`TILE` 템플릿)은 `widget.context(...)`의 결과 그대로다(`value`, `sub`, `href`, `more`, `tone`, `rows`). 전용 템플릿 위젯(`todo_lists`, `spc_alarms`, `audits`, `kpi_yield`)은 각 템플릿(`qms/templates/qms/widgets/*.html`)이 화면에 보이는 값을 같은 이름의 키로 담는다. 모델 객체는 `str()`이나 필요한 필드로 바꾸고, 링크는 템플릿이 쓰는 기존 주소 그대로 넣는다
  - `GET /api/qms/todo/` → `{"widgets": [{"key", "title", "size", "x", "y", "data": {...} | null, "error": bool}], "available": [{"key", "title"}]}`. `x`·`y`는 `layout_for`가 준 값이다. 위젯 하나의 계산이 예외를 내면 `data: null, error: true`로 두고 `logging.getLogger('qms').exception`으로 기록한다(지금 `todo` 뷰와 같다)
  - `POST /api/qms/dashboard/` 본문 `[{key, size, x?, y?}]` → `valid_layout`이 거짓이면 400 `{"detail": "저장할 수 없는 위젯 배치입니다."}`. 참이면 `save_layout` 후 `{"ok": true}`

- [ ] **Step 1: 실패하는 테스트 작성** (`qms/api/tests.py`, 클래스 `TodoApiTest`)

준비: `qms/tests.py`의 `DashboardTest`를 참고한다.

```python
def test_widgets_match_layout(self):
    self.client.force_login(self.qe)
    data = self.client.get('/api/qms/todo/').json()
    self.assertEqual([w['key'] for w in data['widgets']], [w['key'] for w in layout_for(self.qe)])
    held = next(w for w in data['widgets'] if w['key'] == 'held_lots')
    self.assertEqual(held['data']['value'], Hold.objects.filter(released_at__isnull=True).values('lot').distinct().count())

def test_inspector_no_kpi_widgets(self):
    self.client.force_login(self.insp)
    keys = [w['key'] for w in self.client.get('/api/qms/todo/').json()['available']]
    self.assertNotIn('kpi_ppm', keys)

def test_broken_widget_isolated(self):
    with mock.patch.dict(WIDGETS, {'leave': replace(WIDGETS['leave'], context=lambda *a: 1 / 0)}):
        self.client.force_login(self.qe)
        r = self.client.get('/api/qms/todo/')
    self.assertEqual(r.status_code, 200)
    leave = next(w for w in r.json()['widgets'] if w['key'] == 'leave')
    self.assertTrue(leave['error'])

def test_save_layout_rejects_forbidden_widget(self):
    self.client.force_login(self.insp)
    r = self.client.post('/api/qms/dashboard/', [{'key': 'kpi_ppm', 'size': 'normal'}], format='json')
    self.assertEqual(r.status_code, 400)

def test_every_allowed_widget_serializes(self):
    # qe·superuser 각각, available의 모든 위젯을 normal·wide로 배치해 저장한 뒤 GET이 200이고 error가 없다
    ...
```

`held_lots`의 값 계산이 다르면 `due_items`의 `held_lots` 정의(`qms/due.py`)를 읽고 그것과 비교한다. `leave` 위젯이 레이아웃에 없으면 `available`에 있는 다른 타일 위젯으로 바꾼다.

- [ ] **Step 2: 실패 확인** — Run: `.\.venv\Scripts\python manage.py test qms.api.tests.TodoApiTest` / Expected: FAIL

- [ ] **Step 3: 구현.** `dashboard_save` 뷰는 `valid_layout`·`save_layout`을 부르도록 바꾼다. 응답은 그대로 둔다.

- [ ] **Step 4: 전체 테스트** — Run: `.\.venv\Scripts\python manage.py test` / Expected: OK. 기존 `DashboardTest`도 그대로 통과해야 한다.

- [ ] **Step 5: 커밋**

```bash
git add qms/widgets.py qms/views.py qms/api/
git commit -m "feat: 내 할 일 위젯 데이터·배치 저장 API 추가"
```

---

### Task 9: React 프로젝트 기반 (빌드·서빙·로그인·공통 틀)

**Files:**
- Create: `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`
- Create: `frontend/src/main.tsx`, `frontend/src/theme.ts`, `frontend/src/api/client.ts`, `frontend/src/api/auth.ts`, `frontend/src/layout/AppLayout.tsx`, `frontend/src/pages/Login.tsx`
- Create: `frontend/dist/` (빌드 결과, 커밋)
- Modify: `.gitignore` (`frontend/node_modules/` 추가), `config/settings.py` (`STATICFILES_DIRS`), `config/urls.py`, `core/views.py` (`spa` 뷰)
- Test: `core/api/tests.py` (클래스 `SpaTest`)

**Interfaces:**
- Consumes: Task 6의 `/api/auth/csrf/`·`login/`·`logout/`·`me/`
- Produces:
  - Django `core.views.spa(request, rest='')` — `settings.BASE_DIR / 'frontend' / 'dist' / 'index.html'`을 `HttpResponse`로 돌려준다. 파일이 없으면 `Http404`. 로그인 없이 열린다(데이터를 담지 않는 정적 문서이고, 로그인 화면도 이 문서가 그린다)
  - URL: `path('app/', spa)`, `re_path(r'^app/(?P<rest>.*)$', spa)`
  - `STATICFILES_DIRS = [('app', BASE_DIR / 'frontend' / 'dist')]`. Vite `base: '/static/app/'`, `build.outDir: 'dist'`. 개발 서버 프록시는 `/api`·`/admin`·`/static` → `http://127.0.0.1:8000`
  - `frontend/src/api/client.ts`:
    - `api<T>(path: string, init?: RequestInit): Promise<T>` — `credentials: 'same-origin'`. 쓰기 요청이면 `csrftoken` 쿠키를 `X-CSRFToken` 헤더로 보낸다. JSON 본문이면 `Content-Type: application/json`
    - 403이고 로그인 상태가 아니면 `/app/login?next=<현재 경로>`로 보낸다
    - 그 밖의 오류는 `ApiError { status: number; detail: string; fields: Record<string, string[]> }`를 던진다
  - 경로: `/app/login`, `/app/overview`, `/app/todo`. `/app/`은 `/app/todo`로 보낸다
  - `AppLayout`: 상단 바(제품명 `QMS+MES`, 사용자 이름, 로그아웃, "기존 화면" 링크 `/todo/`)와 사이드바(`me.nav` 그대로, 그룹 7개). 사이드바 항목의 `href`가 `/app/`으로 시작하면 React 라우터로 열고, 아니면 기존 화면으로 전체 이동한다. `/todo/`와 `/overview/` 메뉴는 `/app/todo`·`/app/overview`로 바꿔 보여준다
  - `theme.ts`: `core/static/qms/fiori.css`의 `:root` 값을 antd `ConfigProvider` 토큰으로 옮긴다. 최소 `colorPrimary`(`#0057d2`), 배경·글자·테두리·성공·경고·오류 색, `fontFamily`(fiori.css의 시스템 글꼴 목록 그대로), `borderRadius`. 다크 모드는 `prefers-color-scheme`을 보고 `theme.darkAlgorithm`과 fiori.css 다크 값으로 바꾼다
  - 로케일: antd `ko_KR`, `dayjs/locale/ko`

- [ ] **Step 1: 실패하는 테스트 작성** (`SpaTest`)

```python
def test_app_serves_index(self):
    r = self.client.get('/app/overview')
    self.assertEqual(r.status_code, 200)
    self.assertContains(r, '<div id="root">')
    self.assertContains(r, '/static/app/assets/')
```

- [ ] **Step 2: 실패 확인** — Run: `.\.venv\Scripts\python manage.py test core.api.tests.SpaTest` / Expected: FAIL (404)

- [ ] **Step 3: Vite 프로젝트 생성과 패키지 설치**

Run (in `frontend/`): `npm init -y`. 그다음 `npm install react react-dom antd @ant-design/icons react-router-dom @tanstack/react-query dayjs`, `npm install -D typescript vite @vitejs/plugin-react @types/react @types/react-dom`. `@types/react`, `@types/react-dom`은 TypeScript로 React를 쓰는 데 필요한 타입 정의다. 승인 목록의 `typescript`·`react`에 딸린 것으로 보고 설치한다(Ruling). `package.json` scripts는 `"dev": "vite"`, `"build": "tsc -b && vite build"`.

- [ ] **Step 4: 위 Interfaces대로 구현하고 빌드**

Run: `npm run build` (in `frontend/`)
Expected: `dist/index.html`과 `dist/assets/*.js` 생성. 외부 URL(`http://`·`https://`)을 불러오는 코드가 없어야 한다: `grep -r "https\?://" frontend/dist/index.html`의 결과가 비어 있어야 한다.

- [ ] **Step 5: Django 연결, 테스트 통과 확인**

Run: `.\.venv\Scripts\python manage.py test core.api` / Expected: OK

- [ ] **Step 6: 수동 확인 (브라우저)**

`runserver` 후 `http://127.0.0.1:8000/app/`를 연다. 로그아웃 상태에서 로그인 화면이 떠야 한다. 로그인하면 사이드바 7묶음이 보여야 한다. 세션을 지운 뒤 메뉴를 누르면 로그인 화면으로 가야 한다(Review Focus 1). 확인 결과를 ledger에 적는다.

- [ ] **Step 7: 커밋**

```bash
git add .gitignore config/settings.py config/urls.py core/views.py core/api/tests.py frontend/
git commit -m "feat: React 앱 기반(Vite·antd·Fiori 테마·로그인·공통 틀)과 /app/ 서빙 추가"
```

`frontend/node_modules/`가 스테이징되지 않았는지 `git status`로 확인한다.

---

### Task 10: 시범 화면(종합현황·내 할 일)과 화면 흐름 점검, 문서

**Files:**
- Create: `frontend/src/pages/Overview.tsx`, `frontend/src/pages/Todo.tsx`, `frontend/src/components/Tile.tsx`
- Create: `scripts/e2e_browser.py`
- Modify: `frontend/dist/` (다시 빌드), `README.md`, `docs/architecture.md`, `docs/testing.md`

**Interfaces:**
- Consumes: Task 7 `GET /api/qms/overview/`, Task 8 `GET /api/qms/todo/`·`POST /api/qms/dashboard/`, Task 9 `api()`·`AppLayout`
- Produces:
  - `Overview`: 섹션마다 카드 격자. 카드는 제목, 큰 숫자(`tone`에 따라 색), `sub`, 아래 `rows` 목록이다. 카드와 줄을 누르면 `href`로 간다(기존 화면). 카드가 없으면 "볼 수 있는 현황이 없습니다." 안내를 보인다
  - `Todo`: 4칸 격자에 위젯을 `x`·`y`·`size` 순서로 놓는다(wide = 2×2). 위젯 추가(`available`에서 고르기), 빼기, 크기 바꾸기를 하면 `POST /api/qms/dashboard/`로 저장한다. "기본 배치로" 버튼은 빈 배열을 저장한다. `error: true`인 위젯은 "불러오지 못했습니다."를 보인다. 숫자 타일은 `Tile`, 전용 위젯 4종은 Task 8 `widget_data`의 키로 그린다
  - 폭 390px에서는 1칸 세로 배치로 바뀐다
  - `scripts/e2e_browser.py`: 시스템 Python Playwright(`python -m playwright`)로 실행한다
    - `e2e_check.py`처럼 임시 DB를 만들어 `migrate`하고, 사용자를 만들고, `runserver`를 띄운다. 포트는 8766이다
    - 다음을 점검한다: 로그인, `/app/overview`의 카드 수가 API와 같음, `/app/todo`에서 위젯 하나를 추가하고 새로고침해도 남아 있음, 390px 폭에서 가로 스크롤 없음(`document.documentElement.scrollWidth <= 390`), 다크 모드(`color_scheme='dark'`) 배경색이 라이트와 다름
    - 결과는 `e2e_check.py`처럼 항목마다 통과·실패를 출력하고, 하나라도 실패하면 종료 코드 1로 끝낸다

- [ ] **Step 1: 점검 스크립트를 먼저 작성하고 실패 확인**

Run: `python scripts\e2e_browser.py` (시스템 Python)
Expected: 카드 수·위젯 항목이 FAIL(화면이 아직 없음). 종료 코드 1

- [ ] **Step 2: 화면 구현 후 빌드** — Run: `npm run build` (in `frontend/`) / Expected: 성공

- [ ] **Step 3: 점검 통과 확인** — Run: `python scripts\e2e_browser.py` / Expected: 전 항목 통과, 종료 코드 0

- [ ] **Step 4: 1단계 전체 검증**

Run:
```
.\.venv\Scripts\python manage.py check
.\.venv\Scripts\python manage.py makemigrations --check --dry-run
.\.venv\Scripts\python manage.py test
.\.venv\Scripts\python scripts\e2e_check.py
python scripts\e2e_browser.py
```
Expected: 모두 통과. 실제 출력 숫자를 ledger에 적는다.

- [ ] **Step 5: 운영 방식으로 한 번 띄워 보기 (spec 7장 1단계 완료 기준)**

`QMS_DEBUG=0`으로 `collectstatic` 후 waitress(`scripts/serve.ps1`의 방식)로 띄우고 `/app/overview`가 열리는지 확인한다. 이때 `data/`의 운영 DB를 쓰므로 조회만 하고 아무것도 저장하지 않는다. `collectstatic`이 `data/static/`(STATIC_ROOT)에 파일을 쓰는 것은 지금 배포 절차와 같다.

- [ ] **Step 6: 문서 갱신**
  - `README.md`: 새 화면 주소 `/app/`, 개발 PC에서 프런트를 고칠 때의 명령(`cd frontend`, `npm ci`, `npm run dev`, `npm run build`), 운영 PC는 빌드하지 않는다는 점
  - `docs/architecture.md`: `core/rules.py`·`qms/rules.py`, `core/api`·`qms/api`, `frontend/`의 역할 한 줄씩. `docs/architecture-migration-plan.md` 링크
  - `docs/testing.md`: `scripts/e2e_browser.py` 명령과 시스템 Python Playwright가 필요하다는 점. 테스트 수를 실제 실행한 숫자로 고친다

- [ ] **Step 7: 커밋**

```bash
git add frontend/ scripts/e2e_browser.py README.md docs/architecture.md docs/testing.md
git commit -m "feat: React 시범 화면(공장 종합현황·내 할 일)과 브라우저 흐름 점검 추가"
```

---

## 이 계획 다음

- 1단계가 끝나면 사용자가 `/app/overview`·`/app/todo`를 써 본다. spec의 중단 기준(기존보다 크게 나아졌다고 느끼지 못하면 멈춤)은 사용자가 "끝까지"를 골라 자동 중단하지 않는다. 사용자가 멈추라고 하면 멈춘다.
- 2단계(업무 화면 묶음별 전환) 계획은 이 계획의 Task 6~9 인터페이스(`ModelPerms`, 오류 처리기, `api()`, `AppLayout`)를 바탕으로 따로 쓴다.
