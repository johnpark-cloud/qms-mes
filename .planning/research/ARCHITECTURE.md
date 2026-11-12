# Architecture Research

**Domain:** 사내 설치형 Django + React QMS/MES (Django 6.1, DRF, React SPA `/app/`)
**Researched:** 2026-11-12
**Confidence:** HIGH (코드·승인 계획서 직접 읽음). 단, 아래 「권장」 표시는 계획서에 없는 내 제안이라 MEDIUM이며 phase 계획 때 확정한다.

범위: (A) 모듈 켜기/끄기, (B) 범용 기록 화면(`RecordSpec` + `records` API + `RecordShell`/`GenericRecordPage`)이 기존 구조에 어디에 앉고, 무엇이 무엇과 말하며, 어떤 순서로 지어야 하는가.

---

## 먼저 알아야 할 충돌과 발견 (계획서와 코드가 어긋나는 곳)

| # | 발견 | 영향 | 권장 |
|---|------|------|------|
| 1 | **`core/records.py`는 이미 있다.** 삭제(`delete_record`)·잠금(`is_locked`, `can_edit_locked`, `edit_unlocked`) 규칙 파일이며 `core/rules.py`, `core/admin.py`, `core/views.py`, `core/models.py:637`, `qms/api/specs.py`, `qms/api/plans.py`, `qms/admin.py`가 import한다. 계획서는 「새 파일」이라고 적었다. | 같은 이름에 덮어쓰면 위 7곳이 깨진다. 업무 규칙 파일이라 약화 금지 대상이기도 하다 | 기록 설명서는 **`core/recordspec.py`**(레지스트리·`RecordSpec`), 모델별 설명서 등록은 앱 쪽(`qms/recordspecs.py`, `core/recordspecs.py`). `core/records.py`는 건드리지 않는다. 문서·계획의 「core/records.py」 표기를 고친다 |
| 2 | **`record_url`은 상세 주소만 푼다.** 코드는 상세뿐 아니라 목록(`admin:..._changelist` + `?lot__id__exact=` 같은 관리 목록 필터)과 추가(`..._add?lot=`)도 직접 만든다: `qms/widgets.py:156-243`, `qms/overview.py:23`, `core/timeline.py:44`, `qms/views.py:232`, `core/admin.py:67-68 related_panel`, `core/nav.py`(30곳). | `record_url`만 일원화하면 목록·추가·필터 링크가 `/admin/`에 계속 남는다. 관리 목록 필터 문법(`lot__id__exact`)은 Django 관리 화면 전용이라 `records` 목록 API도 같은 걸러내기 입력을 받아야 한다 | `record_url`을 **`detail_url` / `list_url(label, **filters)` / `add_url(label, **initial)`** 세 갈래로 넓힌다(권장, 아래 「링크 한 곳」) |
| 3 | **프런트에 두 번째 주소표가 있다.** `frontend/src/layout/AppLayout.tsx`의 `MOVED`가 서버 메뉴 href(`/admin/qms/controlplan/` 등)를 새 주소로 바꿔 준다. | 서버 `core/nav.py`와 클라이언트 `MOVED`가 따로 늘어난다. B1~B6에서 화면을 옮길 때마다 두 곳을 고쳐야 한다 | 서버 `nav_url`이 레지스트리를 보고 `/app/...`를 직접 내려주게 하고 `MOVED`는 단계적으로 비운다 |
| 4 | **삭제·수정 요청 로직이 뷰 안에 있다.** `core/views.py:160-195 edit_request`는 EditRequest 생성 + 관리자 즉시 승인이 뷰 본문이다(`approve`는 이미 `rules.approve`). | B2의 범용 API가 같은 흐름을 부르려면 규칙이 `core/rules.py`에 있어야 한다. 복붙하면 규칙이 두 군데가 된다 | B2 시작 때 `core/rules.py`에 `submit_edit_request(obj, kind, user, reason, password)`를 뽑고 기존 뷰도 그것을 부른다(동작 불변, 기존 테스트가 회귀망) |
| 5 | **관리 화면 URL은 `url_name`이 모델을 담는다.** `admin:<app>_<model>_<changelist|add|change|history|delete>`이고 `path`에 kwargs가 없다(`app_label`/`model_name` kwargs는 `approve/`, `request/`, `print/` 같은 우리 뷰에만 있다). 계획서의 「`/admin/<app>/<model>/…`는 kwargs로 판정」은 정확하지 않다. | 미들웨어가 kwargs만 보면 관리 화면 전체가 새 나간다 | `module_of_request`는 ① 우리 뷰 kwargs ② 관리 `url_name` 접두 파싱 ③ **관리 자동완성**(`admin:autocomplete`는 GET `app_label`·`model_name`·`field_name`)·`admin:app_list`(`app_label` kwarg)까지 본다. URL 전수 테스트가 admin 패턴을 `url_name`으로 분해해 모델 매핑을 확인해야 한다 |
| 6 | **`ModelPerms`·`require_perm`·`has_*_permission`은 모듈을 모른다.** `ensure_roles`가 migrate마다 권한을 다시 세팅하므로 권한 제거는 못 쓴다(계획서도 같은 결론). | 모듈 판정은 권한 계층 옆의 별도 계층이다 | 판정은 미들웨어(거친 문) + 개체 수준 훅(고운 문) 두 겹(아래 패턴 2) |

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 브라우저                                                                   │
│  React SPA /app/ (frontend/src)                    Django 화면 /todo/ 등   │
│  ┌────────────┐ ┌──────────────┐ ┌─────────────────┐   /admin/ (뒷방)     │
│  │ AppLayout  │ │ RecordShell  │ │ GenericRecordPage│                      │
│  │ nav·me     │ │ (겉틀)       │ │ /app/r/:app/:model/:id                  │
│  │ 모듈 안내  │ │ RecordPage→  │ │ 설명서만으로 그림 │                      │
│  └─────┬──────┘ └──────┬───────┘ └────────┬────────┘                      │
└────────┼───────────────┼──────────────────┼───────────────────────────────┘
         │ /api/auth/me/ │ 기존 전용 API    │ /api/records/...
