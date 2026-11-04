# 업무 화면 재설계 1묶음 (공통 틀 + 검사기준서) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** React 화면에 Notion식 공통 틀(명령창·데이터 목록·기록 페이지·편집 표·승인/개정·문서 내보내기·두 층 이력)을 만들고, 첫 업무 화면인 검사기준서를 그 틀로 옮긴다.

**Architecture:**
- **규칙은 서버 공용 함수에 둔다.** `qms/rules.py`·`core/rules.py`에 두고 admin과 DRF API가 같은 함수를 부른다.
- **이력은 두 층이다.** 새 모델은 `core.RevisionLog`(신청형 개정 이력) 하나뿐이다. 자동 감사 기록은 기존 simple-history를 그대로 읽는다.
- **문서 구조 하나에서 두 출력을 낸다.** 서버가 dict를 만들면 `.xlsx`는 openpyxl(`core/export.py`)이, PDF는 React 인쇄 화면 + 브라우저 "PDF로 저장"이 만든다.

**Tech Stack:** Django 6.1.2, DRF 3.18.3, django-simple-history, openpyxl / React 19, TypeScript, Vite 8, antd 6, react-router 7, @tanstack/react-query 5 / Playwright(시스템 Python, 검증 전용)

**Spec:** `docs/superpowers/specs/2026-11-03-notion-style-frontend-design.md` (8장 1번 묶음, 9장 완료 기준)

## Global Constraints

- 새 의존성 금지: `requirements.txt`, `frontend/package.json`을 바꾸지 않는다. 외부 CDN·폰트·아이콘도 로드하지 않는다. 오프라인에서 동작해야 한다.
- 화면 문구·오류 메시지·커밋 메시지는 한국어로 쓴다. antd 영어 기본 문구("Select an option" 등)를 남기지 않는다.
- 업무 규칙은 모델 `clean()/save()` 또는 서버 공용 함수·뷰에서 강제한다. 화면에서 버튼을 숨기는 것은 편의일 뿐이다.
- simple-history 자동 기록을 줄이거나 끄지 않는다. 새 모델에는 `history = HistoricalRecords()`를 둔다.
- 마이그레이션은 새 테이블 추가(`core.RevisionLog`)만 한다. 기존 행·컬럼은 바꾸지 않는다.
- 권한은 기존 Django 권한(`qms/apps.py ensure_roles`)과 `is_approver`만 쓴다. 새 권한·역할은 만들지 않는다.
- 색은 `DESIGN.md`의 Fiori 토큰(주색 `#0057d2`, 다크 모드 값)을 유지한다. 표·속성 글자는 14px, 제목은 24px로 한다.
- 초안 표시 문구는 정확히 `초안 — 승인 전`이다.
- 확정된 개정 이력 수정·삭제 오류는 정확히 `확정된 개정 이력은 수정할 수 없습니다.`이다.
- 동시 수정 오류는 정확히 `다른 사람이 먼저 고쳤습니다. 다시 불러오세요.`이다(HTTP 409).
- 다운로드 형식은 `?export=xlsx`로 고른다. DRF가 `?format=`를 가로채 404를 내기 때문이다(아래 판정 1).
- 작업 브랜치는 `notion-ui-bundle1`이다(master에서 분기). `data/`, `.superpowers/`, `.venv/`, 사용자 파일 `docs/superpowers/plans/2026-11-02-react-drf-phase0-1.md`는 `git add`하지 않는다.
- 커밋은 한국어 Conventional Commits로 쓰고, 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`를 붙인다.
- React를 바꾼 태스크는 `cd frontend; npm run build`(tsc 포함)를 통과시키고 `frontend/dist/`를 다시 만들어 같은 커밋에 넣는다.

## 설계 판정 (스펙이 열어 둔 것 또는 스펙과 코드가 어긋난 것)

1. **`?format=` → `?export=`:**
   - 스펙 6장은 `?format=xlsx`라고 썼다.
   - DRF `URL_FORMAT_OVERRIDE`가 이 이름을 가로채서, 렌더러가 없으면 뷰 전에 404를 낸다.
   - 그래서 `?export=xlsx`를 쓴다.
2. **동시 수정 번호:**
   - 스펙의 `history.latest().history_id`(검사기준 한 건)만으로는 검사항목만 바뀐 경우를 못 잡는다.
   - 그래서 `spec_version(spec)` = 검사기준 이력과 그 검사항목 이력(삭제 포함) 중 가장 큰 `history_id`로 한다.
   - 스키마 변경은 없다.
3. **품번·검사 구분은 만들 때만 고른다:**
   - 기록 페이지에서는 읽기 전용이다.
   - 이유: 개정 계보(같은 품번·구분)가 끊기지 않게 하려는 것이다.
4. **이전 개정과 비교:**
   - 검사항목은 이름으로 짝짓는다. SPC 관리도도 이름으로 이어지기 때문이다.
   - 비교 결과 글(`diff_text`)을 "이력 남기기"의 미리 채움 내용으로 쓴다.
   - 초안에서 마지막으로 복사한 뒤 감사 기록에 생긴 변경과 같은 뜻이다(스펙 P7 2단계).
   - 이전 개정이 없으면(Rev.1) `최초 제정`이다.
   - 감사 기록을 읽어 만드는 일반 미리 채움은 개정 번호가 없는 기록(2묶음 이후)에서 만든다.
5. **문서의 개정 이력 표:**
   - 같은 품번·구분에서 현재 개정 이하인 모든 개정의 `확정` 이력을 시간순으로 모은다.
   - 화면 탭에는 `대기` 이력도 보인다.
   - 작성자는 `spec.history.earliest().history_user`, 승인자는 `approved_by`다.
   - 검사기준서에는 문서번호가 없다(`None`).
6. **`ExcelTemplate` 여러 줄 매핑:**
   - 스펙 예시(`{"A12:rows": "characteristics", "A": "name"}`)처럼 평평하게 두면 한 양식에 여러 줄 블록을 둘 수 없다.
   - 그래서 값을 객체로 둔다: `{"A12:rows": {"path": "characteristics", "cols": {"A": "name", "B": "lsl"}}}`
   - 경로 읽기 안전 규칙(`USER_FIELDS`·`READ_METHODS`·`PRIVATE_APPS`)은 기존 한 칸 매핑과 같은 함수를 쓴다.
7. **잠긴 기준서의 "수정 요청":**
   - 1묶음에서는 기존 화면 `/request/edit/qms/inspectionspec/<pk>/`(url 이름 `edit_request`)로 이동하는 링크로 둔다.
   - API로 옮기는 일은 부적합 묶음(5)에서 한다.
8. **화면의 `editable`:**
   - 기준: `not is_locked(spec) or edit_unlocked(spec, user)`, 그리고 수정 권한이 있을 것.
   - 시스템 관리자도 승인된 기준서는 읽기 전용으로 본다(스펙 P5).
   - 서버의 기존 관리자 예외(`can_edit_locked`)는 그대로 둔다.
9. **메뉴:**
   - `core/nav.py`의 `'검사기준'`은 admin url 이름을 그대로 둔다.
     - 이유: 전체 메뉴 묶음(`core/admin.py grouped_app_list`)이 admin 주소로 짝짓기 때문이다.
   - React 사이드바만 `AppLayout`의 `MOVED`로 `/admin/qms/inspectionspec/` → `/app/specs`로 바꾼다.
   - `'감사 기록'`은 새 줄로 넣는다: url 이름 `app_audit`, 권한 칸에 호출 가능한 `is_approver`.
10. **"엑셀로"(목록)·"내보내기"(기록):**
    - 둘 다 다운로드 링크(`<a href … download>`)로 연다.
    - 이유: 세션 쿠키로 GET하면 되고, fetch→Blob 코드가 필요 없다.

## Review Focus

1. **다른 기준서의 검사항목 id를 저장 요청에 넣는 경우:** 남의 항목을 고치지 못하고 400(`characteristics.{i}.id`)으로 거부해야 한다 → Task 1 `test_save_rejects_foreign_row`
2. **엑셀에서 붙여 넣은 숫자에 천 단위 쉼표·앞뒤 공백·빈칸이 있는 경우:** `1,234.5`는 1234.5로, 빈칸은 규격 없음(None)으로 저장되고 `abc`는 그 칸에 오류가 나야 한다 → Task 1 `test_save_normalizes_numbers`, Task 8 e2e 붙여넣기 데이터
3. **승인된 기준서의 검사항목을 API로 지우는 경우:** 일반 사용자는 거부되고(409 또는 403), 항목은 그대로 남아야 한다 → Task 1 `test_save_delete_on_approved_rejected`
4. **브라우저 저장소(localStorage)를 쓸 수 없는 경우(사생활 보호 모드·차단):** "최근 연 기록"만 비고 화면은 정상이어야 한다 → Task 6 e2e `localStorage 차단에도 화면 정상`
5. **명령창에서 결과가 없을 때 Enter를 누르는 경우:** 아무 데도 가지 않고 `찾는 기록이 없습니다`를 보여야 한다 → Task 6 e2e `명령창 결과 없음 Enter`

---

## 파일 구조

| 파일 | 책임 |
| --- | --- |
| `qms/rules.py` (수정) | 검사기준 공용 규칙: 새 개정, 저장, 비교, 개정 이력 모으기 |
| `qms/admin.py` (수정) | `new_revision` 동작이 `new_spec_revision`을 부른다 |
| `core/models.py` (수정) | `RevisionLog` 모델 |
| `core/migrations/0009_revisionlog.py` (생성) | 새 테이블 2개(`RevisionLog`, `HistoricalRevisionLog`) |
| `core/admin.py` (수정) | `RevisionLog` 읽기 전용 admin 등록(시스템 관리자 확인용) |
| `core/rules.py` (수정) | `request_revision_log`, `confirm_revision_log`, `approve_and_log` |
| `core/export.py` (생성) | `document_xlsx(doc)`, `table_xlsx(title, columns, rows)` |
| `qms/models.py` (수정) | `InspectionSpec.document()`, `ExcelTemplate.fill` 여러 줄 매핑 |
| `qms/api/specs.py` (생성) | 검사기준 API 뷰 |
| `qms/api/urls.py` (수정) | 검사기준 경로 |
| `core/api/views.py`·`core/api/urls.py` (수정) | 검색·품번 찾기·개정 이력 확정·감사 기록 API |
| `core/audit.py` (생성) | 감사 기록 조회: 모델 허용 목록, 이력 줄 → 바뀐 칸 |
| `core/nav.py`·`config/urls.py` (수정) | 감사 기록 메뉴, `app_audit` 경로 |
| `frontend/src/api/client.ts` (수정) | 오류 본문 보존·DRF 필드 오류 풀기 |
| `frontend/src/api/specs.ts` (생성) | 검사기준 타입·호출 |
| `frontend/src/lib/recent.ts`, `frontend/src/lib/tsv.ts` (생성) | 최근 기록(localStorage), 붙여넣기 글 나누기 |
| `frontend/src/components/CommandPalette.tsx` (생성) | Ctrl+K 명령창 |
| `frontend/src/components/DataList.tsx` (생성) | P2 목록(탭·검색·더 보기·엑셀로·미리보기 패널) |
| `frontend/src/components/RecordPage.tsx` (생성) | P3 머리·속성 블록·오른쪽 탭 틀 |
| `frontend/src/components/EditGrid.tsx` (생성) | P4 편집 표 |
| `frontend/src/components/SaveBar.tsx`, `SignModal.tsx` (생성) | 저장 띠, 비밀번호 서명 창 |
| `frontend/src/components/DocumentView.tsx` (생성) | 문서 구조 → A4 화면 |
| `frontend/src/pages/specs/SpecList.tsx`, `SpecPage.tsx`, `SpecPrint.tsx` (생성) | 검사기준서 화면 3개 |
| `frontend/src/pages/AuditLog.tsx` (생성) | 감사 기록 화면 |
| `frontend/src/app.css` (생성) | 밀도·구분선·비교 색·인쇄(`@page A4`) |
| `frontend/src/main.tsx`, `frontend/src/layout/AppLayout.tsx` (수정) | 경로, 명령창·최근 기록 |
| `scripts/e2e_browser.py` (수정) | 브라우저 점검 추가 |
| `DESIGN.md`, `docs/business-rules.md`, `docs/testing.md`, `README.md`, `docs/architecture.md` (수정) | 문서 |

---

### Task 1: 검사기준 공용 규칙 (새 개정·저장·비교)

**Files:**
- Modify: `qms/rules.py`
- Modify: `qms/admin.py:61-72` (`InspectionSpecAdmin.new_revision`)
- Test: `qms/tests_rules.py` (새 클래스 `SpecRulesTest`)

**Interfaces:**
- Consumes: `core.rules.save_with_lock(obj, user, children)`, `core.rules.child_editable(parent, user)`, `core.rules.Locked`
- Produces:
  - `new_spec_revision(spec: InspectionSpec) -> InspectionSpec` — 반드시 트랜잭션 안에서 부른다
  - `open_or_new_revision(spec: InspectionSpec) -> tuple[InspectionSpec, bool]` — (초안, 새로 만들었는가)
  - `spec_version(spec: InspectionSpec) -> int`
  - `class Stale(Exception)` — 메시지 `다른 사람이 먼저 고쳤습니다. 다시 불러오세요.`
  - `save_spec(spec, user, data: dict, rows: list[dict], version: int | None) -> InspectionSpec`
    - `data` 키: `sampling`, `note`
    - `rows` 한 줄: `{'id': int|None, 'name', 'lsl', 'usl', 'unit', 'special', 'plan_line': int|None, 'delete': bool}`
  - `prev_revision(spec) -> InspectionSpec | None` — 같은 품번·구분에서 개정번호가 바로 아래인 것
  - `compare_specs(prev: InspectionSpec | None, cur: InspectionSpec) -> dict | None`
    - 돌려주는 모양: `{'fields': {name: [old, new]}, 'rows': [{'id': int|None, 'name': str, 'status': 'added'|'removed'|'changed', 'cells': [field...]}]}`
    - `prev`가 None이면 None을 돌려준다
  - `diff_text(diff: dict | None) -> str`
  - `spec_logs(spec, confirmed_only: bool) -> QuerySet[RevisionLog]` — Task 2가 모델을 만든 뒤 Task 2에서 추가한다

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `SpecRulesTest.setUp`
  - 사용자: `eng`(품질엔지니어), `lead`(품질팀장)
  - 품번 `R1`, 승인된 Rev.1 기준서
  - 검사항목 2개: `두께` 9~11 mm SC, `폭` 4~6 mm(관리계획서 항목 연결 1개)
  - admin 비교용: 같은 구성의 품번 `R2`(`self.item2`)와 승인된 Rev.1 `self.spec2`
  - 남의 항목용: 품번 `R3`의 초안 `self.other_draft`
  - admin 동작 호출용: `self.superuser`

```python
def test_new_revision_matches_admin(self):
    # 같은 원본을 두 번 만들어 하나는 admin 동작, 하나는 공용 함수로 개정한다
    via_func = new_spec_revision(self.spec)
    self.client.force_login(self.superuser)
    self.client.post(reverse('admin:qms_inspectionspec_changelist'),
                     {'action': 'new_revision', '_selected_action': [self.spec2.pk]})
    via_admin = InspectionSpec.objects.get(item=self.item2, revision=2)
    snap = lambda s: (s.revision, s.sampling, s.note, sorted(
        (c.name, c.lsl, c.usl, c.unit, c.special, c.plan_line_id is not None) for c in s.characteristics.all()))
    self.assertEqual(snap(via_func), snap(via_admin))
    self.assertEqual(via_func.revision, 2)
    self.assertFalse(via_func.is_approved)

