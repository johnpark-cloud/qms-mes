# 업무 화면 재설계 2묶음 (검사 입력 + 검사 목록 + 검사 성적서) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현장 검사 입력(`/inspect/`)을 React 화면 `/app/inspect`로 옮긴다. 수입·공정·출하검사 목록과 검사 기록 페이지를 1묶음 공통 틀로 만든다. 검사 성적서를 문서 구조(.xlsx·PDF)로 낸다.

**Architecture:**
- **판정 규칙은 손대지 않는다.** 새 API는 기존 공용 함수 `qms.rules.measurement`·`submit_inspection`·`receive_lot`만 부른다. 옛 htmx 화면도 같은 함수를 쓰므로 두 경로의 결과가 같다(동등성 테스트로 증명).
- **성적서는 문서 구조 하나에서 나온다.** `Inspection.document()`가 dict를 만든다. `.xlsx`는 `core/export.py document_xlsx`가 만들고, PDF는 React 인쇄 화면이 만든다. 옛 인쇄 화면의 `print_table()`도 이 구조에서 만든다(스펙 P6).
- **옛 화면은 남긴다.** `/inspect/`와 admin 검사 화면은 지우지 않는다. 메뉴만 새 화면으로 잇는다. 템플릿 제거는 모든 묶음이 끝난 뒤 상위 문서 5단계에서 한다.

**Tech Stack:** Django 6.1.2, DRF 3.18.3, django-simple-history, openpyxl / React 19, TypeScript, Vite 8, antd 6, react-router 7, @tanstack/react-query 5 / Playwright(시스템 Python, 검증 전용)

**Spec:** `docs/superpowers/specs/2026-11-03-notion-style-frontend-design.md` (5.2 검사 입력, P6 문서 내보내기, 4장 표 "검사 입력"·"수입·공정·출하검사", 8장 2번 묶음)

## Global Constraints

