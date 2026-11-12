# Project Research Summary

**Project:** QMS+MES (localhost) — 모듈 켜기/끄기(A) + 기록 화면 재설계·관리 화면 대체(B)
**Domain:** 온프레미스 Django + React QMS/MES (ISO 9001 / IATF 16949 / AS9100)
**Researched:** 2026-11-13
**Confidence:** MEDIUM-HIGH (코드 직접 확인 항목은 HIGH, 시장 관례·라이선스 만료 동작은 MEDIUM-LOW)

## Executive Summary

이 제품은 사내 PC 한 대에서 도는 QMS+MES다. 핵심 가치는 "부적합·인터록 규칙이 어떤 화면 변경이나 모듈 설정에서도 약해지지 않는 것"이다. 조사 결론은 새 의존성 없이 기존 스택(Django 6.1.2, DRF 3.18.3, antd 6, react-query, simple-history)만으로 A와 B를 모두 만들 수 있다는 것이다. 예외는 Ed25519 검증기 하나이며, 표준 라이브러리(`hashlib`, 정수 연산)로 직접 쓰고 RFC 8032 7.1절 벡터로 검증한다.

권고 접근은 두 갈래다. A(모듈 게이트)는 "대응표 한 장(`core/modules.py`) + 두 겹 문"으로 만든다. 거친 문은 `process_view` 미들웨어(fail-closed)이고 고운 문은 서비스·뷰 계층의 `can_write`/`assert_active`다. B(범용 기록 화면)는 서버 기록 설명서(`RecordSpec`) + APIView 기반 records API + `ModelForm` 검증으로 만든다. 저장은 항상 기존 `core.rules`(`save_with_lock` 등)를 거치고, 서명·승인·판정·처분 칸은 전용 엔드포인트로만 받는다.

가장 큰 위험은 세 가지다. (1) 범용 저장 API가 MRB 서명·승인·판정 칸을 그대로 받아 인터록과 서명을 우회하는 것. (2) 모듈 끄기·라이선스 만료가 풀 수 없는 인터록(보류 LOT, 4M 초품)이나 부적합 등록 불가 상태를 만드는 것. (3) 기존 고객이 라이선스 파일 없이 업그레이드해 기능을 잃는 것. 이 중 (2)(3)은 사용자 결정이 필요한 항목이라 해당 단계 착수 전에 확정해야 한다. 로드맵 순서는 승인된 계획대로 B0, A1, A2, A3, A4, B1, B2, B3, B4, B5, B6(11단계)이며 조사 결과는 이 순서를 바꾸지 않고 각 단계의 내용과 선행 조건만 구체화한다.

## 교차 조사에서 정정된 사항 (모든 단계 계획에 반영)

네 조사 파일이 공통으로 짚은, PROJECT.md·승인 계획과 어긋나는 지점이다. 로드맵과 단계 계획은 아래를 전제로 쓴다.

