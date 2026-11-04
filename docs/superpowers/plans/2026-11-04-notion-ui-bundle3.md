# 업무 화면 재설계 3묶음 (기준정보: 품번·BOM·라우팅·공정·관리계획서·고객사별 8D 기한·엑셀 일괄 등록) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기준정보 메뉴 다섯 개(품번·BOM·라우팅, 공정, 관리계획서, 고객사별 8D 기한, 엑셀 일괄 등록)를 admin 기본 화면에서 React 새 화면으로 옮긴다. 관리계획서는 문서 출력(.xlsx·PDF)까지 만든다.

**Architecture:**
- **규칙은 손대지 않는다.** 저장은 모델 `full_clean()`·`save()`와 `core.rules.save_with_lock`을 거친다. 승인 잠금(`Approvable.save`, `ControlPlanLine.save`)과 "기록 삭제는 시스템 관리자만"(`BaseAdmin.has_delete_permission`)을 API도 그대로 지킨다.
- **하위 항목 표 저장은 한 함수로 모은다.** 새 `core/grid.py collect_rows()`가 줄 목록(추가·변경·삭제 표시)을 검증해 나눈다. BOM·라우팅·관리계획서 항목·공정 표·8D 기한 표가 모두 이것을 쓴다. 검사기준서의 `save_spec`은 바꾸지 않는다(리팩터링 금지).
- **admin 동작과 API는 같은 함수를 부른다.** 관리계획서의 "검사기준 초안 만들기"(`ControlPlanAdmin.make_specs`) 본문을 `qms.rules.make_specs_from_plan`으로 옮긴다. 엑셀 일괄 등록은 기존 `core.importer.run_import`를 그대로 쓰고, 미리보기는 같은 처리를 되돌림(rollback)으로 실행한다. 동등성 테스트로 확인한다.
- **옛 화면은 남긴다.** admin과 `/import/`는 지우지 않는다. 메뉴만 새 화면으로 잇는다(`AppLayout.tsx`의 주소 대응표).

**Tech Stack:** Django 6.1, DRF, django-simple-history, openpyxl / React 19, TypeScript, Vite, antd 6, react-router 7, @tanstack/react-query 5 / Playwright(시스템 Python, 검증 전용)

**Spec:** `docs/superpowers/specs/2026-11-03-notion-style-frontend-design.md` (P2~P7, 4장 표 "기준정보 및 시스템 관리" 줄, 8장 3번 묶음)

## Global Constraints