def test_open_or_new_reuses_draft(self):
    draft, created = open_or_new_revision(self.spec)
    again, created2 = open_or_new_revision(self.spec)
    self.assertEqual((created, created2, again.pk), (True, False, draft.pk))

def test_save_adds_changes_deletes_in_one_go(self):
    draft, _ = open_or_new_revision(self.spec)
    keep, drop = draft.characteristics.order_by('name')   # 두께, 폭
    rows = [{'id': keep.pk, 'name': '두께', 'lsl': '9.5', 'usl': '11', 'unit': 'mm', 'special': 'SC', 'plan_line': None},
            {'id': drop.pk, 'delete': True},
            {'id': None, 'name': '길이', 'lsl': '', 'usl': '', 'unit': '', 'special': '', 'plan_line': None},
            {'id': None, 'name': '', 'lsl': '', 'usl': '', 'unit': '', 'special': '', 'plan_line': None}]  # 빈 줄은 무시
    save_spec(draft, self.eng, {'sampling': 'n=8', 'note': ''}, rows, spec_version(draft))
    self.assertEqual(sorted(draft.characteristics.values_list('name', flat=True)), ['길이', '두께'])
    self.assertEqual(draft.characteristics.get(name='두께').lsl, Decimal('9.5'))
    self.assertEqual(InspectionSpec.objects.get(pk=draft.pk).sampling, 'n=8')

def test_save_normalizes_numbers(self):          # Review Focus 2
    draft, _ = open_or_new_revision(self.spec)
    save_spec(draft, self.eng, {}, [{'id': None, 'name': '무게', 'lsl': ' 1,234.5 ', 'usl': '', 'unit': 'g'}], None)
    c = draft.characteristics.get(name='무게')
    self.assertEqual((c.lsl, c.usl), (Decimal('1234.5'), None))

def test_save_bad_row_saves_nothing_and_points_to_cell(self):
    draft, _ = open_or_new_revision(self.spec)
    before = draft.characteristics.count()
    rows = [{'id': None, 'name': '가', 'lsl': '1'}, {'id': None, 'name': '나', 'lsl': 'abc'}]
    with self.assertRaises(ValidationError) as cm:
        save_spec(draft, self.eng, {}, rows, None)
    self.assertIn('characteristics.1.lsl', cm.exception.message_dict)
    self.assertEqual(draft.characteristics.count(), before)

def test_save_rejects_foreign_row(self):         # Review Focus 1
    other = Characteristic.objects.create(spec=self.other_draft, name='남의 항목')
    draft, _ = open_or_new_revision(self.spec)
    with self.assertRaises(ValidationError) as cm:
        save_spec(draft, self.eng, {}, [{'id': other.pk, 'name': '바꿈'}], None)
    self.assertIn('characteristics.0.id', cm.exception.message_dict)
    self.assertEqual(Characteristic.objects.get(pk=other.pk).name, '남의 항목')

def test_save_on_approved_is_locked(self):
    c = self.spec.characteristics.first()
    with self.assertRaises(Locked):
        save_spec(self.spec, self.eng, {}, [{'id': c.pk, 'name': '바꿈', 'lsl': '9', 'usl': '11'}], None)

def test_save_delete_on_approved_rejected(self):  # Review Focus 3
    c = self.spec.characteristics.first()
    with self.assertRaises((Locked, PermissionDenied)):
        save_spec(self.spec, self.eng, {}, [{'id': c.pk, 'delete': True}], None)
    self.assertTrue(Characteristic.objects.filter(pk=c.pk).exists())

