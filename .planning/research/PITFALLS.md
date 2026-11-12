# Pitfalls Research

**Domain:** 온프레미스 Django + React QMS/MES — (A) 모듈 켜기/끄기 + 서명 라이선스 + 미들웨어 차단, (B) 범용 `records` API + React 기록 화면으로 Django 관리 화면 대체
**Researched:** 2026-11-13
**Confidence:** HIGH (코드 직접 확인한 항목) / MEDIUM (일반 도메인 경험에서 온 항목, 각 항목에 표시)

근거 표기: 「코드 확인」= 이 저장소 파일을 읽어 확인한 사실. 「경험」= 비슷한 프로젝트의 일반적 실패 양상이며 이 저장소에서 아직 확인하지 않은 것.

---

## Critical Pitfalls

### Pitfall 1: 범용 저장 API가 MRB 서명·승인 칸을 그대로 받는다 (서명 위조)

**What goes wrong:**
`PUT/POST records/<app.model>/`가 모델 `full_clean()` + `save()`만 부르면, 요청 본문의 `approved_by`·`approved_at`·`closed_at`·`mailed_at`·`result`가 그대로 저장된다. 비밀번호를 한 번도 입력하지 않았는데 부적합이 「품질팀장 승인 + 처분 + 종결」 상태가 되고 보류가 풀린다.

**Why it happens:**
코드 확인: `Nonconformance.clean()`(`core/models.py:462`)은 `approved_by`가 승인자 그룹인지만 본다. 비밀번호 확인은 모델이 아니라 admin 폼 `NonconformanceForm.clean()`(`core/admin.py:508`)과 `core/rules.py` `sign_disposition`/`dispose_nc`에 있다. 폼은 `exclude=['approved_by','approved_at']`로 이 칸을 막는다. 범용 API는 폼을 거치지 않으므로 이 보호막이 사라진다. `docs/business-rules.md` 머리말은 「규칙은 모델에서 강제」라고 하지만 MRB 서명은 실제로 폼·규칙 함수 층에 있다.

**How to avoid:**
- 설명서(`RecordSpec`)에 **쓰기 가능 칸 화이트리스트**를 필수로 둔다. `fields='__all__'`·`exclude` 방식 금지. 서명·승인·종결·판정·보류 해제 칸(`approved_by`, `approved_at`, `closed_at`, `mailed_at`, `result`, `nonconformance`, `released_at`)은 어떤 설명서에도 쓰기 칸으로 넣지 않는다.
- 화이트리스트에 없는 칸이 본문에 있으면 조용히 무시하지 말고 400으로 거부한다 (`dispose_nc`의 「처분에서 바꿀 수 없는 칸」 방식과 같다).
- 처분·승인·판정은 범용 PUT이 아니라 전용 동작 엔드포인트(`dispose_nc`, `core.rules.approve`, `submit_inspection`)만 쓴다. 범용 PUT은 이 동작 칸을 모른다.
- 회귀 테스트: 품질엔지니어·시스템 관리자 양쪽이 PUT으로 `approved_by=<품질팀장 id>`, `disposition='SCRAP'`를 보내도 400/403이고 DB가 안 바뀌는지.

**Warning signs:**
설명서가 모델 필드를 반복문으로 자동 생성한다. 시리얼라이저가 `ModelSerializer(fields='__all__')`다. 테스트에서 API로 처분을 저장했는데 비밀번호를 안 넣었다.

**Phase to address:** B1(설명서 구조에 화이트리스트 강제), B2(저장 API), B3(부적합 전용 처분 본문). B1에서 구조를 잘못 잡으면 B2~B6 전체가 오염된다.

---

### Pitfall 2: 권한을 모델 권한(`has_perm`)만으로 검사해 admin의 행 단위 규칙이 사라진다

**What goes wrong:**
`require_perm(user, 'core.change_hold')`처럼 Django 모델 권한만 확인하면, admin이 막던 동작이 열린다. 품질엔지니어가 보류(`Hold.released_at`)를 직접 풀거나, 판정된 검사를 고치거나, 개정(`DocumentRevision`)·PPAP 요소를 추가·수정할 수 있게 된다.

**Why it happens:**
코드 확인: `qms/apps.py` `ensure_roles`는 `core`·`qms` 앱의 `delete_` 이외 **모든 권한**을 품질엔지니어·품질팀장에게 준다(`change_hold` 포함). 그런데 `HoldAdmin`(`core/admin.py:613-621`)은 `has_add/change/delete_permission`을 전부 `False`로 막고, `InspectionAdmin`은 판정된 검사의 변경을 막고(`qms/admin.py:109`), `DocumentRevisionAdmin`은 변경을 막고(`:433`), `PpapElementAdmin`은 추가를 막는다(`:332`). 이 업무 규칙은 권한표가 아니라 **ModelAdmin 메서드**에 있다. `docs/business-rules.md`의 위치 열도 `core/admin.py`를 가리키는 항목이 많다.

**How to avoid:**
- 권한 판정을 한 함수로 모은다: `admin.site._registry[model].has_add/change/delete_permission(fake_request, obj)`를 그대로 호출하거나, 같은 규칙을 `RecordSpec.can(action, obj, user)`로 옮기되 **모든 등록 ModelAdmin과 동등한지 대조하는 테스트**를 둔다 (모델 × 동작 × 역할 전수 표).
- 설명서에 없는 모델·동작은 기본 거부(fail-closed). 새 모델이 `ensure_roles`로 자동 권한을 받아도 API가 열리지 않아야 한다.
- 보류(Hold)는 설명서에 읽기 전용으로만 등록하고 쓰기 동작을 아예 정의하지 않는다.

**Warning signs:**
`records.py`에 `has_perm` 호출만 있고 `_registry`·`has_change_permission` 호출이 없다. 「보류 읽기 전용」을 프런트 설명서의 `readonly: true`로만 표현했다.

**Phase to address:** B1(권한 판정 구조), B2(전수 대조 테스트), B3(보류·부적합).

---

### Pitfall 3: 인터록 검사가 「새로 만들 때만」 걸려 있어, 범용 PUT으로 기존 행을 옮기면 우회된다

**What goes wrong:**
기존 `Shipment`·`WorkResult`·`LotLink`의 `lot` 칸을 보류 중이 아닌 LOT에서 보류 중인 LOT으로 바꾸거나, 반대로 보류 LOT의 출하 기록을 새 LOT으로 돌려도 막히지 않는다. 판정된 검사를 `result='PASS'`로 새로 만들면 `finalize()`(자격·측정값 누락·부적합 자동 등록·SPC)가 통째로 생략된다.

**Why it happens:**
코드 확인: `assert_usable`은 `self._state.adding`일 때만 호출된다(`core/models.py:256,352,593`). admin 폼은 이 칸들을 수정하게 두긴 하지만 사용 빈도가 낮았다. 범용 편집 모드는 모든 칸을 편집 가능하게 만들기 쉽다. `Inspection.clean()`도 `result`가 비었는지 확인하지 않고, `save()`는 「이미 판정된 행의 수정」만 막는다(`qms/models.py:215`). 즉 `result`가 채워진 **새 행**은 통과한다.

**How to avoid:**
- 편집 화이트리스트에서 `lot`, `work_order`, `step`, `spec`, `result`, `nonconformance`, 참조 FK는 **생성 후 읽기 전용**으로 둔다.
- `Inspection`·`Measurement`는 범용 POST/PUT 대상에서 제외하고 `qms.rules.submit_inspection` 경로만 쓴다(PROJECT.md B0도 소급 추가·`_finalize`를 B2까지 admin에 남긴다고 적었다 — 이 결정을 B2에서도 유지할지 명시적으로 승인받는다).
- 인터록 규칙을 약화하지 않으려면 「수정 시에도 같은 검사」가 필요한지 사용자 승인 사항으로 올린다(규칙 변경이므로 임의로 하지 않는다).
- 테스트: 보류 LOT으로 기존 출하/실적/계보를 옮기는 PUT이 거부되는지, `result` 채운 POST가 거부되는지.