1. **`core/records.py`는 이미 있다.** `delete_record`, `is_locked`, `can_edit_locked`, `edit_unlocked`, `blockers` 등 삭제·잠금 규칙이 들어 있고 7곳 이상이 import한다. 새 설명서를 같은 이름으로 만들면 덮어쓰거나 깨진다. **`RecordSpec`은 `core/recordspec.py`**(틀·레지스트리), 모델별 설명서는 **`core/recordspecs.py`**와 **`qms/recordspecs.py`**(`QmsConfig.ready()`에서 등록)에 둔다. `core/records.py`는 건드리지 않는다. PROJECT.md B1의 "서버 기록 설명서 `core/records.py`" 표기를 정정해야 한다.
2. **`record_url`을 넓힌다.** 코드는 상세 주소뿐 아니라 목록(`?lot__id__exact=` 같은 admin 필터)과 추가(`..._add?lot=`) 주소도 직접 만든다. `core/relations.py`에서 `detail_url` / `list_url(label, **filters)` / `add_url(label, **initial)` 세 갈래 helper로 일원화한다. `list_url`의 필터 이름은 설명서의 `filters`에 선언된 것만 받는다(임의 ORM 조회 금지).
3. **모듈 게이트는 두 겹이다.** (거친 문) 미들웨어 `process_view`, 대응표에 없는 URL은 fail-closed. (고운 문) 서비스 계층 `can_write(obj, user)`/`assert_active(model)`. 미들웨어가 못 보는 경로는 뷰 안에서 반드시 검사한다: 범용 `/api/records/<label>/`, admin 자동완성(`admin:autocomplete`의 GET `app_label`·`model_name`), 첨부 `?ct=`, 메모 `?ct=`, 첨부 다운로드(`pk`만 받음), `edit_request`의 본문 대상. 미들웨어에서 `request.body`를 읽지 않는다. admin URL은 kwargs가 아니라 `url_name`(`admin:<app>_<model>_<action>`) 접두 파싱으로 판정한다.
4. **범용 저장은 `ModelForm`이다.** DRF `ModelSerializer`는 `Model.clean()`을 호출하지 않아 업무 규칙이 조용히 빠질 수 있다(구현 첫 테스트로 재확인). `modelform_factory(fields=요청 키 ∩ 설명서 쓰기 허용 칸)`을 쓴다. 쓰기 허용 칸 화이트리스트는 설명서마다 필수이며, 목록 밖 칸은 무시가 아니라 400으로 거부한다. 처분·승인·판정 칸(`approved_by`, `approved_at`, `closed_at`, `mailed_at`, `result`, `released_at`, `disposition` 등)은 전용 엔드포인트로만 쓴다. **admin의 `has_*_permission` 오버라이드를 그대로 보존**해야 한다(`HoldAdmin` 전부 False, 판정된 검사 변경 불가, `DocumentRevisionAdmin` 변경 불가, `PpapElementAdmin` 추가 불가). `ensure_roles`가 `delete_` 외 모든 권한을 두 역할에 주므로 모델 권한만으로는 부족하다. 변경은 PATCH + `version`(409)이다.
5. **`assert_usable`은 `_state.adding`일 때만 걸린다**(`core/models.py:256,352,593`). 범용 PUT이 기존 `Shipment`·`WorkResult`·`LotLink`의 LOT FK를 바꾸지 못하도록 LOT·작업지시·공정·검사기준·참조 FK는 생성 후 읽기 전용으로 둔다. `result`가 채워진 새 `Inspection` POST도 막는다(`finalize()` 우회 방지). `Inspection`·`Measurement`는 `qms.rules.submit_inspection` 경로만 쓴다.
6. **`ensure_roles`가 `ModuleSwitch`에도 add/change 권한을 자동 부여한다.** 품질엔지니어·품질팀장에서 제외하고, `has_change_permission`은 `is_superuser`만, `clean()`에서도 서버가 검사한다. 품질팀장 계정 테스트를 둔다.
7. **A1은 전수 테스트를 둘 둔다.** (a) `get_resolver()` 재귀 + admin URL을 `url_name`으로 분해해 모든 URL이 모듈 또는 BASE에 매핑됐는지. (b) 설명서 등록(`relations.is_registered`) 모델 전부가 `module_of_model`을 통과하는지. (b)가 B1 이후 새 설명서가 대응표 밖으로 나가는 것을 강제한다. 시드 마이그레이션은 **`qms/migrations`** 에 둔다(`core`의 `ModuleSwitch` 스키마에 의존, `core→qms` 역의존 금지). A1은 **자리표시 "모두 허용" 라이선스 구현**을 함께 두어 A1과 A2를 따로 출시해도 키 파일 없는 기존 고객이 기능을 잃지 않게 한다.
8. **Ed25519 검증기는 표준 라이브러리로 `core/ed25519.py`에 둔다.** RFC 8032 7.1절 벡터(빈 메시지, 1바이트, 2바이트, 1023바이트, SHA(abc)) + `S >= L` 거부, 비정규 인코딩 거부, 1비트 변조 거부, 왕복 테스트. 서명 대상은 원문 바이트(파일 = base64(payload) + base64(signature))이고 서명이 맞은 뒤에만 JSON을 읽는다. 결과는 `(경로, mtime_ns, size)` 키로 캐시한다. 개인키는 저장소 밖.
9. **B 단계마다 `npm run build` 후 `frontend/dist`를 같은 커밋에 넣는다.** master 직접 push·CI 없음 구조라 낡은 `dist`가 곧 고객 배포본이다.

## Key Findings

### Recommended Stack (STACK.md)

새로 설치할 것은 없다. `requirements.txt`, `frontend/package.json`은 변경하지 않는다.

**서버(기존 시설 재사용):**
- Django 6.1.2 클래스형 미들웨어 `process_view` — `resolver_match`가 이미 채워진 시점에서 `url_name`·namespace로 판정. `core/middleware.py`에 추가.
- `ModuleSwitch` 모델 + `HistoricalRecords()` — 켜기/끄기 이력이 심사 증적. 요청당 1쿼리, 캐시하지 않음(LocMemCache는 `manage.py` 변경을 못 본다).
- DRF `APIView`(`schema = None`) + `require_perm` + `ModelForm` — 기존 API와 같은 방식. `ModelViewSet`·`DefaultRouter`·`ModelSerializer`는 쓰지 않는다.
- `core.rules`(`save_with_lock`, `approve`, `delete_as`, `dispose_nc`, `sign_disposition`) — 범용 API는 새 업무 규칙을 만들지 않고 호출만 한다.
- `core.grid.record_version` — 동시 수정 409.

