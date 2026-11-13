# Requirements: QMS+MES (localhost)

**Defined:** 2026-11-13
**Core Value:** 부적합·인터록 규칙이 어떤 화면 변경이나 모듈 설정에서도 약해지지 않고, 기록이 이력과 함께 보존된다.
**근거:** 승인된 계획 `C:\Users\gogog\.claude\plans\twinkling-dreaming-lollipop.md`(2026-11-13 범위 축소 반영), `.planning/research/SUMMARY.md`

## v1 Requirements

### 기록 화면 틀 (SHELL) — B0

- [x] **SHELL-01**: 사용자는 모든 React 기록 상세 화면에서 같은 배치(머리 띠 + 기본정보 4열 + 본문 + 오른쪽 열)를 본다. 품번·검사기준·관리계획서도 포함한다.
- [x] **SHELL-02**: 사용자는 기록 화면의 버튼을 「주요 1개 · 이력 · ⋯ 메뉴」 순서로 보고, 삭제(또는 삭제 요청)는 「⋯」 메뉴 한 곳에서만 찾는다.
- [x] **SHELL-03**: 검사원은 검사 상세에서 28px 판정 띠(합격·불합격·미판정, 색+글자)를 본다.
- [x] **SHELL-04**: 검사원은 측정값 표에서 하한·기준(중앙)·상한·단위·측정값·위치 막대·판정·계측기를 한 줄에 본다. 숫자는 규격 자릿수로 맞춘다.
- [x] **SHELL-05**: 검사원은 검사 상세에서 공급사·입고 수량·샘플링·검사기준 승인자·연결 CAPA를 본다(상세 API에 읽기 전용 키 추가, 기존 키 유지).
- [x] **SHELL-06**: 사용자는 390px 폭에서 오른쪽 열이 본문 아래로 내려간 화면을 보고, 라이트·다크 모두 토큰 색으로 본다.
- [x] **SHELL-07**: DESIGN.md에 「기록 화면 규칙」(배치·간격·글자 크기·상태 색·버튼 위치)이 있다.

### 모듈 켜기/끄기 (MOD) — A1·A3·A4

- [x] **MOD-01**: 시스템 관리자는 모듈(`core/modules.py` 대응표의 키)을 켜고 끌 수 있다. 행이 없는 모듈은 켜진 것으로 본다. 다른 역할은 바꿀 수 없다(서버 검사).
- [x] **MOD-02**: 모든 URL 패턴이 모듈 또는 기본 플랫폼에 매핑되어 있고, 빠진 패턴이 있으면 테스트가 실패한다.
- [x] **MOD-03**: 꺼진 모듈의 화면·API를 일반 사용자가 열면 404를 받는다. 시스템 관리자는 조회(GET)만 할 수 있다.
- [x] **MOD-04**: 꺼진 모듈은 메뉴와 `me` 응답에서 빠지고, React는 해당 경로에 「비활성 모듈」 안내를 보인다.
- [x] **MOD-05**: requires 관계가 지켜진다: 필요한 모듈이 꺼져 있으면 켜기를 거부하고, 다른 켜진 모듈이 필요로 하는 모듈은 끄기를 거부한다.
- [x] **MOD-06**: 열린 기록(미종결 CAPA, 초품 합격 전 4M, 미종결 클레임·SCAR·심사, 미승인 PPAP, 미판정 검사, 열린 작업지시)이 있으면 끄기를 거부하고 번호 목록을 보인다.
- [x] **MOD-07**: 꺼진 모듈이라도 시스템 관리자는 종결 화이트리스트(CAPA·클레임·SCAR·심사 종결, 4M 초품 판정 기록)로 기록을 닫아 인터록을 풀 수 있다. 그 밖의 쓰기는 403이다.
- [x] **MOD-08**: 인터록 거부 메시지에 원인 모듈과 기록 번호가 붙는다(예: `[4M 변경] CR-…`). 규칙 자체는 바뀌지 않는다.
- [x] **MOD-09**: 부적합·보류·LOT·기준정보·시스템은 기본 플랫폼이라 끌 수 없고, 업무 규칙은 모듈 설정과 무관하게 모델에서 동작한다.
- [x] **MOD-10**: 꺼진 모듈의 기록은 내 할 일·기한·알림 메일·위젯·종합현황에서 빠진다.
- [x] **MOD-11**: LOT 이력·검색·연결 패널은 꺼진 모듈 기록을 빼지 않고 「비활성 모듈 기록 N건」으로 보인다.
- [x] **MOD-12**: `collect`·엑셀 일괄 등록(작업지시)·엑셀 보고서 양식 대상·`audit_pack`이 모듈 상태를 따른다(꺼지면 거부 또는 표시).
- [x] **MOD-13**: 고객사별 8D 기한 설정 메뉴가 「고객 클레임 › 클레임 설정」으로 옮겨지고 `qms_claim`에 속한다.

### 기록 화면 이전 (REC) — B1~B6