- 새 의존성 금지: `requirements.txt`, `frontend/package.json`을 바꾸지 않는다. 외부 CDN·폰트·아이콘을 로드하지 않는다. 오프라인에서 동작해야 한다.
- 마이그레이션 없음: 모델 필드·테이블을 바꾸지 않는다. `makemigrations --check --dry-run`은 `No changes detected`여야 한다.
- 새 권한·역할을 만들지 않는다. 기존 권한만 쓴다: 검사 입력 `qms.add_inspection`, 입고 등록 `core.add_lot`, 검사 목록·성적서 `qms.view_inspection`.
- 업무 규칙(`docs/business-rules.md` §검사 판정·계측기·보류)을 바꾸지 않는다. 판정·부적합 등록·SPC 경보·자격·교정 기한 검사는 모델과 `qms/rules.py`에 있는 그대로 쓴다.
- 화면 문구·오류 메시지·커밋 메시지는 한국어로 쓴다. antd 영어 기본 문구를 남기지 않는다.
- 색은 `DESIGN.md` Fiori 토큰을 쓴다. 합격 색은 `--sapPositiveColor` 계열, 규격 이탈 색은 `--sapNegativeColor` 계열이다(antd `success`/`error` 상태로 표시해도 된다).
- 다운로드 형식은 `?export=xlsx`로 고른다(`?format=`는 DRF가 가로챈다).
- API 400 응답 모양은 `{'detail': 글, 'fields': {...}}`다(`qms/api/specs.py _bad`와 같다).
- 초안 표시 문구는 정확히 `초안 — 승인 전`이다(`core/export.py DRAFT_MARK`). 검사 성적서는 미판정일 때 초안이다.
- 작업 브랜치는 `notion-ui-bundle2`다(master `b95a7fc`에서 분기).
- `git add` 금지: `data/`, `.superpowers/`, `.venv/`, 사용자 파일 3개(`docs/superpowers/plans/2026-11-02-react-drf-phase0-1.md`, `docs/superpowers/plans/2026-11-03-notion-ui-bundle1.md`, `docs/superpowers/specs/2026-11-03-notion-style-frontend-design.md`).
- 커밋은 한국어 Conventional Commits로 쓰고 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`를 붙인다.
- React를 바꾼 태스크는 `cd frontend; npm run build`(tsc 포함)를 통과시키고 `frontend/dist/`를 다시 만들어 같은 커밋에 넣는다.

## 설계 판정 (스펙이 열어 둔 것)

1. **검사 대기 목록의 정의:**
   - 대상 LOT은 두 조건을 모두 만족한다.
     - 그 품번에 승인된 해당 구분 기준이 있다.
     - 그 LOT에 같은 구분의 검사가 하나도 없다. 개정은 따지지 않는다.
   - 오래된 순(`created_at`, `pk`)으로 보인다. 기간 제한은 두지 않는다(스펙 "내 판단").
2. **보류 중인 LOT도 검사할 수 있다.**
   - 옛 화면이 그렇게 동작하고, 업무 규칙에도 보류 LOT 검사 금지는 없다.
   - 목록과 측정 화면에는 `보류` 표시만 붙인다.
3. **같은 LOT을 다시 검사하는 것은 서버에서 막지 않는다.**
   - 재작업·수리 뒤 재검사가 정상 흐름이다(부적합 처분 규칙).
   - 두 번 누름은 화면에서만 막는다. 판정 버튼은 요청 중에 비활성이다.
4. **모르는 계측기 번호:**
   - 판정 요청의 `gauge`가 없는 id면 400 `계측기를 찾을 수 없습니다.`를 낸다.
   - 옛 화면은 조용히 "계측기 없음"으로 저장했다. API는 몰래 값을 버리지 않는다.
   - `gauge`가 `null`이면 옛 화면과 같이 계측기 없이 저장한다. 계측기를 꼭 적어야 하는지는 모델 규칙이 정한다.
5. **검사 성적서 문서 구조:**
   - `revisions`는 `None`이다. 검사 기록에는 개정 이력이 없다.
   - `document_xlsx`와 `DocumentView`는 `revisions`가 `None`이면 개정 이력 절을 통째로 뺀다. 빈 목록이면 지금처럼 빈 표를 낸다. 그래서 검사기준서는 바뀌지 않는다.
   - 승인란은 `작성` = 검사자·검사 일자, `승인` = 빈칸이다. 빈칸은 종이에 서명할 자리다.
6. **규격 글은 한 곳에서 만든다.**
   - `Characteristic.spec_text()`를 둔다. 측정 화면 API, 문서 구조, `print_table`이 같이 쓴다.
   - 결과: `9.9 ~ 10.1 mm`, `- ~ 10.1 mm`, 계수형은 `OK/NG`.
7. **명령창(Ctrl+K) 동작 추가는 이 묶음에 넣지 않는다.** LOT 검색은 1묶음 검색 API가 이미 LOT 이력으로 잇는다.

## Review Focus

1. **측정 화면을 연 뒤 판정 전에 기준이 새로 승인되거나 계측기 교정 기한이 지난 경우:** 판정은 400과 모델의 한국어 메시지로 거부된다. 검사·측정값은 하나도 남지 않는다 → Task 2 `test_submit_rejects_stale_spec_and_expired_gauge`
2. **값에 쉼표·앞뒤 공백·글자가 섞인 경우:**
   - `" 10.0 "`은 숫자로 판정된다.
   - `"10,0"`·`"abc"`·`"NaN"`은 숫자가 아니다. 측정 확인에서 `null`이 되고, 판정에서는 `값을 입력하세요`로 거부된다.
   - → Task 2 `test_check_and_submit_value_forms`
3. **손으로 만든 요청(`values`가 목록, 키가 숫자가 아님, 값이 숫자형, 본문이 목록):** 500이 아니라 400이다 → Task 2 `test_submit_bad_body_400`
4. **입고 권한(`core.add_lot`)이 없는 검사원이 없는 LOT을 스캔한 경우:**
   - 조회는 404 `등록되지 않은 LOT입니다.`와 `can_receive: false`를 준다. 품목·협력사 목록은 주지 않는다.
   - 입고 POST는 403이다.
   - 화면은 입고 창 대신 안내만 보인다.
   - → Task 2 `test_unknown_lot_without_add_lot`, Task 4 화면 분기
5. **판정 버튼을 두 번 빠르게 누른 경우:** 검사 기록은 1건만 생긴다 → Task 7 e2e `판정 두 번 눌러도 1건`

---

## 파일 구조

| 파일 | 책임 |
| --- | --- |
| `qms/models.py` (수정) | `Characteristic.spec_text()`, `Inspection.document()`, `print_table()`을 문서 구조에서 만든다 |
| `core/export.py` (수정) | `document_xlsx`: `revisions is None`이면 개정 이력 절 생략 |
| `qms/api/inspections.py` (생성) | 검사 입력 API(대기·LOT 조회·입고·측정 화면·측정 확인·판정)와 검사 기록 API(목록·상세·문서) |
| `qms/api/urls.py` (수정) | 위 경로 |
| `qms/api/tests.py` (수정) | `InspectApiTest`, `InspectionApiTest` |
| `qms/tests.py` (수정) | `InspectionDocumentTest` |
| `frontend/src/api/inspect.ts` (생성) | 타입·호출 |
| `frontend/src/pages/inspect/InspectPage.tsx` (생성) | 스캔 칸, 입고 창, 검사 대기 목록 |
| `frontend/src/pages/inspect/MeasurePage.tsx` (생성) | 측정 입력·즉시 색·판정 |
| `frontend/src/pages/inspections/InspectionList.tsx`, `InspectionPage.tsx`, `InspectionPrint.tsx` (생성) | 검사 목록, 기록 페이지, A4 성적서 |
| `frontend/src/components/PrintPage.tsx` (생성) | 인쇄 화면 공용 틀(돌아가기·인쇄·.xlsx). `SpecPrint`도 이것을 쓴다 |
| `frontend/src/components/DocumentView.tsx`, `RecordPage.tsx` (수정) | `revisions: null` 처리, 상태 `합격`·`불합격`·`미판정` |
| `frontend/src/api/specs.ts` (수정) | `DocStruct.revisions`를 `... \| null`로 |
| `frontend/src/main.tsx`, `frontend/src/layout/AppLayout.tsx` (수정) | 경로, 메뉴 `MOVED` |
| `scripts/e2e_browser.py` (수정) | 검사 흐름 점검 |
| `README.md`, `docs/architecture.md`, `docs/testing.md` (수정) | 문서 |

---

### Task 1: 검사 성적서 문서 구조

**Files:**
- Modify: `qms/models.py` (`Characteristic`, `Inspection.print_table` ~149-163)
- Modify: `core/export.py` (`document_xlsx` ~71-73)
- Test: `qms/tests.py` 새 클래스 `InspectionDocumentTest`

**Interfaces:**
- Produces:
  - `Characteristic.spec_text() -> str`
  - `Inspection.document() -> dict`. 키는 `InspectionSpec.document()`와 같다: `title, number, revision, draft, head, tables, revisions, signoff`. 값은 모두 JSON 글이다.
  - `print_table() -> (title, ['항목', '내용', '비고·판정'], rows)`. 모양은 지금과 같다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`InspectionDocumentTest`의 준비 데이터:
- 품번 `D-1`(협력사 `성일철강`, 수량 50 LOT `D-LOT-1`)
- 승인된 수입검사 기준: `두께` 9.9~10.1 mm, `외관` 규격 없음
- 사용 가능한 계측기 `G-01`
- `submit_inspection`으로 두께 `11.0`, 외관 `OK`, 계측기 `G-01` 판정 → 불합격

```python
def test_document_structure(self):
    d = self.insp.document()
    self.assertEqual(d['title'], '수입검사 성적서')
    self.assertEqual(d['revision'], 'Rev.1')
    self.assertFalse(d['draft'])
    self.assertIsNone(d['revisions'])
    head = dict(d['head'])
    self.assertEqual((head['LOT'], head['협력사'], head['수량'], head['판정']), ('D-LOT-1', '성일철강', '50', '불합격'))
    self.assertEqual(head['부적합'], self.insp.nonconformance.number)
    t = d['tables'][0]
    self.assertEqual(t['columns'], ['검사항목', '규격', '측정값', '계측기', '판정'])
    self.assertEqual(t['rows'][0], ['두께', '9.9 ~ 10.1 mm', '11', 'G-01', '불합격'])
    self.assertEqual(t['rows'][1], ['외관', 'OK/NG', 'OK', '', '합격'])
    self.assertEqual(d['signoff']['written_by'], self.user.username)
    self.assertEqual(d['signoff']['approved_by'], '')

