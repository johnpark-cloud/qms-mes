# QMS+MES (localhost)

## What This Is

중소 제조사가 사내 PC 한 대(또는 사내망)에서 쓰는 품질경영(QMS)·생산관리(MES) 시스템이다. 품질팀·검사원·현장 관리자가 검사·부적합·CAPA·문서·심사·출하를 한 곳에서 기록하고, 인터록으로 불량품 출하를 막는다. 최종 형태는 QMS+MES+일부 ERP이며 ISO 9001·IATF 16949·AS9100 심사 대응을 목표로 한다.

## Core Value

부적합·인터록 규칙이 어떤 화면 변경이나 모듈 설정에서도 약해지지 않고, 기록이 이력과 함께 보존된다.

## Requirements

### Validated

<!-- 이미 동작 중인 기능 (README.md, docs/business-rules.md 기준) -->

- ✓ MES: 품번·BOM·공정 라우팅, 작업지시·실적(이전 공정 실적 없으면 차단), LOT·계보(분할·병합), 출하 — 기존
- ✓ 부적합 등록 → LOT과 하위 계보 전체 보류 → 투입·실적·출하 차단, MRB 처분 규칙 — 기존
- ✓ 검사: 승인된 검사기준만, 판정 후 수정 불가, 불합격 → 부적합 자동 등록, 검사원 자격 — 기존
- ✓ 계측기 교정 기한 지난 계측기 측정 거부 — 기존
- ✓ 4M 변경 후 초품 합격 전 출하 차단, 특별특성 SPC 경보 → 부적합 — 기존
- ✓ CAPA·내부심사·PPAP·고객 클레임(8D)·SCAR·문서·심사 증적·KPI·SPC — 기존
- ✓ 승인 서명(비밀번호 재입력), 승인 후 잠금, 삭제는 시스템 관리자만, 삭제·수정 요청 흐름 — 기존
- ✓ simple-history 변경 이력, 백업·복원, 엑셀 보고서·인쇄/PDF, 출하성적서 — 기존
- ✓ React SPA `/app/`: 품번·검사기준·관리계획서 상세(RecordPage), 검사 입력·결과, 종합현황, 내 할 일, 메모, LOT 이력 — 기존
- ✓ 운영 DB PostgreSQL 18 — fe17c1c

### Active

<!-- 승인된 계획: C:\Users\gogog\.claude\plans\twinkling-dreaming-lollipop.md -->

**B. 기록 화면 재설계 + Django 관리 화면 대체 (안 1 「머리 띠 + 오른쪽 열」)**

- [ ] B0: 공통 틀 `RecordShell`, `RecordPage` 겉모양 교체, 검사 상세 재작성(판정 띠·측정값 표·위치 막대·「⋯」 메뉴), 상세 API 읽기 전용 키 추가, DESIGN.md 「기록 화면 규칙」
- [ ] B1: 서버 기록 설명서 `core/records.py`, `records` API(목록·상세), `GenericRecordPage`(`/app/r/:app/:model/:id`), `record_url` 일원화 — 문서·문서 개정·계측기·검사원 자격
- [ ] B2: 범용 저장·추가 API, 편집 모드, 승인·수정 요청·삭제 요청 연결
- [ ] B3: LOT·부적합·보류(처분 서명 전용 본문, 보류 읽기 전용)
- [ ] B4: CAPA·클레임(+클레임 설정)·SCAR·4M 변경
- [ ] B5: 내부심사·체크리스트·심사 항목·PPAP
- [ ] B6: 작업지시·실적·출하·기준정보, 메뉴의 관리 화면 링크 정리

**A. 모듈 켜기/끄기 (M0 수정판)**

- [ ] A1: `core/modules.py` 대응표(requires/enhances), URL 전수 매핑 테스트, `ModuleSwitch` + 행 추가 데이터 마이그레이션, 미들웨어 판정, nav·me 필터
- [ ] A2: 라이선스 키(Ed25519, 표준 라이브러리 검증기), 만료 시 읽기 전용, 발급 스크립트
- [ ] A3: 끄기 전 열린 기록 검사, 시스템 관리자 종결 화이트리스트, 인터록 메시지에 원인 표시
- [ ] A4: 소비처 필터(due·notify·위젯·검색·타임라인·import·report·audit_pack·collect), 클레임 설정 메뉴 이동, 문서

### Out of Scope

- 삭제를 무효 처리(사유 기록)로 바꾸기 — 별도 업무 규칙 변경, 승인 필요
- 기준값(nominal)·소수 자릿수 모델 칸 — 스키마 변경, 별도 작업
- personal(연차·급여) 화면 이전 — 판매 모듈에서 빠짐, 코드·데이터는 유지
- Django 관리 화면 삭제 — 시스템 관리자 뒷방으로 남김
- 새 의존성·CDN·외부 폰트 — 오프라인 동작 원칙
- AI 기능 — 제품 비전에서 제외
- PR 기반 출시 — master 직접 push