def test_stale_version_rejected(self):
    draft, _ = open_or_new_revision(self.spec)
    v = spec_version(draft)
    save_spec(draft, self.lead, {'note': '먼저'}, [], v)
    with self.assertRaises(Stale):
        save_spec(InspectionSpec.objects.get(pk=draft.pk), self.eng, {'note': '나중'}, [], v)

def test_compare_and_text(self):
    draft, _ = open_or_new_revision(self.spec)
    rows = [{'id': c.pk, 'delete': True} for c in draft.characteristics.filter(name='폭')]
    rows += [{'id': draft.characteristics.get(name='두께').pk, 'name': '두께', 'lsl': '9', 'usl': '10.5', 'unit': 'mm', 'special': 'SC'},
             {'id': None, 'name': '길이'}]
    save_spec(draft, self.eng, {'sampling': 'n=8'}, rows, None)
    diff = compare_specs(self.spec, draft)
    self.assertEqual(diff['fields']['sampling'][1], 'n=8')
    self.assertEqual({r['name']: r['status'] for r in diff['rows']}, {'두께': 'changed', '폭': 'removed', '길이': 'added'})
    self.assertEqual(next(r for r in diff['rows'] if r['name'] == '두께')['cells'], ['usl'])
    text = diff_text(diff)
    for part in ('샘플링', '항목 추가: 길이', '항목 삭제: 폭', '두께'):
        self.assertIn(part, text)
    self.assertEqual(diff_text(compare_specs(None, self.spec)), '최초 제정')
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `.\.venv\Scripts\python manage.py test qms.tests_rules.SpecRulesTest`
Expected: FAIL. `ImportError: cannot import name 'new_spec_revision'`

- [ ] **Step 3: `qms/rules.py`에 함수를 구현하고 admin 동작이 이를 부르게 한다**
  - **`new_spec_revision`:** `qms/admin.py:64-71`의 본문을 그대로 옮긴다. admin 동작은 `with transaction.atomic(): for spec in queryset: new_spec_revision(spec)`로 바꾼다.
  - **`open_or_new_revision`:**
    - 같은 품번·구분에서 `approved_at__isnull=True`이고 개정번호가 가장 큰 것을 찾는다.
    - 있으면 `(그것, False)`, 없으면 `transaction.atomic` 안에서 `(new_spec_revision(spec), True)`를 돌려준다.
  - **`spec_version`:** 다음 두 값 중 큰 것이다. 이력이 없으면 0이다.
    - `spec.history` 최대 `history_id`
    - `Characteristic.history.filter(spec_id=spec.pk)` 최대 `history_id`
  - **`save_spec` 처리 순서:** 전체를 `transaction.atomic` 안에서 한다.
    1. `version`이 None이 아니고 `spec_version(spec)`와 다르면 `Stale`을 낸다.
    2. 권한을 확인한다. 없으면 `PermissionDenied`.
       - 항상 `qms.change_inspectionspec`
       - 새 줄이 있으면 `qms.add_characteristic`
       - 바뀐 줄이 있으면 `qms.change_characteristic`
       - 삭제 줄이 있으면 `qms.delete_characteristic`이 필요하고, `child_editable(spec, user)`가 거짓이면 `Locked(LOCKED_MSG)`를 낸다.
    3. 각 줄을 처리한다.
       - `id`가 있는데 이 기준서의 항목이 아니면 `characteristics.{i}.id` 오류(`다른 검사기준의 항목입니다.`)를 쌓는다.
       - 이름·하한·상한·단위가 모두 빈 새 줄은 건너뛴다.
       - 숫자 칸은 앞뒤 공백과 `,`를 없애고, 빈 글이면 None으로 둔다.
       - `full_clean(exclude=['spec'])` 오류는 `characteristics.{i}.{field}` 키로 쌓는다.
    4. 쌓인 오류가 있으면 `ValidationError(dict)`를 낸다.
    5. `spec.sampling`·`spec.note`를 `data`에서 채운다(없는 키는 그대로 둔다).
    6. `save_with_lock(spec, user, children=바뀐·새 줄)`을 부른다.
    7. 삭제 줄을 지운다.
  - **`compare_specs`:** 대상 칸은 `sampling`, `note`와 줄의 `lsl`, `usl`, `unit`, `special`, `plan_line_id`다. 줄은 이름으로 짝짓는다(판정 4).
  - **`diff_text`:** 한 줄씩 쓴다.
    - 속성: `샘플링: 'n=5' → 'n=8'`
    - 항목 추가: `항목 추가: 길이`
    - 항목 삭제: `항목 삭제: 폭`
    - 항목 변경: `항목 변경: 두께 (상한 11 → 10.5)`
    - 칸 이름은 모델 `verbose_name`이다. 단, `하한(LSL)`은 `하한`으로 줄인다.
    - `None`이면 `최초 제정`, 바뀐 것이 없으면 `변경 없음`이다.

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `.\.venv\Scripts\python manage.py test qms.tests_rules qms.tests`
Expected: 모두 OK. 기존 admin `new_revision` 관련 테스트도 통과해야 한다.

- [ ] **Step 5: 커밋**

```bash
git add qms/rules.py qms/admin.py qms/tests_rules.py
git commit -m "feat: 검사기준 새 개정·저장·비교를 공용 규칙으로 만든다"
```

---

### Task 2: 개정 이력 모델 `RevisionLog`와 규칙

**Files:**
- Modify: `core/models.py` (`EditRequest` 다음에 둔다)
- Create: `core/migrations/0009_revisionlog.py` (`makemigrations core`로 만든다)
- Modify: `core/admin.py` (읽기 전용 등록)
- Modify: `core/rules.py`
- Modify: `qms/rules.py` (`spec_logs`)
- Test: `core/tests_rules.py` (새 클래스 `RevisionLogTest`), `qms/tests_rules.py` (`SpecRulesTest.test_spec_logs_across_revisions`)

**Interfaces:**
- Consumes: `core.rules.approve(obj, user, password)`, Task 1 `open_or_new_revision`
- Produces:
  - **`RevisionLog` 칸:**
    - `content_type`, `object_id`(PositiveBigIntegerField), `target`(GenericForeignKey)
    - `object_repr`(200), `label`(20, 예 `Rev.2`), `changes`(Text), `reason`(Text)
    - `requested_by`, `requested_at`(auto_now_add)
    - `status`(`PENDING='PENDING'` 표시 `대기`, `CONFIRMED='CONFIRMED'` 표시 `확정`)
    - `approved_by`, `approved_at`, `history`
    - `verbose_name='개정 이력'`, `ordering=['requested_at', 'pk']`
  - `request_revision_log(obj, user, label: str, changes: str, reason: str) -> RevisionLog`
  - `confirm_revision_log(log: RevisionLog, user, password: str) -> RevisionLog`
  - `approve_and_log(obj, user, password: str, label: str, changes: str, reason: str) -> RevisionLog` — 승인 서명과 확정 이력을 한 트랜잭션에서 처리한다
  - `qms.rules.spec_logs(spec, confirmed_only: bool) -> QuerySet[RevisionLog]` — 판정 5의 형제 개정 모음

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
class RevisionLogTest(TestCase):
    # setUp: 품질팀장 lead(pw-lead-123), 품질엔지니어 eng, 초안 검사기준 spec(Rev.1)
    def test_request_then_confirm_then_immutable(self):
        log = request_revision_log(self.spec, self.eng, 'Rev.1', '최초 제정', '신규 품번')
        self.assertEqual(log.status, RevisionLog.PENDING)
        confirm_revision_log(log, self.lead, 'pw-lead-123')
        log.refresh_from_db()
        self.assertEqual((log.status, log.approved_by), (RevisionLog.CONFIRMED, self.lead))
        log.reason = '바꿈'
        with self.assertRaisesMessage(ValidationError, '확정된 개정 이력은 수정할 수 없습니다.'):
            log.save()
        with self.assertRaisesMessage(ValidationError, '확정된 개정 이력은 수정할 수 없습니다.'):
            log.delete()

    def test_reason_and_changes_required(self):
        with self.assertRaisesMessage(ValidationError, '사유를 입력하세요.'):
            request_revision_log(self.spec, self.eng, 'Rev.1', '내용', ' ')
        with self.assertRaisesMessage(ValidationError, '변경 내용을 입력하세요.'):
            request_revision_log(self.spec, self.eng, 'Rev.1', '', '사유')

    def test_confirm_needs_approver_and_password(self):
        log = request_revision_log(self.spec, self.eng, 'Rev.1', '최초 제정', '사유')
        with self.assertRaisesMessage(PermissionDenied, '품질팀장만 승인할 수 있습니다.'):
            confirm_revision_log(log, self.eng, 'pw-eng-123')
        with self.assertRaisesMessage(ValidationError, '비밀번호가 맞지 않습니다.'):
            confirm_revision_log(log, self.lead, 'wrong')

    def test_approve_and_log_is_atomic(self):
        with self.assertRaises(ValidationError):
            approve_and_log(self.spec, self.lead, 'wrong', 'Rev.1', '최초 제정', '사유')
        self.assertFalse(RevisionLog.objects.exists())
        self.assertFalse(InspectionSpec.objects.get(pk=self.spec.pk).is_approved)
        log = approve_and_log(self.spec, self.lead, 'pw-lead-123', 'Rev.1', '최초 제정', '사유')
        self.assertEqual(log.status, RevisionLog.CONFIRMED)
        self.assertTrue(InspectionSpec.objects.get(pk=self.spec.pk).is_approved)

    def test_plain_save_leaves_no_revision_log_but_history(self):   # 스펙 9장 "개정 이력 표시"
        n = self.spec.history.count()
        save_spec(self.spec, self.eng, {'note': '메모'}, [], None)
        self.assertEqual(RevisionLog.objects.count(), 0)
        self.assertEqual(self.spec.history.count(), n + 1)