- 새 의존성 금지: `requirements.txt`, `frontend/package.json`을 바꾸지 않는다. 외부 CDN·폰트·아이콘을 로드하지 않는다.
- 마이그레이션 없음. `makemigrations --check --dry-run`은 `No changes detected`여야 한다.
- 새 권한·역할을 만들지 않는다. 쓰는 권한은 아래 "권한" 표에 있는 것뿐이다.
- 업무 규칙(`docs/business-rules.md`)을 바꾸지 않는다. 화면이 아니라 서버가 막는다.
- 기록(품번·공정·관리계획서·고객사 8D 기한) 자체의 삭제는 시스템 관리자(`is_superuser`)만 한다. 하위 줄(BOM·라우팅·관리계획서 항목) 삭제는 admin 인라인과 같게 `delete_<모델>` 권한으로 한다.
- 화면 문구·오류 메시지·커밋 메시지는 한국어로 쓴다. antd 영어 기본 문구를 남기지 않는다.
- 다운로드 형식은 `?export=xlsx`로 고른다(`?format=`는 DRF가 가로챈다).
- API 400 응답 모양은 `{'detail': 글, 'fields': {...}}`다. 줄 오류 키는 `<표>.<줄 번호>.<칸>`이다(예: `bom.2.qty`). 동시 수정은 409 `다른 사람이 먼저 고쳤습니다. 다시 불러오세요.`, 잠금은 409(`core.rules.Locked`)다.
- 초안 표시 문구는 정확히 `초안 — 승인 전`이다(`core/export.py DRAFT_MARK`).
- 작업 브랜치는 `notion-ui-bundle3`이다(master `3bbdf05`에서 분기).
- `git add` 금지: `data/`, `.superpowers/`, `.venv/`.
- 커밋은 한국어 Conventional Commits로 쓰고 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`를 붙인다.
- React를 바꾼 태스크는 `cd frontend; npm run build`(tsc 포함)를 통과시키고 `frontend/dist/`를 다시 만들어 같은 커밋에 넣는다.
- 작업 파일은 CRLF다. 고친 뒤 줄바꿈 형식을 바꾸지 않는다.

## 권한

| 화면·동작 | 필요한 권한 |
| --- | --- |
| 품번 목록·페이지·엑셀 | `core.view_item` |
| 새 품번 | `core.add_item` |
| 품번 저장 | `core.change_item` + 바뀐 줄 종류에 따라 `core.add_/change_/delete_bomline`, `core.add_/change_/delete_routingstep` |
| 공정 표 조회·저장 | `core.view_process` / `core.add_process`(새 줄)·`core.change_process`(고친 줄) / 줄 삭제는 `is_superuser` |
| 고객사별 8D 기한 표 | 위와 같은 방식으로 `qms.*_customerrule` |
| 관리계획서 조회·엑셀·문서 | `qms.view_controlplan` |
| 새 관리계획서·새 개정 | `qms.add_controlplan` |
| 관리계획서 저장 | `qms.change_controlplan` + `qms.add_/change_/delete_controlplanline` |
| 승인 서명 | `is_approver` (`core.rules.approve`가 검사) |
| 검사기준 초안 만들기 | `qms.add_inspectionspec` |
| 엑셀 일괄 등록 | 설정 목록 `core.view_importprofile`, 미리보기·확정은 대상 모델의 add+change (`core.views.import_view`와 같다) |

## 설계 판정 (스펙이 열어 둔 것)

1. **API 주소:** core 기준정보는 `/api/core/…`, qms는 기존처럼 `/api/qms/…`에 둔다. 기존 `/api/items/`(품번 찾기)는 그대로 둔다.
2. **품번 페이지:** 속성(품번·품명·구분) + 편집 표 두 개(BOM, 라우팅). 한 번의 저장 요청에 셋을 담고 한 트랜잭션에서 처리한다. 품번은 승인 대상이 아니라 잠금이 없다.
3. **공정·고객사 8D 기한:** 목록 자체가 편집 표다(P4). 페이지를 따로 만들지 않는다. 동시 수정 번호는 그 모델 이력 전체의 최대 `history_id`다.
4. **줄 순서 맞바꾸기:** 라우팅 `순서`나 BOM `자품번`이 저장 요청 안에서 겹치면 그 줄에 `같은 값이 두 번 있습니다.`를 낸다. 두 줄의 순서를 한 번에 맞바꾸면 DB 고유 제약(`uniq_routing_seq`)에 걸린다. 이때 400 `순서를 맞바꿀 때는 두 번에 나눠 저장하세요.`로 바꾼다. `shortcut:` 주석을 단다.
5. **관리계획서 새 개정:** 검사기준서와 같다. 같은 품번·단계에 미승인 개정이 있으면 그 초안을 연다. 없으면 같은 품번·단계의 최신 승인본 항목을 모두 복사해 Rev+1을 만든다. admin에는 이 동작이 없으므로 동등성 테스트 대상이 아니다.
6. **관리계획서 비교:** 항목은 (공정 코드, 특성) 쌍으로 짝짓는다. 비교 칸은 특성·공정을 뺀 모든 입력 칸이다.
7. **AP(조치 우선순위):** 편집 표에는 넣지 않는다(계산 값이라 고칠 칸이 아니다). 문서 출력 표의 마지막 열로 넣는다.
8. **관리계획서 문서는 A4 가로다.** 열이 15개라 세로에는 들어가지 않는다. 문서 구조에 `'landscape': True`를 더하고, `document_xlsx`와 React 인쇄 화면이 이를 따른다. 이 키가 없는 기존 문서(검사기준서·성적서)는 지금처럼 세로다.
9. **엑셀 일괄 등록 확정:** 서버는 상태를 저장하지 않는다. 화면이 미리보기 때 고른 파일을 확정 때 다시 보낸다. 확정도 `run_import`이므로, 그 사이 데이터가 바뀌어 오류가 생기면 전부 되돌리고 오류를 보인다.
10. **사용처(where-used), 즐겨찾기, 품번 일괄 삭제는 이 묶음에 넣지 않는다.**

## Review Focus

1. **라우팅 두 줄의 순서를 맞바꿔 한 번에 저장:** 500이 아니라 400과 `순서를 맞바꿀 때는 두 번에 나눠 저장하세요.`가 나오고 아무것도 바뀌지 않는다 → Task 2 `test_routing_swap_rejected_cleanly`
2. **엑셀에서 붙여 넣은 소요량 `1,000`과 공백:** `1000`으로 저장된다. `abc`는 그 칸에 오류가 난다 → Task 1 `test_number_cells`
3. **승인된 관리계획서의 항목을 API로 고침:** 409 잠금, 아무것도 안 바뀜 → Task 4 `test_approved_plan_locked`
4. **엑셀 일괄 등록 미리보기:** 모든 줄이 맞아도 DB에 아무것도 남지 않는다 → Task 5 `test_preview_writes_nothing`
5. **품번 표에서 참조 중인 공정을 지우려는 관리자:** `ProtectedError`가 500이 아니라 409와 한국어 메시지로 나온다(기존 `core/api/exceptions.py` 처리) → Task 3 `test_delete_used_process`

---

### Task 1: 공용 표 저장 도구

**Files:**
- Create: `core/grid.py`
- Modify: `core/rules.py` (`Stale` 이동), `qms/rules.py` (`Stale`을 `core.rules`에서 가져오기만)
- Test: `core/tests_grid.py`

**Interfaces:**
- Produces:
  - `core.rules.Stale(Exception)` — 기본 메시지 `다른 사람이 먼저 고쳤습니다. 다시 불러오세요.`. `qms.rules`는 `from core.rules import Stale`로 다시 내보내 기존 `from qms.rules import Stale`이 그대로 동작한다.
  - `core.grid.clean_number(v) -> str | None` — 앞뒤 공백·천 단위 쉼표 제거, 빈 글은 `None`.
  - `core.grid.collect_rows(rows: list, own: dict[int, Model], make: Callable[[], Model], fields: dict[str, str], prefix: str, exclude: list[str] = (), unique: tuple[str, ...] = ()) -> tuple[list, list, list, dict]` — 돌려주는 값은 `(new, changed, deleted, errors)`.
    - `fields`의 값은 `'text' | 'number' | 'fk' | 'int'`. `fk`는 `<칸>_id`에 넣는다(빈 값은 `None`). `number`는 `clean_number`를 거친다. `int`는 정수가 아니면 그 칸 오류 `정수를 입력하세요.`.
    - `id`가 `own`에 없으면 `{prefix}.{i}.id: ['다른 기록의 항목입니다.']`.
    - `delete: true`이면 `deleted`로. 새 줄인데 모든 칸이 비었으면 건너뛴다.
    - 각 객체에 `full_clean(exclude=exclude, validate_constraints=False)`를 부르고 오류를 `{prefix}.{i}.{칸}`에 담는다.
    - `unique`에 적힌 칸이 남는 줄(삭제 제외) 사이에서 겹치면 겹친 뒤쪽 줄에 `같은 값이 두 번 있습니다.`.
  - `core.grid.table_version(model, **filters) -> int` — `model.history.filter(**filters)`의 최대 `history_id`, 없으면 0.
  - `core.grid.record_version(obj, children: list[tuple[type[Model], str]]) -> int` — `obj.history`와 각 `(자식 모델, fk 칸 이름)`의 이력(`{fk}_id=obj.pk`) 중 최대 `history_id`.

- [ ] **Step 1: 실패하는 테스트 작성** (`core/tests_grid.py`, `BomLine`·`Item`으로 검사)
  - `test_number_cells`: `qty: ' 1,000 '` → 새 줄의 `qty == Decimal('1000')`; `qty: 'abc'` → `errors['bom.1.qty']` 존재.
  - `test_foreign_id_rejected`: 다른 품번의 BomLine pk → `errors['bom.0.id'] == ['다른 기록의 항목입니다.']`.
  - `test_blank_and_delete`: 빈 새 줄은 무시, `{'id': x, 'delete': True}` → `deleted == [x 객체]`.
  - `test_duplicate_in_request`: 같은 `component` 두 줄 → `errors['bom.1.component'] == ['같은 값이 두 번 있습니다.']`.
  - `test_versions`: 품번 저장 뒤 `record_version(item, [(BomLine, 'parent')])`가 커지고, BomLine 추가 뒤 다시 커진다.
  - `test_stale_reexport`: `from qms.rules import Stale; from core.rules import Stale as S2; assert Stale is S2`.
- [ ] **Step 2: 실패 확인** — `.venv/Scripts/python manage.py test core.tests_grid` → ImportError.
- [ ] **Step 3: 구현** — 위 시그니처대로. `qms.rules`의 `Stale` 클래스 정의를 지우고 import로 바꾼다. `qms/api/specs.py`는 고치지 않는다.
- [ ] **Step 4: 통과 확인** — `manage.py test core.tests_grid qms.tests_rules qms.api` → OK.
- [ ] **Step 5: 커밋** — `feat: 하위 항목 표 저장을 검증하는 공용 도구를 더한다`

### Task 2: 품번 API (목록·새 품번·상세·BOM·라우팅 저장)

**Files:**
- Create: `core/api/master.py`
- Modify: `core/rules.py` (`save_item`), `core/api/urls.py`
- Test: `core/api/tests_master.py`

**Interfaces:**
- Consumes: Task 1 `collect_rows`, `record_version`, `Stale`.
- Produces:
  - `core.rules.save_item(item, user, data: dict, bom: list, routing: list, version: int | None) -> Item`
    - 속성 `code`·`name`·`item_type`(`data`에 있는 것만), BOM 칸 `{'component': 'fk', 'qty': 'number'}`(unique `component`, prefix `bom`), 라우팅 칸 `{'seq': 'int', 'process': 'fk'}`(unique `seq`, prefix `routing`).
    - 권한은 위 "권한" 표. 부족하면 `PermissionDenied('이 작업을 할 권한이 없습니다.')`.
    - 저장 순서: 지울 줄 삭제 → 품번 `full_clean()`·`save_with_lock` → 고친 줄·새 줄 저장. 줄 저장의 `IntegrityError`는 `ValidationError({'routing': ['순서를 맞바꿀 때는 두 번에 나눠 저장하세요.']})`(BOM이면 `bom` 키에 `같은 자품번이 이미 있습니다.`)로 바꾼다.
  - API (모두 `schema = None`, `require_perm` 사용):
    - `GET /api/core/items/?tab=all|RAW|SEMI|FIN&q=&page=` → `{count, page, has_more, results: [{id, code, name, item_type, item_type_display, bom_count, routing_count}]}`, 50줄씩, `code` 순. `q`는 품번·품명 부분 일치. `?export=xlsx` → 열 `['품번', '품명', '구분', 'BOM 수', '라우팅 수']`, 파일명 `품번.xlsx`.
    - `POST /api/core/items/` `{code, name, item_type}` → 201 상세. 모델 검증 오류는 400 `fields`.
    - `GET /api/core/items/<pk>/` → `{id, title, code, name, item_type, version, editable, can_delete_rows: {bom, routing}, bom: [{id, component, qty}], routing: [{id, seq, process}], item_options: [{value, label}] (자기 자신 제외), process_options: [{value, label}], type_options: [{value, label}]}`. `qty`는 Task 1과 같은 숫자 글(`1`, `0.25`).
    - `PUT /api/core/items/<pk>/` `{code?, name?, item_type?, bom: [...], routing: [...], version}` → 상세. `Stale` → 409.

- [ ] **Step 1: 실패하는 테스트 작성** (`core/api/tests_master.py`, 클래스 `ItemApiTest`)
  - `test_list_tabs_search_export`: RAW 1·FIN 1 → `tab=RAW` count 1; `q=` 품명 일부; `export=xlsx` 응답이 xlsx이고 첫 행이 열 이름.
  - `test_create_and_duplicate`: 201; 같은 code 다시 → 400, `fields.code` 있음.
  - `test_save_bom_routing`: BOM 2줄·라우팅 2줄 저장 → DB에 그대로; 한 줄 `delete` → 사라짐; 이력(`BomLine.history`) 남음.
  - `test_row_error_saves_nothing`: 라우팅 한 줄 `seq: 'x'` → 400 `fields['routing.1.seq']`, 품명 변경도 저장 안 됨.
  - `test_routing_swap_rejected_cleanly`: 10/20 두 줄을 20/10으로 → 400 `순서를 맞바꿀 때는 두 번에 나눠 저장하세요.`, DB 그대로.
  - `test_stale_version`: 다른 저장 뒤 옛 `version`으로 PUT → 409.
  - `test_permissions`: `view_item`만 있는 사용자 PUT → 403; `change_item`만 있고 `add_bomline` 없이 BOM 줄 추가 → 403.
- [ ] **Step 2: 실패 확인** — `manage.py test core.api.tests_master` → 404/ImportError.
- [ ] **Step 3: 구현** — `core/api/urls.py`에 `path('core/items/', …)`, `path('core/items/<int:pk>/', …)`. 목록 숫자는 `annotate(Count('bom_lines', distinct=True), Count('routing', distinct=True))`. 엑셀은 `core.export.table_xlsx`·`xlsx_response`.
- [ ] **Step 4: 통과 확인** — `manage.py test core` → OK.
- [ ] **Step 5: 커밋** — `feat: 품번·BOM·라우팅 API를 더한다`

### Task 3: 공정 표·고객사별 8D 기한 표 API

**Files:**
- Modify: `core/rules.py` (`save_table`), `core/api/master.py`, `core/api/urls.py`, `qms/api/views.py`, `qms/api/urls.py`
- Test: `core/api/tests_master.py` (`ProcessApiTest`), `qms/api/tests.py` (`CustomerRuleApiTest`)

**Interfaces:**
- Consumes: Task 1 `collect_rows`, `table_version`, `Stale`.
- Produces:
  - `core.rules.save_table(model, user, rows: list, fields: dict, unique: tuple, version: int | None) -> None` — 모델 전체를 한 표로 저장한다. 권한: 새 줄 `add_`, 고친 줄 `change_`, 지운 줄 `is_superuser`(아니면 `PermissionDenied('시스템 관리자만 삭제할 수 있습니다.')`). prefix는 `rows`. 삭제는 `core.rules.delete_as`.
  - `GET/PUT /api/core/processes/` — 칸 `{'code': 'text', 'name': 'text'}`, unique `code`. GET → `{version, editable, can_delete, rows: [{id, code, name}]}`(`code` 순). `?export=xlsx` → 열 `['공정 코드', '공정명']`, 파일명 `공정.xlsx`. PUT `{rows, version}` → GET과 같은 모양.
  - `GET/PUT /api/qms/customer-rules/` — 칸 `{'customer': 'text', 'containment_hours': 'int', 'corrective_days': 'int'}`, unique `customer`. 엑셀 열 `['고객사', '봉쇄(D3) 기한(시간)', '대책(D5) 기한(일)']`, 파일명 `고객사별 8D 기한.xlsx`.

- [ ] **Step 1: 실패하는 테스트 작성**
  - `ProcessApiTest.test_add_edit`: 두 줄 추가 → 2개; 하나 이름 변경 → 바뀜; 오래된 `version` → 409.
  - `ProcessApiTest.test_delete_superuser_only`: 일반 사용자(`change_process`·`delete_process` 있음) 삭제 → 403, 남아 있음; 관리자 → 지워짐.
  - `ProcessApiTest.test_delete_used_process`: 라우팅이 쓰는 공정을 관리자가 삭제 → 409(기존 `ProtectedError` 처리), 남아 있음.
  - `CustomerRuleApiTest.test_save_and_export`: 고객사 1줄 저장, `containment_hours: '하루'` → 400 `fields['rows.0.containment_hours']`; `export=xlsx` 첫 행 열 이름.
- [ ] **Step 2: 실패 확인** — 해당 테스트 → 404.
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — `manage.py test core qms.api` → OK.
- [ ] **Step 5: 커밋** — `feat: 공정·고객사별 8D 기한 표 API를 더한다`

### Task 4: 관리계획서 API (목록·상세·저장·새 개정·승인·개정 이력·문서·검사기준 초안)

**Files:**
- Create: `qms/api/plans.py`
- Modify: `qms/rules.py`, `qms/models.py` (`ControlPlan.document`), `qms/admin.py` (`make_specs`가 공용 함수 호출), `qms/api/urls.py`, `core/export.py` (`landscape`)
- Test: `qms/api/tests_plans.py`

**Interfaces:**
- Consumes: Task 1 `collect_rows`, `record_version`, `Stale`; 기존 `core.rules.approve`, `approve_and_log`, `request_revision_log`, `qms.api.specs._log`, `core.export.document_xlsx`.
- Produces (`qms/rules.py`):
  - `plan_version(plan) -> int` = `record_version(plan, [(ControlPlanLine, 'plan')])`.
  - `PLAN_FIELDS = {'process': 'fk', 'characteristic': 'text', 'special': 'text', 'lsl': 'number', 'usl': 'number', 'unit': 'text', 'method': 'text', 'sampling': 'text', 'inspection_type': 'text', 'reaction': 'text', 'failure_mode': 'text', 'severity': 'int', 'occurrence': 'int', 'detection': 'int'}`
  - `save_plan(plan, user, data, lines, version) -> ControlPlan` — 속성은 `stage`만(품번·개정은 읽기 전용). prefix `lines`. 줄 삭제는 `child_editable(plan, user)`가 아니면 `Locked`. 저장은 `save_with_lock(plan, user, children=…)`.
  - `current_plan(item, stage) -> ControlPlan | None` — 승인된 것 중 개정번호가 가장 큰 것.
  - `open_or_new_plan_revision(plan) -> (ControlPlan, bool)` — 설계 판정 5.
  - `prev_plan(plan)`, `compare_plans(prev, cur) -> dict | None`(모양은 `compare_specs`와 같다: `{'fields': {...}, 'rows': [{id, name, status, cells, values}]}`, `name`은 `"{공정 코드} {특성}"`), `plan_diff_text(diff) -> str`(첫 제정 `최초 제정`, 변경 없음 `변경 없음`), `plan_logs(plan, confirmed_only)`.
  - `make_specs_from_plan(plan) -> list[InspectionSpec]` — `ControlPlanAdmin.make_specs`의 한 계획서분 본문을 그대로 옮긴다. 미승인이면 `ValidationError(f'{plan}: 승인 후에 만들 수 있습니다.')`. admin 동작은 이 함수를 부르고 `ValidationError`를 지금과 같은 오류 메시지로 바꾼다.
- Produces (`ControlPlan.document()`): 검사기준서와 같은 키 + `'landscape': True`. `head` = 품번·품명·단계·개정. `tables[0]` = `{'title': '관리 항목', 'columns': ['공정', '특성', '특별특성', '하한', '상한', '단위', '측정방법', '샘플링', '검사 구분', '이상 시 조치', '잠재 고장모드', 'S', 'O', 'D', 'AP']}`. `revisions` = `plan_logs(confirmed_only=True)`. `draft` = 미승인.
- Produces (`core/export.py`): `document_xlsx(doc)`가 `doc.get('landscape')`이면 `ws.page_setup.orientation = 'landscape'`.
- API (`/api/qms/plans/…`, 응답 모양은 `qms/api/specs.py`를 따른다):
  - `GET plans/?tab=all|draft|approved|current&q=&page=` — 열 `['품번', '품명', '단계', '개정', '상태', '항목 수', '승인자', '승인일']`, `export=xlsx` 파일명 `관리계획서.xlsx`.
  - `POST plans/` `{item, stage}` → 201. 같은 품번·단계가 있으면 409 `{'detail': '이미 있는 관리계획서입니다. 새 개정으로 만드세요.', 'existing': pk}`.
  - `GET/PUT plans/<pk>/` — 상세: `{id, title, item, stage, stage_display, revision, status, approved_by, approved_at, version, editable, can_approve, can_delete_rows, can_make_specs, prev_id, lines: [...PLAN_FIELDS 칸 + id], process_options, special_options, type_options(빈 값 '없음' 포함), stage_options, diff, edit_request_url}`.
  - `POST plans/<pk>/new-revision/` → `{id, created}`.
  - `POST plans/<pk>/approve/` `{password, version?, log?}` — `SpecApproveView`와 같은 처리.
  - `GET/POST plans/<pk>/revision-log/` — 미리 채움 `{'label': f'Rev.{rev}', 'changes': plan_diff_text(...)}`.
  - `GET plans/<pk>/document/` (`export=xlsx` 파일명 `{품번}_{단계}_관리계획서_Rev{n}.xlsx`).
  - `POST plans/<pk>/make-specs/` → `{'made': [{'id', 'title'}]}`. 미승인 → 400.

- [ ] **Step 1: 실패하는 테스트 작성** (`qms/api/tests_plans.py`)
  - `test_list_create_conflict`: 목록 탭 4개 숫자, 생성 201, 같은 품번·단계 409 `existing`.
  - `test_save_lines_and_errors`: 3줄 저장 OK; `lsl: '5', usl: '1'` → 400 `fields['lines.0.usl'] == ['하한이 상한보다 클 수 없습니다.']`(기존 `check_limits`가 `usl` 칸에 낸다), 아무것도 저장 안 됨.
  - `test_approved_plan_locked`: 승인 뒤 줄 변경 PUT → 409, 줄 그대로.
  - `test_new_revision_copies_and_reuses_draft`: 승인본 → 새 개정 `created=True`, 줄 수·값 같음; 다시 → 같은 id, `created=False`.
  - `test_approve_with_log_and_document`: `log` 포함 승인 → 확정 이력 1줄; 문서 `revisions` 1줄, `landscape` True, `draft` False; xlsx의 `page_setup.orientation == 'landscape'`; 미승인 문서 xlsx에 `초안 — 승인 전`.
  - `test_make_specs_same_as_admin` (동등성): 같은 승인 계획서 두 개를 만들고 하나는 admin 동작, 하나는 API로 → 생긴 검사기준의 (구분, 개정, 샘플링, 항목 이름·하한·상한·단위·특별특성) 목록이 같다. 미승인 → API 400.
  - `test_compare_plans`: 이전 개정 대비 바뀐 칸·추가·삭제 줄 표시, `plan_diff_text`에 `항목 추가:` 포함.
- [ ] **Step 2: 실패 확인** — `manage.py test qms.api.tests_plans` → 404/ImportError.
- [ ] **Step 3: 구현** — admin `make_specs`를 공용 함수 호출로 바꾼 뒤 기존 `qms/tests.py`의 make_specs 테스트(258·262행 부근)가 그대로 통과해야 한다.
- [ ] **Step 4: 통과 확인** — `manage.py test qms core` → OK.
- [ ] **Step 5: 커밋** — `feat: 관리계획서 API와 문서 출력을 더한다`

### Task 5: 엑셀 일괄 등록 API (미리보기·확정)

**Files:**
- Modify: `core/importer.py`, `core/api/master.py`, `core/api/urls.py`
- Test: `core/api/tests_master.py` (`ImportApiTest`)

**Interfaces:**
- Produces:
  - `core.importer.preview_import(profile, uploaded) -> dict` — `{'count': int, 'errors': [str], 'rows': [{'line': int, 'values': {필드: 글}}]}`. `run_import`과 같은 처리를 하되 끝에 늘 `transaction.set_rollback(True)`. `run_import`의 반환 모양 `(count, errors)`는 바꾸지 않는다(옛 `/import/` 화면이 쓴다). 두 함수는 내부 함수 하나를 함께 쓴다.
  - `GET /api/core/import/profiles/` → `[{id, name, target, target_display, header_row, mapping}]` (`core.view_importprofile`).
  - `POST /api/core/import/` multipart `{profile, file, commit: '0'|'1'}` → `commit=0`이면 `preview_import` 결과, `1`이면 `{'count', 'errors'}`. 권한은 `import_view`와 같다(대상 모델 add+change, 아니면 403). 오류가 있으면 400이 아니라 200으로 `errors`를 돌려준다(옛 화면과 같은 의미: 파일 내용 문제는 요청 실패가 아니다).

- [ ] **Step 1: 실패하는 테스트 작성**
  - `test_preview_writes_nothing`: 맞는 2줄 CSV → `count == 2`, `rows` 2개, `Item.objects.count()` 그대로.
  - `test_commit_same_as_old_view` (동등성): 같은 파일을 옛 `/import/`와 API(`commit=1`)로 각각 새 DB 상태에서 올리면 생긴 품번 (code, name, item_type) 목록이 같다.
  - `test_error_rolls_back`: 한 줄 구분이 틀린 파일 `commit=1` → `errors[0]`이 `3행:`으로 시작, 품번 0개.
  - `test_permission`: `add_item`만 있는 사용자 → 403.
- [ ] **Step 2~4:** 실패 확인 → 구현 → `manage.py test core` OK.
- [ ] **Step 5: 커밋** — `feat: 엑셀 일괄 등록 미리보기·확정 API를 더한다`

### Task 6: 품번·공정·8D 기한 화면

**Files:**
- Create: `frontend/src/api/master.ts`, `frontend/src/pages/items/ItemList.tsx`, `frontend/src/pages/items/ItemPage.tsx`, `frontend/src/pages/master/TablePage.tsx`
- Modify: `frontend/src/main.tsx`, `frontend/src/components/RecordPage.tsx` (`status`를 선택 값으로)

**Interfaces:**
- Consumes: Task 2·3 API. 기존 부품 `DataList`, `RecordPage`, `EditGrid`(`GridColumn`, `withTail`, `isBlank`, `newKey`), `SaveBar`, `api/client.ts`의 칸 오류 풀이.
- Produces: 경로 `/app/items`, `/app/items/:id`, `/app/processes`, `/app/customer-rules`.
  - `TablePage` props: `{ title: string; endpoint: string; columns: GridColumn[]; exportName: string }`. 공정과 8D 기한이 같은 부품을 쓴다.
  - `ItemPage`: 속성(품번·품명·구분 선택) + "BOM" 편집 표(자품번 선택·소요량) + "라우팅" 편집 표(순서·공정 선택). 저장 띠(`SaveBar`) 하나로 셋을 한 번에 보낸다. 409면 `SaveBar`의 다시 불러오기 문구.
  - `ItemList`: 탭 전체/원자재/반제품/완제품, 검색, 엑셀, "새 품번" 버튼(품번·품명·구분 입력 창 → 만든 뒤 페이지로 이동).
- 화면 동작은 `pages/specs/SpecPage.tsx`·`SpecList.tsx`와 같게 한다(같은 부품, 같은 키 조작: Tab·Enter·붙여넣기).

- [ ] **Step 1:** 구현.
- [ ] **Step 2:** `cd frontend; npm run build` → 성공(타입 오류 0).
- [ ] **Step 3:** `.venv/Scripts/python manage.py runserver`로 띄워 `/app/items`에서 품번 하나를 만들고 BOM 2줄을 붙여넣기로 넣어 저장되는지 직접 확인한다. 브라우저 확인을 못 했으면 보고에 그렇게 적는다.
- [ ] **Step 4: 커밋** (dist 포함) — `feat: 품번·공정·고객사별 8D 기한 새 화면을 더한다`

### Task 7: 관리계획서·엑셀 일괄 등록 화면

**Files:**
- Create: `frontend/src/api/plans.ts`, `frontend/src/pages/plans/PlanList.tsx`, `PlanPage.tsx`, `PlanPrint.tsx`, `frontend/src/pages/import/ImportPage.tsx`
- Modify: `frontend/src/main.tsx`, `frontend/src/components/DocumentView.tsx`·`PrintPage.tsx` (`landscape`이면 `@page { size: A4 landscape }`)

**Interfaces:**
- Consumes: Task 4·5 API, 기존 `SignModal`, `DocumentView`, `PrintPage`.
- Produces: 경로 `/app/plans`, `/app/plans/:id`, `/app/plans/:id/print`(앱 틀 밖, `SpecPrint`처럼), `/app/import`.
  - `PlanPage`는 `SpecPage`와 같은 머리 버튼 줄: 새 개정, 승인 서명(이력 남기기 포함), 이전 개정과 비교, 내보내기 ▾(.xlsx·PDF), 수정 요청. 더해서 승인본에 "검사기준 초안 만들기"(`can_make_specs`) → 결과 검사기준 링크 목록을 알림으로 보인다.
  - `ImportPage`: 설정 선택 → 파일 고르기 → "미리보기" → 줄 표(행 번호 + 매핑 칸) + 오류 목록 → 오류가 없고 1줄 이상일 때만 "확정" 활성 → 결과 `N건 등록했습니다.`.

- [ ] **Step 1:** 구현.
- [ ] **Step 2:** `npm run build` → 성공.
- [ ] **Step 3:** 관리계획서 인쇄 화면을 브라우저에서 열어 A4 가로로 보이는지 확인한다.
- [ ] **Step 4: 커밋** (dist 포함) — `feat: 관리계획서·엑셀 일괄 등록 새 화면을 더한다`

### Task 8: 메뉴 연결, 브라우저 점검, 문서, 전체 검증

**Files:**
- Modify: `frontend/src/layout/AppLayout.tsx` (주소 대응표), `scripts/e2e_browser.py`, `README.md`, `docs/testing.md`, `docs/architecture.md`(API 목록이 있으면), `DESIGN.md`(새 패턴이 있을 때만)

**Interfaces:**
- 주소 대응표에 더한다: `'/admin/core/item/': '/app/items'`, `'/admin/core/process/': '/app/processes'`, `'/admin/qms/controlplan/': '/app/plans'`, `'/admin/qms/customerrule/': '/app/customer-rules'`, `'/import/': '/app/import'`.

- [ ] **Step 1: `e2e_browser.py`에 점검 추가** (각각 PASS/FAIL 한 줄)
  - `품번 BOM 붙여넣기 저장`: 새 품번 → BOM 표에 2줄 TSV 붙여넣기 → 저장 → API로 BOM 2줄 확인.
  - `공정 표 줄 추가`: `/app/processes`에서 맨 아래 빈 줄에 입력 → 저장 → 새로고침 뒤 보임.
  - `관리계획서 새 개정·검사기준 초안`: 승인본에서 새 개정 → Rev+1 페이지; 승인본에서 검사기준 초안 만들기 → 링크 1개 이상.
  - `관리계획서 PDF A4 가로 1쪽`: `page.pdf(format='A4', landscape=True)`의 쪽 수 1.
  - `엑셀 일괄 등록 미리보기→확정`: 2줄 CSV → 미리보기 2줄 → 확정 → `2건 등록했습니다.`.
  - `메뉴 → 기준정보 새 화면`: 메뉴 "품번·BOM·라우팅" 누르면 `/app/items`.
- [ ] **Step 2: 전체 검증** (모두 실제로 실행하고 출력 그대로 기록)
  - `.venv/Scripts/python manage.py test` → `OK`, 개수 기록
  - `.venv/Scripts/python manage.py makemigrations --check --dry-run` → `No changes detected`
  - `.venv/Scripts/python scripts/e2e_check.py` → 전부 통과
  - `python scripts/e2e_browser.py` → 전부 통과(기존 31 + 새 6)
- [ ] **Step 3: 문서** — README 기준정보 절에 새 화면 주소와 동작(붙여넣기, 엑셀 일괄 등록 미리보기), `docs/testing.md`의 테스트 수·브라우저 점검 목록을 고친다.
- [ ] **Step 4: 커밋** — `feat: 기준정보 메뉴를 새 화면으로 잇고 브라우저 점검을 더한다`