**화면:** antd 6.6.8 `Form`/`Select`/`DatePicker`, react-query 5, react-router-dom 7(선언형 `BrowserRouter`, `useBlocker` 불가), 기존 `RecordPage`·`SaveBar`·`SignModal`·`EditGrid`·`RelationsPanel`·`MemoPanel`·`AttachmentPanel`·`AuditLog`·`api()`.

**쓰지 않는 것:** `cryptography`/`PyNaCl`, `django-waffle`/`constance`, 권한 박탈 방식 모듈 끄기, `ModelAdmin.has_module_permission` 37곳 오버라이드, 경로 접두사 문자열 매칭, 기계 지문 바인딩, `react-hook-form`/`formik`/AG Grid/`axios`/`zustand`.

### Expected Features (FEATURES.md)

**Table stakes:** 모듈 단위 구성, 규격별 패키지 프리셋, 서버 측 접근 차단, 업그레이드 시 기존 데이터 보존, 만료 안내, 만료 후에도 데이터 읽기 보존, 끄기 전 열린 기록 검사, 시스템 관리자만 설정 변경 + 이력. 기록 화면은 머리 띠(번호·제목·상태), 기본정보 격자, 하위 표, 연결·첨부·메모·이력 오른쪽 열, 승인 서명·잠금, 수정·삭제 요청, 인쇄·엑셀, 칸별 검증 오류, 목록 화면.

**Differentiators:** 인터록이 모듈 on/off와 무관하게 모델에서 동작, 종결 화이트리스트(풀 수 없는 인터록 방지), 인터록 메시지에 원인 표시, 오프라인 Ed25519 라이선스, 라이선스(판매사)와 스위치(고객)의 AND 판정, 서버 `RecordSpec` 하나로 28종 화면 생성, 검사 결과 화면(판정 띠 + 측정값 표 + 공차 위치 막대).

**하지 않는 것(Anti-features):** 부적합·보류 모듈 끄기, 권한 제거로 모듈 숨기기, 만료 시 로그인 차단·데이터 숨김, 좌석 과금, 하드웨어 지문, 화면 레이아웃 사용자 편집, 화면에서 업무 규칙 재구현, 인라인 즉시 저장, 삭제의 무효 처리 전환(별도 승인).

**v1.x로 미룸:** 만료 임박 N일 전 경고(권장하나 Pitfall 5 때문에 A2에 포함하는 편을 권고), 켜기 전 점검 화면, 목록 열 설정 저장. **v2+:** AS9100 전용 모듈, 기준값·자릿수 칸.

### Architecture Approach (ARCHITECTURE.md)

의존 방향은 `qms → core` 자유, `core → qms`는 라벨 문자열 + `apps.get_model` 지연 참조만이다. 그래서 `core/modules.py`·`core/recordspec.py`는 qms 모델을 import하지 않는다.

**주요 컴포넌트:**
1. `core/modules.py` — 모듈 대응표(모델 라벨, `url_names`, requires/enhances, `open_records`, 종결 허용). 모든 판정의 단일 출처. 메뉴 항목의 모듈은 `nav_keys` 대신 url 이름에서 도출.
2. `core/license.py` + `core/ed25519.py` — 서명 검증과 mtime 캐시. A1에서는 "모두 허용" 자리표시.
3. `core/middleware.py` `module_gate` — 꺼짐은 일반 사용자 404(`/api/`는 `{'detail', 'code': 'module_inactive'}` JSON), 시스템 관리자 GET 허용, 쓰기는 종결 허용 모델만. SPA 껍데기 `/app/*`는 막지 않는다.
4. `core/recordspec.py` / `recordspecs.py` / `qms/recordspecs.py` — 설명서. 기본값은 `_meta`에서 파생, 예외만 선언. 허용 목록 방식(등록된 모델만 열림, `personal`과 이력 표는 자연히 제외).
5. `core/api/records.py` — `GET/POST records/<app.model>/`, `GET/PATCH records/<app.model>/<pk>/`, `POST .../actions/<name>/`, `.../options/?q=`(FK 선택지, 대상 `view_` 권한 확인 후 20건).
6. `core/relations.py` — `detail_url`/`list_url`/`add_url`. 설명서 레지스트리를 보고 `/app/…`로, 없으면 admin 주소로 폴백.
7. 프런트 `RecordShell`(B0), `GenericRecordPage`(`/app/r/:app/:model/:id`, B1), `ModuleOff.tsx`(A1).

**핵심 패턴:** 대응표 한 장에서 모든 판정 도출 / 두 겹 문 / 설명서 기본값은 `_meta` / 범용 API는 설명서를 통해서만 열고 저장은 기존 규칙 함수로 / 공통 틀 + 전용 본문 슬롯. 종결 허용은 URL이 아니라 `(모델 라벨, 열린 상태 술어)`로 쓴다(admin 변경 폼 POST는 종결과 일반 수정을 URL로 구분할 수 없다). 서버 `nav_url`이 `/app/…`를 직접 내려 `AppLayout.tsx`의 `MOVED` 표를 점차 비운다.