```

`qms/tests_rules.py`에 추가할 테스트:

```python
def test_spec_logs_across_revisions(self):
    # Rev.1 확정 1건 + Rev.2 대기 1건 → Rev.2 문서용은 1건, 탭용은 2건
    self.assertEqual(spec_logs(draft, confirmed_only=True).count(), 1)
    self.assertEqual(spec_logs(draft, confirmed_only=False).count(), 2)
    self.assertEqual(spec_logs(self.spec, confirmed_only=False).count(), 1)   # Rev.1에서는 Rev.2 이력이 안 보인다
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `.\.venv\Scripts\python manage.py test core.tests_rules.RevisionLogTest`
Expected: FAIL. `ImportError: cannot import name 'RevisionLog'`

- [ ] **Step 3: 모델·마이그레이션·규칙을 구현한다**
  - **모델:**
    - 칸 정의는 `EditRequest`를 따른다.
    - `save()`: `pk`가 있고 DB 행이 `CONFIRMED`이면 ValidationError를 낸다.
    - `delete()`: 자기 상태가 `CONFIRMED`이면 ValidationError를 낸다.
  - **마이그레이션:** `.\.venv\Scripts\python manage.py makemigrations core -n revisionlog`로 만든다.
    - 결과를 읽어 `CreateModel` 2개(`RevisionLog`, `HistoricalRevisionLog`)만 있는지 확인한다.
  - **admin:**
    - `RevisionLog`를 `BaseAdmin`으로 등록한다.
    - 모든 칸을 `readonly_fields`로 하고, `has_add_permission`은 False로 한다.
    - 화면 메뉴(`core/nav.py`)에는 넣지 않는다.
  - **`request_revision_log`:**
    - `changes`·`reason`을 `strip()`한 뒤 빈 글이면 오류를 낸다.
    - `object_repr=str(obj)[:200]`
  - **`confirm_revision_log`:**
    - 확인 순서: `is_approver` → 이미 확정(`이미 확정된 개정 이력입니다.`) → 비밀번호
    - 문구는 `approve`와 같다.
  - **`approve_and_log`:**
    - `transaction.atomic` 안에서 `approve(obj, user, password)`를 부른다(비밀번호 확인 포함).
    - 그다음 `CONFIRMED` 상태로 바로 만든다. `approved_by=user`, `approved_at`은 `obj.approved_at`과 같은 값이다.
  - **`spec_logs`:**
    - 같은 품번·구분이고 `revision__lte=spec.revision`인 기준서 id들을 모은다.
    - `content_type`이 InspectionSpec인 `RevisionLog`만 고른다. `confirmed_only`이면 `CONFIRMED`만 남긴다.

- [ ] **Step 4: 테스트와 마이그레이션 점검을 돌린다**

Run:
- `.\.venv\Scripts\python manage.py test core.tests_rules qms.tests_rules`
- `.\.venv\Scripts\python manage.py makemigrations --check --dry-run`

Expected: 테스트 OK, `No changes detected`

- [ ] **Step 5: 커밋**

```bash
git add core/models.py core/migrations/0009_revisionlog.py core/admin.py core/rules.py core/tests_rules.py qms/rules.py qms/tests_rules.py
git commit -m "feat: 신청·승인형 개정 이력(RevisionLog)을 추가하고 확정 후 수정을 막는다"
```

---

### Task 3: 문서 구조와 .xlsx 내보내기, 양식 여러 줄 매핑

**Files:**
- Create: `core/export.py`
- Modify: `qms/models.py` (`InspectionSpec.document`, `ExcelTemplate.fill`·`_resolve`, `mapping` help_text)
- Test: `qms/tests.py` (새 클래스 `SpecDocumentTest`)

**Interfaces:**
- Consumes: Task 1 `qms.rules.prev_revision`, Task 2 `qms.rules.spec_logs`
- Produces:
  - `InspectionSpec.document(self) -> dict`
    - 모양:
      ```
      {'title': str, 'number': None, 'revision': 'Rev.N', 'draft': bool,
       'head': [[label, value]],
       'tables': [{'title', 'columns': [str], 'rows': [[str]]}],
       'revisions': [{'label', 'changes', 'reason', 'requested_by', 'approved_by', 'approved_at'}],
       'signoff': {'written_by', 'written_at', 'approved_by', 'approved_at'}}
      ```
    - 값은 모두 JSON으로 바꿀 수 있는 글이다. 날짜는 `YYYY-MM-DD`이고, 없으면 `''`다.
  - `core.export.DRAFT_MARK = '초안 — 승인 전'`
  - `core.export.document_xlsx(doc: dict) -> bytes`
  - `core.export.table_xlsx(title: str, columns: list[str], rows: list[list]) -> bytes`
  - `core.export.XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'`
  - `core.export.xlsx_response(data: bytes, filename: str) -> HttpResponse` — 기존 `excel_report`처럼 `content_disposition_header(True, filename)`을 쓴다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
class SpecDocumentTest(TestCase):
    # setUp: 품번 R1 양극재, 승인된 Rev.1(항목 두께 9~11 mm SC, 폭 4~6 mm), 확정 개정 이력 1건(Rev.1 '최초 제정')
    def cells(self, data):
        ws = load_workbook(BytesIO(data)).active
        return ws, {str(c.value) for row in ws.iter_rows() for c in row if c.value not in (None, '')}

    def test_document_structure(self):
        doc = self.spec.document()
        self.assertEqual(doc['title'], 'R1 수입검사 Rev.1')
        self.assertFalse(doc['draft'])
        self.assertIn(['품번', 'R1'], doc['head'])
        self.assertEqual(doc['tables'][0]['columns'], ['항목명', '하한', '상한', '단위', '특별특성', '관리계획서 항목'])
        self.assertEqual(doc['tables'][0]['rows'][0][:4], ['두께', '9', '11', 'mm'])
        self.assertEqual(doc['revisions'][0]['changes'], '최초 제정')
        self.assertEqual(doc['signoff']['approved_by'], 'lead')

    def test_xlsx_one_sheet_with_all_parts_and_a4(self):   # 스펙 9장 문서 출력
        ws, vals = self.cells(document_xlsx(self.spec.document()))
        self.assertEqual(len(ws.parent.worksheets), 1)
        for v in ('R1 수입검사 Rev.1', '검사항목', '두께', '폭', '개정 이력', '최초 제정', '작성', '승인', 'lead'):
            self.assertIn(v, vals)
        self.assertEqual(str(ws.page_setup.paperSize), '9')
        self.assertEqual(ws.page_setup.orientation, 'portrait')
        self.assertTrue(ws.sheet_properties.pageSetUpPr.fitToPage)
        self.assertNotIn(DRAFT_MARK, vals)

    def test_draft_marked(self):                              # 스펙 9장 초안 표시
        draft, _ = open_or_new_revision(self.spec)
        doc = draft.document()
        self.assertTrue(doc['draft'])
        ws, vals = self.cells(document_xlsx(doc))
        self.assertIn(DRAFT_MARK, vals)
        self.assertIn(DRAFT_MARK, ws.oddHeader.center.text)

    def test_template_rows_mapping(self):
        # 빈 통합문서를 양식 파일로 저장해 ExcelTemplate(target=InspectionSpec)를 만든다
        tpl.mapping = {'B2': 'item.code', 'A5:rows': {'path': 'characteristics', 'cols': {'A': 'name', 'B': 'lsl', 'C': 'spec.approved_by.password'}}}
        ws = load_workbook(BytesIO(tpl.fill(self.spec))).active
        self.assertEqual(ws['B2'].value, 'R1')
        self.assertEqual({ws['A5'].value, ws['A6'].value}, {'두께', '폭'})
        self.assertIsNone(ws['C5'].value)          # 안전 규칙은 줄 매핑에도 적용된다
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `.\.venv\Scripts\python manage.py test qms.tests.SpecDocumentTest`
Expected: FAIL. `ModuleNotFoundError: No module named 'core.export'`

- [ ] **Step 3: 구현한다**
  - **`document_xlsx` 배치:** 한 시트에 아래 순서로 놓는다.
    1. 1행: 제목(굵게, 합친 칸)
    2. 초안이면 2행에 `DRAFT_MARK`를 쓴다. 이때 `ws.oddHeader.center.text = DRAFT_MARK`도 넣는다.
    3. 머리 정보: `이름 | 값`을 두 쌍씩 한 줄에 둔다.
    4. 빈 줄을 하나 둔다.
    5. 표마다: 제목 줄, 머리 줄(굵게, 얇은 테두리), 데이터 줄
    6. `개정 이력` 표: 열은 `개정 | 변경 내용 | 사유 | 신청 | 승인 | 승인일`
    7. 결재란: `작성 | 이름 | 일자`, `승인 | 이름 | 일자`
    - 인쇄 설정: `paperSize = ws.PAPERSIZE_A4`, `orientation='portrait'`, `fitToPage=True`, `fitToWidth=1`, `fitToHeight=0`
  - **`table_xlsx`:** 1행은 머리 줄(굵게)이다. 인쇄 설정은 A4 가로(`landscape`), 너비 맞춤이다.
  - **`InspectionSpec.document`:**
    - 머리 정보는 `품번`, `품명`, `검사 구분`, `개정`, `샘플링`, `비고`다.
    - 숫자는 `format(d.normalize(), 'f')`로 뒤의 0을 없앤다.
    - 작성자 `written_by`: `self.history.earliest().history_user`의 `get_full_name() or username`. 없으면 `''`다.
  - **`ExcelTemplate`:**
    - 루프 안의 경로 읽기를 `_resolve(obj, path)`로 빼낸다. 기존 동작은 바꾸지 않는다.
    - 키가 `:rows`로 끝나면 `_resolve(obj, value['path'])`를 구한다. 그것이 관계 관리자면 `.all()`을 줄마다 돌린다. 각 열은 `_resolve(row, col_path)`로 채운다.
    - `mapping` help_text에 여러 줄 예시를 더한다(`makemigrations` 결과가 help_text 변경 1건이면 그 마이그레이션도 같이 커밋한다).

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `.\.venv\Scripts\python manage.py test qms`
Expected: OK. 기존 `ExcelTemplate` 테스트도 통과해야 한다.