**Warning signs:**
범용 편집 화면에서 LOT 선택 칸이 편집 가능하다. 테스트가 「새로 만들 때」만 인터록을 확인한다.

**Phase to address:** B2(저장 API 화이트리스트), B3(LOT·부적합), B6(작업지시·실적·출하).

---

### Pitfall 4: 모듈을 끄면 풀 수 없는 인터록이 생기는데, 라이선스 경로는 「끄기 전 검사」를 우회한다

**What goes wrong:**
(a) 라이선스가 갱신되며 모듈이 빠지거나, 라이선스 파일이 없어지거나, 만료돼도 열린 4M 변경·CAPA가 남는다. 끄기 전 열린 기록 검사(`open_records`)는 `ModuleSwitch` 화면에만 걸려 있어 이 경로에서는 실행되지 않는다. (b) 시스템 관리자 종결 화이트리스트가 실제로는 존재하지 않는 동작을 가정한다.

**Why it happens:**
계획서: `active = 라이선스 허용 ∧ ModuleSwitch.enabled ∧ 라이선스 유효`. 끄는 경로가 셋(스위치, 라이선스 변경, 만료)인데 검사는 하나다. 또 4M 초품 해제는 「그 품번의 합격 검사(초품)가 나올 때까지」(`ChangeRequest.awaiting_first_article`)이므로 해제 수단은 **검사 판정**이다. 「초품 판정 기록」이라는 단독 쓰기 동작은 없다. `qms_inspection` 모듈이 꺼지면(`qms_change`가 requires로 막더라도 라이선스로는 꺼질 수 있다) 해제 경로 자체가 사라진다. 비슷하게 재작업·수리 처분은 `lot.inspections`에 재검사 합격이 있어야 한다(`Nonconformance.clean`). 기본 플랫폼인 부적합이 qms 모듈에 의존한다.

**How to avoid:**
- `open_records` 검사를 `active()` 변경이 일어나는 **모든 경로**에서 평가한다. 최소한 라이선스 교체 화면에서 「이 라이선스로 비활성이 되는 모듈의 열린 기록」을 경고하고, 시작 시 로그와 시스템 관리자 배너에 표시한다.
- 라이선스 발급 스크립트가 `requires` 닫힘(closure)을 검증한다 (`qms_audit`만 넣고 `qms_capa`를 빼는 키는 발급 거부).
- 종결 화이트리스트를 **실제 호출 가능한 동작**(url_name + 메서드 + 모델)으로 열거한다. 「초품 해제」는 (i) 검사 판정을 시스템 관리자에게 허용하는지, (ii) 수동 해제라는 새 업무 규칙을 만드는지 중 하나를 사용자 승인 사항으로 올린다 — 둘 다 업무 규칙 변경에 닿는다.
- 재작업·수리 처분이 `qms_inspection` 없이도 가능한지(규칙상 불가) 문서화하고, 그 경우 처분 화면이 이유를 보여 준다.
- 「모든 모듈 끔」 상태에서 `docs/business-rules.md`의 인터록 표 전부를 다시 도는 테스트 행렬을 만든다 (DB에서 `ModuleSwitch`를 전부 비우고 모델 규칙이 여전히 발동하는지).

**Warning signs:**
`open_records`가 스위치 뷰 안에서만 호출된다. 화이트리스트가 「초품 판정 기록」처럼 모델·뷰 이름이 없는 문장이다. 라이선스 패키지 표에 `requires` 검증이 없다.

**Phase to address:** A1(`active` 정의·경로 일원화), A2(라이선스 검증기·발급 시 closure 검증), A3(핵심: `open_records`·화이트리스트·메시지).

---

### Pitfall 5: 라이선스 만료의 「모든 쓰기 거부」가 부적합 등록·보류까지 막는다

**What goes wrong:**
만료일 아침에 현장이 불량을 발견해도 시스템에 부적합을 등록할 수 없다. 격리·보류가 시스템에 안 걸리므로 그 LOT이 출하될 수 있다. 제품의 핵심 가치(「부적합·인터록 규칙이 어떤 설정에서도 약해지지 않는다」)와 정면 충돌한다.

**Why it happens:**
계획서 2절: 만료 시 로그인·로그아웃·라이선스 교체만 예외이고 모든 POST/PUT/PATCH/DELETE를 거부한다. 부적합 등록(`nc_quick`, 검사 불합격 자동 등록)·보류 해제가 기본 플랫폼인데도 막힌다. 반대로 읽기 전용 모드에서 출하(POST)는 막히므로 출하 차단은 오히려 안전하지만, **기록하는 쪽이 막히는 것**이 문제다.

**How to avoid:**
- 사용자 결정을 받는다: 만료 읽기 전용에서도 **부적합 등록·메모·검사 불합격 입력(보류를 거는 방향 쓰기)은 허용**하고, 새 생산·출하·승인·처분만 막을지. 이 결정 없이 A2를 구현하지 않는다.
- 만료 14일 전부터 경고 배너·내 할 일 알림(`qms/due.py`와 같은 방식). 만료 당일에 처음 알게 되지 않도록 한다.
- 만료 판정 입력: 시스템 시계를 뒤로 돌리면 무한 연장된다. DB의 simple-history 최대 `history_date`를 「이 시각 이전으로는 가지 않는다」 하한으로 써서 시계 되돌림을 감지한다 (경험, 저비용). 소스가 고객 PC에 있어 완전 방어는 불가능하다는 계획서 전제를 문서에 그대로 적는다.
- 만료일 비교는 로컬(한국 표준시) 날짜 기준으로, 당일 포함 여부를 정해 테스트한다.

**Warning signs:**
읽기 전용 허용 목록에 `nc_quick`·`inspect_submit`이 없다. 라이선스 테스트가 「조회·엑셀 허용, 쓰기 거부」만 확인한다.

**Phase to address:** A2 (결정 필요 항목으로 A2 시작 전에 확정).

---

### Pitfall 6: 기존 고객 업그레이드 시 라이선스 파일이 없으면 모든 모듈이 사라진다

**What goes wrong:**
계획서: 「행이 없으면 꺼짐」, 「라이선스 파일이 없으면 기본 플랫폼만」. 마이그레이션이 데이터 있는 모듈의 `ModuleSwitch`를 켜도, 라이선스가 없으면 `active()`가 거짓이라 업그레이드 즉시 검사·CAPA·출하 화면이 404가 된다. 「기존 고객이 기능을 잃지 않음」(PROJECT.md Key Decisions)과 모순이다.

**Why it happens:**
라이선스(판매사 소유)와 스위치(고객 소유)를 합쳐 판정하므로 한쪽의 부재가 전체 차단이 된다. 순서(① backup ② 키 배치 ③ migrate)를 README에 적는 것만으로는 사람이 순서를 틀리면 막을 수 없다.

