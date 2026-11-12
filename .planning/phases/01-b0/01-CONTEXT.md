# Phase 1: 기록 화면 공통 틀과 검사 상세 (B0) - Context

**Gathered:** 2026-11-13
**Status:** Ready for planning

<domain>
## Phase Boundary

React 기록 상세 4화면(품번·검사기준·관리계획서·검사)을 같은 배치 「머리 띠 + 기본정보 4열 + 본문 + 오른쪽 열」로 바꾼다. 검사 상세는 판정 띠·측정값 표·위치 막대·「⋯」 메뉴로 다시 쓴다. 검사 상세 API에는 읽기 전용 키만 더한다. DESIGN.md에 「기록 화면 규칙」을 적는다.

범위 밖: 서버 기록 설명서·범용 records API·GenericRecordPage(B1), 편집·저장(B2), 모델·마이그레이션·업무 규칙·역할 권한 변경.
</domain>

<decisions>
## Implementation Decisions

### 공통 틀 (SHELL-01, SHELL-06)
- **D-01:** `RecordPage`의 겉모양을 「RecordShell」 배치로 바꾼다. props 계약(`title`, `status`, `actions`, `props`, `children`, `side`)은 그대로 둔다. 새 파일을 만들지 `RecordPage.tsx` 안에서 바꿀지는 계획자가 정한다(호출 4곳이 바뀌지 않는 쪽).
  - 머리 띠: 제목 + 상태 + 오른쪽 버튼 묶음.
  - 기본정보: 4열 그리드, 한 칸은 「이름 값」 쌍. 이름은 보조색(대비 4.5:1 이상), 값은 본문 15px.
  - 본문(왼쪽 넓게) + 오른쪽 열(좁게, antd `Tabs`).
  - 지금의 인라인 style을 `frontend/src/app.css`(또는 기존 전역 CSS) 클래스로 옮긴다. 색은 `core/static/qms/fiori.css` 토큰 변수만 쓴다.
  - 390px 폭: 기본정보 1~2열, 오른쪽 열은 본문 아래로 내려간다.
  - Reversibility: 겉모양만 바뀌므로 커밋 되돌리기로 복구된다.

### 버튼 (SHELL-02)
- **D-02:** 버튼 순서는 「주요 1개 · 이력 · ⋯」이다. 「⋯」은 antd `Dropdown`으로 만든다.
  - 「이력」은 `/app/audit?model=…&id=…`(기존 AuditLog 화면)로 간다.
  - 「⋯」 메뉴: 엑셀 받기, 엑셀 양식, 삭제(또는 삭제 요청). 삭제는 이 메뉴에만 둔다.
  - 삭제 동작은 기존 서버 규칙을 그대로 쓴다. 시스템 관리자는 삭제, 그 밖의 사용자는 삭제 요청이다. 권한은 서버가 검사하며 버튼 숨김에 기대지 않는다. 기존 경로(`delete_record`, `request/` 흐름)를 연결만 하고 새 규칙은 만들지 않는다.
  - 검사기준·관리계획서는 기존 버튼(새 개정·이력 남기기·이전 개정과 비교·승인)을 유지한다. 주요 1개를 고르고 나머지는 「⋯」으로 옮긴다. 순서와 자리만 바꾸며 기능은 그대로다.
  - 검사 상세의 주요 버튼은 「인쇄/PDF」(`/inspections/:id/print`)다.
  - 품번은 지금 버튼이 없다(`actions={null}`). 「이력」과 「⋯」만 둔다.