- [ ] **Step 5: 커밋**

```bash
git add core/export.py qms/models.py qms/tests.py qms/migrations/
git commit -m "feat: 검사기준서 문서 구조와 A4 엑셀 내보내기, 양식 여러 줄 매핑을 추가한다"
```

---

### Task 4: 검사기준 API

**Files:**
- Create: `qms/api/specs.py`
- Modify: `qms/api/urls.py`
- Test: `qms/api/tests.py` (새 클래스 `SpecApiTest`)

**Interfaces:**
- Consumes: Task 1~3 함수 전부, `core.api.permissions.require_perm`, `core.rules.approve`, `core.export.*`
- Produces: 경로는 모두 `/api/qms/` 아래에 둔다. 응답은 dict다.

| 메서드·경로 | 권한 | 응답 |
| --- | --- | --- |
| `GET specs/?tab=all\|draft\|approved\|current&q=&page=1` | `qms.view_inspectionspec` | `{count, page, has_more, results:[{id, item_code, item_name, inspection_type, inspection_type_display, revision, status, is_current, char_count, approved_by, approved_at}]}`, 50줄 |
| 같은 경로 `&export=xlsx` | 같음 | 필터를 그대로 적용한 모든 줄. 열: `품번, 품명, 검사 구분, 개정, 상태, 항목 수, 승인자, 승인일` |
| `POST specs/ {item, inspection_type}` | `qms.add_inspectionspec` | 201 상세. 같은 품번·구분이 있으면 409 `{detail:'이미 있는 검사기준입니다. 새 개정으로 만드세요.', existing:<최고 개정 id>}` |
| `GET specs/<id>/` | view | 상세(아래) |
| `PUT specs/<id>/ {sampling, note, characteristics, version}` | `save_spec` 안에서 확인 | 상세. `Stale`이면 409 `{detail: Stale 문구}` |
| `POST specs/<id>/new-revision/` | `qms.add_inspectionspec` | `{id, created}` |
| `POST specs/<id>/approve/ {password, log?: {changes, reason}}` | `approve` 안의 `is_approver` | 상세. `log`가 있으면 `approve_and_log` |
| `GET specs/<id>/revision-log/` | view | `{results:[{id, label, changes, reason, status, status_display, requested_by, requested_at, approved_by, approved_at, spec_id}], prefill:{label:'Rev.N', changes: diff_text(...)}}` |
| `POST specs/<id>/revision-log/ {changes, reason}` | `qms.change_inspectionspec` | 201 한 줄. `label`은 서버가 `Rev.{revision}`으로 정한다 |
| `GET specs/<id>/document/` (`&export=xlsx`) | view | `document()` dict 또는 xlsx. 파일 이름 `{item.code}_{type_display}_Rev{n}.xlsx` |

- **상세 응답 칸:**
  - 기본: `id, title, item:{id, code, name}, inspection_type, inspection_type_display, revision, sampling, note, status, approved_by, approved_at`
  - `status`는 `'초안'` 또는 `'승인됨'`이다(목록 응답도 같다). 화면의 `잠김` 배지는 `status == '승인됨' and not editable`일 때 붙인다.
  - 편집 상태:
    - `version`: `spec_version`
    - `editable`: 판정 8의 기준
    - `can_approve`: `is_approver and not approved`
    - `prev_id`: 이전 개정의 id
  - 검사항목 `characteristics`: `[{id, name, lsl, usl, unit, special, plan_line, spc_url}]`
    - `spc_url`은 `reverse('spc', args=[id])`다.
  - 선택 목록:
    - `plan_line_options`: `[{value, label}]`. 같은 품번 관리계획서의 줄이다.
    - `special_options`: `SPECIAL`에서 `('', '-')`를 `('', '없음')`으로 바꾼 것
  - 비교·서식:
    - `diff`: `compare_specs(prev, spec)`
    - `templates`: `[{id, name, url}]`. 대상이 InspectionSpec인 `ExcelTemplate`이고, `url`은 기존 `excel_report` 주소다.
    - `edit_request_url`: 판정 7의 주소

- [ ] **Step 1: 실패하는 테스트를 쓴다** (`qms/api/tests.py` 방식: `APIClient`, 그룹이 있는 사용자, `force_login`)

```python
class SpecApiTest(TestCase):
    # setUp: eng(품질엔지니어), lead(품질팀장, pw-lead-123), insp(검사원), 품번 R1, 승인된 Rev.1(두께·폭), 초안 다른 품번 R2 Rev.1
    def test_list_tabs_and_current(self):
        r = self.c(self.eng).get('/api/qms/specs/?tab=current')
        self.assertEqual([x['id'] for x in r.json()['results']], [self.spec.pk])
        self.assertEqual(self.c(self.eng).get('/api/qms/specs/?tab=draft').json()['count'], 1)

    def test_list_export_xlsx(self):
        r = self.c(self.eng).get('/api/qms/specs/?tab=all&export=xlsx')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], XLSX)
        ws = load_workbook(BytesIO(r.content)).active
        self.assertEqual(ws['A1'].value, '품번')
        self.assertEqual(ws.max_row, 3)

    def test_create_conflict_points_to_existing(self):
        r = self.c(self.eng).post('/api/qms/specs/', {'item': self.item.pk, 'inspection_type': 'INCOMING'}, format='json')
        self.assertEqual((r.status_code, r.json()['existing']), (409, self.spec.pk))

    def test_put_on_approved_rejected(self):               # 스펙 9장
        c = self.spec.characteristics.first()
        body = {'characteristics': [{'id': c.pk, 'name': '바꿈', 'lsl': '1', 'usl': '2'}], 'version': None}
        r = self.c(self.eng).put(f'/api/qms/specs/{self.spec.pk}/', body, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Characteristic.objects.get(pk=c.pk).name, c.name)

    def test_put_field_errors_by_row(self):
        draft = self.new_draft()
        body = {'characteristics': [{'id': None, 'name': '가', 'lsl': 'abc'}], 'version': None}
        r = self.c(self.eng).put(f'/api/qms/specs/{draft.pk}/', body, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('characteristics.0.lsl', r.json()['fields'])

    def test_put_stale_409(self):
        draft = self.new_draft()
        old = self.c(self.eng).get(f'/api/qms/specs/{draft.pk}/').json()['version']
        self.c(self.lead).put(f'/api/qms/specs/{draft.pk}/', {'note': 'a', 'characteristics': [], 'version': old}, format='json')
        r = self.c(self.eng).put(f'/api/qms/specs/{draft.pk}/', {'note': 'b', 'characteristics': [], 'version': old}, format='json')
        self.assertEqual((r.status_code, r.json()['detail']), (409, '다른 사람이 먼저 고쳤습니다. 다시 불러오세요.'))

    def test_inspector_cannot_edit(self):
        draft = self.new_draft()
        r = self.c(self.insp).put(f'/api/qms/specs/{draft.pk}/', {'characteristics': [], 'version': None}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_new_revision_then_approve_with_log(self):
        r = self.c(self.eng).post(f'/api/qms/specs/{self.spec.pk}/new-revision/')
        new_id = r.json()['id']
        self.assertEqual(InspectionSpec.objects.get(pk=new_id).revision, 2)
        self.assertEqual(self.c(self.eng).post(f'/api/qms/specs/{new_id}/approve/', {'password': 'x'}, format='json').status_code, 403)
        r = self.c(self.lead).post(f'/api/qms/specs/{new_id}/approve/',
                                   {'password': 'pw-lead-123', 'log': {'changes': '두께 상한 변경', 'reason': '고객 요청'}}, format='json')
        self.assertEqual(r.json()['status'], '승인됨')
        logs = self.c(self.eng).get(f'/api/qms/specs/{new_id}/revision-log/').json()['results']
        self.assertEqual([(l['label'], l['status']) for l in logs][-1], ('Rev.2', 'CONFIRMED'))

    def test_document_xlsx_endpoint(self):
        r = self.c(self.insp).get(f'/api/qms/specs/{self.spec.pk}/document/?export=xlsx')
        self.assertEqual((r.status_code, r['Content-Type']), (200, XLSX))
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `.\.venv\Scripts\python manage.py test qms.api.tests.SpecApiTest`
Expected: FAIL. 404(경로 없음)

- [ ] **Step 3: `qms/api/specs.py`에 뷰를 구현하고 `qms/api/urls.py`에 경로를 더한다**
  - 기존 `qms/api/views.py`처럼 `APIView`가 dict를 돌려준다. `schema = None`이다.
  - 오류는 기존 예외 처리기(`core.api.exceptions.handler`)에 맡긴다.
    - `Locked` → 409
    - ValidationError dict → 400 + `fields`
    - `PermissionDenied` → 403
  - `Stale`만 뷰에서 409로 바꾼다.
  - `tab=current`는 `Exists`로 거른다. 같은 품번·구분에 승인된 더 높은 개정이 없는 승인본만 남긴다.
  - 정렬은 `item__code, inspection_type, -revision`이다.

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `.\.venv\Scripts\python manage.py test qms.api`
Expected: OK

- [ ] **Step 5: 커밋**

```bash
git add qms/api/specs.py qms/api/urls.py qms/api/tests.py
git commit -m "feat: 검사기준 목록·상세·저장·개정·승인·개정 이력·문서 API를 추가한다"
```

---

### Task 5: 공통 API (검색·품번 찾기·개정 이력 확정·감사 기록)와 메뉴

**Files:**
- Create: `core/audit.py`
- Modify: `core/api/views.py`, `core/api/urls.py`
- Modify: `core/nav.py` (`visible_nav`가 호출 가능한 권한을 받는다. 기준정보 묶음에 `('감사 기록', 'app_audit', is_approver)`를 더한다)
- Modify: `config/urls.py` (`path('app/audit', core_views.spa, name='app_audit')`를 `re_path(r'^app/…')` 앞에 둔다)
- Test: `core/api/tests.py` (새 클래스 `CommonApiTest`), `core/tests.py` (`ShellTest`에 메뉴 테스트 1개)

**Interfaces:**
- Consumes: `core.search.search(user, q)`, Task 2 `confirm_revision_log`, `qms.models.PRIVATE_APPS`
- Produces:
  - **`GET /api/search/?q=`:** `{results: search(user, q)}`
  - **`GET /api/items/?q=`:**
    - 권한: `core.view_item`
    - 응답: `[{id, code, name}]`, 최대 20개
    - 찾는 곳: 품번·품명 `icontains`
  - **`POST /api/revision-log/<id>/approve/ {password}`:** 개정 이력 한 줄을 돌려준다(Task 4와 같은 모양).
  - **`GET /api/audit-log/`:**
    - 권한: `is_approver`. 아니면 403 `품질팀장만 볼 수 있습니다.`
    - `model`이 없으면: `{models:[{key:'qms.inspectionspec', label:'검사기준'}]}`
    - `model=app.model&id=&page=`이면: `{count, page, has_more, results:[{history_id, date, user, type:'생성'|'변경'|'삭제', object_id, object_repr, changes:[{field, old, new}]}]}`
    - 최신순으로 50줄씩 준다.
  - `core.audit.audited_models() -> dict[str, type]`
    - `history` 관리자가 있는 모델만 담는다. `app_label`이 `PRIVATE_APPS`(personal·auth 등)에 있는 모델은 뺀다.
  - `core.audit.rows(model, object_id: int | None) -> QuerySet` 그리고 `core.audit.row_payload(h) -> dict`
    - 바뀐 칸은 `h.diff_against(h.prev_record)`로 구한다. 칸 이름은 `verbose_name`이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
class CommonApiTest(TestCase):
    # setUp: lead(품질팀장), eng(품질엔지니어), 품번 R1, LOT 'RAW-2611-001', 초안 검사기준과 대기 개정 이력 1건
    def test_search_partial_lot(self):
        r = self.c(self.eng).get('/api/search/?q=2611')
        self.assertTrue(any(x['label'] == 'RAW-2611-001' and '/trace/?lot=' in x['url'] for x in r.json()['results']))

    def test_items_lookup(self):
        self.assertEqual(self.c(self.eng).get('/api/items/?q=양극').json()[0]['code'], 'R1')

    def test_audit_log_approver_only_and_no_private(self):
        self.assertEqual(self.c(self.eng).get('/api/audit-log/').status_code, 403)
        keys = {m['key'] for m in self.c(self.lead).get('/api/audit-log/').json()['models']}
        self.assertIn('qms.inspectionspec', keys)
        self.assertFalse(any(k.startswith(('personal.', 'auth.')) for k in keys))
        self.assertEqual(self.c(self.lead).get('/api/audit-log/?model=personal.leaveprofile').status_code, 404)

    def test_audit_log_rows_show_changes(self):
        self.spec.note = '바꿈'; self.spec.save()
        r = self.c(self.lead).get(f'/api/audit-log/?model=qms.inspectionspec&id={self.spec.pk}').json()
        self.assertEqual(r['results'][0]['type'], '변경')
        self.assertIn({'field': '비고', 'old': '', 'new': '바꿈'}, r['results'][0]['changes'])

    def test_confirm_revision_log_endpoint(self):
        r = self.c(self.lead).post(f'/api/revision-log/{self.log.pk}/approve/', {'password': 'pw-lead-123'}, format='json')
        self.assertEqual(r.json()['status'], 'CONFIRMED')
        r = self.c(self.lead).post(f'/api/revision-log/{self.log.pk}/approve/', {'password': 'pw-lead-123'}, format='json')
        self.assertEqual(r.status_code, 400)
```