## Context

- 스택: Python 3.12, Django 6.1, DRF, django-simple-history, openpyxl, waitress, whitenoise, htmx(동봉), PostgreSQL 18, React SPA(antd, `frontend/dist` 커밋).
- 앱 경계: `core`(기준정보·MES·공통), `qms`(품질), `personal`(개인). 역할 권한은 `qms/apps.py`의 `ensure_roles`가 migrate마다 다시 세팅한다.
- 관리 화면 등록 37종 중 28종은 관리 화면만 있다. 메뉴 44개 중 24개가 `/admin/`을 가리킨다.
- 관리 화면 주소를 직접 만드는 코드: `core/search.py`, `core/timeline.py`, `qms/overview.py`, `qms/widgets.py`, `qms/similar.py`, `qms/memo.py`, `qms/views.py`, `core/views.py:170,204,228`. `core/relations.py:80` `record_url`이 이미 「React 화면 있으면 `/app/`」 규칙을 가진다.
- 재사용 대상: `BaseAdmin` `begin_edit`/`finish_edit`, `delete_record`, `ReportLinksMixin`, `ApprovalAdminMixin`, `related_panel`, `capa_links`, 모델 `document()`; React `RecordPage`·`DataList`·`SaveBar`·`SignModal`·`EditGrid`·`RelationsPanel`·`MemoPanel`·`AttachmentPanel`·`AuditLog`.
- 검사 상세 API `qms/api/inspections.py:256-278`에 공급사·수량·샘플링·항목별 하한/상한/단위·계측기 이름·검사기준 승인자·CAPA가 빠져 있다. 모두 기존 모델에 있다.
- 테스트: `manage.py test`(464건, PostgreSQL), `scripts/e2e_check.py`(76), `scripts/e2e_browser.py`(43, 시스템 Python), `makemigrations --check --dry-run`, `npm run build`.

## Constraints

- **기술 스택**: 기존 스택 유지, 새 의존성 금지 — 오프라인 고객 PC에서 동작해야 함
- **업무 규칙**: `docs/business-rules.md`의 인터록·판정·승인 규칙은 모델(`clean()`/`save()`)·서버 뷰에서 강제, 약화 금지 — 품질 시스템의 존재 이유
- **데이터**: `data/` 운영 DB·첨부 삭제·덮어쓰기 금지, 데이터 마이그레이션은 행 추가만 — 고객 기록 보존
- **보안**: 권한은 서버에서 검사(`has_*_permission`, `require_perm`), 버튼 숨김만으로 막지 않음
- **이력**: 모든 업무 기록 simple-history 유지 — 심사 증적
- **언어**: 화면 문구·오류·커밋·문서는 한국어
- **출시**: 단계마다 테스트 통과 후 master 직접 push, PR 없음

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 기록 화면 배치 안 1 「머리 띠 + 오른쪽 열」 | 사용자 선택(2026-11-12) | — Pending |
| Django 관리 화면 대체 = React 공통 틀 + 서버 기록 설명서 + 범용 `records` API | 28종을 화면별로 다시 만들지 않고 설명서로 그림, 기존 로직 재사용 | — Pending |
| `record_url`을 유일한 주소 기준으로 | 화면을 옮길 때마다 링크가 저절로 따라감 | — Pending |
| 순서 B0 → A1~A4 → B1~B6 | B0는 A와 겹치지 않음, B1 이후 새 경로는 A 대응표에 바로 등록 | — Pending |
| 라이선스 서명 Ed25519, 표준 라이브러리 검증기 | 새 의존성 없음, RFC 8032 테스트 벡터로 검증 | — Pending |
| 모듈 행 없으면 꺼짐 + 기존 데이터 있는 모듈만 켜는 행 추가 마이그레이션 | 기존 고객이 업그레이드 후 기능을 잃지 않음 | — Pending |
| 꺼진 모듈: 일반 사용자 404, 시스템 관리자 GET + 종결 화이트리스트 | 풀 수 없는 인터록 방지 | — Pending |
| 부적합·보류는 기본 플랫폼(끌 수 없음) | 핵심 인터록 | — Pending |
| master 직접 push, PR 없음 | 사용자 결정 | — Pending |

## Evolution

이 문서는 단계 전환과 milestone 경계에서 갱신한다.

**단계 전환 후** (`/gsd-transition`):
1. 무효가 된 요구사항 → Out of Scope로 이유와 함께 옮김
2. 검증된 요구사항 → Validated로 단계 표시와 함께 옮김
3. 새 요구사항 → Active에 추가
4. 기록할 결정 → Key Decisions에 추가
5. 「What This Is」가 여전히 맞는지 확인

**Milestone 후** (`/gsd-complete-milestone`):
1. 전체 절 검토
2. Core Value 점검
3. Out of Scope 이유 재확인
4. Context를 현재 상태로 갱신

---
*Last updated: 2026-11-12 after initialization*