**How to avoid:**
- 기존 고객용 「레거시 유예」 라이선스 모드를 정한다: 키가 없고 마이그레이션이 기존 데이터를 근거로 모듈을 켰다면 N일(예: 30일) 유예 후에도 **읽기 전용**으로만 전환하고 데이터 접근은 보장한다. 그 정책을 사용자 승인으로 확정한다.
- 라이선스가 없거나 서명이 틀리면 서버가 죽거나 모든 요청이 500이 되면 안 된다. 검증 실패는 「기본 플랫폼 + 시스템 관리자 배너」로 안전하게 떨어진다(fail-safe, 단 fail-open은 아님). 임포트 시점이 아니라 지연 로딩하고 예외를 가둔다.
- `migrate` 출력에 「켜진 모듈 / 라이선스 없음 → 비활성」 요약을 남기고, 운영 DB 사본 리허설을 필수 체크리스트에 둔다(`docs/testing.md`).

**Warning signs:**
마이그레이션 테스트가 라이선스 없는 상태의 `active()`를 검증하지 않는다. README 업그레이드 순서가 유일한 방어다.

**Phase to address:** A1(마이그레이션·기본값), A2(라이선스 없음/만료 정책), A4(문서).

---

### Pitfall 7: 모듈 대응표가 URL 이름만 보고, 본문·쿼리·객체 ID로 정해지는 접근을 놓친다

**What goes wrong:**
미들웨어가 `process_view`에서 `url_name`/kwargs만 보면 다음이 모두 새는다: 첨부 업로드 `POST /api/attachments/`(대상이 본문에 있음), 첨부 다운로드 `/attachments/<id>/`(모듈이 첨부가 붙은 기록의 종류로 정해짐), admin 자동완성 `admin:autocomplete`(대상 모델이 쿼리스트링 `app_label`·`model_name`), `search`·`trace`·타임라인·연결 패널 결과, `edit_request`(본문의 대상), `memo` 링크, 감사 기록 API. 꺼진 모듈의 기록 번호·제목이 다른 화면으로 노출되고 첨부가 받아진다.

**Why it happens:**
코드 확인: `config/urls.py`의 `approve/`·`request/`·`print/`는 kwargs에 `app_label`/`model_name`이 있어 판정이 쉽지만, `attachment_download`는 `pk`만 받는다. 계획서 4절도 kwargs 모델 판정만 언급한다.

**How to avoid:**
- 판정을 미들웨어 한 곳에만 두지 않는다. 미들웨어는 1차 차단(URL 기반)이고, 모델이 확정되는 **서비스 함수**(`records` 설명서 조회, `can_view_target`, 첨부 생성, `edit_request`)가 `modules.assert_active(model)`을 다시 부른다 (이중 방어).
- 미들웨어의 기본값은 **fail-closed**: 대응표에 없는 URL은 기본 플랫폼이 아니면 거부. 모르는 라벨(`Foo.Bar`)·대소문자 변형은 404.
- URL 전수 테스트는 `get_resolver()` 재귀에 더해 (i) `admin.site._registry` 모델 × admin URL 6종 (ii) `RecordSpec` 등록 모델 × `records` 동작 전수 (iii) 쿼리스트링 의존 URL(autocomplete) 목록을 따로 점검한다.
- 본문 읽기(`request.body`)를 미들웨어에서 하지 않는다. 대용량 업로드가 메모리에 올라가고 파서와 충돌한다. 본문 기반은 뷰/서비스 층에서 판정한다.

**Warning signs:**
전수 테스트가 URL 패턴 수만 센다. `attachments`·`autocomplete`가 대응표에 「BASE」로 들어가 있다.

**Phase to address:** A1(미들웨어·대응표·fail-closed), A4(검색·타임라인·첨부·연결 패널 소비처), B1(`records` 도입 때 설명서 모델 전수 연결).

---

### Pitfall 8: `ensure_roles`가 `ModuleSwitch` 쓰기 권한을 품질엔지니어·품질팀장에게 자동으로 준다

**What goes wrong:**
새 모델 `core.ModuleSwitch`를 만드는 순간 `add_/change_/view_modulesswitch` 권한이 생기고, `migrate`마다 `ensure_roles`가 `delete_` 외 전부를 두 역할에 부여한다. 시스템 관리자만 켜고 끌 수 있어야 하는 설정이 품질팀장에게 열린다. 같은 이유로 라이선스 상태 모델(생기는 경우)·`EditRequest`류도 자동 부여된다.

**Why it happens:**
코드 확인: `qms/apps.py` `ensure_roles`는 `Permission.objects.filter(content_type__app_label__in=['core','qms']).exclude(codename__startswith='delete_')`로 **허용 목록이 아니라 전체 허용에서 일부 제외**하는 구조다. `TEAM_LEAD_ONLY`만 예외로 처리된다.

**How to avoid:**
- `ensure_roles`에서 `modulesswitch`의 add/change를 두 역할에서 제외한다 (`eng_only`/`engineer` 양쪽). 계획서가 「`ensure_roles`가 migrate마다 권한을 다시 세팅하므로 권한 제거 방식은 쓰지 않는다」고 한 것은 모듈 차단 얘기이고, 이 모델에는 해당하지 않는다.
- `has_change_permission`에서 `request.user.is_superuser`를 요구하고 `clean()`에서도 서버가 검사한다 (계획서와 같음).
- 테스트: 품질팀장 계정으로 스위치 PUT/POST/admin 변경이 403.

**Warning signs:**
권한 테스트가 시스템 관리자와 검사원만 있고 품질팀장 케이스가 없다.

**Phase to address:** A1.

---

### Pitfall 9: 데이터 마이그레이션이 앱 간 순환 의존을 만들거나 모듈 판정이 틀린 기록 수를 쓴다

**What goes wrong:**
`ModuleSwitch`는 `core`에 있는데 「`Capa`가 1건이라도 있으면 `qms_capa` 켬」 판정은 `qms` 모델을 읽어야 한다. `core` 마이그레이션이 `qms`를 참조하면 의존성이 순환한다(`qms`가 이미 `core`에 의존). 대표 모델이 없는 모듈(`qms_kpi`, `qms_document`는 `Document`)은 판정이 비어 있다.

**Why it happens:**
계획서 3절은 「모듈별 대표 모델」만 적었고 어느 앱 마이그레이션에서 실행하는지 정하지 않았다.

**How to avoid:**
- 데이터 마이그레이션은 `qms` 앱의 새 마이그레이션에 두고 `core`의 `ModuleSwitch` 마이그레이션에 의존시킨다 (역방향 의존 금지). `apps.get_model` 역사 모델로 `exists()`만 쓴다.
- 대표 모델 표를 계획서에 확정한다. KPI는 클레임·검사 중 하나라도 켜지면 켠다 같은 파생 규칙으로.
- 행 추가만 하고 `get_or_create`로 멱등. reverse는 이 마이그레이션이 만든 행만 지운다.
- 적용 전 `backup`, 운영 DB 사본 리허설, 출력 요약 (AGENTS.md 승인 규칙: 행 추가만이므로 허용 범위지만 되돌릴 수 있게).

**Warning signs:**
`makemigrations --check`가 의존성 경고를 낸다. 새 DB에서 `migrate`한 뒤 `ModuleSwitch` 행이 0건이다(정상) — 그리고 기존 DB 사본에서는 의도한 행만 생기는지 비교 테스트가 없다.

**Phase to address:** A1.

---

### Pitfall 10: 모듈 게이트를 켜는 순간 기존 464건 테스트·e2e가 줄줄이 깨지고, 우회 스위치로 「고치게」 된다

**What goes wrong:**
기본값이 「꺼짐」이라 기존 테스트가 전부 404가 된다. 가장 빠른 해결은 `settings.MODULE_GATE = False` 같은 환경 변수 우회인데, 이것이 운영에 남거나 게이트 버그를 가린다.

**Why it happens:**
기본 꺼짐 설계와 단일 테스트 DB 구성의 충돌.