`core/tests.py` `ShellTest`에 추가할 테스트:

```python
def test_audit_menu_only_for_approver(self):
    labels = lambda u: [l for _, items in visible_nav(u) for l, _ in items]
    self.assertIn('감사 기록', labels(lead))
    self.assertNotIn('감사 기록', labels(eng))
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `.\.venv\Scripts\python manage.py test core.api.tests.CommonApiTest core.tests.ShellTest`
Expected: FAIL. 404, `감사 기록` 없음

- [ ] **Step 3: 구현한다**
  - `visible_nav`의 조건을 `perm is None or (perm(user) if callable(perm) else user.has_perm(perm))`으로 바꾼다.
  - `grouped_app_list`는 권한 칸을 쓰지 않으므로 고치지 않는다.
  - 감사 기록의 `model` 키가 허용 목록에 없으면 404를 낸다.
  - `old`·`new`는 `str()`로 바꾼다. None은 `''`로 둔다.

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `.\.venv\Scripts\python manage.py test core`
Expected: OK

- [ ] **Step 5: 커밋**

```bash
git add core/audit.py core/api/views.py core/api/urls.py core/api/tests.py core/nav.py core/tests.py config/urls.py
git commit -m "feat: 검색·품번 찾기·개정 이력 확정·감사 기록 API와 감사 기록 메뉴를 추가한다"
```

---

### Task 6: 앱 틀 — 오류 풀기, 명령창(Ctrl+K), 최근 연 기록, 밀도 CSS

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/lib/recent.ts`
- Create: `frontend/src/components/CommandPalette.tsx`
- Create: `frontend/src/app.css`
- Modify: `frontend/src/main.tsx` (`import './app.css'`)
- Modify: `frontend/src/layout/AppLayout.tsx`
- Test: `scripts/e2e_browser.py`

**Interfaces:**
- Consumes: Task 5 `GET /api/search/`
- Produces:
  - **`client.ts`:**
    - `class ApiError extends Error { status: number; detail: string; fields: Record<string, string[]>; body: any }`
    - 본문에 `detail`이 없는 DRF 직렬화 오류(`{name: ['…']}`)는 `fields`로 쓴다. `detail`은 첫 메시지다.
    - 기존 `ApiError(status, detail, fields)` 호출부는 그대로 동작해야 한다.
  - **`recent.ts`:**
    - `type Recent = { label: string; href: string }`
    - `addRecent(r: Recent): void` — 맨 앞에 두고, 같은 `href`는 하나로 합치고, 최대 5개를 둔다.
    - `getRecent(): Recent[]`
    - 키는 `qms.recent`다. 모든 읽기·쓰기는 `try/catch`로 감싸고, 실패하면 `[]`다.
  - **`CommandPalette`:** `<CommandPalette open onClose />`
    - 입력하면 250ms 뒤에 검색한다.
    - 위·아래 화살표로 고르고, Enter로 연다. `/app/`으로 시작하면 `navigate`, 아니면 `location.href`다.
    - 빈 입력이면 "최근 연 기록"을 보인다.
    - 결과가 없으면 `찾는 기록이 없습니다`를 보이고, Enter를 눌러도 아무 일도 하지 않는다.
  - **`AppLayout`:**
    - 머리에 `검색 (Ctrl+K)` 칸 모양 버튼을 둔다. `aria-label="명령창 열기"`다.
    - 전역 `keydown`에서 Ctrl/⌘+K를 받아 연다.
    - 사이드바 맨 위에 "최근 연 기록" 묶음을 둔다. 비면 숨긴다.
    - `MOVED`에 `'/admin/qms/inspectionspec/': '/app/specs'`를 더한다.
  - **`app.css` 클래스:**
    - `.page-title`: 24px
    - `.prop-grid`: 두 열의 "이름 : 값", 14px
    - `.grid-table`: 14px, 얇은 구분선
    - 비교 표시: `.diff-changed`(배경 `--warning` 계열 옅은 색), `.diff-added`, `.diff-removed`(취소선)
    - `.cell-error`: 빨간 테두리
    - 색은 `theme.ts`의 Fiori 값으로 정하고 다크 모드 값도 둔다.

- [ ] **Step 1: 실패하는 브라우저 점검을 쓴다** — 기존 `세션 끊김` 점검 앞에 넣는다.

```python
manage('shell', '-c', "from core.models import Item, Lot; i=Item.objects.create(code='E2E-R1', name='E2E 양극재', item_type='RAW'); Lot.objects.create(number='RAW-2611-001', item=i)")
page.goto('/app/todo')
page.keyboard.press('Control+k')
page.get_by_placeholder('LOT·품번·번호 또는 동작').fill('2611')
page.locator('[data-palette-item]').first.wait_for()
page.keyboard.press('Enter')
page.wait_for_url('**/trace/?lot=RAW-2611-001')
check('명령창: LOT 일부 + Enter → 그 기록', '/trace/?lot=RAW-2611-001' in page.url, page.url)

page.goto('/app/todo')
page.keyboard.press('Control+k')
page.get_by_placeholder('LOT·품번·번호 또는 동작').fill('없는번호-zz')
page.get_by_text('찾는 기록이 없습니다').wait_for()
page.keyboard.press('Enter'); page.wait_for_timeout(300)
check('명령창 결과 없음 Enter → 이동 안 함', page.url.endswith('/app/todo'), page.url)   # Review Focus 5

ctx2 = browser.new_context(base_url=BASE, storage_state=page.context.storage_state())
ctx2.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked') }})")
p2 = ctx2.new_page(); p2.goto('/app/todo')
try:
    p2.locator('[data-widget]').first.wait_for(); ok = True
except Exception:
    ok = False
check('localStorage 차단에도 화면 정상', ok)                                                 # Review Focus 4
ctx2.close()
```