### Critical Pitfalls (PITFALLS.md, 상위 5)

1. **범용 저장이 서명·승인 칸을 받는다**(Pitfall 1) — MRB 서명은 모델이 아니라 admin 폼 `NonconformanceForm`과 `rules.sign_disposition`에 있다. 화이트리스트 필수, 목록 밖 칸은 400, 처분·승인·판정은 전용 엔드포인트. 구조를 B1에서 잘못 잡으면 B2~B6이 오염된다.
2. **모델 권한만 검사해 admin의 행 단위 규칙이 사라진다**(Pitfall 2) — admin `_registry`의 `has_*_permission`과 동등한지 모델 × 동작 × 역할 전수 대조 테스트. 설명서에 없는 모델·동작은 기본 거부. Hold는 읽기 전용으로만 등록.
3. **모듈 끄기·만료가 풀 수 없는 인터록을 만든다**(Pitfall 4, 5) — 끄는 경로가 셋(스위치, 라이선스 변경, 만료)인데 `open_records` 검사는 하나다. 4M 초품 해제 수단은 검사 판정뿐이고, 재작업·수리 처분도 재검사 합격이 필요하다. 만료 시 모든 쓰기 거부는 부적합 등록과 보류 해제까지 막는다.
4. **라이선스 없는 기존 고객 업그레이드**(Pitfall 6) — "행 없으면 꺼짐 + 라이선스 없으면 기본 플랫폼만"이 겹치면 업그레이드 즉시 검사·CAPA·출하가 404가 된다. 검증 실패는 예외가 아니라 안전한 기본값으로 떨어져야 한다(fail-safe, fail-open 아님).
5. **URL 외 경로의 모듈 누수와 테스트 우회 스위치**(Pitfall 7, 10) — 첨부·autocomplete·`edit_request`는 URL만으로 모델을 모른다. 게이트 켜는 순간 기존 464건 테스트가 404로 깨지는데 `MODULE_GATE=False` 같은 우회 스위치를 만들면 안 된다. 테스트 믹스인이 `ModuleSwitch` 전체 켜기 + 테스트 키 서명 라이선스를 심는다.

그 밖의 중요 항목: 승인된 수정 요청 동시 소모(12, `select_for_update` + 조건부 갱신), 낙관적 동시성(13), admin `save_model`/`get_form`/`limit_choices_to` 누락(14), admin 주소 잔존(15, `reverse('admin:` grep 테스트), 숫자 서식과 서버 `passed` 불일치(16), B0 읽기 키의 권한·모듈 누수(17), `frontend/dist` 누락(18), `RecordPage` props 계약·e2e 선택자 파손(19).

## Implications for Roadmap

순서는 승인된 계획으로 고정이다: **B0 → A1 → A2 → A3 → A4 → B1 → B2 → B3 → B4 → B5 → B6**. 이 순서가 맞는 이유는 B0가 A와 겹치지 않고, A1이 A·B 전체의 바닥이며, B1 이후의 새 경로가 A 대응표에 바로 등록되는 구조를 A가 먼저 만들어 두기 때문이다.

### Phase 1: B0 — 공통 틀과 검사 상세
**Rationale:** A와 독립이고 지적 사항 4건을 직접 해결하며 이후 모든 B의 기반이다.
**Delivers:** `RecordShell`, `RecordPage` 겉모양 교체(props 계약 유지), 검사 상세 재작성(판정 띠·측정값 표·위치 막대·「⋯」 메뉴), 상세 API 읽기 키 추가(`qms/api/inspections.py:256-278`), `lib/num.ts`, DESIGN.md 「기록 화면 규칙」, `RecordPage.status` 타입을 `status.tone` 기반으로 확장.
**Avoids:** Pitfall 16(항목별 서버 `passed` 사용, Decimal은 문자열, 측정값을 반올림하지 않음, 경계값 e2e), 17(신규 읽기 키마다 대상 모델 `view_` 권한 확인, 모듈 필터 후크 자리), 19(기준선 e2e 먼저, 스크린샷 4화면 × 라이트·다크 × 390px), 18(`npm run build` + `dist` 커밋).
**Research flag:** 불필요. 기존 코드가 선례.