### 검사 상세 API (SHELL-05)
- **D-03:** `InspectionDetailView.get`(`qms/api/inspections.py:256-278`)에 읽기 전용 키만 더한다. 기존 키의 이름·형식은 바꾸지 않는다.
  - `lot.supplier`, `lot.qty`
  - `spec.sampling`, `spec.revision`, `spec.approved_by`(이름, `_who`), `spec.approved_at`
  - 측정값 항목마다 `lsl`, `usl`, `unit`, `is_variable`, `special`(CC/SC 등), `decimals`
  - 계측기는 기존 `gauge`(번호 문자열)를 유지하고, 객체가 필요하면 새 키(예: `gauge_name`)로 더한다.
  - `capa`: 검사 → 부적합 → CAPA 연결이 있으면 `{id, number, url}` 목록, 없으면 빈 목록.
  - 값은 모두 기존 모델에서 읽는다(`Inspection.document()` `qms/models.py:166` 참고). 쿼리 수가 늘지 않도록 `select_related`/`prefetch_related`를 쓴다.
  - 테스트를 먼저 쓴다(`qms/api/tests.py`). 기존 키 유지도 테스트로 확인한다.

### 숫자 표시 (SHELL-04)
- **D-04:** `frontend/src/lib/num.ts`를 새로 만든다: `fmtNum(value, decimals)`, `specPosition(lsl, usl, v)`.
  - 자릿수 = 하한·상한 중 소수 자릿수가 큰 쪽. 서버가 `decimals`를 주면 그것을 쓴다.
  - 기준(중앙) = 양쪽 한계가 있을 때 중앙값, 회색. 한쪽만 있으면 「—」.
  - 위치 막대: 하한~상한 사이 점. 양 끝 10% 안이면 주의 색, 한계 밖이면 오류 색. 한쪽 규격이면 숨긴다.
  - 계수형(`is_variable=false`): 하한·기준·상한·단위는 「—」, 판정은 「합격/불합격」 글자.
  - 숫자 칸은 오른쪽 정렬, `font-variant-numeric: tabular-nums`.
  - 판정은 서버 `passed` 값을 그대로 쓴다. 화면에서 다시 계산하지 않는다.
  - 표 열: 항목 | 하한 | 기준(중앙) | 상한 | 단위 | 측정값 | 위치 | 판정 | 계측기. 항목명 옆에 CC·SC를 작은 글자로 보인다.

### 판정 띠 (SHELL-03)
- **D-05:** 검사 상세 머리 띠에 28px/500 판정 글자를 둔다. 합격은 성공 토큰, 불합격은 오류 토큰, 미판정은 중립 토큰이다. 색과 글자를 함께 쓴다(색만으로 구분하지 않는다).

### 기존 동작 유지
- **D-06:** 다음을 유지한다.
  - e2e 선택자: 탭 「연결」·「첨부」, region 「연결」, `[data-attachment]`, 「올리기」.
  - 검사의 소급 추가(`?full=1`)와 `_finalize`는 관리 화면에 남긴다(B2에서 옮김).
  - 검사자 표시는 `_who`(이름 우선) 그대로.
  - `addRecent`, 내보내기 경로(`?export=xlsx`, 양식 `templates[].url`).

### 문서·검증 (SHELL-07)
- **D-07:** DESIGN.md에 「기록 화면 규칙」 절을 더한다(배치·간격·글자 크기·상태 색·버튼 위치). `scripts/e2e_browser.py`에 판정 띠 글자, 측정값 표 머리글, 「⋯」 메뉴 점검을 더한다. 1920×1080 라이트·다크와 390px에서 4화면 스크린샷을 확인한다. `npm run build` 후 `frontend/dist`를 함께 커밋한다.

### Claude's Discretion
- 컴포넌트 파일 나누기(RecordShell 분리 여부), CSS 클래스 이름, 위치 막대 그리는 방법(div 또는 SVG).
- 「⋯」 메뉴 항목 순서(삭제는 맨 아래, 구분선 위).
- 검사기준·관리계획서에서 주요 버튼 하나를 무엇으로 할지(승인 대기면 「승인」, 승인됨이면 「새 개정」을 권장).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 계획·요구사항
- `C:\Users\gogog\.claude\plans\twinkling-dreaming-lollipop.md` — 승인된 계획, 「B0 상세」「B0 검사 화면 규칙」「B0 순서」 절
- `.planning/REQUIREMENTS.md` — SHELL-01~07
- `.planning/ROADMAP.md` — Phase 1 성공 기준, 공통 완료 조건
- `.planning/PROJECT.md` — 제약(새 의존성 금지, 권한 서버 검사)