- [ ] **Step 2: 점검을 돌려 실패를 확인한다**

Run: `python scripts\e2e_browser.py`
Expected: 새 점검 3개가 FAIL이다(명령창 입력칸이 없다). 기존 8개는 PASS다.

- [ ] **Step 3: 위 Interfaces대로 구현하고 빌드한다**

Run: `cd frontend; npm run build`
Expected: 오류 없이 `dist/` 생성

- [ ] **Step 4: 점검을 돌려 통과를 확인한다**

Run: `python scripts\e2e_browser.py`
Expected: `11/11 통과`

- [ ] **Step 5: 커밋**

```bash
git add frontend/src frontend/dist scripts/e2e_browser.py
git commit -m "feat: React 화면에 Ctrl+K 명령창·최근 연 기록·필드 오류 풀기를 추가한다"
```

---

### Task 7: 데이터 목록 부품과 검사기준 목록

**Files:**
- Create: `frontend/src/api/specs.ts`
- Create: `frontend/src/components/DataList.tsx`
- Create: `frontend/src/pages/specs/SpecList.tsx`
- Modify: `frontend/src/main.tsx` (AppLayout 안에 `specs` 경로)
- Test: `scripts/e2e_browser.py`

**Interfaces:**
- Consumes: Task 4 `GET /api/qms/specs/`, `POST /api/qms/specs/`, Task 5 `GET /api/items/`
- Produces:
  - **`specs.ts`:** 타입 `SpecRow`, `SpecDetail`, `CharRow`, `RevLog`, `DocStruct`는 Task 4 응답 칸 이름 그대로다.
  - **`DataList<T>` props:**
    - `columns`: antd `ColumnsType<T>`
    - `tabs: {key, label}[]`
    - `fetchPage(tab, q, page): Promise<{count, has_more, results: T[]}>`
    - `exportHref(tab, q): string`
    - `peek?: (row: T) => ReactNode`
    - `onOpen(row: T)`
    - `toolbar?: ReactNode`
    - `rowKey`
  - **`DataList` 동작:**
    - 탭·검색 칸(300ms 지연)·"엑셀로" 링크(`download`)를 둔다.
    - "더 보기"는 다음 쪽을 이어 붙인다. `count`도 표시한다.
    - 줄을 누르면 오른쪽 `Drawer` 미리보기가 열린다. 안에 "전체 화면으로" 버튼이 있다.
    - 표에는 `data-row` 속성을 단다.
  - **`SpecList`:**
    - 탭: `전체 / 초안 / 승인됨 / 유효본만` (`all/draft/approved/current`)
    - 열은 스펙 5.1과 같다.
    - 미리보기: 머리 정보와 검사항목 이름 목록
  - **"새 기준서" 창:**
    - 품번 고르기: `Select showSearch`, `/api/items/`, `notFoundContent='찾는 품번이 없습니다'`
    - 검사 구분 고르기
    - 만들면 `/app/specs/:id`로 간다.
    - 409면 `이미 있는 검사기준입니다.` 안내와 "그 기준서 열기" 버튼(`existing`)을 보인다.

- [ ] **Step 1: 실패하는 브라우저 점검을 쓴다**

```python
page.goto('/app/specs')
page.get_by_role('button', name='새 기준서').click()
page.get_by_label('품번').fill('E2E-R1')
page.locator('.ant-select-item-option', has_text='E2E-R1').click()
page.get_by_label('검사 구분').click()
page.locator('.ant-select-item-option', has_text='수입검사').click()
page.get_by_role('button', name='만들기').click()
page.wait_for_url('**/app/specs/*')
spec_id = page.url.rstrip('/').split('/')[-1]
check('새 기준서 → Rev.1 초안 페이지', api_get(page, f'/api/qms/specs/{spec_id}/')['revision'] == 1, page.url)

page.goto('/app/specs')
page.locator('[data-row]').first.wait_for()
want = api_get(page, '/api/qms/specs/?tab=all')['count']
check('검사기준 목록 줄 수가 API와 같음', page.locator('[data-row]').count() == want, f'API {want}')
with page.expect_download() as dl:
    page.get_by_role('link', name='엑셀로').click()
check('목록 엑셀로 받기', open(dl.value.path(), 'rb').read(2) == b'PK', dl.value.suggested_filename)
```

- [ ] **Step 2: 점검을 돌려 실패를 확인한다**

Run: `python scripts\e2e_browser.py`
Expected: 새 점검 3개가 FAIL이다(`/app/specs`가 `/app/todo`로 돌아간다).

- [ ] **Step 3: 구현하고 빌드한다**

Run: `cd frontend; npm run build`
Expected: 성공

- [ ] **Step 4: 점검을 돌려 통과를 확인한다**

Run: `python scripts\e2e_browser.py`
Expected: `14/14 통과`

- [ ] **Step 5: 커밋**

```bash
git add frontend/src frontend/dist scripts/e2e_browser.py
git commit -m "feat: 데이터 목록 부품과 검사기준 목록·새 기준서 화면을 추가한다"
```

---

### Task 8: 기록 페이지 — 편집 표·저장 띠·승인 서명·새 개정·개정 이력 탭·비교

**Files:**
- Create: `frontend/src/lib/tsv.ts`
- Create: `frontend/src/components/RecordPage.tsx`, `EditGrid.tsx`, `SaveBar.tsx`, `SignModal.tsx`
- Create: `frontend/src/pages/specs/SpecPage.tsx`
- Modify: `frontend/src/main.tsx` (`specs/:id`)
- Test: `scripts/e2e_browser.py`

**Interfaces:**
- Consumes: Task 4 상세·PUT·new-revision·approve·revision-log, Task 5 revision-log approve, Task 6 `addRecent`, `ApiError.fields`
- Produces:
  - **`parseTsv(text: string): string[][]`**
    - `\r\n`과 `\n`으로 줄을 나눈다. 끝의 빈 줄은 버린다.
    - 큰따옴표로 감싼 칸 안의 탭·줄바꿈·`""`는 엑셀 규칙대로 푼다.
  - **`RecordPage` props:**
    - `title`, `status: '초안'|'승인됨'|'잠김'`
    - `actions: ReactNode`(머리 버튼 줄)
    - `props: {label, node}[]`(속성 블록)
    - `children`(본문)
    - `side: {key, label, node}[]`(오른쪽 탭)
  - **`EditGrid` props:**
    - `columns: {key, label, kind: 'text'|'number'|'select'|'link', options?: {value, label}[], width?}[]`
    - `rows: GridRow[]`, `onChange(rows)`, `readOnly`
    - `errors: Record<string, string[]>` — 키는 `characteristics.{i}.{field}`
    - `diff?`: Task 4 `diff`
  - **`GridRow` 칸:** `{_key: string, id: number|null, delete?: boolean, ...값}`
  - **`EditGrid` 동작:**
    - 칸은 `<input>`이다.
    - Tab은 오른쪽 칸으로, Enter는 아래 칸으로 간다.
    - 맨 아래 빈 줄에 쓰면 새 줄이 생긴다.
    - 붙여 넣기(`onPaste`)는 누른 칸부터 `parseTsv` 결과를 채운다. 줄이 모자라면 새로 만든다.
    - 휴지통 버튼을 누르면 `delete: true`가 되고 취소선이 그어진다. 다시 누르면 되돌린다.
    - 선택 칸은 antd `Select showSearch`이고 `placeholder='선택'`이다.
    - 오류 칸에는 `.cell-error`와 메시지 툴팁을 단다.
    - 표에는 `data-grid` 속성을, 줄에는 `data-grid-row` 속성을 단다.
  - **`SaveBar`:** 고친 것이 있을 때만 바닥에 붙는다.
    - 문구: `변경 {n}건`
    - 버튼: `저장 (Ctrl+S)`, `취소`
    - Ctrl+S로도 저장한다.
    - 409를 받으면 서버 문구와 "다시 불러오기" 버튼을 보인다.
  - **`SignModal` props:**
    - `title`, `withLog?: {prefill: string}` — "승인하며 이력 남기기" 체크와 변경 내용·사유 칸
    - `onSubmit(password, log?)`
    - 비밀번호 칸 라벨은 `비밀번호`다. 서버 오류는 창 안에 보인다.
  - **`SpecPage` 머리 버튼 줄:**
    - `저장`(SaveBar)
    - `새 개정`: 승인본일 때. `new-revision` 후 `navigate`한다.
    - `승인 서명`: `can_approve`일 때
    - `이력 남기기`: 초안일 때. 미리 채운 내용과 사유를 받는 창을 연다.
    - `이전 개정과 비교`: `prev_id`가 있을 때 켜고 끈다.
    - `내보내기 ▾`: `.xlsx`(document 링크), `PDF`(`/app/specs/:id/print`), 양식들(`templates`)
    - `수정 요청`: 잠겼을 때. `edit_request_url`로 간다.
  - **`SpecPage` 그 밖:**
    - 오른쪽 탭은 `개정 이력`과 `메모`다. 개정 이력 탭에는 승인자에게 `확정` 버튼(SignModal)이 보인다.
    - 메모 탭은 1묶음에서 기존 메모 화면 링크 한 줄만 둔다.
    - 페이지를 열면 `addRecent({label: title, href: '/app/specs/' + id})`를 부른다.
    - 잠긴 기준서는 모든 칸이 읽기 전용이고 `잠김` 배지가 붙는다.