### Phase 2: A1 — 모듈 대응표·ModuleSwitch·게이트 뼈대
**Rationale:** A·B 전체의 바닥. 전수 테스트가 있어야 이후 모든 새 경로가 대응표에 들어간다.
**Delivers:** `core/modules.py`(BASE 포함, `module_of_model/request`, `active()`), 전수 테스트 2종, `ModuleSwitch`(`core` 스키마) + `qms` 시드 마이그레이션(행 추가만, `get_or_create` 멱등, reverse는 만든 행만 삭제), `module_gate`(fail-closed, 위 정정 3번의 우회 경로 포함), `visible_nav`·`me_payload.modules` 필터, `ModuleOff.tsx`(404 본문 `code`), 자리표시 "모두 허용" 라이선스, 테스트 시드 믹스인.
**Avoids:** Pitfall 7, 8(`ensure_roles` 제외), 9(마이그레이션 위치·대표 모델 표 확정), 10(우회 스위치 금지), 4(`active()` 변경 경로 일원화), 6(기본값), 23.
**Research flag:** 불필요(패턴 확정). 단 운영 DB 사본으로 시드 결과를 확인한다(`docs/testing.md`, `backup` 선행).

### Phase 3: A2 — 라이선스 키와 만료 읽기 전용
**Rationale:** 판매 가능 조건. A1의 `active()`에 끼워 넣는다.
**Delivers:** `core/ed25519.py`, `core/license.py`(mtime 캐시, 지연 로딩, 예외를 가둠), `scripts/issue_license.py`(requires 닫힘 검증, 개인키는 저장소 밖), 만료 14일 전 경고와 만료 띠, 만료 시 쓰기 거부 + 예외 목록, 시계 되돌림 하한(simple-history 최대 시각, 권고).
**Avoids:** Pitfall 5(만료 정책), 11(원문 바이트 서명, 가변성·변조 테스트), 6(키 없음·손상·서명 오류는 기본 플랫폼 + 시스템 관리자 배너).
**Research flag:** **필요.** 만료·레거시 정책은 사용자 결정(아래 결정 1, 2) 선행. Ed25519 구현은 RFC 원문 대조.

### Phase 4: A3 — 끄기 전 검사와 종결 허용
**Rationale:** 핵심 가치(인터록 보존) 보장 단계. 두 겹 문이 전제다.
**Delivers:** 모듈별 `open_records` 술어, `modules.can_write(obj, user)`(`BaseAdmin.has_change_permission`과 이후 records API가 공유), 종결 허용을 `(라벨, 열린 상태)`로 열거(실제 호출 가능한 동작만), 라이선스 교체 화면에서 비활성이 될 모듈의 열린 기록 경고, 인터록 메시지에 원인 모듈 표시, "전 모듈 끔" 행렬 테스트(`docs/business-rules.md` 1~9절 전부), `core/modules.py`가 모델·rules에서 import되지 않는 방향 테스트.
**Avoids:** Pitfall 4, 25.
**Research flag:** **필요.** 모듈별 "열린 기록" 정의와 4M 초품 해제 수단은 도메인 확인 + 사용자 결정(아래 결정 1, 3, 4).

### Phase 5: A4 — 소비처 필터와 링크 helper 치환
**Rationale:** A4가 열 파일(`qms/due.py`, `widgets.py`, `overview.py`, `core/search.py`, `timeline.py`)은 B1이 `record_url`로 바꿀 파일과 거의 같다. 한 번만 연다.
**Delivers:** 소비처 필터(due·notify·위젯·검색·타임라인·importer·report·`audit_pack`·collect·첨부·autocomplete·기본 플랫폼의 모듈 연결 칸), `group_payload` 단계에서 "비활성 모듈 기록 N건"(`relations_for`의 `@cache`는 건드리지 않음), `reverse('admin:…')`를 `detail_url`/`list_url`/`add_url`로 치환(해결 결과는 아직 admin 주소), 클레임 설정 메뉴 이동, README·`docs/` 갱신.
**Avoids:** Pitfall 7, 15(grep 테스트 도입), 23, 24, 6(업그레이드 순서 문서).
**Research flag:** 불필요(목록 작업). 결정 6(감사 로그 탭 공개)은 B1 전에 확정.

### Phase 6: B1 — 설명서·records API(읽기)·GenericRecordPage
**Rationale:** 위험이 낮은 4종(문서·문서 개정·계측기·검사원 자격)으로 틀을 검증한다. 설명서 구조의 잘못은 B2~B6 전체를 오염시킨다.
**Delivers:** `core/recordspec.py`(쓰기 허용 칸 화이트리스트 필수 구조, `_meta` 기본값, `exclude`, `select_related` 필수, 권한은 admin `has_*_permission` 동등 호출 또는 `RecordSpec.can`), `core/api/records.py`(목록·상세·options), `GenericRecordPage`, 레지스트리 기반 `record_url`/세 갈래 helper, `/api/records/…`와 `app.model` 라벨 판정을 모듈 게이트에 등록, 모델별 admin 오버라이드 대응 체크리스트(이후 B 단계 완료 기준), 기록별 변경 이력 엔드포인트(`view_` 기준 vs 품질팀장 전용은 결정 6).
**Avoids:** Pitfall 1, 2, 14, 15, 22(`assertNumQueries`), `personal` 등록 금지 테스트.
**Research flag:** 구조 확정 단계라 계획 시 `/gsd-plan-phase --research-phase` 권장(권한 동등성 표, `FieldDef`/`extra` 사용 여부 확인).