**How to avoid:**
- 우회 스위치를 만들지 않는다. 테스트 베이스(`TestCase` 믹스인)가 `ModuleSwitch` 전체 켜기 + 테스트용 키로 서명한 라이선스를 심는 헬퍼를 쓴다. 게이트 자체 테스트만 그 헬퍼를 해제한다.
- 테스트 서명 키는 운영 공개키와 분리하고 운영 코드가 테스트 키를 신뢰하지 않게 한다 (`settings`에서 공개키 목록을 주입하되 운영 기본은 판매사 키 하나).
- `scripts/e2e_check.py`·`e2e_browser.py`도 같은 시드 단계를 거친다.

**Warning signs:**
`if settings.DEBUG`나 환경 변수로 게이트를 건너뛰는 분기가 코드에 있다.

**Phase to address:** A1(테스트 인프라는 미들웨어와 같은 커밋에서).

---

### Pitfall 11: 순수 파이썬 Ed25519 검증기의 구현 오류와 서명 대상 바이트의 정규화 문제

**What goes wrong:**
RFC 8032 참조 구현을 옮길 때 (i) `S >= L`인 서명을 거부하지 않는 가변성(malleability), (ii) 비정규 점 인코딩·`y >= p` 허용, (iii) 서명을 JSON 파싱 후 재직렬화한 문자열에 대해 검증해서 키 순서·공백 차이로 정상 키가 거부되거나 위조 여지가 생김, (iv) 요청마다 검증해 느림(순수 파이썬 Ed25519 검증은 수십 ms)이 생긴다.

**Why it happens:**
참조 구현 중심의 학습 코드라 방어 검사가 얇고, 라이선스를 「JSON 파일 + 서명 필드」로 두면 정규화 규칙이 모호하다. (경험, MEDIUM)

**How to avoid:**
- 서명 대상은 **원문 바이트**: 파일 = `base64(payload bytes) + base64(signature)`. 파싱·재직렬화 금지. 검증 성공한 바이트에서만 JSON을 읽는다.
- RFC 8032 7.1절 벡터 5종 외에 `S >= L` 거부, 비정규 인코딩 거부, 서명 1비트 변조 거부 케이스를 테스트에 넣는다.
- 검증 결과는 파일 mtime+크기를 키로 프로세스 메모리에 캐시한다. 요청마다 `stat`만 한다.
- 공개키는 코드 상수, 개인키는 저장소 밖(`scripts/issue_license.py`는 경로 인자로 받음). 개인키가 커밋되지 않도록 `.gitignore` 점검.

**Warning signs:**
검증 테스트가 정상 벡터만 있다. 서명 검증이 요청 핫패스에서 매번 돈다.

**Phase to address:** A2.

---

### Pitfall 12: 범용 편집이 한 건 승인 잠금 해제(`EditRequest`)를 동시에·부분적으로 소모한다

**What goes wrong:**
(a) 두 탭이 같은 승인된 수정 요청 1회분을 동시에 사용해 둘 다 저장된다. (b) 부모 저장 후 하위 표 저장이 실패했는데 `finish_edit`이 이미 승인을 「사용됨」으로 만들어 사용자는 다시 수정 요청을 해야 한다. (c) 시스템 관리자는 `_edit_unlocked = True`가 되어 하위 표와 `approved_*` 칸까지 풀린다.

**Why it happens:**
코드 확인: `begin_edit`(`core/rules.py:25`)는 `bool(unlock) or user.is_superuser`로 잠금 해제를 정하고, `edit_unlocked`는 `.first()`로 잠금 없이 조회하며, `finish_edit`은 현재 상태를 다시 확인하지 않고 `USED`로 저장한다. `save_with_lock`은 `@transaction.atomic`이라 부모·자식이 같은 트랜잭션이지만, 범용 API가 `save_with_lock`을 쓰지 않고 별도로 `obj.save()`를 호출하면 이 보호가 빠진다. admin은 `changeform_view`가 atomic이라 같은 효과를 얻었다.

**How to avoid:**
- 범용 저장은 반드시 `save_with_lock`(또는 같은 단일 트랜잭션 함수)을 통과한다. 직접 `obj.save()` 금지 — 린트성 테스트(`records` 모듈 소스에 `.save(` 직접 호출 금지)를 둔다.
- `edit_unlocked` 조회에 `select_for_update()`를 쓰고 `finish_edit`은 `status=APPROVED`일 때만 `USED`로 갱신(조건부 update 후 행 수 확인).
- 승인 후 잠금은 풀려도 `approved_by`·`approved_at`은 화이트리스트에서 항상 제외 (Pitfall 1).

**Warning signs:**
`records.py`에 `transaction.atomic` 없이 `save()`가 있다. 승인 소모 테스트가 순차 실행만 한다.

**Phase to address:** B2.

---

### Pitfall 13: 낙관적 동시성 제어가 검사기준에만 있다 — 범용 PUT은 조용히 덮어쓴다

**What goes wrong:**
두 사람이 같은 CAPA·클레임·문서를 열어 각각 저장하면 마지막 저장이 앞 저장을 지운다. 이력(simple-history)에는 남지만 사용자는 덮어쓴 사실을 모른다. PUT이 「전체 교체」 의미로 구현되면 본문에 없는 칸이 기본값으로 리셋된다.

**Why it happens:**
코드 확인: `spec_version`(기준서·항목 이력 중 최대 `history_id`)과 409는 `qms/rules.py` `save_spec`에만 있다(`docs/business-rules.md` 3절). 모델에는 `updated_at`이 없다.

**How to avoid:**
- 범용 상세 응답에 `version`(그 기록의 최신 `history.first().history_id`)을 포함하고, 저장은 `version`이 같을 때만 허용, 다르면 409 `다른 사람이 먼저 고쳤습니다. 다시 불러오세요.` (기존 문구 재사용).
- PUT 대신 **변경된 칸만 보내는 PATCH**. 본문에 없는 칸은 건드리지 않는다. 모르는 칸은 400 (Pitfall 1).
- 하위 표는 행 id 기반 (id 없는 행 = 추가, 목록에 없는 id = 삭제로 해석하지 않고 명시적 삭제 목록을 받는다) — 다른 기준서의 항목 id를 400으로 거부하는 기존 규칙(`save_spec`)을 일반화한다.

**Warning signs:**
`records` 상세 응답에 version이 없다. 같은 기록을 두 세션에서 저장하는 테스트가 없다.

**Phase to address:** B2(범용 규칙), B4·B5(8D 단계·심사 지적처럼 하위 표가 있는 모델에서 재확인).

---

### Pitfall 14: admin 폼·`save_model`에만 있던 로직을 범용 API가 빠뜨린다

**What goes wrong:**
admin이 폼 `clean`·`save_model`·`get_readonly_fields`로 하던 일이 API에서 사라진다: 문서번호 자동 부여와 번호 겹침 재시도(`qms/admin.py` `DocumentAdmin.save_model`, 최대 20번), 메모 작성자 고정(`MemoAdmin`: 본인 글만 수정), 검사기준 문서 `get_form`(개정 자동 채움), `first_article_state` 같은 파생 읽기 전용 칸, 폼 필드 `limit_choices_to`(거래처는 고객만, 일부 FK 필터).

**Why it happens:**
모델 `clean()`/`save()` 규칙은 이식되지만 admin 계층의 부가 동작은 설명서에 옮겨 적는 과정에서 누락되기 쉽다. 「기존 로직을 그대로 재사용」을 약속하지만 admin 클래스의 메서드를 하나씩 확인한 목록이 없다.