- [ ] **Step 1: 실패하는 브라우저 점검을 쓴다** (Task 7에서 만든 `spec_id` 초안을 쓴다)

```python
tsv = '\n'.join(f'항목{i}\t{i},000.5\t{i + 1}\tmm' if i != 3 else f'항목{i}\t\t\t' for i in range(1, 11))
page.goto(f'/app/specs/{spec_id}')
first = page.locator('[data-grid] [data-grid-row] input').first
first.click()
page.evaluate("t => { const dt = new DataTransfer(); dt.setData('text/plain', t);"
              " document.activeElement.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true})) }", tsv)
page.get_by_text('변경 10건').wait_for()
page.keyboard.press('Control+s')
page.get_by_text('저장했습니다').wait_for()
chars = api_get(page, f'/api/qms/specs/{spec_id}/')['characteristics']
check('검사항목 10줄 붙여넣기 → 저장 → 서버 10개', len(chars) == 10 and chars[0]['lsl'] == '1000.5', f'{len(chars)}개')

page.get_by_role('button', name='승인 서명').click()
page.get_by_label('비밀번호').fill('e2e-pass-123')
page.get_by_role('button', name='서명').click()
page.get_by_text('승인됨').first.wait_for()
page.get_by_role('button', name='새 개정').click()
page.wait_for_function(f"() => !location.pathname.endsWith('/{spec_id}')")
draft_id = page.url.rstrip('/').split('/')[-1]   # Task 9 점검이 쓴다
new = api_get(page, f'/api/qms/specs/{draft_id}/')
check('승인본 → 새 개정 → Rev.2 초안, 항목 복사', new['revision'] == 2 and len(new['characteristics']) == 10, page.url)
```

- [ ] **Step 2: 점검을 돌려 실패를 확인한다**

Run: `python scripts\e2e_browser.py`
Expected: 새 점검 2개가 FAIL이다(`[data-grid]` 없음).

- [ ] **Step 3: 구현하고 빌드한다**

Run: `cd frontend; npm run build`
Expected: 성공

- [ ] **Step 4: 점검을 돌려 통과를 확인한다**

Run: `python scripts\e2e_browser.py`
Expected: `16/16 통과`

- [ ] **Step 5: 커밋**

```bash
git add frontend/src frontend/dist scripts/e2e_browser.py
git commit -m "feat: 검사기준서 기록 페이지(편집 표·붙여넣기·저장·승인·새 개정·개정 이력)를 추가한다"
```

---

### Task 9: A4 인쇄 화면(PDF)과 감사 기록 화면

**Files:**
- Create: `frontend/src/components/DocumentView.tsx`
- Create: `frontend/src/pages/specs/SpecPrint.tsx`
- Create: `frontend/src/pages/AuditLog.tsx`
- Modify: `frontend/src/main.tsx` (`specs/:id/print`는 AppLayout 밖, `audit`는 안)
- Modify: `frontend/src/app.css` (인쇄 규칙)
- Test: `scripts/e2e_browser.py`

**Interfaces:**
- Consumes: Task 4 `GET …/document/`, Task 5 `GET /api/audit-log/`
- Produces:
  - **`<DocumentView doc={DocStruct} />`:**
    - A4 한 장의 틀이다. 다음을 그린다.
      - 제목
      - 오른쪽 위 결재란(작성·승인·일자)
      - 머리 정보 표
      - 본문 표들
      - 개정 이력 표
    - 초안이면 대각선 워터마크 `초안 — 승인 전`을 둔다. 화면에도 인쇄에도 나온다.
    - 2묶음 이후 다른 기록도 이 부품을 쓴다.
  - **인쇄 CSS:**
    - `@page { size: A4 portrait; margin: 12mm }`
    - `@media print`에서 `.print-bar`를 숨긴다.
    - 표 글자는 10pt이고, 줄은 `break-inside: avoid`다.
  - **`SpecPrint`:**
    - 위에 `.print-bar`를 둔다. 안에는 `← {제목}` 돌아가기, `인쇄 / PDF로 저장`(`window.print()`), `.xlsx 받기` 링크가 있다.
    - 그 아래에 `DocumentView`를 둔다.
  - **`AuditLog`:**
    - 모델 고르기(Select)와 기록 id 칸을 둔다.
    - 표는 `일시 · 사용자 · 구분 · 기록 · 바뀐 칸(이름: 이전 → 이후)`이다. 아래에 "더 보기"가 있다.
    - 주소 `?model=&id=`로 바로 열 수 있다.
    - 403이면 `품질팀장만 볼 수 있습니다.`를 보인다.

- [ ] **Step 1: 실패하는 브라우저 점검을 쓴다**

```python
page.goto(f'/app/specs/{spec_id}/print')
page.locator('.doc-page').wait_for()
page.emulate_media(media='print')
pdf = page.pdf(format='A4', print_background=True)
pages = pdf.count(b'/Type /Page') - pdf.count(b'/Type /Pages')
check('승인본 인쇄 화면 → PDF A4 1쪽', pages == 1, f'{pages}쪽')
page.emulate_media(media='screen')

page.goto(f'/app/specs/{draft_id}/print')   # draft_id: Task 8의 Rev.2 초안
check('초안 인쇄 화면에 "초안 — 승인 전"', page.get_by_text('초안 — 승인 전').count() >= 1)

page.goto(f'/app/audit?model=qms.inspectionspec&id={spec_id}')
page.locator('[data-audit-row]').first.wait_for()
check('감사 기록: 저장 이력이 보임', page.locator('[data-audit-row]').count() >= 2)
```

PDF 확인 방법: `page.pdf`는 headless Chromium에서만 된다. `msedge` 채널로 실행했을 때 실패하면 `PASS`로 바꾸지 말고 FAIL과 이유를 출력한다.

- [ ] **Step 2: 점검을 돌려 실패를 확인한다**

Run: `python scripts\e2e_browser.py`
Expected: 새 점검 3개가 FAIL이다.

- [ ] **Step 3: 구현하고 빌드한다**

Run: `cd frontend; npm run build`
Expected: 성공

- [ ] **Step 4: 점검을 돌려 통과를 확인한다**

Run: `python scripts\e2e_browser.py`
Expected: `19/19 통과`

- [ ] **Step 5: 커밋**

```bash
git add frontend/src frontend/dist scripts/e2e_browser.py
git commit -m "feat: 검사기준서 A4 인쇄 화면(PDF)과 감사 기록 화면을 추가한다"
```

---

### Task 10: 문서 갱신과 전체 검증

**Files:**
- Modify: `DESIGN.md` ("React 화면" 절: 14px/24px 밀도, 얇은 구분선, 비교 색, 인쇄 규칙)
- Modify: `docs/business-rules.md`
  - 새 절 "개정 이력(RevisionLog)": 신청 → 승인자 비밀번호 확정 → 확정 후 수정·삭제 불가, `core/models.py`·`core/rules.py`
  - §3에 "검사기준 저장은 `qms.rules.save_spec`(admin과 같은 잠금)"을 더한다.
  - §11에 "감사 기록 화면은 품질팀장·관리자만, personal 제외"를 더한다.
- Modify: `docs/testing.md` (단위 테스트 수·e2e_browser 19개와 점검 목록·새 테스트 파일 클래스)
- Modify: `README.md` (검사기준서 새 화면 `/app/specs`, 감사 기록, 문서 내보내기 사용법)
- Modify: `docs/architecture.md` (`core/export.py`, `core/audit.py`, `qms/api/specs.py`, `RevisionLog`)

**Interfaces:**
- Consumes: Task 1~9 결과
- Produces: 없음

- [ ] **Step 1: 전체 검증을 실행하고 실제 숫자를 받는다**

Run:
- `.\.venv\Scripts\python manage.py test`
- `.\.venv\Scripts\python scripts\e2e_check.py`
- `python scripts\e2e_browser.py`
- `.\.venv\Scripts\python manage.py makemigrations --check --dry-run`

Expected:
- 테스트: `OK`, 수가 215보다 많다.
- e2e_check: 기존 76개 모두 통과
- e2e_browser: `19/19 통과`
- 마이그레이션 점검: `No changes detected`

- [ ] **Step 2: 위 문서에 Step 1의 실제 숫자와 새 동작을 적는다**

숫자는 Step 1 출력 그대로 쓴다. 실행하지 못한 점검이 있으면 문서와 보고에 그대로 적는다.

- [ ] **Step 3: 커밋**

```bash
git add DESIGN.md docs/business-rules.md docs/testing.md README.md docs/architecture.md
git commit -m "docs: 검사기준서 새 화면·개정 이력·감사 기록·문서 내보내기를 문서에 반영한다"
```

---

## 남은 위험 (실행 전에 알아 둘 것)

- **운영 DB:** 마이그레이션 `0009`는 새 테이블만 만든다. 그래도 운영 DB에 적용하기 전에는 `backup`을 실행한다(AGENTS.md). 이 계획은 운영 DB에 적용하지 않는다.
- **번들 크기:** JS 번들은 이미 860 kB다. 화면이 늘면 더 커진다. 경로별 나눠 싣기(`React.lazy`)는 이 계획에 넣지 않았다.
- **시스템 관리자 예외:** 서버는 기존대로 승인된 기록을 관리자가 고칠 수 있게 둔다(`can_edit_locked`). React 화면만 읽기 전용으로 보인다(판정 8).