### Phase 7: B2 — 범용 저장·편집 모드·승인/요청 연결
**Rationale:** B3~B6이 모두 의존하는 쓰기 경로. 규칙 코드를 새로 쓰지 않는다.
**Delivers:** PATCH + `version`(409), 생성 후 읽기 전용 FK, `save_with_lock` 단일 경로(`records` 소스에 직접 `.save(` 금지 린트 테스트), `edit_unlocked`에 `select_for_update` + `finish_edit` 조건부 갱신(동시 2회 저장 중 1회만 성공), 하위 표는 행 id 기반 + 명시적 삭제 목록, `delete_record` 경유 삭제, 승인·수정 요청·삭제 요청 연결, 서명 검증 대상은 항상 `request.user`, 만료·꺼진 모듈에서 범용 저장 거부 테스트, 사용자 정의 칸(`extra`) 변환의 `core/` 공유 여부 확인.
**Avoids:** Pitfall 1, 3, 12, 13, 20, 21.
**Research flag:** **필요.** `submit_edit_request` 추출(결정 5) 사용자 승인 후 착수, `ApprovalAdminMixin`/`ReportLinksMixin` 동작을 액션으로 옮기는 범위 확인.

### Phase 8: B3 — LOT·부적합·보류
**Rationale:** 핵심 인터록이 닿는 단계라 전용 본문을 쓴다.
**Delivers:** 처분 서명 전용 본문(`sign_disposition`/`dispose_nc` 전용 액션), 보류는 읽기 전용(쓰기 동작 미정의), 부적합은 범용 저장 경로에서 제외, 범용 PUT·PATCH로 처분·승인·보류 해제가 우회되지 않음을 증명하는 테스트(품질엔지니어·시스템 관리자 양쪽), 부적합 화면의 CAPA/클레임/SCAR 칸을 모듈 꺼짐 시 숨기되 값 보존, 재작업·수리 처분이 `qms_inspection` 없이 불가함을 화면이 이유와 함께 표시.
**Avoids:** Pitfall 1, 3, 20, 21, 24.
**Research flag:** **필요.** 우회 불가 증명 테스트 설계.

### Phase 9: B4 — CAPA·클레임(+설정)·SCAR·4M 변경
**Delivers:** 설명서 4묶음, 8D 단계 같은 하위 표, 종결 액션을 `closing=True`로 A3의 종결 허용 규칙과 연결(규칙은 한 번만 기술), `qms/admin.py` 오버라이드 대응표 검증.
**Avoids:** Pitfall 13, 14, 15, 27.
**Research flag:** 불필요. B1~B3 패턴 반복. 4M 초품 해제 경로는 결정 3 반영.

### Phase 10: B5 — 내부심사·체크리스트·심사 항목·PPAP
**Delivers:** 설명서 묶음, 심사 지적 하위 표, `PpapElementAdmin` 추가 불가 규칙 보존.
**Avoids:** Pitfall 13, 14, 15.
**Research flag:** 불필요.

### Phase 11: B6 — 작업지시·실적·출하·기준정보와 메뉴 정리
**Rationale:** 마지막. 기준정보는 `FieldDef`가 만드는 `extra` JSON 칸 때문에 정적 선언만으로는 안 되는 유일한 곳이다.
**Delivers:** 설명서 묶음, `FieldDef` 기반 동적 칸, 기준정보는 삭제 대신 「사용」 끄기(모델별 삭제 가능 여부를 설명서에 둠), 메뉴의 `/admin/` 링크 정리(서버가 최종 주소를 내려 `MOVED` 제거), grep 허용 목록을 0으로, e2e 메뉴 점검 갱신.
**Avoids:** Pitfall 3(작업지시·실적·출하의 LOT 읽기 전용), 15, 26, 27.
**Research flag:** **필요**(`FieldDef`/`extra` 동적 칸).

### Phase Ordering Rationale

- B0는 프런트 겉틀뿐이라 A와 충돌하지 않는다. `RecordPage.status` 타입 확장을 B0에서 끝내야 B1이 의존할 수 있다.
- A1에서 전수 테스트 2종과 자리표시 라이선스를 만들어야 "새 경로는 A 대응표에 바로 등록"이 약속이 아니라 강제가 된다.
- A3의 두 겹 문은 B4(화면 이전) 전에 CAPA·클레임·SCAR·4M·심사 종결을 열어 두는 유일한 방법이다. A3 없이는 B4 이전에 풀 수 없는 인터록이 생긴다.
- A4가 만지는 파일은 B1이 바꿀 파일과 겹치므로 A4에서 helper로 치환해 두면 B1~B6은 `register()` 한 줄로 링크가 따라간다.
- B2 시작 전에 규칙 함수가 `core/rules.py`에 있어야 한다(결정 5 승인 시 추출). B3는 B2의 편집을 쓰지 않는다.
- 위험 순서: 위험이 낮은 4종(B1) → 쓰기(B2) → 핵심 인터록(B3) → 반복(B4, B5) → 동적 칸(B6).