═════════╪═══════════════╪══════════════════╪═══════ HTTP (세션·CSRF) ═══════
┌────────▼───────────────▼──────────────────▼───────────────────────────────┐
│ ① 미들웨어 계층 (config/settings.py MIDDLEWARE)                            │
│   Session → Auth → … → HistoryRequest → [core.middleware.module_gate]      │
│   → no_store_pages                       ▲ 신규: process_view에서 판정      │
│        module_gate 는 core/modules.py 와 core/license.py 만 부른다          │
├────────────────────────────────────────────────────────────────────────────┤
│ ② 라우팅 (config/urls.py → core/api/urls.py → qms/api/urls.py)             │
│   기존 전용 API  +  신규 core/api/records.py (범용, 라벨을 URL 인자로)      │
├────────────────────────────────────────────────────────────────────────────┤
│ ③ 판정·설명 계층 (core, qms 모델을 라벨 문자열로만 안다)                    │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐ ┌────────────────────┐   │
│  │core/modules│ │core/license│ │core/recordspec│ │core/relations.py   │   │
│  │ 대응표·active│ │ 서명 검증·캐시│ │ RecordSpec 레지스트리│ │ record_url→링크 한 곳│   │
│  │ open_records│ │ core/ed25519│ │ + qms/recordspecs│ │ relations_for(@cache)│   │
│  └─────┬──────┘ └────────────┘ └───────┬──────┘ └─────────┬──────────┘   │
│        │ 소비: nav · me · due · notify · widgets · search · timeline ·      │
│        │       importer · report · audit_pack · collect · relations        │
├────────┼───────────────────────────────────────────────────────────────────┤
│ ④ 업무 규칙 계층 (바꾸지 않는다)                                            │
│   core/rules.py (save_with_lock, approve, delete_as, sign_disposition)     │
│   core/records.py (is_locked, can_edit_locked, delete_record)              │
│   qms/rules.py (검사 판정·저장)   모델 clean()/save() 인터록                │
├────────────────────────────────────────────────────────────────────────────┤
│ ⑤ 저장소: PostgreSQL 18 (+ simple-history)   data/license.key (파일)        │
│   신규 core.ModuleSwitch(key unique, enabled, changed_by, changed_at)       │
└────────────────────────────────────────────────────────────────────────────┘
```

의존 방향은 현재 규칙을 지킨다: `qms → core`는 자유, `core → qms`는 라벨 문자열 + `apps.get_model` 지연 참조만, `personal`은 어느 쪽도 import하지 않는다. 그래서 **`core/modules.py`·`core/recordspec.py`는 qms 모델을 import하지 않는다.** qms 쪽 설명서는 `qms/recordspecs.py`가 `QmsConfig.ready()`에서 `core.recordspec.register(...)`로 밀어 넣는다(권장, 기존 `qms/apps.py`의 `ensure_roles` 훅과 같은 자리).

### Component Responsibilities

| 컴포넌트 | 책임 | 실제 위치 | 말하는 상대 |
|----------|------|-----------|-------------|
| 모듈 대응표 | 모듈 키 → `models`(라벨), `url_names`/`url_prefixes`, `spa_paths`, requires/enhances, `open_records` 검사, 종결 허용 목록. `module_of_model/request`, `active(key)`, `active_set()` | **신규 `core/modules.py`** (순수 파이썬 상수 + 함수) | `ModuleSwitch`, `core/license.py`, 미들웨어·소비처 전부 |
| 모듈 스위치 | 고객 관리자의 켜기/끄기. 행 없으면 꺼짐. 시스템 관리자만, `clean()`에서 license·requires 검사, `history = HistoricalRecords()` | **신규 `core/models.py` `ModuleSwitch`** + `core/admin.py`(BaseAdmin) | `core/modules.py` |
| 라이선스 | `data/license.key` 서명 검증(Ed25519), 만료일, 허용 모듈. 결과를 mtime 키로 캐시 | **신규 `core/license.py`, `core/ed25519.py`**, 발급은 `scripts/issue_license.py`(저장소 밖 개인키) | `core/modules.active()`, 미들웨어(만료 시 쓰기 거부) |
| 모듈 문 | 요청마다 `process_view`에서 판정: 꺼진 모듈 → 일반 404 / 관리자 GET만 / 만료 라이선스 → 쓰기 403 | **신규 `core/middleware.py` `module_gate`** (기존 `no_store_pages` 옆) | `core/modules.py`, `core/license.py` |
| 메뉴 필터 | `visible_nav`가 꺼진 모듈 항목을 거른다. `me_payload`에 `modules` 추가 | `core/nav.py`, `core/api/views.py:23 me_payload`, `core/context_processors.py` | `core/modules.py` |
| 기록 설명서 | 모델별 `RecordSpec(title, status, fields, tables, side, list_columns, filters, actions)` + 레지스트리. 기본값은 `_meta`에서 만든다 | **신규 `core/recordspec.py`**, `core/recordspecs.py`(core 모델), `qms/recordspecs.py`(qms 모델) | `core/rules.py`, `core/records.py`, `core/relations.py`, 모델 `document()` |
| 범용 API | `GET/POST records/<app.model>/`, `GET/PUT records/<app.model>/<pk>/`, `POST .../actions/<name>/` | **신규 `core/api/records.py`** + `core/api/urls.py` 한 줄 | 레지스트리, 모듈 판정, `core/rules.py`, `ModelPerms` 계열 권한 |
| 링크 한 곳 | `detail_url`/`list_url`/`add_url`. 설명서가 있으면 `/app/…`, 없으면 관리 화면 | **`core/relations.py`의 `record_url` 확장**(권장) | 레지스트리; 소비처 7+개 파일이 호출 |
| 공통 틀 | 머리 띠 + 본문 + 오른쪽 열. `RecordPage` props 계약 유지 | **신규 `frontend/src/components/RecordShell.tsx`**, 기존 `RecordPage.tsx`가 안으로 위임 | 기존 `RelationsPanel`·`AttachmentPanel`·`MemoPanel`·`AuditLog`·`SaveBar`·`SignModal`·`EditGrid` |
| 범용 화면 | 설명서 JSON만으로 `RecordShell`을 채운다 | **신규 `frontend/src/pages/records/GenericRecordPage.tsx`**, 라우트 `r/:app/:model/:id`를 `main.tsx`에 한 줄 | `/api/records/…`, `me.modules` |

---

## Recommended Project Structure

```
core/
├── modules.py            # [A1] 대응표 + active() + open_records(). qms는 라벨 문자열만
├── license.py            # [A2] 키 파일 읽기·검증·캐시 (mtime 키)
├── ed25519.py            # [A2] RFC 8032 검증기 (표준 라이브러리)
├── middleware.py         # [A1] module_gate 추가 (기존 no_store_pages 유지)
├── models.py             # [A1] ModuleSwitch 추가
├── recordspec.py         # [B1] RecordSpec·register()·spec_for(label)·기본값(_meta)
├── recordspecs.py        # [B1~] core 모델 설명서 (LOT·부적합·보류·출하·기준정보…)
├── records.py            # 기존 그대로 (삭제·잠금 규칙) — 이름 충돌 주의
├── relations.py          # [B1] record_url → detail_url/list_url/add_url
├── nav.py                # [A1] 항목의 모듈은 url 이름에서 도출 / [B] 주소는 레지스트리에서
├── rules.py              # [B2] submit_edit_request 추가 (뷰에서 뽑기)
└── api/records.py        # [B1] 목록·상세 / [B2] 저장·추가·actions
qms/
├── recordspecs.py        # [B1~] qms 모델 설명서, ready()에서 등록
├── apps.py               # ready()에서 recordspecs 등록 (ensure_roles와 나란히)
└── migrations/00NN_seed_moduleswitch.py   # [A1] 행 추가만 (아래 마이그레이션 결정)
frontend/src/
├── components/RecordShell.tsx   # [B0]
├── components/RecordPage.tsx    # [B0] 겉모양만 위임, props 계약 유지
├── pages/records/GenericRecordPage.tsx   # [B1]
├── pages/ModuleOff.tsx          # [A1] 「비활성 모듈」 안내
└── api/records.ts               # [B1]
scripts/issue_license.py         # [A2]
```

### Structure Rationale

- **판정·설명 코드는 `core`에 두고 qms는 등록만 한다.** 앱 경계(`core`·`qms`·`personal`)와 `core→qms` 지연 참조 규칙을 그대로 지킨다. 새 앱을 만들지 않는다.
- **`recordspec.py`(틀)와 `recordspecs.py`(내용)를 나눈다.** 28종 설명서가 한 파일에 쌓이는 것을 막고, B단계마다 한 묶음씩 추가해도 틀 파일은 안 건드린다.
- **마이그레이션 위치(권장):** 스키마(`ModuleSwitch`)는 `core/migrations`, **행 추가 데이터 마이그레이션은 `qms/migrations`** 에 둔다(`core` 스키마 마이그레이션에 의존). 시드가 `Capa`·`ChangeRequest` 같은 qms 모델 개수를 세야 하는데, 이것을 core 마이그레이션에 두면 core 마이그레이션이 qms 마이그레이션에 의존해 의존 방향이 뒤집힌다.

---

## Architectural Patterns

### Pattern 1: 대응표 한 장에서 모든 판정을 도출한다

**What:** `core/modules.py`가 유일한 진실이다. 메뉴 항목의 모듈은 별도 `nav_keys`를 쓰지 않고 **url 이름 → 모델/url_names → 모듈**로 도출한다(권장; 계획서는 `nav_keys`를 따로 둠). 관리 `changelist` 이름이면 `module_of_model`로, `todo`·`kpi`·`suppliers`처럼 모델이 없는 화면만 `url_names`에 명시한다.
**When:** 모든 소비처(미들웨어·nav·me·due·notify·위젯·검색·타임라인·importer·report·audit_pack·collect).
**Trade-offs:** 표가 한 곳이라 어긋남이 줄고, 새 모델이 하나 늘어도 테스트 한 개가 잡는다. 대신 표가 길어진다(모델 ~40, URL ~60).

```python
# core/modules.py (골격)
BASE = 'base'   # 끌 수 없음: 홈·기준정보·시스템·LOT·부적합·보류
MODULES = {
  'qms_capa': Module(models={'qms.capa'}, url_names={...}, spa_paths=('/app/…',),
                     requires=(), enhances=('qms_claim','qms_supplier','qms_audit')),
  ...
}
def module_of_model(label): ...          # 전수: 모든 업무 모델이 모듈 또는 BASE
def module_of_request(match): ...        # 우리 뷰 kwargs / 관리 url_name / records 라벨
def active_set(): ...                    # 한 쿼리: ModuleSwitch.enabled ∩ license.allowed
def active(key): return key in active_set()
```

**전수 테스트를 두 개 둔다(둘 다 A1):** ① `get_resolver()`를 재귀로 돌며 모든 패턴(관리 패턴은 `url_name`으로 분해)이 모듈 또는 BASE에 매핑되는지, ② `relations.is_registered`인 모든 모델이 `module_of_model`을 통과하는지. ②가 B1 이후의 새 `RecordSpec`·새 모델이 대응표 밖에 나가는 것을 막는다.

### Pattern 2: 두 겹 문 — 미들웨어(거친 문) + 개체 훅(고운 문)

**What:** `process_view`는 URL/라벨까지만 안다. 「꺼진 모듈이라도 시스템 관리자는 **열려 있는 기록**을 종결할 수 있다」는 개체 상태를 봐야 한다.
- 거친 문(`module_gate`, 미들웨어): 일반 사용자 404, 관리자 GET 허용, 관리자 쓰기는 「종결 가능 모델」 목록에 있는 모델만 통과시킨다, 그 밖은 403.
- 고운 문: 통과한 쓰기가 실제 닫기인지 개체로 확인. `modules.can_write(obj, user)`를 `BaseAdmin.has_change_permission`(`core/admin.py:73`)과 `core/api/records.py`(B2)가 같이 부른다. 규칙은 「꺼진 모듈의 기록은 **아직 열려 있을 때만** 시스템 관리자가 쓸 수 있다」(권장, 닫힌 기록은 읽기 전용).
**When:** A3.
**Trade-offs:** URL 화이트리스트만으로는 admin 변경 폼 POST(필드 전체 POST)를 「종결」과 구분할 수 없다. 이 두 겹이 없으면 A3가 B4(CAPA 등 화면 이전) 전에는 구현 불가능하다.
**종결 허용을 라벨 기준으로 쓴다:** URL이 아니라 `(model label, 열린 상태 술어)`로 둔다. B2 이후 같은 종결이 `records` API의 `actions/<name>/`을 거쳐도 규칙이 한 번만 적힌다. RecordSpec의 `actions` 항목에 `closing=True`를 달아 연결한다(권장).

### Pattern 3: 설명서 기본값은 `_meta`, 덮어쓰기만 적는다

**What:** `RecordSpec`의 `fields`·`list_columns`·`filters` 기본값을 `Model._meta`(verbose_name, choices, FK→이름)에서 만들고 spec에는 예외만 적는다. `core/relations.py`가 이미 같은 방식(「모델 `_meta`에서 만들므로 따로 등록하지 않는다」)이다. 관리 화면 `ModelAdmin`을 읽어 기본값을 만들지는 않는다(관리 화면은 뒷방으로 남기고 나중에 달라질 수 있다).
**When:** B1~B6의 28종.
**Trade-offs:** 설명서가 짧아지고 새 칸이 자동 노출된다. 비밀번호·해시·내부 칸 노출을 막으려면 **기본값을 허용 목록이 아니라 「모델이 `is_registered`이고 spec 존재」 + 칸 제외 목록(`exclude`)** 으로 두고 테스트로 `password`류 칸 비노출을 확인한다.

### Pattern 4: 범용 API는 설명서를 통해서만 열고, 저장은 기존 규칙 함수를 그대로 탄다

**What:** `core/api/records.py`는 ① `spec_for(label)` 없으면 404(등록 안 된 모델 차단) ② 모듈 판정(미들웨어가 이미 라벨 kwargs로 판정하지만 뷰에서도 `can_write`) ③ 모델 권한(`view_*`/`add_*`/`change_*`, 삭제는 `delete_as`) ④ 저장은 `core.rules.save_with_lock(obj, user, children)`, 승인은 `rules.approve`, 삭제는 `rules.delete_as`, 수정/삭제 요청은 `submit_edit_request`(발견 4). ⑤ 오류는 `core/api/exceptions.py` 형식 `{detail, fields}`로 칸별 변환(`full_clean` → `ValidationError.message_dict`). 새 업무 규칙 코드는 쓰지 않는다.
**동시 저장:** 기존 `core/grid.py record_version`/`table_version` + `Stale` 409를 그대로 쓴다(`SpecPage.tsx`의 `version` 필드와 같은 계약).
**처분 서명(MRB)·보류 읽기 전용:** 범용 PUT으로 처분을 받지 않는다. `sign_disposition`은 `actions/sign/`(전용 본문, B3)으로만 들어온다.

### Pattern 5: 공통 틀 + 전용 본문 슬롯

**What:** `RecordShell`이 머리 띠·오른쪽 열 레이아웃만 갖고, 본문은 children(전용 화면: 검사, 부적합 처분) 또는 `GenericRecordPage`가 설명서로 채운다. 기존 `RecordPage`(props: title, status, actions, props, children, side)는 시그니처를 유지하고 내부만 `RecordShell`로 위임해 품번·검사기준·관리계획서가 자동으로 새 모양이 된다.
**주의:** `RecordPage.status`의 유니온 타입(`'초안'|'승인됨'|…`)을 설명서의 `status.tone` 기반 문자열로 넓혀야 한다(B0에서 같이 정리).

---

## Data Flow

### 요청 흐름: 모듈 문

```
브라우저 요청
   │
   ▼  SessionMiddleware → AuthenticationMiddleware (request.user 준비) → … → module_gate.process_view
   │
   ├─ license.state()  ── data/license.key mtime 변경 시에만 재검증, 결과 캐시
   │     만료이고 쓰기 메서드이고 예외(로그인·로그아웃·csrf·license 교체)가 아니면 → 403 (JSON 또는 HTML)
   │
   ├─ key = modules.module_of_request(request.resolver_match)   # kwargs / url_name / records 라벨
   │     BASE 또는 None(미매핑은 테스트가 막음) → 통과
   │
   ├─ modules.active(key)? → 통과
   │
   └─ 꺼짐:
        일반 사용자 → 404  (/api/ 경로는 JSON {"detail":…, "code":"module_inactive"}, 그 외 HTML 404)
        시스템 관리자 GET/HEAD → 통과
        시스템 관리자 쓰기 → 종결 허용 모델이면 통과(개체 훅이 최종 확인), 아니면 403
                              「비활성 모듈 — 종결 처리만 가능」