**How to avoid:**
- 모델별로 대응 `ModelAdmin`의 오버라이드 메서드(`save_model`, `get_form`, `get_readonly_fields`, `formfield_for_foreignkey`, `has_*_permission`, 폼 `clean`/`_post_clean`)를 표로 만들어 **B단계 착수 전** 체크리스트로 쓴다. 단계 완료 기준에 「그 모델의 admin 오버라이드 전부가 설명서·서비스 함수에 대응된다」를 넣는다.
- 공유 가능한 로직은 `core/rules.py`·`qms/rules.py`로 내려 admin과 API가 같은 함수를 쓰게 한다 (`dispose_nc`·`save_spec`이 이미 그 방식).
- FK 선택지는 `limit_choices_to`와 admin `formfield_for_foreignkey` 결과를 설명서의 `choices` 소스로 쓴다.

**Warning signs:**
설명서 정의에 `save_model` 대응이 없다. API로 만든 문서의 번호가 규칙과 다르다.

**Phase to address:** B1(문서·계측기 등 낮은 위험 묶음에서 체크리스트 검증), B4·B5·B6(묶음마다).

---

### Pitfall 15: 「관리 화면 주소」가 남아 한쪽만 옮겨진 반쪽 UI가 된다

**What goes wrong:**
`record_url` 일원화를 해도 직접 주소를 만드는 곳이 남아, 승인·요청 처리 후 돌아가기, 검색·타임라인·종합현황·메모 링크가 옛 admin으로 간다. 반대로 모듈이 꺼진 모델의 `record_url`은 `/app/...` 404 링크를 만든다. 메뉴·링크·북마크가 단계마다 섞인다.

**Why it happens:**
코드 확인(PROJECT.md): `core/search.py`, `core/timeline.py`, `qms/overview.py`, `qms/widgets.py`, `qms/similar.py`, `qms/memo.py`, `qms/views.py`, `core/views.py:170,204,228`, `core/admin.py` `related_panel`(`reverse('admin:..._change')` 직접 호출)이 각자 주소를 만든다.

**How to avoid:**
- 테스트로 강제: `reverse('admin:` 및 `'/admin/'` 문자열이 `record_url` 구현과 허용 목록 파일 밖에 없는지 소스 grep 테스트. B1 시작 때 이 테스트를 먼저 넣고 허용 목록을 단계마다 줄인다.
- `record_url`이 모듈 상태를 알도록: 꺼진 모듈의 기록은 일반 사용자에게는 링크 없는 텍스트 + 「비활성 모듈 기록」, 시스템 관리자에게는 읽기 링크 (A4 규칙과 같이).
- 단계마다 해당 모델이 옛 admin에서 열릴 때 「새 화면으로」 링크 (계획서 대로).

**Warning signs:**
`related_panel`이 아직 `reverse('admin:...')`를 부른다. 검색 결과 링크가 모델마다 다른 모양이다.

**Phase to address:** B1(일원화 구조와 grep 테스트), B2~B6(단계별 허용 목록 축소), A4(모듈 상태 반영).

---

### Pitfall 16: 화면 숫자 서식(`fmtNum`)이 판정과 다르게 보인다

**What goes wrong:**
측정값이 `10.5004`(저장 `decimal_places=5`), USL이 `10.50`인데 화면은 소수 둘째 자리로 줄여 `10.50 / 합격`처럼 보이거나 서버 판정은 불합격인데 표시값은 규격 안으로 보인다. 심사원이 성적서를 대조하면 불일치로 지적된다. 위치 막대·색을 JS 부동소수로 계산하면 서버 판정(`Measurement.passed`, Decimal)과 경계값에서 어긋난다.

**Why it happens:**
B0의 `fmtNum(value, decimals)`는 「하한·상한 중 소수 자릿수가 큰 쪽에 맞춰」 표시하고 `normalize()`로 0을 뺀다. 측정값 자릿수가 규격 자릿수보다 크면 반올림으로 의미가 바뀐다. 계획서가 자릿수 칸 부재(모델에 없음)를 인정하고 있다.

**How to avoid:**
- 판정(합격/불합격)·판정 띠 색·행 합격 표시는 **서버가 계산한 `passed`**를 그대로 쓴다. 프런트에서 재계산하지 않는다 (API에 항목별 `passed` 포함 — B0 읽기 키 추가 목록에 넣는다).
- 표시 자릿수는 `max(규격 자릿수, 측정값 실제 자릿수)`로 하여 측정값을 절대 반올림하지 않는다 (필요하면 더 길게 보인다). 0 제거는 화면 표시용에서도 규격과 같은 자릿수는 유지.
- Decimal은 API에서 **문자열**로 주고 프런트는 문자열 비교로 위치 막대를 계산하거나, 위치 막대는 서버가 비율을 계산한다.
- e2e에 경계값(`USL=10.5`, 값 `10.50001`) 한 건.

**Warning signs:**
프런트에서 `value <= usl` 비교로 색을 정한다. API가 Decimal을 숫자로 직렬화해 정밀도가 떨어진다 (`qms/api/plans.py`의 `_num` 같은 변환 확인).

**Phase to address:** B0.

---

### Pitfall 17: B0 읽기 전용 키 추가가 권한·모듈 범위 밖 정보를 흘린다

**What goes wrong:**
검사 상세 API에 계측기 이름, 검사기준 승인자, CAPA를 추가하면 `view_inspection` 권한만 있는 검사원이 `view_capa`·`view_gauge` 권한이 없는데도 CAPA 번호·계측기 정보를 본다. A 도입 후에는 꺼진 모듈(`qms_capa`)의 정보도 노출된다.

**Why it happens:**
상세 API는 하나의 권한으로 열리고 하위 정보는 같은 응답에 섞인다. `RelationsView`는 「볼 권한 없는 표는 개수도 알리지 않는다」(`docs/business-rules.md` 10절)를 지키지만 신규 키는 이 패턴을 따르지 않기 쉽다.

**How to avoid:**
- 신규 읽기 키마다 대상 모델 보기 권한을 확인하고 없으면 키를 아예 빼거나 `null`. 테스트에 검사원 계정 케이스.
- 모듈 필터: A1 이후 같은 함수가 `modules.active(model)`도 본다 (B0에서는 후크만 두고 A1에서 채움).

**Warning signs:**
테스트 계정이 항상 품질팀장/시스템 관리자다.

**Phase to address:** B0(권한 필터), A4(모듈 필터).

---

## Moderate Pitfalls

### Pitfall 18: 프런트 `frontend/dist`를 안 빌드·안 커밋한 채 master에 push한다

**What goes wrong:**
master 직접 push + PR/CI 없음(사용자 결정) 구조라, API는 바뀌었는데 커밋된 `frontend/dist`는 옛 것이어서 고객이 업데이트 후 깨진 화면을 본다. 또는 `dist`와 소스가 어긋나 e2e가 통과해도 배포본은 다르다.

**How to avoid:**
단계 종료 체크리스트에 `npm run build` → `git status frontend/dist`에 변경이 있으면 같은 커밋에 포함, e2e는 빌드 후 실행. push 직전 `git diff --exit-code frontend/dist` 또는 빌드 해시 확인 스크립트. `e2e_browser.py`가 시스템 Python으로 돌아가므로 `.venv`와 환경 차이로 통과·실패가 갈리지 않는지 단계마다 한 번 확인.

**Phase to address:** B0~B6 모든 단계 (완료 기준), A1(nav·me 변경이 `dist`를 건드릴 때).

### Pitfall 19: `RecordPage` props 계약·e2e 선택자를 깨뜨려 기존 화면 3종이 동시에 깨진다

**What goes wrong:**
B0가 `RecordPage` 겉모양을 `RecordShell`로 바꾸면서 품번·검사기준·관리계획서 화면과 e2e 선택자(탭 「연결」·「첨부」, region 「연결」, `[data-attachment]`, 「올리기」)가 함께 깨진다. 1920×1080에서 머리 띠+기본정보+첫 표가 한 화면에 안 들어간다.