### Research Flags

**깊은 조사 필요:** A2(만료·레거시 정책, Ed25519), A3(열린 기록 술어·종결 수단), B1(권한 동등성 구조), B2(`submit_edit_request` 추출 범위), B3(우회 불가 증명), B6(`FieldDef` 동적 칸).
**표준 패턴(조사 생략 가능):** B0, A1, A4, B4, B5.
**공통:** A1·B1 시점마다 PostgreSQL 마이그레이션 결과를 운영 DB 사본으로 확인한다.

## 사용자 결정이 필요한 열린 항목 (이 문서는 결정하지 않는다)

> **2026-11-13 갱신:** 사용자가 "나만 사용할거야. 판매용이 아니야."라고 밝혔다. 위 본문의 라이선스(Ed25519·만료 읽기 전용·자리표시 라이선스·시드 마이그레이션)·패키지·레거시 고객 내용은 무효다. 로드맵은 A2를 빼고 10단계(B0, A1, A3, A4, B1~B6)다. 모듈 행이 없으면 켜짐이다.

AGENTS.md상 핵심 업무 규칙·보안 변경·요청받지 않은 리팩터링은 사전 승인 대상이다. 아래는 해당 단계 착수 전에 사용자에게 무엇을, 왜, 되돌릴 방법과 함께 물어야 한다.