- [x] **REC-01**: 서버 기록 설명서(`core/recordspec.py`)가 모델별 제목·상태·칸·하위 표·오른쪽 열을 정의하고, 등록되지 않은 모델은 404다.
- [x] **REC-02**: 사용자는 `records` API로 목록(탭·필터·엑셀)과 상세를 받는다. 권한은 기존 모델 권한으로 서버에서 검사한다.
- [x] **REC-03**: 사용자는 `/app/r/:app/:model/:id`에서 설명서만으로 그린 기록 화면을 본다.
- [x] **REC-04**: `record_url`이 유일한 주소 기준이 되어, 검색·타임라인·종합현황·위젯·유사 건·메모·승인 후 돌아가기 링크가 옮긴 화면을 따라간다.
- [ ] **REC-05**: 사용자는 기록 화면에서 「수정」으로 칸을 바꾸고 저장한다. 저장은 `full_clean`·잠금·simple-history를 그대로 타고, 오류는 칸별로 보인다.
- [ ] **REC-06**: 사용자는 기록 화면에서 승인(비밀번호 재입력)·수정 요청·삭제 요청을 한다. 승인된 기록은 수정할 수 없다.
- [x] **REC-07**: 문서·문서 개정·계측기·검사원 자격이 새 기록 화면으로 열린다(B1).
- [ ] **REC-08**: LOT·부적합·보류가 새 기록 화면으로 열린다. 처분 서명은 MRB 비밀번호 전용 본문, 보류는 읽기 전용이다(B3).
- [ ] **REC-09**: CAPA·클레임(+클레임 설정)·SCAR·4M 변경이 새 기록 화면으로 열린다. 출처 연결·8D 단계 표·초품 상태를 보인다(B4).
- [ ] **REC-10**: 내부심사·체크리스트·심사 항목·PPAP가 새 기록 화면으로 열린다. 지적→CAPA 버튼, PPAP 요소 표(승인 후 잠금)를 보인다(B5).
- [ ] **REC-11**: 작업지시·실적·출하·기준정보(부서·거래처·코드값·번호 규칙·사용자 정의 칸·엑셀 양식·가져오기 설정)가 새 기록 화면으로 열리고, 일반 메뉴에 `/admin/` 링크가 남지 않는다(B6).
- [x] **REC-12**: 옮긴 모델의 관리 화면 변경 페이지 위에 「새 화면으로」 링크가 있고, `/admin/` 주소·권한은 그대로 열린다.
- [x] **REC-13**: B1 이후 새로 생긴 경로는 모두 모듈 대응표에 등록되어 MOD-02 테스트를 통과한다.

## v2 Requirements

- **V2-01**: 삭제를 무효 처리(사유 기록)로 바꾸기
- **V2-02**: 기준값(nominal)·소수 자릿수 모델 칸
- **V2-03**: 검사 세부 플래그(`qms_inspection.incoming`, `.spc`) 화면 숨김
- **V2-04**: FAI·FOD 등 항공 모듈

## Out of Scope

| Feature | Reason |
|---------|--------|
| 라이선스 키·만료 읽기 전용·규격별 패키지 | 본인 전용, 판매용 아님(2026-11-13) |
| 기존 고객 데이터 마이그레이션(행 추가) | 모듈 행 없으면 켜짐이라 불필요 |
| personal(연차·급여) 화면 이전 | 이번 범위 아님, 코드·데이터 유지 |
| Django 관리 화면 삭제 | 시스템 관리자 뒷방으로 남김 |
| 새 의존성·CDN·외부 폰트 | 오프라인 동작 원칙 |
| AI 기능 | 제품 비전에서 제외 |

## 미결 결정 (단계 전에 정함)

| # | 결정 | 정할 시점 |
|---|------|-----------|
| 3 | 검사 모듈이 꺼졌을 때 4M 해제 경로 | A3 전 (Phase 3) |
| 5 | `submit_edit_request`를 `core/rules.py`로 옮길지(승인 필요) | B2 전 (Phase 6) |
| 6 | 감사 기록 탭을 누구에게 보일지 | B1 전 (Phase 5) |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SHELL-01 | Phase 1 | Complete |
| SHELL-02 | Phase 1 | Complete |
| SHELL-03 | Phase 1 | Complete |
| SHELL-04 | Phase 1 | Complete |
| SHELL-05 | Phase 1 | Complete |
| SHELL-06 | Phase 1 | Complete |
| SHELL-07 | Phase 1 | Complete |
| MOD-01 | Phase 2 | Complete |
| MOD-02 | Phase 2 | Complete |
| MOD-03 | Phase 2 | Complete |
| MOD-04 | Phase 2 | Complete |
| MOD-05 | Phase 2 | Complete |
| MOD-09 | Phase 2 | Complete |
| MOD-06 | Phase 3 | Complete |
| MOD-07 | Phase 3 | Complete |
| MOD-08 | Phase 3 | Complete |
| MOD-10 | Phase 4 | Complete |
| MOD-11 | Phase 4 | Complete |
| MOD-12 | Phase 4 | Complete |
| MOD-13 | Phase 4 | Complete |
| REC-01 | Phase 5 | Complete |
| REC-02 | Phase 5 | Complete |
| REC-03 | Phase 5 | Complete |
| REC-04 | Phase 5 | Complete |
| REC-07 | Phase 5 | Complete |
| REC-12 | Phase 5 | Complete |
| REC-13 | Phase 5 | Complete |
| REC-05 | Phase 6 | Pending |
| REC-06 | Phase 6 | Pending |
| REC-08 | Phase 7 | Pending |
| REC-09 | Phase 8 | Pending |
| REC-10 | Phase 9 | Pending |
| REC-11 | Phase 10 | Pending |

**Coverage:**
- v1 requirements: 33 total
- Mapped to phases: 33
- Unmapped: 0

---
*Requirements defined: 2026-11-13*
*Traceability updated: 2026-11-13 (로드맵 작성)*