def test_spec_text_forms(self):  # 하한만·상한만·계수형
    ...  # '9.9 ~ - mm', '- ~ 10.1 mm', 'OK/NG'

def test_unjudged_is_draft(self):  # admin에서 만든 미판정 검사
    insp = Inspection.objects.create(lot=..., spec=..., inspector=self.user)
    self.assertTrue(insp.document()['draft'])
    self.assertEqual(dict(insp.document()['head'])['판정'], '미판정')

def test_xlsx_without_revisions(self):
    ws = load_workbook(BytesIO(document_xlsx(self.insp.document()))).active
    texts = [c.value for row in ws.iter_rows() for c in row if c.value]
    self.assertNotIn('개정 이력', texts)
    self.assertIn('측정 결과', texts)

def test_print_table_from_document(self):
    title, header, rows = self.insp.print_table()
    self.assertEqual(title, '수입검사 성적서')
    self.assertIn('성일철강', str(rows))
    self.assertIn('11', str(rows))
```

검사기준서 xlsx에 `개정 이력`이 그대로 있는지는 기존 `SpecDocumentTest`가 지킨다. 그 테스트는 고치지 않는다.

- [ ] **Step 2: 실패 확인**

Run: `.\.venv\Scripts\python manage.py test qms.tests.InspectionDocumentTest`
Expected: FAIL (`'Inspection' object has no attribute 'document'`)

- [ ] **Step 3: 구현**

- `spec_text()`: 위 판정 6의 모양을 쓴다. 숫자는 `format(d.normalize(), 'f')`다.
- `document()`:
  - `head` 순서: `LOT, 품번, 품명, 협력사(없으면 '-'), 수량, 검사기준(str(spec)), 샘플링, 검사자, 검사 일시('%Y-%m-%d %H:%M' 현지 시각), 판정(합격/불합격/미판정), 부적합(번호 또는 '')`
  - 표 제목은 `측정 결과`다.
  - 측정값: 계량형은 정규화한 숫자, 계수형은 `OK`/`NG`, 값이 없으면 `-`다. 판정 칸은 `합격`/`불합격`이다.
  - `number`: `None`
  - `revision`: `f'Rev.{spec.revision}'`
  - `draft`: `result == ''`
- `print_table()`: `document()`에서 만든다.
  - 머리 정보: `[k, v, '']`
  - 측정 줄: `[항목, f'{규격} → {측정값}' + (계측기 있으면 f' ({번호})'), 판정]`
  - 끝 줄: `['판정', 판정, 부적합 번호]`
  - 옛 인쇄 화면 템플릿은 바꾸지 않는다.
- `document_xlsx`: `doc['revisions'] is None`이면 개정 이력 제목과 표를 쓰지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `.\.venv\Scripts\python manage.py test qms core`
Expected: `OK`. 기존 `QmsTest`의 `print_table` 검사(`qms/tests.py` ~674)와 `SpecDocumentTest`도 통과해야 한다.

- [ ] **Step 5: 커밋**

```bash
git add qms/models.py core/export.py qms/tests.py
git commit -m "feat: 검사 성적서 문서 구조를 만들고 옛 인쇄 화면도 같은 구조를 쓴다"
```

---

### Task 2: 검사 입력 API

**Files:**
- Create: `qms/api/inspections.py`
- Modify: `qms/api/urls.py`
- Test: `qms/api/tests.py` 새 클래스 `InspectApiTest`

**Interfaces:**
- Consumes: `qms.rules.measurement`, `submit_inspection`, `receive_lot`, `RECEIVE_MSG`. `qms.views.DEFECT_TYPES`는 그 자리에서 import한다(옮기지 않는다). `Characteristic.spec_text()`(Task 1). `qms/api/specs.py`의 `_bad`, `PAGE_SIZE`, 페이지 계산 방식.
- Produces (모든 경로는 `/api/qms/` 아래, 권한은 `qms.add_inspection`):

| 경로 | 요청 | 응답 |
| --- | --- | --- |
| `GET inspect/queue/?tab=INCOMING\|PROCESS\|OUTGOING&q=&page=&export=xlsx` | 틀린 tab은 `INCOMING` | `{count, page, has_more, results:[{id, number, item_code, item_name, supplier, qty, created_at, on_hold, spec_id}]}` |
| `GET inspect/lot/?number=` | 빈 번호 → 400 | 200 `{lot, specs:[{id, title, inspection_type, inspection_type_display, done}]}` / 404 `{detail:'등록되지 않은 LOT입니다.', can_receive, items?:[{value,label}], suppliers?:[str]}` |
| `POST inspect/receive/` | `{number, item, qty, supplier}`. `core.add_lot` 필요 | 201(새로 만듦) 또는 200(이미 있음) `{lot, specs, created}` / 400 `RECEIVE_MSG` |
| `GET inspect/form/<lot>/<spec>/` | 승인 안 된 기준 → 404 | `{lot, spec:{id,title,sampling}, characteristics:[{id,name,spec_text,unit,is_variable,special}], gauges:[{value,label}], defect_types:[str]}` |
| `POST inspect/check/` | `{spec, values:{"<id>": 글}}` | `{results:{"<id>": true\|false\|null}}`. 그 기준의 항목만 |
| `POST inspect/submit/` | `{lot, spec, gauge:id\|null, values, defect_type, defect_qty}` | 201 `{id, result, result_display, nonconformance:{id, number}\|null}` / 400 `{detail, fields:{}}` |

필드 값:
- `lot`: `{id, number, item_code, item_name, supplier, qty, on_hold}`
- `qty`: 정규화한 글
- `done`: 그 LOT에 그 구분 검사가 있는가
- `gauges`: 쓸 수 있는 것만. `active=True`이고 `usable_on(오늘)`인 것. 옛 `inspect_form`과 같다.
- `queue`의 `spec_id`: 그 구분의 현재 기준 pk. `Subquery`로 구한다.
- `on_hold`: `Exists(Hold, released_at null)`로 구한다. 줄마다 쿼리하지 않는다.
- 엑셀 열: `LOT, 품번, 품명, 협력사, 수량, 생성일, 보류`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`InspectApiTest`의 준비 데이터: Task 1과 같은 품번·기준·계측기, `검사원` 그룹 사용자, LOT `Q-1`(검사 없음)·`Q-2`(이미 수입검사함).

- `test_queue_lists_uninspected_oldest_first`
  - INCOMING 탭에 `Q-1`만 있다. 보류를 걸면 `on_hold`가 `True`다.
  - 기준이 없는 PROCESS 탭은 비어 있다.
  - `?export=xlsx`는 200이고 `Content-Type`에 `spreadsheetml`이 들어 있다.
- `test_lot_lookup`: `Q-2` 조회의 수입검사 `done`이 `True`다.
- `test_unknown_lot_without_add_lot`: 404 응답의 `can_receive`가 `False`이고 `items` 키가 없다. receive POST는 403이다.
- `test_receive_creates_or_reuses`
  - 새 번호는 201이고 `created`가 `True`다.
  - 같은 번호는 200이고 `created`가 `False`다.
  - 수량 `0`은 400이고 `detail`이 `RECEIVE_MSG`다.
- `test_form_only_usable_gauges`: 교정 기한이 지난 계측기는 목록에 없다.
- `test_check_and_submit_value_forms` (Review Focus 2)
  - check `{" 10.0 ": true, "10,0": null, "abc": null, "NaN": null, "11": false}`를 각 항목 값으로 확인한다.
  - 계수형 `OK`는 true, `NG`는 false, `ok`는 null이다.
  - submit에 `"10,0"`을 넣으면 400이고 `detail`에 `값을 입력하세요`가 들어 있다. `Inspection.objects.count()`는 그대로다.
- `test_submit_pass_and_fail`
  - 합격은 201이고 `nonconformance`가 `None`이다.
  - 불합격은 `nonconformance.number`가 있고, LOT이 보류된다(`on_hold`).
  - `defect_type`·`defect_qty`가 부적합에 들어간다.
- `test_submit_rejects_stale_spec_and_expired_gauge` (Review Focus 1)
  - 측정 화면을 받은 뒤 Rev.2를 승인하고 Rev.1로 판정한다 → 400. `detail`에 `유효본이 아닙니다`가 들어 있다.
  - 계측기 `last_calibrated`를 `오늘 - interval_days - 1일`로 바꿔 교정 기한을 넘긴 뒤 판정한다 → 400. `next_due`는 필드가 아니라 계산 값이다.
  - 두 경우 모두 검사·측정값 수가 그대로다.
- `test_submit_bad_body_400` (Review Focus 3)
  - 다음은 모두 400이다: 본문이 `[]`, `values: []`, `values: {"x": "1"}`(그 기준 항목이 아님 → 모든 항목 `값을 입력하세요`), `values: {"<id>": 10.0}`(숫자형), `gauge: 99999`(`계측기를 찾을 수 없습니다.`), `lot: "a"`.
  - 없는 lot·spec id는 404다.
- `test_permission`: `qms.add_inspection`이 없는 staff는 queue·lot·form·check·submit 모두 403이다.
- `test_api_matches_old_view` (동등성)
  - 같은 값(`11.0`, `OK`, 불량유형 `치수`, 수량 `3`)을 넣는다. 한 번은 옛 `POST /inspect/<lot>/<spec>/submit/`로, 한 번은 API로 다른 LOT에 판정한다.
  - 두 검사의 `result`, 측정값 `(characteristic_id, value, ok, gauge_id)` 목록, 부적합 `(defect_type, defect_qty, inspected_qty, detected_by_id, origin)`이 같다.

- [ ] **Step 2: 실패 확인**

Run: `.\.venv\Scripts\python manage.py test qms.api.tests.InspectApiTest`
Expected: FAIL (404, 경로 없음)

- [ ] **Step 3: 구현**

- 뷰는 `APIView`, `schema = None`, `require_perm`을 쓴다. `qms/api/specs.py` 방식을 따른다.
- 대기 목록 쿼리:
  ```python
  Lot.objects.filter(Exists(approved_spec_of_type), ~Exists(Inspection.objects.filter(lot=OuterRef('pk'), spec__inspection_type=tab)))
  ```
  `q`는 LOT 번호·품번·협력사에 `icontains`로 건다.
- 판정 본문 검사:
  - `values`는 dict여야 한다.
  - 키는 `str.isdigit()`인 것만 `int`로 바꾼다.
  - 값이 `str`가 아니면 버린다. 그러면 `submit_inspection`이 `값을 입력하세요`로 거부한다.
- 오류 변환:
  - `ValidationError`는 `_bad(' '.join(e.messages))`로 바꾼다.
  - `lot`·`spec`·`gauge`가 정수가 아니면 400이다.
- 입고: 옛 `inspect_receive`와 같은 검사를 하고 `receive_lot`을 부른다.

- [ ] **Step 4: 통과 확인**

Run: `.\.venv\Scripts\python manage.py test qms`
Expected: `OK`

- [ ] **Step 5: 커밋**

```bash
git add qms/api/inspections.py qms/api/urls.py qms/api/tests.py
git commit -m "feat: 검사 입력 API(검사 대기·LOT 조회·입고·측정 확인·판정)를 더한다"
```

---

### Task 3: 검사 기록 API (목록·상세·성적서)

**Files:**
- Modify: `qms/api/inspections.py`, `qms/api/urls.py`
- Test: `qms/api/tests.py` 새 클래스 `InspectionApiTest`

**Interfaces:**
- Consumes: `Inspection.document()`(Task 1), `document_xlsx`, `table_xlsx`, `xlsx_response`
- Produces (권한 `qms.view_inspection`):

| 경로 | 응답 |
| --- | --- |
| `GET inspections/?tab=INCOMING\|PROCESS\|OUTGOING&q=&page=&export=xlsx` | `{count, page, has_more, results:[{id, inspected_at, lot_number, item_code, item_name, supplier, spec_title, inspector, result, result_display, nc_number}]}`. 최신 순(`-inspected_at`, `-pk`). `q`는 LOT 번호·품번·협력사 |
| `GET inspections/<id>/` | `{id, title, status:'합격'\|'불합격'\|'미판정', lot:{id, number, trace_url}, item:{code, name}, spec:{id, title}, inspector, inspected_at, nonconformance:{id, number, url}\|null, measurements:[{name, spec_text, value, gauge, passed}], templates:[{id, name, url}]}` |
| `GET inspections/<id>/document/` (+`?export=xlsx`) | 문서 구조 / 파일 `{LOT}_{구분}성적서.xlsx` |

- `trace_url`: `reverse('trace') + '?lot=' + 번호`
- `nonconformance.url`: `reverse('admin:core_nonconformance_change', args=[pk])`
- `templates`: `ExcelTemplate.objects.filter(target=ContentType(Inspection))`. url은 `reverse('excel_report', args=[t.pk, insp.pk])`다(검사기준과 같은 방식).
- 엑셀 열: `검사 일시, LOT, 품번, 품명, 협력사, 검사기준, 검사자, 판정, 부적합`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

- `test_list_tabs_and_search`
  - 수입 2건, 출하 1건을 만든다. 탭마다 그 구분만 보인다.
  - `q=성일`이 협력사로 찾는다.
  - xlsx는 200이다.
- `test_detail_and_document`
  - 불합격 검사의 `status`는 `불합격`이고 `nonconformance.number`가 있다.
  - document 응답의 `title`은 `수입검사 성적서`다.
  - `?export=xlsx`의 `Content-Disposition`에 `.xlsx`가 들어 있다.
- `test_permission`: `view_inspection`이 없으면 목록·상세·문서 모두 403이다. 없는 id는 404이고 `detail`은 `찾을 수 없습니다.`다.

- [ ] **Step 2: 실패 확인**

Run: `.\.venv\Scripts\python manage.py test qms.api.tests.InspectionApiTest`
Expected: FAIL

- [ ] **Step 3: 구현** — `qms/api/specs.py`의 `SpecListView`·`SpecDocumentView` 방식을 따른다. `select_related('lot__item', 'spec', 'inspector', 'nonconformance')`로 줄마다 쿼리하지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `.\.venv\Scripts\python manage.py test qms`
Expected: `OK`

- [ ] **Step 5: 커밋**

```bash
git add qms/api/inspections.py qms/api/urls.py qms/api/tests.py
git commit -m "feat: 검사 목록·상세·성적서 문서 API를 더한다"
```

---

### Task 4: 검사 입력 화면 — 스캔·입고·검사 대기 목록

**Files:**
- Create: `frontend/src/api/inspect.ts`, `frontend/src/pages/inspect/InspectPage.tsx`
- Modify: `frontend/src/main.tsx` (경로 `inspect`), `frontend/src/layout/AppLayout.tsx` (`MOVED`에 `'/inspect/': '/app/inspect'`)

**Interfaces:**
- Consumes: Task 2 API, `DataList`(columns·tabs·fetchPage·exportHref·onOpen·rowKey), `api()`/`ApiError`
- Produces: `inspect.ts`가 내보내는 것
  - 타입 `QueueRow`, `LotInfo`, `LotSpec`, `FormData`, `SubmitResult`
  - 함수 `fetchQueue(tab, q, page)`, `lookupLot(number)`, `receiveLot(body)`, `fetchForm(lotId, specId)`, `checkValues(specId, values)`, `submitInspection(body)`
  - 측정 화면 주소: `/inspect/:lotId/:specId`(basename `/app` 아래)

- [ ] **Step 1: 화면을 만든다**

- **스캔 칸:**
  - 화면에 들어오면 포커스가 간다.
  - Enter로 조회한다. 한글 입력 조합 중의 Enter(`e.nativeEvent.isComposing` 또는 `keyCode 229`)는 무시한다.
  - 조회 중에는 다시 조회하지 않는다.
  - 조회 뒤에는 칸을 비우고 다시 포커스한다.
- **조회 결과:**
  - LOT 정보 줄(품번·협력사·수량·`보류` 태그)을 보인다.
  - 검사 구분마다 버튼을 보인다. `done`이면 `재검사` 표시를 붙인다. 누르면 측정 화면으로 간다.
  - 기준이 하나도 없으면 `이 품번에는 승인된 검사기준이 없습니다.`를 보인다.
- **404:**
  - `can_receive`가 참이면 입고 등록 창(antd Modal)을 띄운다.
    - 칸: LOT 번호(스캔 값, 수정 가능), 품목(Select, 검색), 입고수량, 협력사(AutoComplete, `suppliers`)
    - 저장하면 LOT 조회 결과를 보인다. `created`가 거짓이면 `이미 등록된 LOT입니다. 기존 LOT으로 검사합니다.`를 보인다.
  - 거짓이면 `등록되지 않은 LOT입니다. 입고 등록 권한이 있는 사람에게 요청하세요.`를 보인다.
- **검사 대기 목록:**
  - `DataList`, 탭 `수입`·`공정`·`출하`
  - 열: LOT·품번·품명·협력사·수량·생성일·보류
  - 줄을 누르면 `/inspect/{id}/{spec_id}`로 간다.
  - 비어 있으면 `검사 대기 중인 LOT이 없습니다.`를 보인다.
- 오류는 `ApiError.detail`을 그대로 보인다.

- [ ] **Step 2: 빌드**

Run: `cd frontend; npm run build`
Expected: 오류 없이 `dist/` 생성

- [ ] **Step 3: 커밋**

```bash
git add frontend/src frontend/dist
git commit -m "feat: React 검사 입력 화면(LOT 스캔·입고 등록·검사 대기 목록)을 더한다"
```

---

### Task 5: 측정 화면과 판정

**Files:**
- Create: `frontend/src/pages/inspect/MeasurePage.tsx`
- Modify: `frontend/src/main.tsx` (경로 `inspect/:lotId/:specId`)

**Interfaces:**
- Consumes: `fetchForm`, `checkValues`, `submitInspection`(Task 4)
- Produces: 판정 결과 화면에서 성적서 링크 `/inspections/{id}/print`(Task 6 경로)

- [ ] **Step 1: 화면을 만든다**

- **머리:** LOT·품번·검사기준·샘플링·`보류` 태그
- **표:** 항목마다 한 줄이다.
  - 열: 항목명·규격(`spec_text`)·입력칸·결과
  - 계량형 입력칸은 `inputMode="decimal"`이다.
  - 계수형은 `OK`/`NG` 두 버튼이다.
  - 입력칸에서 Enter를 치면 다음 칸으로 간다(바코드·숫자 키패드 흐름).
- **즉시 색:**
  - 입력이 멈추고 300ms 뒤에 바뀐 값만 모아 `checkValues`를 한 번 부른다.
  - `true`이면 `합격`(성공 색), `false`이면 `규격 이탈`(오류 색)이다. `null`이고 값이 있으면 `숫자가 아닙니다`다.
  - 판정은 화면에서 계산하지 않는다. 서버 응답만 쓴다.
- **계측기:** Select에 `gauges`만 있다. 계량형 항목이 있는데 목록이 비면 `쓸 수 있는 계측기가 없습니다(교정 기한 확인).`를 보인다.
- **불량유형·수량:**
  - 결과에 `false`가 하나라도 있을 때만 보인다. 불량유형은 `defect_types` Select다.
  - 서버는 불합격일 때만 이 값을 쓰므로 그대로 보내도 된다.
- **판정 버튼:**
  - 요청 중에는 `loading`이고 다시 누를 수 없다.
  - 성공하면 결과 화면을 보인다.
    - `합격` 또는 `불합격`을 크게 보인다.
    - 불합격이면 `부적합 {number} 등록 — LOT이 보류되었습니다.`를 보인다.
    - 버튼: `성적서 인쇄`, `다음 LOT 스캔`(→ `/inspect`)
  - 400이면 `detail`을 Alert로 보이고 입력값은 그대로 둔다.

- [ ] **Step 2: 빌드**

Run: `cd frontend; npm run build`
Expected: 오류 없음

- [ ] **Step 3: 커밋**

```bash
git add frontend/src frontend/dist
git commit -m "feat: React 측정 입력·판정 화면을 더한다"
```

---

### Task 6: 검사 목록·기록 페이지·성적서 인쇄

**Files:**
- Create: `frontend/src/pages/inspections/InspectionList.tsx`, `InspectionPage.tsx`, `InspectionPrint.tsx`, `frontend/src/components/PrintPage.tsx`
- Modify: `frontend/src/pages/specs/SpecPrint.tsx` (`PrintPage`를 쓰는 얇은 감싸개로)
- Modify: `frontend/src/components/DocumentView.tsx` (`doc.revisions`가 `null`이면 개정 이력 절 생략)
- Modify: `frontend/src/components/RecordPage.tsx` (`status` 형식에 `'합격' | '불합격' | '미판정'` 추가. 색: 합격 green, 불합격 red, 미판정 orange)
- Modify: `frontend/src/api/specs.ts` (`DocStruct.revisions: Revision[] | null`), `frontend/src/api/inspect.ts`
- Modify: `frontend/src/main.tsx` (`inspections`, `inspections/:id`는 `AppLayout` 안에, `inspections/:id/print`는 밖에. `specs/:id/print`와 같다)
- Modify: `frontend/src/layout/AppLayout.tsx` (`MOVED`)

**Interfaces:**
- Consumes: Task 3 API
- Produces: `PrintPage({ docUrl: string, backTo: string, queryKey: unknown[] })`. 돌아가기 링크·`인쇄 / PDF로 저장`·`.xlsx 받기`(`docUrl + '?export=xlsx'`)·`DocumentView`를 그린다.

- [ ] **Step 1: 화면을 만든다**

- **목록:**
  - `DataList`, 탭 `수입검사`·`공정검사`·`출하검사`. 탭은 주소 `?tab=`과 맞춘다.
  - 열: 검사 일시·LOT·품번·협력사·검사기준·검사자·판정(태그)·부적합
  - 엑셀로 버튼과 미리보기 패널(`peek`: 머리 정보)이 있다.
- **기록 페이지:**
  - `RecordPage`를 쓴다.
  - 속성: LOT(이력 링크)·품번·검사기준(검사기준 페이지 링크 `/specs/{id}`)·검사자·검사 일시·부적합(admin 링크)
  - 본문은 측정 결과 표(읽기 전용)다.
  - 머리 버튼은 `내보내기 ▾`다. 항목: `.xlsx`, `PDF(인쇄 화면)`, `templates`의 회사 양식
  - 판정된 검사는 고칠 수 없으므로 편집 버튼이 없다.
- **인쇄:** `InspectionPrint`는 `PrintPage`에 `/api/qms/inspections/{id}/document/`를 넘긴다.
- **메뉴 `MOVED`:** 다음 세 주소를 각각 `/app/inspections?tab=INCOMING`·`PROCESS`·`OUTGOING`으로 바꾼다.
  - `/admin/qms/inspection/?spec__inspection_type__exact=INCOMING`
  - `/admin/qms/inspection/?spec__inspection_type__exact=PROCESS`
  - `/admin/qms/inspection/?spec__inspection_type__exact=OUTGOING`
  - 실제 문자열은 `core.nav.nav_url` 결과와 같아야 한다. `/api/me/` 응답에서 확인한다.

- [ ] **Step 2: 빌드**

Run: `cd frontend; npm run build`
Expected: 오류 없음

- [ ] **Step 3: 커밋**

```bash
git add frontend/src frontend/dist
git commit -m "feat: React 검사 목록·기록 페이지·검사 성적서 인쇄 화면을 더한다"
```

---

### Task 7: 브라우저 점검, 문서 갱신, 전체 검증

**Files:**
- Modify: `scripts/e2e_browser.py`
- Modify: `README.md` (검사 입력 새 화면 `/app/inspect`, 검사 목록 `/app/inspections`, 성적서 내보내기)
- Modify: `docs/architecture.md` (`qms/api/inspections.py`, `Inspection.document()`)
- Modify: `docs/testing.md` (단위 테스트 수, e2e_browser 점검 수와 새 점검 목록)

**Interfaces:**
- Consumes: Task 1~6 결과

- [ ] **Step 1: e2e 데이터와 점검을 더한다**

기존 `manage('shell', '-c', ...)` 방식으로 임시 DB에 데이터를 만든다.
- 품번 `E2E-I1`
- 수입검사 기준: `두께` 9.9~10.1 mm, `외관` 계수형. 승인은 `approved_at`·`approved_by=boss`를 queryset `update`로 넣는다.
- 사용 가능한 계측기 `E2E-G1`
- LOT `E2E-IN-1`, `E2E-IN-2`

점검(`check(name, ok, detail)`):
1. `검사 대기에 미검사 LOT`: `/app/inspect` 수입 탭에 `E2E-IN-1`이 보인다.
2. `스캔 → 측정 화면`: 스캔 칸에 `E2E-IN-1` + Enter → 수입검사 버튼 → 측정 표가 보인다.
3. `입력 즉시 색`: 두께 `10.0` → `합격`, `11` → `규격 이탈`이 보인다.
4. `판정 두 번 눌러도 1건` (Review Focus 5): 판정 버튼을 `dblclick`한다. `api_get`으로 `/api/qms/inspections/?tab=INCOMING&q=E2E-IN-1`의 `count`가 1이다.
5. `불합격 → 부적합 번호`: 결과 화면에 `부적합`과 번호가 보인다.
6. `없는 LOT → 입고 창`: `E2E-NEW-1` 스캔 → 입고 창 → 품목·수량 입력·저장 → 수입검사 버튼이 보인다.
7. `검사 목록 탭`: `/app/inspections?tab=INCOMING`에 `E2E-IN-1` 줄이 있다. 누르면 기록 페이지가 열린다.
8. `성적서 A4 1쪽`: `/app/inspections/{id}/print`의 PDF가 1쪽이고 인쇄 막대가 보이지 않는다. 검사기준서 점검(`scripts/e2e_browser.py` ~235-238 `page.pdf`·`/Type /Page` 세기)과 같은 방법을 쓴다.
9. `메뉴 → 새 화면`: 사이드바 `검사 입력`과 `수입검사` 링크가 `/app/inspect`, `/app/inspections?tab=INCOMING`으로 간다.

- [ ] **Step 2: 전체 검증을 실행한다**

Run:
- `.\.venv\Scripts\python manage.py test`
- `.\.venv\Scripts\python scripts\e2e_check.py`
- `python scripts\e2e_browser.py`
- `.\.venv\Scripts\python manage.py makemigrations --check --dry-run`

Expected:
- 단위 테스트: `OK`, 294개보다 많다.
- e2e_check: 기존 점검 모두 통과. 옛 `/inspect/` 흐름이 그대로 동작한다.
- e2e_browser: 기존 20개 + 새 9개 모두 통과(`29/29 통과`)
- 마이그레이션 점검: `No changes detected`

- [ ] **Step 3: 문서에 Step 2의 실제 숫자와 새 화면을 적는다**

실행하지 못한 점검이 있으면 문서와 보고에 그대로 적는다.

- [ ] **Step 4: 커밋**

```bash
git add scripts/e2e_browser.py README.md docs/architecture.md docs/testing.md
git commit -m "docs: 검사 입력·검사 목록·검사 성적서 새 화면을 문서에 반영한다"
```

---

## 남은 위험 (실행 전에 알아 둘 것)

- **운영 DB:** 이 묶음은 마이그레이션이 없다. 1묶음의 `core 0009`·`qms 0009`는 아직 운영 DB에 적용하지 않았다. 적용하기 전에 `backup`을 다시 실행한다.
- **현장 PC 검증:** 실제 바코드 스캐너(키보드 입력 + Enter)와 터치 화면에서는 시험하지 않는다. e2e는 키보드 입력으로 흉내만 낸다.
- **옛 화면과 새 화면이 함께 있다:** 둘 다 같은 공용 함수를 쓰므로 판정 결과는 같다(동등성 테스트). 다만 화면 모양은 다르다. 옛 화면은 상위 문서 5단계에서 지운다.
- **번들 크기:** 화면 5개가 늘어 JS 번들이 더 커진다. 경로별 나눠 싣기는 이 계획에 넣지 않았다.