**How to avoid:**
계획서의 「props 계약 유지」를 TypeScript 타입 수준에서 고정(기존 props 타입 불변 + 새 props는 선택). 교체 전에 해당 e2e를 먼저 돌려 기준선을 남기고, 교체 뒤 같은 선택자로 통과시킨다. 스크린샷 4화면(검사·품번·검사기준·관리계획서) × 라이트·다크 × 390px를 B0 완료 조건에 둔다.

**Phase to address:** B0.

### Pitfall 20: 비밀번호 재입력(SignModal)이 잘못된 사용자·로그에 노출된다

**What goes wrong:**
범용 승인·서명 엔드포인트가 `approver_id`를 본문에서 받아 다른 사람의 비밀번호로 서명하게 하거나, 오류 응답·로그·이력에 비밀번호가 남는다.

**How to avoid:**
서명 검증 대상은 항상 `request.user` (코드 확인: `sign_disposition`·`approve`가 이미 `user.check_password`). 비밀번호 칸은 응답·simple-history·`SECRET_FIELDS`에 없게 유지하고 설명서의 `fields`에 절대 넣지 않는다. 실패 횟수 제한은 현재 없으므로 필요하면 사용자 승인 사항으로 따로 올린다 (보안 변경).

**Phase to address:** B2(승인 연결), B3(MRB 서명).

### Pitfall 21: 하위 표 삭제·보류 삭제가 이력과 보류를 깨뜨린다

**What goes wrong:**
범용 하위 표 편집(`EditGrid`)이 `qs.delete()`나 `bulk_*`를 써서 simple-history를 건너뛴다. 부적합 삭제가 같은 LOT의 다른 부적합 보류까지 지운다.

**How to avoid:**
삭제는 반드시 `core.records.delete_record`(코드 확인: 해당 부적합이 만든 보류만 삭제) 경유. 다건 저장은 `bulk_create_with_history`/`bulk_update_with_history`만 허용 (`docs/business-rules.md` 11절). 일반 사용자 삭제는 요청 흐름만, 직접 삭제는 `is_superuser`(서버).

**Phase to address:** B2, B3.

### Pitfall 22: 목록 API가 28종 × 파생 칸으로 N+1·느린 목록이 된다

**What goes wrong:**
`status(obj)`·`_who`·`related_panel`을 행마다 호출해 목록 한 페이지에 수백 쿼리가 나간다.

**How to avoid:**
설명서에 `select_related`/`prefetch_related`를 필수로 두고, 목록용 `status`는 값만 쓰는 가벼운 함수로 분리한다. `assertNumQueries` 상한 테스트를 모델별로 한 번. 이 시스템 규모(단일 PC, SQLite→PostgreSQL 18, 수천~수만 행)에서는 페이지 50행 기준 쿼리 수만 지키면 충분하다.

**Phase to address:** B1(구조), B4~B6.

### Pitfall 23: SPA의 모듈 상태가 오래돼 보이지 않아야 할 버튼이 보이고, 404와 「비활성 모듈」을 구분 못 한다

**What goes wrong:**
`me_payload.modules`를 로그인 때만 받으면 시스템 관리자가 모듈을 끈 뒤에도 다른 사용자의 메뉴·버튼이 남아 눌렀을 때 일반 404 화면이 뜬다.

**How to avoid:**
404 응답 본문에 `code: "module_off"`를 포함해 SPA가 「비활성 모듈」 안내를 보인다 (계획서의 「일반 사용자 404」는 상태 코드 유지, 본문만 구분). `me`는 화면 진입·포커스 복귀 때 다시 읽는다. 서버가 막으므로 화면은 보조 수단이라는 원칙 유지.

**Phase to address:** A1, A4.

### Pitfall 24: 기본 플랫폼이 모듈 모델을 직접 참조해 꺼진 모듈 링크가 죽는다

**What goes wrong:**
코드 확인: 부적합 admin이 `capa_links`·`similar_html`·`related()`로 qms의 CAPA·클레임·SCAR를 직접 보여 준다. `Nonconformance.capa`/`capa_required`가 모듈 모델을 가리킨다. 모듈이 꺼지면 기본 플랫폼 화면에 죽은 링크·빈 패널이 생기고 심하면 오류가 난다.

**How to avoid:**
`enhances` 관계(계획서 표)를 실제로 소비하는 코드를 `core/modules.py`의 `enhances_active(a, b)` 한 곳으로. 부적합 상세의 CAPA/클레임/SCAR 칸은 해당 모듈이 꺼지면 숨기되 값은 보존. A4의 소비처 목록에 「기본 플랫폼 화면의 모듈 연결 칸」을 추가한다.

**Phase to address:** A4, B3(부적합 화면 설계에서).

### Pitfall 25: 일부만 구현한 「모듈 무관 규칙」 문서가 거짓이 된다

**What goes wrong:**
`docs/business-rules.md`에 「모듈과 무관하게 모델에서 동작한다」를 적었지만 테스트가 일부 규칙만 덮어서, 나중에 모듈 판정이 모델 `clean()`에 새어 들어가도 모른다.

**How to avoid:**
Pitfall 4의 「전 모듈 끔」 행렬 테스트를 문서 표의 모든 규칙(1~9절)에 대응시켜 만들고, 규칙을 바꾸면 이 테스트도 함께 고친다는 문장을 문서에 둔다. `core/modules.py`가 모델 모듈(`models.py`, `rules.py`)에서 임포트되지 않게 한다 (모델은 모듈 상태를 몰라야 한다 — 임포트 방향 테스트).

**Phase to address:** A3(테스트 행렬), A4(문서).

---

## Minor Pitfalls

### Pitfall 26: 메뉴·e2e 점검이 옛 admin 경로를 가정한다

메뉴 44개 중 24개가 `/admin/`이다. 단계마다 바꾼 항목만 `/app/`으로 옮기고 e2e의 메뉴 점검 목록도 같이 고친다. 허용 목록 테스트로 남은 admin 링크 수를 단계마다 줄어드는 숫자로 고정.

**Phase to address:** B1~B6.

### Pitfall 27: 비활성·사용 중지 기준정보를 지우도록 구현한다

기준정보(부서·거래처)는 지우지 않고 「사용」을 끈다(`docs/business-rules.md` 11절). 범용 삭제 동작이 기준정보에도 열려 있으면 이 규칙이 깨진다. 설명서에 모델별 삭제 가능 여부를 둔다.

**Phase to address:** B6.

### Pitfall 28: `ModuleSwitch` 이력·이름 문구가 한국어 규칙·`history`를 빠뜨린다

주변 코드의 방식(`history = HistoricalRecords()`, 한국어 `verbose_name`, `BaseAdmin`)을 따른다. 모듈 켜기·끄기는 심사 증적에 남아야 하므로 변경 사유·변경자(`changed_by`)를 이력과 함께 보존.