### 규칙·디자인
- `AGENTS.md` — 작업 절차, 승인 대상
- `DESIGN.md` — 토큰, 글자 크기(Lead 28px/500), 새 절을 더할 곳
- `PRODUCT.md` — 사용자·사용 환경
- `docs/business-rules.md` — 삭제는 시스템 관리자만, 삭제·수정 요청 흐름, 판정 후 수정 불가
- `docs/testing.md` — 테스트 명령과 완료 기준
- `core/static/qms/fiori.css` — 색·간격 토큰

### 코드
- `qms/api/inspections.py` — `InspectionDetailView`(256-278), `_inspection`, `_who`, `InspectionDocumentView`
- `qms/models.py:166` — `Inspection.document()`(협력사·수량·샘플링 만드는 법)
- `qms/api/tests.py` — API 테스트 위치
- `frontend/src/components/RecordPage.tsx` — 바꿀 겉모양
- `frontend/src/pages/inspections/InspectionPage.tsx` — 다시 쓸 화면
- 품번·검사기준·관리계획서 페이지(`RecordPage` 사용처 3곳, `grep RecordPage frontend/src`)
- `frontend/src/pages/AuditLog.tsx` — 「이력」 버튼 대상
- `core/views.py` — 삭제·삭제 요청 처리(`delete_record`, `request/`)
- `scripts/e2e_browser.py` — 점검 추가 위치
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RecordPage`: 4화면이 함께 쓰는 틀. props 계약을 유지하면 호출처 수정이 최소다.
- `RelationsPanel`, `MemoPanel`, `AttachmentPanel`: 오른쪽 열 탭 내용.
- `AuditLog` 페이지(`/app/audit`): 「이력」 버튼 대상.
- `SignModal`, `LogModal`: 검사기준·관리계획서 승인·이력 남기기.
- `_who`: 사람 이름 표시(이름 우선, 없으면 아이디).
- `Inspection.document()`: 협력사·수량·샘플링을 이미 만든다.

### Established Patterns
- API는 `require_perm(VIEW_PERM)`으로 서버 권한 검사.
- 측정값 `value`는 `normalize` 후 `'f'` 형식 문자열, 계수형은 OK/NG.
- React 데이터는 `@tanstack/react-query` `useQuery` + `api()`.
- 색은 fiori.css 토큰 변수, 다크 모드는 토큰으로 처리.

### Integration Points
- `frontend/src/api/inspect`의 `InspectionDetail` 타입에 새 키를 선택 필드로 더한다.
- `frontend/dist`는 커밋 대상이다.
</code_context>

<specifics>
## Specific Ideas

- 사용자가 지적한 문제(2026-11-12): 삭제가 두 번 나옴, 인쇄/PDF가 값처럼 보임, 아이디 `insp_lee` 노출, 항목마다 전체 폭 사용.
- 배치는 사용자가 고른 안 1 「머리 띠 + 오른쪽 열」.
- 1920×1080에서 머리 띠·기본정보·첫 하위 표가 스크롤 없이 보여야 한다.
- 그라데이션 없음, 카드 한 겹, 구역은 여백과 구분선으로 나눈다.
</specifics>

<deferred>
## Deferred Ideas

- V2-01: 삭제를 무효 처리(사유 기록)로 바꾸기 — 업무 규칙 변경, 승인 필요.
- V2-02: 기준값(nominal)·소수 자릿수 모델 칸 — 스키마 변경.
- B1 이후: 서버 기록 설명서, records API, GenericRecordPage, `record_url` 일원화.
- B2: 검사 소급 추가(`?full=1`)·`_finalize` React 이전, 편집 모드.
</deferred>

---

*Phase: 01-b0*
*Context gathered: 2026-11-13*