| # | 결정 사항 | 필요한 시점 | 쟁점 |
|---|-----------|-------------|------|
| 1 | ~~라이선스 만료 읽기 전용 상태에서 MRB 처분 등 허용~~ **해소(2026-11-13): 본인 전용·판매용 아님, 라이선스·A2 삭제** | — | 허용 안 하면 만료일에 불량을 시스템에 못 올려 격리·보류가 안 걸리고 보류 LOT을 풀 수도 없다(Core Value 충돌). 허용하면 "만료 시 모든 쓰기 거부" 계획과 달라진다. 허용 범위: 보류를 거는 방향(부적합 등록·메모·불합격 입력)만인지, 인터록을 푸는 처분·초품 판정까지인지. |
| 2 | ~~라이선스 없는 기존 고객~~ **해소(2026-11-13): 모듈 행 없으면 켜짐, 시드 마이그레이션 없음** | — | "행 없으면 꺼짐 + 키 없으면 기본 플랫폼만"이면 업그레이드 즉시 기능 소실. 유예(N일) 후 읽기 전용, 또는 기존 데이터 모듈은 계속 허용 등 정책 선택. A1은 자리표시 "모두 허용"으로 임시 안전하지만 A2 이후 정책 확정 필요. |
| 3 | **검사 모듈이 꺼졌을 때 4M 초품 해제** 수단 | A3 | 해제 수단이 검사 판정뿐이라 `qms_inspection`이 꺼지면 해제 경로가 사라진다. 시스템 관리자에게 검사 판정을 허용할지, 수동 해제 규칙을 신설할지(둘 다 업무 규칙 변경). |
| 4 | **해소·구현(2026-11-13):** LOT FK가 바뀔 때만 다시 검사(`core/models.py` `lot_changed`), 같은 LOT 정정은 허용 | — | 현재 `assert_usable`은 생성 시에만 걸린다. 범용 편집이 열려도 안전하려면 FK 읽기 전용(조사 권고)으로 충분한지, 모델 수준에서 update에도 걸지(규칙 강화·기존 데이터 영향)를 결정. |
| 5 | **B2에서 `edit_request`/`approve` 로직을 `core/rules.py`로 추출**(예: `submit_edit_request`) | B2 착수 전 | AGENTS.md의 "요청받지 않은 리팩터링 금지"에 걸린다. 동작 불변·기존 테스트가 회귀망이라는 전제로 승인 요청. 거부하면 범용 API가 뷰 로직을 복제해 규칙이 두 군데가 된다. |
| 6 | 기록별 **변경 이력(감사 로그) 탭의 열람 권한** | B1 착수 전 | 기존 `/api/audit-log/`는 품질팀장 전용. 상세 화면의 이력 탭을 `view_` 권한 기준으로 열지, 품질팀장 전용으로 둘지. 보안·정보 노출 정책. |

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | 설치 버전·lock 파일·Django 소스(`resolver_match` 시점)를 직접 확인. Ed25519 RFC 코드 형태와 DRF `ModelSerializer`의 `clean()` 미호출은 기억 기반(MEDIUM-HIGH)이라 구현 첫 단계에서 RFC 원문·작은 테스트로 확인. |
| Features | MEDIUM | 규제 요건(변경 이력·전자서명·인터록)은 HIGH. 상용 제품의 화면 배치·라이선스 약관은 마케팅 자료 위주(MEDIUM). 라이선스 만료 후 읽기 전용 동작은 공개 자료로 확인 못 함(LOW), 결정에는 영향 없음. |
| Architecture | HIGH | 코드와 승인 계획을 직접 읽음. "권장" 표시 항목(레지스트리 위치, 두 겹 문, 링크 세 갈래, 마이그레이션 위치, 캐시 원칙, A4 + helper 동시 처리)은 MEDIUM이며 단계 계획에서 확정. |
| Pitfalls | HIGH / MEDIUM | 코드로 확인한 항목(1~9, 12, 13)은 HIGH. 일반 도메인 경험 항목(5의 시계 되돌림, 11의 구현 오류 양상, 일부 성능)은 MEDIUM. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **셸 미동작:** 조사 중 Bash가 동작하지 않아 `manage.py`·테스트를 실행하지 못했다. 모든 내용이 코드 읽기와 grep 근거다. 각 단계 착수 시 `manage.py test`, `makemigrations --check --dry-run`, `scripts/e2e_check.py`, `scripts/e2e_browser.py`, `npm run build`를 실제로 돌려 기준선을 남긴다.
- **PROJECT.md·계획 문서 정정:** B1의 `core/records.py` 표기와 A1의 "`/admin/<app>/<model>/…`는 kwargs로 판정" 문구가 부정확하다(admin은 `url_name` 파싱). 로드맵 작성 시 반영한다.
- **모듈별 "열린 기록" 정의와 대표 모델 표**(예: 열린 작업지시, 미판정 검사, KPI·문서의 파생 규칙)가 미확정이다. A1(시드 대표 모델)과 A3(`open_records`)에서 도메인 확인이 필요하다.
- **4M 초품 해제·재작업 재검사의 모듈 간 의존**(`qms_change`→`qms_inspection`, 부적합→검사)을 `requires`에 반영할지 결정 3과 함께 확정한다.
- **`FieldDef`/`extra` 처리 범위:** `ExtraFieldsForm`(`extra__<키>` → `extra` JSON)이 admin에만 있다. B1에서 대상 모델의 `extra` 사용 여부를 확인하고 B6에서 공유 변환을 `core/`로 옮긴다.
- **시계 되돌림 방지는 권고 수준**이며 소스가 고객 PC에 있어 완전 방어는 불가능하다. 문서에 한계를 그대로 적는다.
- **상용 QMS 화면 배치 표준 부재:** "머리 띠 + 오른쪽 열"은 사용자가 이미 선택한 안이고 요소 구성이 시장 필수 요소와 일치함만 확인했다.

## Sources

### Primary (HIGH confidence)
- 이 저장소 코드: `requirements.txt`, `frontend/package.json`·`package-lock.json`, `config/settings.py`·`urls.py`, `core/{middleware,records,rules,grid,nav,relations,audit,models,admin,views}.py`, `core/api/{urls,views,master,permissions,exceptions}.py`, `qms/{models,admin,apps,rules}.py`, `qms/api/{urls,specs,inspections,plans}.py`, `frontend/src/{main.tsx,api/client.ts,layout/AppLayout.tsx,components/RecordPage.tsx,pages/specs/SpecPage.tsx}`
- `.venv` 내 Django `core/handlers/base.py`(`resolver_match` 시점), simple-history `middleware.py`, antd `useForm.d.ts`
- `docs/business-rules.md`, `docs/architecture.md`, `.planning/PROJECT.md`, 승인된 계획 `C:\Users\gogog\.claude\plans\twinkling-dreaming-lollipop.md`
- Oracle MES 부적합 e-record 공식 문서

### Secondary (MEDIUM confidence)
- SimplerQMS·QT9·isoTracker·SG Systems Global·IQVIA SmartSolve의 가격·라이선스·NCR 자료(마케팅·벤더 글)
- RFC 8032 구조·테스트 벡터·가변성 요건(기억 기반, 구현 시 원문 확인), DRF `ModelSerializer`의 `clean()` 미호출
- 온프레미스 제품의 일반적 실패 양상(라이선스 만료 정책, 성능)

### Tertiary (LOW confidence)
- 상용 제품의 만료 후 동작(공개 자료 없음, 결정에 영향 없음)

---
*Research completed: 2026-11-13*
*Ready for roadmap: yes (결정 1~6은 해당 단계 착수 전 사용자 승인 필요)*