**Phase to address:** A1.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| 범용 `ModelSerializer(fields='__all__')` | 28종 한 번에 | 서명·판정 칸 노출 (Pitfall 1) | 절대 불가 |
| 모델 권한(`has_perm`)만 검사 | 코드 짧음 | admin 행 단위 규칙 소실 (Pitfall 2) | 절대 불가 |
| 미들웨어에서만 모듈 판정 | 한 곳 | 본문·쿼리·ID 경로 누수 (Pitfall 7) | 1차 차단으로만, 서비스 층 이중 방어 필수 |
| 테스트 우회 스위치(`MODULE_GATE=False`) | 464건 즉시 통과 | 운영 우회·게이트 버그 은폐 | 절대 불가, 테스트 시드 헬퍼로 대체 |
| PUT 전체 교체 | 구현 단순 | 칸 리셋·조용한 덮어쓰기 (Pitfall 13) | 절대 불가, PATCH+version |
| 프런트에서 판정 재계산 | API 변경 없음 | 서버 판정과 경계값 불일치 (Pitfall 16) | 절대 불가 |
| 라이선스를 JSON 재직렬화해 검증 | 읽기 쉬움 | 정상 키 거부·위조 여지 (Pitfall 11) | 절대 불가, 원문 바이트 서명 |
| `frontend/dist` 나중에 커밋 | 커밋 작게 | 고객이 옛 화면 (Pitfall 18) | 불가, 단계 완료 기준 |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| simple-history + 범용 API | `update()`·`bulk_create`로 이력 건너뜀 | `*_with_history` 사용, 저장은 `save_with_lock` |
| `ensure_roles` + 새 모델 | 전체 허용 구조라 새 모델 권한이 자동 부여 | 새 모델마다 제외 목록 검토 (Pitfall 8) |
| Django admin 자동완성 | 쿼리스트링으로 모델을 받아 URL 대응표를 우회 | `admin:autocomplete`도 모듈 판정 (Pitfall 7) |
| DRF `SessionAuthentication` + 미들웨어 | `process_view`는 DRF 인증 전이므로 `request.user`는 Django 세션 사용자 — 같은 세션이라 문제 없지만 향후 토큰 인증 추가 시 판정 어긋남 | 현재는 세션만 사용(코드 확인), 토큰 인증 도입 시 미들웨어 재검토 |
| `waitress` 다중 스레드 + 라이선스 캐시 | 캐시 갱신 경쟁 | 불변 객체를 통째로 교체(락 없는 원자적 대입), mtime 비교 |
| PostgreSQL 마이그레이션 | 앱 순환 의존 (Pitfall 9) | `qms` 마이그레이션이 `core`에 의존 |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| 목록의 행별 `status`·FK 이름 쿼리 | 목록 로딩 수 초 | `select_related`, `assertNumQueries` | 행 수천 건 이상 |
| 요청마다 Ed25519 검증 | 모든 요청이 수십 ms 느려짐 | mtime 키 메모리 캐시 | 즉시 (순수 파이썬) |
| 미들웨어가 요청마다 DB로 `ModuleSwitch` 조회 | 쿼리 수 증가 | 짧은 TTL 프로세스 캐시 + 변경 시 무효화(단일 프로세스 전제 확인) | 동시 사용자 수십 명 |
| `Lot.descendants()` 재귀 (기존) | 계보가 깊은 LOT 보류 생성 지연 | 기존 동작 유지, 범용 API가 호출 횟수를 늘리지 않게 | 계보 수천 노드 |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| 범용 API로 `approved_by` 위조 | MRB 서명 위조 — 높음 | 화이트리스트, 전용 동작 (Pitfall 1) |
| 행 단위 admin 권한 미이식 | 보류 해제·판정 수정 — 높음 | `_registry` 동등성 테스트 (Pitfall 2) |
| 꺼진 모듈 첨부 다운로드 가능 | 비활성 모듈 자료 유출 — 중간 | 서비스 층 `assert_active` (Pitfall 7) |
| 서버가 아닌 SPA만 모듈 차단 | 직접 URL 호출 우회 — 중간 | 서버가 막고 화면은 보조 (원칙) |
| 개인(`personal`) 모델이 범용 `records`에 등록 | 연차·급여 열람 규칙 파괴 — 높음 | `PRIVATE_APPS`는 설명서 등록 금지, 테스트로 강제 (`docs/business-rules.md` 10절) |
| 라이선스 개인키가 저장소·고객 PC에 | 위조 키 발급 — 높음 | 개인키는 저장소 밖, `.gitignore`·커밋 전 검사 |
| 시스템 시계 되돌림 | 만료 무력화 — 낮음~중간 | simple-history 최대 시각 하한 (Pitfall 5) |
| 시스템 관리자 종결 화이트리스트가 경로 접두사 단위 | 비활성 모듈에 임의 쓰기 — 중간 | 정확한 url_name+메서드 목록 |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| 인터록 오류가 원인을 안 보임 | 현장이 「왜 못 하나」 모름 | `[4M 변경] CR-… 초품 검사 합격 전` 형식, 칸별 오류 (계획서 5절) |
| 일반 404로 「비활성 모듈」 표시 | 버그로 오인 | 본문 코드로 안내 화면 (Pitfall 23) |
| 만료 당일에야 알림 | 현장 정지 | 14일 전 배너·내 할 일 |
| 편집 모드에서 잠긴 칸이 편집 가능해 보임 | 저장 시점에 409 | 서버가 칸별 `editable`을 응답, 저장 거부 시 칸별 메시지 |
| 상태를 색으로만 표시 | 색각 이상·흑백 인쇄 | 색+글자 (계획서 B0 규칙 유지) |
| 삭제 버튼 두 곳 | 실수 삭제 | 「⋯」 한 곳 (계획서) |

## "Looks Done But Isn't" Checklist