```

- DRF 뷰도 `process_view`를 탄다: 세션 인증은 Django 미들웨어가 `request.user`를 먼저 채우므로 문이 DRF 권한보다 앞서도 사용자를 안다. 응답은 DRF 예외 처리기를 거치지 않으므로 `/api/`에는 `core/api/exceptions.py`와 같은 `{'detail': …}` 모양으로 직접 만든다.
- **SPA 껍데기(`/app/*`, `core.views.spa`)는 404로 막지 않는다.** 로그인 이동·최근 기록 복원이 깨진다. 보안 경계는 API이고, 화면은 보조다: `me.modules`와 API의 `code: module_inactive`로 `ModuleOff` 안내를 보인다.
- **라벨을 URL 인자로 받는 일반 경로는 모두 문을 지나야 한다**(누수 지점): `relations/<label>/<pk>/`, `request/<kind>/<app>/<model>/<pk>/`, `approve/…`, `print/…`, `report/<tpl>/<pk>/`, `media/`, 관리 자동완성, 그리고 **쿼리 인자로 모델을 받는 경로**: `/api/attachments/?ct=`, `/api/qms/memos/?ct=`. 후자 둘은 kwargs가 없으므로 미들웨어가 못 잡는다 → 뷰 안에서 `modules.module_of_model(ct)`를 호출해야 한다.

### 요청 흐름: 범용 기록 화면 (B1 이후)

```
GenericRecordPage (/app/r/qms/gauge/7)
   │ GET /api/records/qms.gauge/7/
   ▼
module_gate → core/api/records.py
   ├ spec = recordspec.spec_for('qms.gauge')  (없으면 404)
   ├ 권한 qms.view_gauge (서버)
   ├ 개체 + spec.fields/tables/side → JSON {title, status:{label,tone}, fields[], tables[], actions[], side[], version, editable}
   │    사람은 _who 규칙(이름 우선), 숫자 형식은 서버가 정한다
   ▼
RecordShell(머리 띠 status, 본문 tables, 오른쪽 열 RelationsPanel·AttachmentPanel·MemoPanel·AuditLog)
   │ [수정] → PUT /api/records/qms.gauge/7/  {fields…, version}
   ▼
records.py → rules.save_with_lock → 모델 clean()/save() → simple-history 행 → 409(잠금·Stale)/400({fields})
```

### 링크 한 곳 (record_url 일원화)

```
호출부(검색·타임라인·종합현황·위젯·유사사례·메모·views·related_panel·nav)
        │  detail_url(obj) / list_url(label, **filters) / add_url(label, **initial)
        ▼
core/relations.py  ── recordspec.spec_for(label)?
        ├ 전용 화면 등록(품번·검사기준·관리계획서·검사: 기존 pages 딕셔너리를 레지스트리 항목으로 옮김) → /app/items/…
        ├ 범용 설명서 등록 → /app/r/<app>/<model>/<id>
        └ 없음 → 기존 관리 주소 (target_url 폴백)
```

현재 `record_url`의 하드코딩 딕셔너리(`core/relations.py:81`)를 레지스트리 항목으로 옮기면 「전용」과 「범용」이 한 표에서 나온다. 화면을 B단계에서 옮길 때 `register()` 한 줄이면 검색·타임라인·메모·종합현황·메뉴가 같이 따라간다.

### 모듈 상태 읽기 (캐시 원칙, 권장)

| 대상 | 방식 | 이유 |
|------|------|------|
| 라이선스 검증 결과 | 프로세스 내 캐시, **파일 mtime**을 키로 | 계획서: 시작 시·파일 변경 시 재검증. Ed25519 순수 파이썬 검증은 느리므로 요청마다 하지 않는다 |
| `ModuleSwitch` 상태 | **캐시하지 않고** 요청당 쿼리 1회(`active_set()`), 미들웨어가 `request.modules`에 메모 | 소수 행이고, 전역 캐시는 waitress 다중 스레드·관리 명령·테스트에서 낡은 값을 만든다 |
| `relations_for` | 기존 `@cache` 유지, **모듈 필터는 payload 단계(`group_payload`)에서** | `@cache`는 모델 메타 전용이라 런타임에 바뀌는 모듈 상태를 넣으면 재시작 전까지 안 바뀐다 |
| 요청 없는 소비처(`notify`, `collect`, `due`) | `modules.active(key)`가 DB를 직접 읽는다(요청 객체에 의존하지 않는다) | 관리 명령에는 request가 없다 |

### 프런트 상태

```
['me'] (react-query) ── nav, perms, modules ──▶ AppLayout 메뉴·ModuleOff 안내
   ▲ 서버 필터와 같은 함수 결과 (core/nav.py visible_nav 가 모듈 필터를 이미 적용)
RecordShell ← useQuery(['record', label, id]) ← /api/records/...
저장 성공 → qc.setQueryData + invalidate(['record-log', …])   (SpecPage.tsx 패턴 그대로)
```

---

## 빌드 순서와 의존성

```
                       ┌─────────────────────────────────────────────┐
 B0 ───────────────────┤ (A·B1 모두와 독립. RecordShell·검사 상세·DESIGN) │
                       └─────────────────────────────────────────────┘
 A1  modules.py 표 ─ 전수 테스트 2종 ─ ModuleSwitch ─ 시드(qms 마이그레이션) ─ module_gate ─ nav/me
  │        ▲ license 인터페이스(allowed_modules/valid)는 A1에서 자리만 만든다
  ▼
 A2  license.py·ed25519.py·발급 스크립트·만료 읽기 전용     (A1의 active()에 끼워 넣기)
  │
  ▼
 A3  open_records · 종결 허용(두 겹 문) · 인터록 메시지 원인 표시
  │
  ▼
 A4  소비처 필터 (+ 같은 파일을 만지는 김에 링크 helper 도입: 아래 권장)
  │
  ▼
 B1  recordspec.py · records API(읽기) · GenericRecordPage · record_url 레지스트리화 · 문서/계측기/자격
  ▼
 B2  저장·추가 API · 편집 모드 · submit_edit_request 추출 · closing 액션
  ▼
 B3 LOT·부적합·보류 → B4 CAPA·클레임·SCAR·4M → B5 심사·PPAP → B6 생산·출하·기준정보·nav 정리
```

### 순서 판단 (계획서 순서 B0 → A1~A4 → B1~B6에 대한 의견)

1. **B0 먼저는 맞다.** 프런트 겉틀·검사 읽기 키뿐이고 A와 겹치지 않는다. 단 `RecordPage.status` 타입 확장은 여기서 끝낸다(B1이 의존).
2. **A1이 A·B 전체의 바닥이다.** 전수 테스트 ②(모든 업무 모델이 모듈 또는 BASE)가 B1 이후 설명서가 대응표 밖으로 나가는 것을 강제한다. 이 테스트를 A1에서 만들지 않으면 계획서의 「새 경로는 A 대응표에 바로 등록」은 약속일 뿐이다.
3. **A1에서 라이선스 인터페이스를 자리만 만들고 기본 구현은 「모두 허용」으로 둔다(권장).** 계획서는 「라이선스 파일이 없으면 기본 플랫폼만」인데, A2 전에 A1만 배포하면 키 파일이 없는 기존 고객의 모듈이 전부 꺼진다. A1·A2를 한 번에 출시하거나, A1 시점 허용 구현을 임시로 두고 A2에서 교체한다. 시드 마이그레이션(기존 데이터 있는 모듈만 켬)은 이 임시 구현과 함께 가야 업그레이드가 안전하다.
4. **A3는 「두 겹 문」이 전제다**(패턴 2). B4 전에 CAPA·클레임·SCAR·4M·심사 종결을 열어 두는 유일한 방법이 관리 화면 변경 폼 POST이므로 URL 화이트리스트가 아니라 `(라벨, 열린 상태)` 규칙이어야 한다.
5. **A4와 「링크 일원화 준비」를 한 번에 만진다(권장).** A4가 건드릴 소비처(`qms/due.py`, `qms/widgets.py`, `qms/overview.py`, `core/search.py`, `core/timeline.py`)는 B1이 `record_url`로 바꿀 파일과 거의 같다. A4에서 각 파일을 열 때 `reverse('admin:…')`를 `detail_url`/`list_url`/`add_url`로 바꿔 두면(해결 결과는 아직 관리 주소) 각 파일을 한 번만 고치고, B1~B6은 레지스트리 `register()`만으로 링크가 이동한다. 이렇게 하면 B 쪽 위험이 줄고 A4의 「클레임 설정 메뉴 이동」과도 충돌하지 않는다.
6. **B2 첫 작업은 `submit_edit_request` 추출**(발견 4). 이것을 먼저 하지 않으면 범용 삭제·수정 요청이 뷰 로직을 복제한다.
7. **B3(LOT·부적합·보류)는 B2의 편집을 쓰지 않고 전용 본문을 쓴다.** 부적합 처분은 `sign_disposition` + 모델 `clean()`가 규칙을 쥐므로 범용 PUT 경로에서 우회되지 않는지 테스트로 막는다(핵심 보호 규칙).
8. **B6 마지막.** 기준정보는 `FieldDef`가 `extra` JSON 칸을 만들므로 설명서가 FieldDef를 읽는 동적 칸이 필요하다(유일하게 정적 선언이 안 되는 곳). 앞 묶음으로 틀이 굳은 뒤에 한다.

### 단계별 산출물과 선행 조건

| 단계 | 새로 생기는 것 | 선행 조건 | 회귀망 |
|------|---------------|-----------|--------|
| B0 | `RecordShell`, 검사 상세 읽기 키(`qms/api/inspections.py:256-278`), `lib/num.ts` | 없음 | `qms/api/tests.py`, `e2e_browser.py` |
| A1 | `core/modules.py`, `ModuleSwitch`, 시드, `module_gate`, nav/me 필터, 전수 테스트 2종, `ModuleOff.tsx` | 없음 | `core/api/tests.py:48-55`(nav 테스트), `core/tests.py:95-127` |
| A2 | `core/license.py`, `core/ed25519.py`, 발급 스크립트, 만료 띠 | A1 | RFC 8032 벡터 |
| A3 | `open_records`, 종결 허용, 메시지 원인 | A1 | 기존 인터록 테스트 전부 |
| A4 | 소비처 필터 + 링크 helper 치환 | A1, A3 | `scripts/e2e_check.py` |
| B1 | `core/recordspec.py`, `core/api/records.py`(읽기), `GenericRecordPage`, 레지스트리 기반 `record_url` | A1, B0 | `core/api/tests_relations.py` |
| B2 | 저장·추가·actions, 편집 모드, `submit_edit_request` | B1 | `core/tests_rules.py`, 잠금·승인 테스트 |
| B3~B6 | 모델 묶음별 `register()` | B2, 대응표 전수 테스트 | 묶음별 e2e + 인터록 테스트 |

---

## Anti-Patterns

### Anti-Pattern 1: 새 `core/records.py`로 덮어쓰기
**What people do:** 계획서 문구대로 같은 이름의 새 파일을 만든다.
**Why it's wrong:** 삭제·잠금 규칙을 import하는 파일 7곳이 깨지거나, 규칙이 새 파일에 섞여 「업무 규칙은 한 곳」 원칙이 무너진다.
**Do this instead:** `core/recordspec.py`.

### Anti-Pattern 2: URL 화이트리스트만으로 종결 허용
**What people do:** 「종결 처리」를 URL 이름 목록으로 허용한다.
**Why it's wrong:** 관리 화면 변경 폼은 하나의 POST라서 종결과 다른 수정을 구분하지 못한다. 거꾸로 막으면 풀 수 없는 인터록이 생긴다(계획서 A 반려 사유 1번).
**Do this instead:** 거친 문 + `(라벨, 열린 상태)` 개체 훅(패턴 2).

### Anti-Pattern 3: 라이선스 만료 쓰기 차단이 인터록 해제도 막는다
**What people do:** 만료 시 모든 쓰기를 403.
**Why it's wrong:** 보류 LOT의 MRB 처분, 4M 초품 판정, 부적합 종결도 쓰기라서 만료 순간 풀 수 없는 보류가 생긴다. A3가 막으려던 문제를 A2가 다시 만든다.
**Do this instead:** 만료 읽기 전용 예외에 「인터록 해제 쓰기」를 넣을지 **사용자에게 결정을 받는다**(보안·핵심 업무 규칙 관련이라 `AGENTS.md`상 사전 승인 대상). 이 질문은 phase A2의 필수 확정 사항이다.

### Anti-Pattern 4: 모듈 상태를 `@cache`나 전역 변수에 둔다
**Why it's wrong:** `relations_for`처럼 모델 메타 캐시는 안전하지만 런타임 설정은 아니다. waitress 스레드·`notify`·`collect`·테스트에서 낡은 상태를 읽는다.
**Do this instead:** 위 「캐시 원칙」.

### Anti-Pattern 5: 모듈 판정을 화면(React)에서만 한다
**Why it's wrong:** `AGENTS.md` 「버튼 숨김만으로 막지 않는다」. 꺼진 모듈의 API·관리 화면·출력이 열려 있으면 모듈 끄기가 장식이 된다.
**Do this instead:** 미들웨어 + 뷰 개체 훅이 권위이고 React `ModuleOff`는 보조.

### Anti-Pattern 6: 범용 PUT이 모든 칸을 받는다
**Why it's wrong:** 부적합 처분 칸(`disposition`, `approved_by`)·승인 칸·잠금 칸을 PUT으로 직접 쓰면 MRB 서명·승인 서명이 우회된다.
**Do this instead:** spec의 편집 가능 칸 허용 목록만 받고, 승인·처분·종결은 이름 붙은 `actions`로만 한다. 승인 후 잠금은 `save_with_lock`이 보장한다.

### Anti-Pattern 7: 관리 목록 필터 문법을 그대로 흉내낸다
**Why it's wrong:** `?lot__id__exact=…`는 Django admin 내부 문법이라 records API가 임의 ORM 조회를 받게 되면 열람 권한을 우회한다.
**Do this instead:** spec의 `filters`에 선언된 이름만 받는다. 기존 `list_url(label, **filters)`가 그 이름을 쓰게 한다.

---

## Integration Points

### Internal Boundaries (실제 파일)

| 경계 | 통신 방식 | 메모 |
|------|-----------|------|
| `core/middleware.py` ↔ `core/modules.py`·`core/license.py` | 직접 호출 | 미들웨어는 DB를 직접 건드리지 않고 `modules.active_set()`만 |
| `core/nav.py` ↔ `core/modules.py` | `visible_nav`가 `active_set()` 한 번 호출 후 항목별 `module_of_url_name` | 현재 `nav.py:19`의 권한 필터와 같은 자리. `core/context_processors.py:17`·`core/api/views.py:23`가 같은 함수를 쓰므로 한 곳 수정 |
| `core/api/views.py me_payload` ↔ 프런트 `src/api/auth.ts` | JSON `modules: {key: bool}` 추가 | 기존 `nav`·`perms` 키는 그대로(읽기 키 추가만) |
| `qms/recordspecs.py` → `core/recordspec.py` | `register()` (ready 시점) | `core→qms` import 없음 |
| `core/api/records.py` ↔ `core/rules.py`·`core/records.py` | 직접 호출 | 규칙 본문 불변 |
| `core/relations.py` ↔ `core/recordspec.py` | `spec_for(label)` | 순환 주의: relations는 recordspec을 지연 import하거나 recordspec이 relations를 import하지 않게 한다 |
| 소비처 ↔ `core/modules.py` | `active(key)`/`module_of_model` | `qms/due.py`, `qms/widgets.py`, `qms/overview.py`, `core/search.py`, `core/timeline.py`, `core/importer.py`, `qms/management/commands/notify.py`·`collect.py`, `qms/views.py audit_pack` |
| `core/relations.py group_payload` ↔ `core/modules.py` | 꺼진 모듈 묶음은 항목 대신 「비활성 모듈 기록 N건」(시스템 관리자에겐 읽기 링크) | 개수 노출 정책은 계획서 6절을 따른다. `@cache`된 `relations_for`는 건드리지 않는다 |
| `qms/apps.py ensure_roles` | 변경 없음 | 모듈은 권한이 아니다 |
| 프런트 `AppLayout` ↔ `RecordShell`/`GenericRecordPage` | `me` 쿼리 공유 | 한 번 받은 `me.modules`로 안내 화면 분기 |

### 외부 서비스

없음. 라이선스는 로컬 파일 + 서명 검증만(오프라인 원칙). 새 의존성 없음(`core/ed25519.py`는 표준 라이브러리, 단위 테스트는 RFC 8032 벡터).

---

## Scaling Considerations

사내 PC 한 대·사용자 수십 명 규모라 「요청 수」가 아니라 「요청마다 드는 고정비」와 「기록 수 증가」를 본다.

| 관심사 | 현재 규모 | 기록이 많아질 때 |
|--------|-----------|------------------|
| 미들웨어 모듈 판정 | 요청당 쿼리 1회(`ModuleSwitch` 소수 행) | 필요하면 요청 메모 + 짧은 TTL. 지금은 불필요 |
| 라이선스 검증 | 순수 파이썬 Ed25519 수십 ms. mtime 캐시로 프로세스당 1회 | 변경 없음 |
| `records` 목록 API | 기존 `PAGE_SIZE=50` 페이지 + `select_related` | spec이 `select_related`/`prefetch`를 선언해야 N+1을 막는다(검사 목록 `qms/api/inspections.py`가 이미 이 방식) |
| 전수 테스트 | URL ~60·모델 ~40 | 문제 없음 |
| `open_records` | 모듈당 1~2 `exists()` 쿼리, 끄기 시에만 | 문제 없음 |

첫 병목은 요청 수가 아니라 **`records` 상세의 하위 표 쿼리(N+1)와 `RelationsView`**(모델 관계마다 `count()`)다. 설명서 상세가 `RelationsView`를 호출하지 않고 오른쪽 열이 탭을 열 때 지연 로드하도록 한다(`RelationsPanel`이 이미 별도 API).

---

## 이 아키텍처에서 phase 계획 시 별도 조사가 필요한 곳

| 단계 | 이유 |
|------|------|
| A2 | 만료 시 인터록 해제 쓰기 정책(Anti-Pattern 3, 사용자 승인 필요), 순수 파이썬 Ed25519 속도·상수 시간성 |
| A3 | 「열린 기록」 술어를 모듈별로 정의(CAPA 미종결, 4M 초품 전 등)하고 관리 변경 폼 경로로 종결이 실제 되는지 확인 |
| B2 | `submit_edit_request` 추출 시 기존 `core/tests.py`·`core/tests_rules.py` 회귀 확인, `ApprovalAdminMixin`/`ReportLinksMixin` 동작을 액션으로 옮기는 범위 |
| B3 | 부적합 처분 서명·보류 해제 규칙이 범용 경로로 우회되지 않음을 증명하는 테스트 설계 |
| B6 | `FieldDef`·`extra` 동적 칸 |
| A1·B1 공통 | PostgreSQL 마이그레이션 시드 결과를 운영 DB 사본으로 확인(`docs/testing.md`) |

일반 패턴(DRF 뷰 + 미들웨어, React 쿼리·폼)은 기존 코드가 그대로 선례라 별도 조사가 필요 없다.

---

## Sources

- `c:\Users\gogog\qms-mes\.planning\PROJECT.md`, `docs/architecture.md`, `C:\Users\gogog\.claude\plans\twinkling-dreaming-lollipop.md` (승인 계획) — HIGH
- 직접 읽은 코드: `core/records.py`, `core/relations.py`, `core/nav.py`, `core/middleware.py`, `core/rules.py`, `core/admin.py:56-180`, `core/views.py:140-272`, `core/api/urls.py`, `core/api/views.py`, `core/api/permissions.py`, `qms/api/urls.py`, `qms/api/specs.py`, `qms/api/inspections.py:235-290`, `qms/memo.py`, `config/urls.py`, `config/settings.py`(MIDDLEWARE·REST_FRAMEWORK), `frontend/src/main.tsx`, `frontend/src/layout/AppLayout.tsx`, `frontend/src/components/RecordPage.tsx`, `frontend/src/pages/specs/SpecPage.tsx` — HIGH
- Django 일반 동작(`process_view` 순서, 관리 URL 이름 규칙 `admin:<app>_<model>_<action>`, `admin:autocomplete`의 GET 인자): 표준 Django 동작, 이 저장소에서 `core/admin.py`·`qms/widgets.py` 호출 형태로 확인 — HIGH
- 「권장」 표시 항목(레지스트리 위치, 두 겹 문, 링크 세 갈래, 마이그레이션 위치, 캐시 원칙, A4+링크 helper 동시 처리): 코드 구조에서 도출한 제안, 계획 단계에서 확정 필요 — MEDIUM

---
*Architecture research for: on-prem Django + React QMS/MES — module gating & generic record screens*
*Researched: 2026-11-12*