- [ ] **범용 저장 API:** 화이트리스트 외 칸 거부 확인 — `approved_by`·`result`·`released_at`·`closed_at`를 보내 400
- [ ] **범용 저장 API:** 품질엔지니어로 Hold 변경·판정된 검사 변경 시도 → 403 (admin과 같은 결과)
- [ ] **범용 저장 API:** 같은 승인 수정 요청으로 동시 2회 저장 → 1회만 성공
- [ ] **범용 저장 API:** 오래된 `version`으로 저장 → 409
- [ ] **모듈 게이트:** `get_resolver()` 전수 + admin 등록 모델 × URL + `records` 등록 모델 × 동작 + autocomplete 모두 매핑
- [ ] **모듈 게이트:** 대응표에 없는 새 URL이 기본 거부인지 (일부러 하나 추가해 확인)
- [ ] **모듈 게이트:** 모든 모듈 끈 상태에서 `docs/business-rules.md` 1~9절 인터록이 모델 레벨에서 그대로 동작
- [ ] **라이선스:** 위조·1비트 변조·`S>=L`·파일 없음·손상·만료·만료 직전 14일 경고
- [ ] **라이선스 만료:** 부적합 등록 허용 여부가 사용자 결정대로 구현되고 테스트됨
- [ ] **마이그레이션:** 운영 DB 사본에서 켜진 모듈 목록 확인, `makemigrations --check` 변경 없음, reverse 확인
- [ ] **권한:** 품질팀장이 `ModuleSwitch`를 못 바꿈 (`ensure_roles` 이후)
- [ ] **B0 화면:** 경계값(규격 끝, 소수 자릿수 많은 값)에서 서버 `passed`와 표시 일치
- [ ] **링크:** `reverse('admin:` 잔존 grep 테스트가 단계마다 줄어든 허용 목록으로 통과
- [ ] **배포:** `npm run build` 후 `frontend/dist` 변경이 같은 커밋에 포함
- [ ] **검증:** `manage.py test`, `e2e_check.py`, `e2e_browser.py`, `makemigrations --check` 실제 출력 확인 (통과를 추측으로 보고하지 않는다)

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| 서명·승인 칸 위조 가능 상태로 배포됨 (1) | HIGH | API 즉시 비활성(쓰기 중단), 이력(`history`)에서 `approved_by` 변경 이력 대조, 영향 기록의 승인 재확인, 화이트리스트 후 재배포 |
| 모듈 끄기로 인터록 갇힘 (4) | MEDIUM | `ModuleSwitch` 직접 켜기(DB, 백업 후), 라이선스 재발급, 열린 기록 종결 |
| 업그레이드 후 라이선스 없음으로 기능 소실 (6) | MEDIUM | 키 배치 후 재시작, 임시로 기존 행 켜기 + 유예 라이선스 발급 |
| 만료로 부적합 등록 불가 (5) | MEDIUM | 임시 갱신 키 발급, 그 사이 종이 부적합 보고서 후 시스템 소급 등록(이력에 사유) |
| 잘못된 마이그레이션 (9) | LOW | reverse(만든 행만 삭제) 후 수정 (행 추가만이므로 데이터 손실 없음, 사전 `backup`) |
| 낡은 `dist` 배포 (18) | LOW | 빌드·커밋·push |
| 동시 편집 덮어쓰기 (13) | MEDIUM | `history`에서 이전 값 복원(수동), version 도입 |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1 서명·승인 칸 위조 | B1(구조), B2, B3 | 위조 PUT 400 테스트, 소스 grep `fields='__all__'` 0건 |
| 2 admin 행 단위 권한 소실 | B1, B2, B3 | 모델×동작×역할 전수 표와 admin 대조 테스트 |
| 3 생성 시점만 걸린 인터록 | B2, B3, B6 | 보류 LOT으로 기존 행 이동·`result` 채운 POST 거부 |
| 4 인터록 갇힘·라이선스 경로 우회 | A1, A2, A3 | 전 모듈 끔 행렬, 라이선스 closure 거부, 화이트리스트 동작 테스트 |
| 5 만료가 부적합 등록 차단 | A2 (시작 전 결정) | 만료 상태에서 NC 등록 테스트 |
| 6 라이선스 없음 업그레이드 | A1, A2, A4 | 키 없는 기존 DB 사본 리허설 |
| 7 URL 외 경로 누수 | A1, A4, B1 | 전수+이중 방어 테스트, autocomplete·첨부 |
| 8 `ensure_roles` 자동 권한 | A1 | 품질팀장 스위치 변경 403 |
| 9 마이그레이션 순환·판정표 | A1 | `makemigrations --check`, 운영 사본 비교 |
| 10 테스트 대량 실패·우회 스위치 | A1 | 소스에 게이트 우회 분기 없음, 시드 헬퍼 사용 |
| 11 Ed25519 구현·서명 정규화 | A2 | RFC 벡터+가변성·변조 테스트 |
| 12 수정 승인 동시 소모 | B2 | 동시 2회 저장 테스트 |
| 13 낙관적 동시성 부재 | B2, B4, B5 | stale version 409 |
| 14 admin 폼·save_model 로직 누락 | B1, B4, B5, B6 | 모델별 admin 오버라이드 대응 체크리스트 |
| 15 admin 주소 잔존 | B1~B6, A4 | `reverse('admin:` grep 테스트 |
| 16 숫자 서식 ≠ 판정 | B0 | 경계값 e2e |
| 17 읽기 키 권한·모듈 노출 | B0, A4 | 검사원 계정 테스트 |
| 18 `dist` 누락 | B0~B6 | 단계 완료 체크리스트 |
| 19 RecordPage 계약·선택자 파손 | B0 | 기준선 e2e, 스크린샷 4종 |
| 20 비밀번호 재입력 오용 | B2, B3 | 서명 대상 `request.user` 고정 테스트 |
| 21 이력·보류 삭제 | B2, B3 | `delete_record` 경유 테스트 |
| 22 N+1 | B1, B4~B6 | `assertNumQueries` |
| 23 SPA 모듈 상태 지연 | A1, A4 | `module_off` 본문 안내 e2e |
| 24 기본 플랫폼의 모듈 링크 | A4, B3 | 꺼진 모듈에서 부적합 화면 |
| 25 모듈 무관 규칙 문서 거짓 | A3, A4 | 행렬 테스트, 임포트 방향 테스트 |
| 26~28 메뉴·기준정보 삭제·이력 문구 | B1~B6, B6, A1 | 메뉴 점검, 삭제 불가 모델 표, 이력 확인 |

## Phase-Specific Warnings

| Phase | Likely Pitfall | Mitigation |
|-------|---------------|------------|
| B0 | 16, 17, 19, 18 | `passed`·권한 필터 읽기 키, 계약 고정, 기준선 e2e, dist |
| A1 | 7, 8, 9, 10, 4(일원화), 6 | fail-closed 미들웨어, `ensure_roles` 제외, `qms` 마이그레이션, 시드 헬퍼 |
| A2 | 5(결정), 11, 6 | 만료 정책 사용자 승인 먼저, 원문 바이트 서명 |
| A3 | 4, 25 | 정확한 화이트리스트, 라이선스 경로 경고, 전 모듈 끔 행렬 |
| A4 | 7, 15, 23, 24 | 소비처 목록에 첨부·autocomplete·기본 플랫폼 연결 칸 추가 |
| B1 | 1, 2, 14, 15, 22 | 설명서 화이트리스트·권한 구조를 낮은 위험 묶음에서 확정 |
| B2 | 1, 3, 12, 13, 20, 21 | `save_with_lock` 단일 경로, version, PATCH |
| B3 | 1, 3, 20, 24 | 처분은 `dispose_nc` 전용, 보류 읽기 전용 |
| B4~B6 | 13, 14, 15, 27 | 모델별 admin 오버라이드 대응표 |

**깊이 조사 필요 단계:** A2 라이선스 정책(만료·유예) 결정, A3 시스템 관리자 종결 화이트리스트(초품 해제 수단), B3 부적합 전용 본문. 나머지는 표준 패턴.

**사용자 승인이 필요한 결정 후보 (AGENTS.md 승인 규칙과 연결):** (1) 만료 읽기 전용에서 부적합 등록 허용 여부, (2) 레거시 고객 유예 라이선스, (3) 비활성 모듈의 4M 초품 해제 수단 — 검사 판정 허용 또는 수동 해제 신설, (4) 인터록을 「수정 시점」에도 강제할지 (Pitfall 3).

## Sources

- 이 저장소 코드 직접 확인 (HIGH): `core/rules.py`(`begin_edit`·`finish_edit`·`save_with_lock`·`sign_disposition`·`dispose_nc`), `core/records.py`(`delete_record`·`edit_unlocked`·`can_edit_locked`), `core/models.py`(`Approvable`·`Nonconformance.clean/save`·`Hold`·`Shipment.clean`·`WorkResult.clean`·`LotLink.clean`·`Lot.assert_usable`), `qms/models.py`(`Inspection.clean/save/finalize`·`Measurement`), `core/admin.py`(`BaseAdmin`·`NonconformanceForm`·`HoldAdmin`), `qms/admin.py`(`has_*_permission` 오버라이드), `qms/apps.py`(`ensure_roles`), `config/settings.py`(미들웨어·DRF 설정), `config/urls.py`, `core/api/permissions.py`, `core/middleware.py`
- `docs/business-rules.md`, `.planning/PROJECT.md`, 승인된 계획 `C:\Users\gogog\.claude\plans\twinkling-dreaming-lollipop.md`
- RFC 8032 (Ed25519) — 가변성·정규 인코딩 요건은 일반 암호 구현 지식 (MEDIUM, 외부 조회는 하지 않음)
- 모듈 게이트·라이선스 만료 정책 항목의 일반 실패 양상 — 비슷한 온프레미스 제품의 경험적 지식 (MEDIUM, 이 저장소에서 미검증)

---
*Pitfalls research for: 온프레미스 Django + React QMS/MES (모듈 게이팅 + 범용 records API)*
*Researched: 2026-11-13*
