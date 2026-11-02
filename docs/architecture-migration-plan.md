# QMS+MES 프론트엔드·백엔드 아키텍처 전환 검토

- 작성일: 2026-11-02
- 대상 커밋: `9b2c609`
- 독자: 저장소 관리자(1인)와 이 저장소에서 작업하는 AI. 파일·함수 단위로 적는다.
- 성격: **검토·계획 문서다.** 이 문서를 쓰면서 소스코드는 바꾸지 않았다.
- 승인 필요: 문서에 적은 패키지 설치, 권한·보안 변경, DB 이전은 하나하나 사용자 승인을 받은 뒤에 실행한다(`AGENTS.md`).
- 표기 규칙: 코드에서 확인한 내용은 위치를 함께 적는다. 확인하지 못한 내용은 **미확인**으로 표시한다.

## 0. 요약

**결론**

1. 전환은 가능하다. 업무 규칙 대부분이 모델 `save()` 안의 `self.clean()` 호출에 있어서, 입력 경로가 admin이든 API든 같은 검증을 받는다.
2. 다만 일부 규칙은 **관리 화면(admin)이나 전용 뷰에만 있다.** API가 이것을 다시 구현하지 않으면 규칙이 우회된다. 해당 규칙은 9장 표에 모두 적었다. 그중 위험이 가장 큰 것은 다음 넷이다.
   - 부적합 MRB 처분 때 비밀번호 재입력
   - 종결된 부적합의 잠금
   - 삭제는 시스템 관리자만
   - 승인 필드는 승인 서명 화면에서만 기록
3. 사용자는 "완전 일괄 교체"를 골랐다. 이 문서는 그 결정을 따른다. 대신 **개발은 기능 묶음별로 하고, 기존 화면을 없애는 일은 마지막 한 단계로 몰아서** 그 전까지 언제든 되돌릴 수 있게 한다(7장, 10장).
4. 운영 PC에는 Node가 필요 없다. React는 개발 PC에서 빌드하고, 결과 정적 파일만 지금처럼 waitress + whitenoise가 제공한다.

**인터뷰에서 정한 사용자 결정**

| 주제 | 결정 |
| --- | --- |
| 전환 동기 | 현장 입력 속도·편의, 외관·대외 인상, 관리 화면의 한계 |
| 유지보수 인력 | 사용자 1인 + AI. React 경험은 적다 |
| 디자인 | Ant Design `ConfigProvider` 토큰을 현재 Fiori 값(`fiori.css`, 주색 #0057d2 등)에 맞춘다 |
| 첫 시범 화면 | 공장 종합현황(`/overview/`) + 내 할 일(`/todo/`) |
| 시범 중단 기준 | 사용자 반응. 기존 화면보다 크게 나아졌다고 느끼지 못하면 멈춘다 |
| 전환 방식 | 완전 일괄 교체. 전부 만든 뒤 업무 템플릿을 지우고 React만 남긴다 |
| 인증 | 같은 출처(origin), Django 세션 + CSRF. JWT는 쓰지 않는다 |
| 사용 기기 | 사무실 PC 중심. 현장 화면(검사 입력의 터치·바코드, 부적합 등록의 휴대폰 사진)도 React로 옮긴다 |
| 잠금 규칙 재사용 | admin과 API가 함께 부르는 공용 함수로 추출한다. 두 경로의 동작이 같다는 것을 테스트로 증명한다 |
| 출력 | 인쇄 화면은 React로 다시 만든다. 엑셀·ZIP은 지금처럼 서버(openpyxl·zipfile)가 만들고 API로 내려준다 |
| 개발 동결 | 필요 없다. 아직 운영 전이다 |
| PostgreSQL | React 전환과 함께 옮긴다 |
| 데이터 | `data/`는 데모·테스트 데이터라 다시 만들 수 있다 |
| 전환 후 admin | 시스템 관리자(superuser)만 쓴다. 보안·권한 변경이므로 구현 때 별도로 승인받는다 |
| 테스트 | Python 중심. API는 Django `TestCase`, 화면 흐름은 Python Playwright로 확인한다. 프런트 단위 테스트는 최소로 둔다 |

**승인이 필요한 항목:** 부록 A에 모았다.

---

## 1. 현재 아키텍처 평가

### 1.1 구성 (2026-11-02 코드 기준)

| 항목 | 현재 | 확인 위치 |
| --- | --- | --- |
| 런타임 | Python 3.12, Django 6.1.2 | `requirements.txt` |
| 의존성 | django-simple-history 3.13.0, openpyxl 3.1.5, waitress 3.0.2, whitenoise 6.12.0 (모두 5개) | `requirements.txt` |
| 화면 | Django admin + 전용 템플릿. 부분 갱신은 동봉한 htmx로 한다 | `core/static/htmx.min.js`, `templates/admin/base_site.html` |
| 자체 JS | `shell.js`, `dashboard.js`, `nc_form.js`, `copy_mail.js` | `core/static/qms/` |
| 디자인 | `fiori.css` 토큰. 다크 모드는 `prefers-color-scheme`. 글꼴은 시스템 글꼴(`"Segoe UI", "Malgun Gothic", …`)이라 외부 로드가 없다 | `core/static/qms/fiori.css` |
| DB | SQLite (`transaction_mode='IMMEDIATE'`, `timeout=20`). `QMS_DB_NAME`을 주면 PostgreSQL 설정을 쓴다. psycopg는 설치되어 있지 않다 | `config/settings.py` 99~112행 |
| 서버 | 개인용은 `서버시작.bat`(runserver), 사내망은 `scripts/serve.ps1`(waitress, `QMS_DEBUG=0`, `collectstatic`) | |
| 인증 | Django 세션. `LOGIN_URL='/admin/login/'`. 모든 전용 뷰는 `@staff_member_required`라서 `is_staff` 사용자만 들어온다 | `config/settings.py`, `core/views.py`, `qms/views.py` |
| 첨부 | `/media/`는 `staff_member_required(serve)`로 준다. 개인 명세서는 `data/private/`(MEDIA_ROOT 밖)에 있고 소유자 전용 뷰로만 준다 | `config/urls.py`, `personal/views.py` |

### 1.2 규모

| 항목 | 수 | 근거 |
| --- | --- | --- |
| 실제 모델 | 44개 (core 14, qms 26, personal 4) + 추상 `Approvable` | `^class` 검색 |
| 변경 이력이 있는 모델 | 39개. 없는 것은 `DashboardLayout`과 personal 4개다. personal은 다른 경로로 개인정보가 새지 않도록 일부러 이력을 쓰지 않는다(`personal/admin.py` `OwnerAdmin` 설명) | `history = HistoricalRecords` 검색 |
| admin에 등록된 모델 | 30개 (core 9, qms 18, personal 3). 나머지는 인라인으로 편집한다 | `@admin.register` |
| URL | `config/urls.py`의 `path` 34개 + `/media/` | |
| 전용 뷰 | 공개 뷰 약 35개 (core 13, qms 21, personal 2). 내부 함수(`_` 시작)는 뺀 수다 | `^def` + 데코레이터 |
| 템플릿 | 36개. 앱 템플릿 32개 + `templates/admin/` 4개 | `find *.html` |
| 테스트 | 155개 (core 60, qms 79, personal 16) + e2e 76개 | `docs/testing.md` |
| 앱 파이썬 코드 | 약 6,750줄 (`core/`, `qms/`, `personal/`의 최상위 `.py`) | `wc -l` |

### 1.3 요청 흐름

```
브라우저 ──HTTP──▶ waitress ──▶ Django 미들웨어 (whitenoise, 세션, CSRF, 인증, simple-history, no_store_pages)
                                    ├─ /admin/…          SimpleHistoryAdmin 기반 BaseAdmin (core/admin.py)
                                    ├─ /todo/ /overview/ /inspect/ /trace/ /nc/new/ /kpi/ …  전용 뷰 + 템플릿
                                    ├─ /approve/ /request/ /print/ /report/                   승인·요청·출력 공통 뷰
                                    └─ /media/            staff 전용 파일
                                          │
                                   모델 save() → self.clean() → DB (SQLite)
```

### 1.4 강점 (전환해도 반드시 지킬 것)

- **규칙이 모델에 있다.** 아래 12개 모델은 `save()`에서 `self.clean()`을 직접 부른다. 그래서 어느 경로로 저장해도 인터록·처분·판정 규칙이 같이 걸린다.
  - core: `WorkResult`, `LotLink`, `Nonconformance`, `Shipment`
  - qms: `Inspection`, `Measurement`, `ChangeRequest`, `CustomerClaim`, `Scar`, `Capa`, `InternalAudit`, `PpapSubmission`
  - 승인 후 잠금은 `Approvable.save`, `Characteristic.save`, `ControlPlanLine.save`, `PpapElement.save`가 `_edit_unlocked` 플래그로 강제한다.
- **이력이 자동으로 남는다.** `HistoryRequestMiddleware`가 요청 사용자를 이력에 기록한다. DRF 뷰도 같은 Django 요청이라 그대로 동작한다. 단, 세션 인증일 때만 그렇다(6.2절).
- **오프라인·단일 PC 운영이 단순하다.** 의존성 5개, 외부 CDN·글꼴 없음, 백업·복원 명령(`backup`, `restore`)이 있다.
- **집계 로직이 화면과 분리되어 있다.** `qms/due.py`, `qms/kpi.py`, `qms/spc.py`, `core/timeline.py`, `core/search.py`는 템플릿 없이 값만 계산한다. 그래서 API에서 그대로 부를 수 있다. 예외는 1.5의 URL 결합이다.

### 1.5 한계와 전환 시 걸림돌

| 한계 | 내용 | 위치 |
| --- | --- | --- |
| admin UI의 입력 효율 | 목록·폼이 Django 기본 구조라서 현장 입력과 휴대폰 화면에 한계가 있다(사용자가 밝힌 전환 동기) | `core/admin.py`, `qms/admin.py` |
| 규칙 일부가 admin 계층에만 있다 | 잠금 해제 1회 소모, 삭제 권한, MRB 비밀번호, 종결 부적합의 읽기 전용 칸 등. 전체 목록은 9.2 | `core/admin.py` `BaseAdmin`, `NonconformanceForm`, `NonconformanceAdmin.get_readonly_fields` |
| 집계 결과에 admin URL이 섞여 있다 | 집계 함수가 `reverse('admin:…')` 링크나 HTML을 돌려준다. React가 쓰려면 링크 대신 식별자(id·모델명)를 돌려주도록 나눠야 한다 | `qms/widgets.py`(`reverse(` 10회), `core/timeline.py`(8회), `core/search.py`(4회), `qms/similar.py` `similar_html` |
| 필드 단위 검증은 `full_clean()`에서만 돈다 | `save()`의 `self.clean()`은 모델 `clean()`만 부른다. `choices`·`max_length`·`unique`·필수 칸 검사와 `validate_photo` 같은 필드 검사기는 `full_clean()`(폼·`core/importer.py`)에서만 돈다. `Evidence.clean`, `Payslip.clean`은 `save()`가 부르지 않는다 | `qms/models.py` 544행, `personal/models.py` 59행, `core/importer.py` 47행 |
| 번호 생성이 SQLite에 맞춰져 있다 | `_nc_number`는 날짜별 순번이다. SQLite IMMEDIATE 트랜잭션이라야 겹치지 않는다. `shortcut:` 주석에 PostgreSQL에서는 중복될 수 있으니 전환 시 DB 시퀀스로 바꾸라고 적혀 있다. `_capa_number`는 "그날 건수 + 1" 방식이다. 동시에 만들면 저장할 때 중복 오류로 막힌다(함수 설명) | `core/models.py` 267~273행, `qms/models.py` 551행 |
| 서버에서 그리는 화면 | SPC 관리도는 서버가 그리는 SVG(`spc.html`의 `<svg>`·`<polyline>`)다. 인쇄 화면 3종은 HTML 템플릿이다 | `qms/spc.py` `control_chart`, `core/templates/core/print.html`·`nc_print.html`, `qms/templates/qms/audit_pack.html` |

---

## 2. 권장 아키텍처

### 2.1 구성도

```
[개발 PC]  frontend/ (React + TS + Vite + antd)  ──npm run build──▶  frontend/dist/  (정적 파일)
                                                                       │ 배포 zip 또는 Git에 포함 (4.3절)
[운영 PC]  waitress ─▶ Django (같은 출처, 포트 1개)
              ├─ /api/…          DRF. 세션 인증 + CSRF. 업무 규칙은 모델 + core/rules.py(새 공용 함수)
              ├─ /admin/…        Django admin. 전환 후 superuser 전용 (승인 필요)
              ├─ /assets/…       whitenoise가 frontend/dist의 JS·CSS 제공
              ├─ /media/…        지금과 같음 (로그인 staff)
              └─ 그 밖의 경로    index.html 하나를 돌려주는 Django 뷰 (React 라우터가 화면 결정)
                                         │
                                  모델 save()/clean() ─▶ SQLite → (5단계) PostgreSQL
```

### 2.2 원칙

1. **같은 출처, 서버 하나.** React와 API를 같은 waitress가 제공한다. CORS 설정도 별도 프런트 서버도 없다.
   - 설치·방화벽·백업 절차가 지금과 같다(`scripts/serve.ps1`).
   - 개발 중에만 Vite 개발 서버(5173)가 `/api`를 Django(8000)로 프록시한다.
2. **Node는 개발 PC에만 둔다.** 운영 PC는 빌드된 정적 파일만 받는다. 운영 PC에 Node가 있는지는 **미확인**이지만, 이 구조에서는 상관이 없다.
3. **규칙은 서버에만 둔다.** React의 입력 검사는 편의를 위한 것이고, 규칙의 근거가 아니다.
   - 모든 저장은 모델 `full_clean()` + `save()`를 거친다.
   - admin에만 있던 규칙은 공용 함수(`core/rules.py`, 새 파일)로 옮기고, admin과 API가 같이 부른다.
4. **세션 인증만 쓴다.** 로그인 화면은 React가 만들고, 로그인 처리는 Django `authenticate()`/`login()`으로 한다.
   - 세션 쿠키, CSRF 쿠키, `X-CSRFToken` 헤더를 쓴다.
   - JWT를 쓰지 않으므로 토큰 저장·갱신 로직이 필요 없다.
5. **admin은 남긴다.** 기준정보 대량 편집, 이력 조회, 비상 수정에 쓴다. 전환 후에는 superuser 전용으로 바꾼다(승인 필요).

### 2.3 왜 이 구성인가

- **같은 출처 + 세션 인증:** 지금 쓰는 `HistoryRequestMiddleware`, `staff_member_required`, CSRF 보호를 그대로 쓸 수 있다. 보안 표면이 늘지 않는다.
- **antd:** npm 패키지로 설치하면 아이콘·스타일이 번들에 들어간다. CDN이 필요 없다.
- **차트 라이브러리를 넣지 않는다:** SPC 관리도는 지금도 직접 그린 SVG다. React에서도 `<svg>`로 그리면 의존성이 늘지 않는다.

---

## 3. 기존 기능 재사용 범위

### 3.1 그대로 쓴다 (수정 없음)

| 대상 | 위치 | 비고 |
| --- | --- | --- |
| 모델 44개와 `clean()`/`save()` 규칙, 마이그레이션 | `core/models.py`, `qms/models.py`, `personal/models.py` | 스키마를 바꾸지 않는다. 예외는 PostgreSQL 번호 시퀀스(5단계) |
| 역할·권한 | `qms/apps.py` `ensure_roles` | API 권한 검사의 근거로 그대로 쓴다 |
| 승인자 판정 | `core/models.py` `is_approver`, `APPROVER_GROUP` | |
| 삭제·잠금 기본 함수 | `core/records.py` `delete_record`, `blockers`, `edit_unlocked`, `can_edit_locked`, `is_locked` | |
| 집계 | `qms/due.py` `due_items`·`recent_spc_alarms`, `qms/kpi.py` `monthly`·`pareto`·`process_yield`·`suppliers`, `qms/spc.py` `control_chart`, `Characteristic.spc_series` | 값만 돌려주므로 serializer로 감싸면 된다 |
| 계보·검사 로직 | `Lot.descendants`, `Lot.assert_usable`, `Inspection.finalize`, `Nonconformance.missing_fields`, `EditRequest.decide` | |
| 엑셀 | `core/importer.py`(가져오기, `full_clean` 포함), `ExcelTemplate.fill`(양식 출력) | API는 파일 업로드·다운로드만 받는다 |
| 관리 명령 | `backup`, `restore`, `collect`, `notify` | `notify` 메일 본문의 링크 경로만 새 화면 주소로 바꿔야 할 수 있다. **미확인**, 1단계에서 확인한다 |
| 디자인 토큰 값 | `core/static/qms/fiori.css` `:root` | antd 토큰으로 옮겨 적는다(값 재사용) |

### 3.2 공용 함수로 추출한다 (admin과 API가 함께 호출)

| 지금 위치 | 하는 일 | 추출 후 |
| --- | --- | --- |
| `BaseAdmin.save_model` | 잠긴 기록이면 수정 승인(`EditRequest` APPROVED) 또는 superuser일 때만 `_edit_unlocked`를 켠다. 저장에 성공하면 승인을 `USED`로 바꾼다 | `core/rules.py` `save_with_lock(obj, user, changed_fields)` |
| `BaseAdmin.save_formset` | 부모의 잠금 해제를 하위 항목(검사항목·관리계획 행 등)에 넘긴다 | 위 함수가 하위 항목 저장도 받는다 |
| `BaseAdmin.has_delete_permission`, `_delete` | 삭제는 superuser만. `delete_record` + `ProtectedError`를 처리한다 | `core/rules.py` `delete_as(obj, user)` |
| `NonconformanceForm.clean`·`_post_clean` | 처분할 때 비밀번호 재확인, `approved_by`/`approved_at` 기록, `missing_fields` 검사 | `core/rules.py` `dispose_nc(nc, user, password, data)` |
| `NonconformanceAdmin.get_readonly_fields` | 종결 후 열린 칸은 `AFTER_APPROVAL`뿐이다. `INTERLOCK` 칸은 관리자도 못 바꾼다 | `core/rules.py` `nc_editable_fields(nc, user)` |
| `NcPhotoInline._open`, `LockedWhenApprovedInline` | 잠긴 부모의 하위 항목·사진은 추가·수정·삭제할 수 없다 | `core/rules.py` `child_editable(parent, user)` |
| `ApprovalAdminMixin` | 승인 필드는 승인 서명 경로에서만 기록한다. 승인되면 모든 칸이 읽기 전용이다 | serializer에서 승인 필드를 항상 읽기 전용으로 둔다 + `nc_editable_fields`와 같은 방식 |
| `InspectionAdmin` | 검사원 = 요청 사용자, 승인된 기준만 선택, 판정 후 수정 불가, `_finalize` → `finalize()` | 검사 생성은 `inspect_submit`의 트랜잭션 블록을 `qms/rules.py` `submit_inspection(...)`로 옮긴다 |
| `MemoAdmin`, `memo_edit` | 메모 수정은 작성자만 | 객체 권한 클래스 1개 |
| `OwnerAdmin` 계열 | 본인 기록만 조회. 남의 것은 404. `owner` = 요청 사용자. 연차 기본정보는 1인 1건 | `personal` API 전용 queryset 필터 + 권한 |
| `core/views.py` `approve` | Approvable만 대상, 승인자만, 비밀번호 재확인 후 `save()` | `core/rules.py` `approve(obj, user, password)` |
| `core/views.py` `_get_record` | 요청·인쇄·승인 경로에서 `personal`·`auth`·`admin`·`sessions`·`contenttypes` 앱을 막는다 | 그대로 import해서 쓴다 |

**추출 원칙**

- 함수 본문은 지금 코드를 옮기기만 하고 동작을 바꾸지 않는다.
- admin 쪽은 새 함수를 부르도록 고친다. 기존 155개 테스트가 그대로 통과해야 한다.
- 같은 입력을 admin과 API에 넣었을 때 결과(저장 여부, 오류 메시지, 이력 행 수)가 같은지 확인하는 **동등성 테스트**를 추가한다.

### 3.3 React로 다시 만든다

| 묶음 | 지금 화면 | 지금 위치 |
| --- | --- | --- |
| 공통 틀 | 상단 바, 사이드바(업무 영역 7묶음), 페이지 헤더, 통합 검색 | `templates/admin/base_site.html`, `qms_sidebar.html`, `core/nav.py`, `core/search.py`, `shell.js` |
| 홈 | 내 할 일(위젯 배치·저장), 공장 종합현황 | `qms/views.py` `todo`·`dashboard_save`·`overview`, `qms/widgets.py`, `dashboard.js` |
| 생산 | 작업지시·실적·LOT·출하 목록·상세, LOT 이력 조회 | admin, `core/views.py` `trace`, `core/timeline.py` |
| 품질 | 검사 입력(LOT 스캔·입고 등록·즉시 판정·성적서), 검사·검사기준·계측기·자격 | `qms/views.py` `inspect_*`, admin |
| 품질보증 | 부적합 간편 등록·상세·MRB 처분·메일·사진 ZIP, 보류, CAPA, 4M, 문서, 내부심사, 심사 증적, 심사 자료 출력 | `core/views.py` `nc_*`, `qms/views.py` `audit_pack*`, admin |
| 고객·협력사 | 클레임(8D), SCAR, PPAP, 협력사 성적표 | admin, `qms/views.py` `suppliers_view` |
| 분석 | KPI, SPC 관리도, 엑셀 양식 출력 | `qms/views.py` `kpi_view`·`spc_view`·`excel_report` |
| 공통 동작 | 승인 서명, 삭제·수정 요청과 결정, 인쇄, 엑셀 가져오기, 현장 메모 | `core/views.py` `approve`·`edit_request*`·`print_view`·`import_view`, `qms/views.py` `memo_*` |
| 개인 | 연차·급여 | `personal/views.py` `me`·`payslip_file` |
| 기록 공통 | 상세 화면 "관련 기록" 패널, 변경 이력 보기 | `core/admin.py` `related_panel`, simple-history |

### 3.4 마지막 단계(5단계)에서 없앤다

- 업무 화면 템플릿 32개와 그 뷰. 인쇄 템플릿도 React로 다시 만든 뒤에 없앤다.
- `htmx.min.js`, `shell.js`, `dashboard.js`, `nc_form.js`, `copy_mail.js`
- `templates/admin/`의 사이드바·관련 기록 커스터마이즈. admin을 superuser 전용으로 바꾸면 기본 admin 화면으로 충분하다. 범위는 5단계에서 다시 정한다.
- 지우기 전에 Git 태그를 남긴다. 되돌리기는 7장의 5단계에 적었다.

---

## 4. 신규 설치 패키지

**모두 설치 전에 사용자 승인을 받는다.** 버전은 설치 시점에 고정하고 이 문서와 `README.md`에 적는다. 아래 버전 범위는 계획 값이며, 실제 호환성은 **미확인**이다.

### 4.1 Python (`requirements.txt`)

| 패키지 | 필요 | 용도 | 비고 |
| --- | --- | --- | --- |
| `djangorestframework` | 필수 | API 뷰·serializer·권한·페이지 | Django 6.1을 지원하는 버전인지 설치 전에 확인한다(**미확인**) |
| `psycopg[binary]` | PostgreSQL 이전 때 필수 | PostgreSQL 드라이버 | `settings.py` 104행 주석에 이미 필요하다고 적혀 있다 |
| `django-filter` | 선택 | 목록 필터를 선언형으로 작성 | 쓰지 않으면 `get_queryset`에서 직접 거른다. 처음에는 넣지 않고 필요할 때 다시 판단한다 |
| `drf-spectacular` | 선택 | OpenAPI 스키마 → TypeScript 타입 생성 | 1인 유지보수에서 타입 불일치를 줄여 준다. 대신 의존성이 하나 더 는다 |

- **오프라인 설치:** 인터넷이 되는 PC에서 `pip download -r requirements.txt -d wheelhouse`로 받는다. 운영 PC에서는 `pip install --no-index --find-links wheelhouse -r requirements.txt`로 설치한다.
- **PostgreSQL 서버 자체**(Windows 설치본)도 새 소프트웨어 설치라서 승인 대상이다.

### 4.2 npm (`frontend/package.json`, 개발 PC 전용)

| 패키지 | 구분 | 용도 |
| --- | --- | --- |
| `react`, `react-dom` | 실행 | UI |
| `antd`, `@ant-design/icons` | 실행 | 컴포넌트·아이콘(번들에 포함) |
| `react-router-dom` | 실행 | 화면 경로 |
| `@tanstack/react-query` | 실행(선택) | 서버 데이터 캐시·재조회·로딩 상태. 쓰지 않으면 `fetch` + 상태 관리를 직접 쓴다 |
| `typescript`, `vite`, `@vitejs/plugin-react` | 개발 | 빌드 |
| `dayjs` | 실행 | antd 날짜 컴포넌트가 쓴다. 한국어 로케일 포함 |

- `@playwright/test` 같은 JS 테스트 도구는 넣지 않는다. 사용자 결정에 따라 화면 흐름은 Python Playwright로 확인한다.
- Python Playwright는 지금 시스템 Python에만 설치되어 있다. 프로젝트 `.venv`나 `requirements.txt`에는 없다. 개발 도구로 따로 적을지는 승인 대상이다.

### 4.3 오프라인 운영 대책

- `package-lock.json`을 커밋한다. `node_modules/`는 커밋하지 않는다(`.gitignore`에 추가).
- **빌드 결과물 배포 방식은 두 가지 중 하나를 고른다.** 1단계 시작 전에 사용자가 정한다.
  - **(가) `frontend/dist/`를 Git에 커밋한다.** 운영 PC는 `git pull`만 하면 된다. 대신 빌드 파일 diff가 커밋에 섞인다.
  - **(나) 배포 zip을 만든다.** 개발 PC에서 빌드하고, 결과를 zip으로 옮긴다. Git 이력은 깨끗하지만 배포 단계가 하나 는다.
  - 운영 PC에 Node가 있는지 모르므로(**미확인**), 두 방식 모두 운영 PC에서 빌드하지 않는다.

---

## 5. 폴더 구조

기존 앱 경계(`core`·`qms`·`personal`)와 의존 방향(`qms → core`, `personal`은 독립)을 그대로 둔다. 새로 생기는 것만 표시한다.

```
config/
  settings.py          + 'rest_framework', REST_FRAMEWORK 설정, STATICFILES_DIRS에 frontend/dist
  urls.py              + path('api/', include(...)), React index 뷰(마지막 줄 catch-all)
core/
  rules.py             (새) 3.2의 공용 함수: save_with_lock, delete_as, dispose_nc, approve, …
  api/                 (새) serializers.py, views.py, permissions.py, urls.py
                         품번·공정·작업지시·실적·LOT·계보·부적합·보류·출하·요청·검색·LOT 이력
qms/
  rules.py             (새) submit_inspection 등 qms 전용 규칙
  api/                 (새) 검사·기준·계측기·자격·관리계획·4M·클레임·SCAR·문서·심사·CAPA·PPAP·메모
                         대시보드·종합현황·KPI·SPC·협력사·엑셀 양식
personal/
  api/                 (새) 연차·급여 (본인 전용)
frontend/              (새) Vite 프로젝트
  package.json, package-lock.json, tsconfig.json, vite.config.ts
  index.html
  src/
    main.tsx           ConfigProvider(Fiori 토큰, 한국어 로케일, 다크 모드)
    api/               fetch 래퍼(CSRF 헤더, 오류 변환), 모델별 호출 함수
    layout/            상단 바, 사이드바(7묶음), 페이지 헤더
    pages/             home/, production/, quality/, assurance/, partners/, analysis/, admin-data/, me/
    components/        승인 서명 대화상자, 삭제·수정 요청, 변경 이력, 관련 기록, SPC 차트(SVG), 인쇄 틀
    theme.ts           fiori.css 값 → antd 토큰
  dist/                빌드 결과 (4.3 결정에 따라 커밋 여부가 달라짐)
scripts/
  e2e_check.py         HTTP 점검. API·React 경로로 단계적으로 바꾼다
  e2e_browser.py       (새) Python Playwright 화면 흐름 점검
```

- **`api/`를 앱마다 둔다.** 새 `api` 앱을 만들면 앱 경계가 흐려지고, `core → qms` 지연 import 규칙(`docs/architecture.md`)을 다시 따져야 한다.
- **`rules.py`를 둔다.** `core/records.py`는 "삭제·잠금 규칙" 파일이다. 처분·승인까지 넣으면 역할이 섞이므로 따로 둔다. 두 파일을 합치는 방안도 0단계에서 다시 볼 수 있다.

---

## 6. API 설계 방향

### 6.1 URL과 리소스

- 경로: `/api/<앱>/<모델 복수형>/`. 예: `/api/core/lots/`, `/api/qms/inspections/{id}/`
- 목록: 페이지 번호 방식(`?page=`, `page_size` 기본 50), 정렬 `?ordering=`, 검색 `?search=`
  - 필터는 지금 admin의 `list_filter`·`search_fields`와 같은 항목만 연다.
  - 종합현황 카드가 쓰는 필터(`status`, `result`, `released_at__isnull`, `closed_at__isnull` 등)는 반드시 포함한다.
- 상세 응답에 넣는 것:
  - 표시용 라벨(`get_FOO_display`)
  - 관련 기록 요약(admin `related()`가 고르는 목록과 같은 기준)
  - `permissions` 블록: `can_change`, `can_delete`, `locked`, `editable_fields`. 화면이 버튼을 숨기는 근거로 쓴다. 서버 검사는 따로 한다.
- 집계 엔드포인트: `/api/qms/todo/`, `/api/qms/overview/`, `/api/qms/kpi/`, `/api/qms/spc/{char_id}/`, `/api/qms/suppliers/`, `/api/core/trace/?lot=`, `/api/core/search/?q=`
  - 각각 지금 뷰와 **같은 권한 검사**(`qms/views.py` `_need`, `_can_inspect`, `_pack_allowed`)를 쓴다.
  - 링크 대신 `{app, model, id}`를 돌려준다(1.5 URL 결합 해소).

### 6.2 인증·세션·CSRF

- `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = [SessionAuthentication]`만 둔다. Basic·Token 인증은 열지 않는다.
- 기본 권한: `IsAuthenticated` + **`is_staff` 검사.** 지금 모든 전용 뷰의 `staff_member_required`와 같은 기준이다.
- 로그인 API:
  - `POST /api/auth/login/`은 `authenticate` → `login`
  - `POST /api/auth/logout/`
  - `GET /api/auth/me/`는 사용자, 역할, 권한 코드 목록, 승인자 여부를 준다.
- CSRF:
  - `SessionAuthentication`은 로그인 사용자의 쓰기 요청에 CSRF를 강제한다.
  - React는 `csrftoken` 쿠키를 읽어 `X-CSRFToken` 헤더로 보낸다.
  - 지금 `CSRF_COOKIE_HTTPONLY`는 설정하지 않았다(기본값 False). 그래서 쿠키를 읽을 수 있다.
- 로그인 화면과 admin 로그인을 분리한다. admin을 superuser 전용으로 바꾸면(승인 필요) 일반 사용자는 `/admin/login/`으로 들어올 수 없다. 그러니 `LOGIN_URL`도 React 로그인 경로로 바꿔야 한다(보안 설정 변경, 승인 대상).

### 6.3 권한

| 계층 | 방식 | 지금 대응 |
| --- | --- | --- |
| 모델 권한 | `DjangoModelPermissions`(view/add/change). 목록 조회에도 `view_` 권한을 요구하도록 `perms_map`을 고친다 | admin의 `has_*_permission` 기본 동작 |
| 삭제 | **DjangoModelPermissions에 맡기지 않는다.** superuser만 직접 삭제한다. 나머지 사용자는 삭제 요청 액션을 쓴다 | `BaseAdmin.has_delete_permission`. 역할에 `delete_measurement`가 있지만(`ensure_roles`), admin에서는 판정 전 검사의 인라인에서만 쓸 수 있다 |
| 객체 권한 | 메모는 작성자만 수정한다. personal은 본인 것만 다루고, 남의 것은 404다 | `MemoAdmin`, `memo_edit`, `OwnerAdmin` |
| 화면 권한 | KPI는 `qms.view_customerclaim`, 협력사는 `qms.view_scar`, SPC는 `qms.view_measurement`, 검사 입력은 `_can_inspect` | `qms/views.py`, `docs/business-rules.md` 10장 |
| 메뉴 | `/api/auth/me/`의 권한 목록으로 메뉴를 거른다. 서버는 6.3 표의 다른 줄로 따로 막는다 | `core/nav.py` |

### 6.4 업무 동작은 액션 엔드포인트로

일반 `PATCH`로 상태가 바뀌지 않게 한다. 승인·처분·판정은 아래 전용 경로로만 가능하다.

| 동작 | 엔드포인트 | 서버 처리 |
| --- | --- | --- |
| 승인 서명 | `POST /api/<app>/<model>/{id}/approve/` `{password}` | `core/rules.py` `approve` (지금 `core/views.py` `approve`와 같다) |
| 부적합 처분(MRB) | `POST /api/core/nonconformances/{id}/dispose/` `{disposition, customer_approval_ref, …, password}` | `dispose_nc`: 비밀번호 확인 → `approved_by`/`approved_at` → `missing_fields` → `save()` |
| 검사 판정 | `POST /api/qms/inspections/submit/` `{lot, spec, gauge, values{char_id: raw}, defect_type, defect_qty}` | `submit_inspection` (지금 `inspect_submit`의 `transaction.atomic` 블록과 같다) |
| 입고 등록 | `POST /api/qms/inspections/receive/` | 지금 `inspect_receive` |
| 측정값 즉시 확인 | `POST /api/qms/characteristics/{id}/check/` | 지금 `inspect_check` (계측기 교정 기한 확인 포함) |
| 삭제 요청·수정 요청 | `POST /api/core/edit-requests/` `{kind, app, model, id, reason, password}` | 지금 `edit_request` |
| 요청 결정 | `POST /api/core/edit-requests/{id}/decide/` | `EditRequest.decide` |
| 삭제(superuser) | `DELETE /api/<app>/<model>/{id}/` | `delete_as` → `delete_record`. 막히면 409와 막는 기록 목록 |
| 대시보드 배치 저장 | `POST /api/qms/dashboard/` | 지금 `dashboard_save` |
| 부적합 메일 | `GET …/nonconformances/{id}/mail/`(본문), `POST …/mail/sent/`(발송 표시) | 지금 `nc_mail`, `_mark_mailed` |

- **승인 필드는 읽기 전용이다.** `approved_by`, `approved_at`, `closed_at`, `inspector`, `result`, `nonconformance`(검사), `author`(메모), `owner`(personal)는 serializer에서 항상 읽기 전용으로 둔다. 지금 admin의 `readonly_fields`·`get_exclude`와 같다.

### 6.5 저장 경로 규칙 (serializer 공통 기반)

1. serializer는 `validate()`에서 인스턴스를 만든 뒤 **`full_clean()`을 부른다.**
   - DRF `ModelSerializer`는 모델 `clean()`을 부르지 않는다.
   - `full_clean()`은 필드 검사기(`validate_photo`, `choices`, `unique`)와 `save()`가 부르지 않는 `clean()`(`Evidence`, `Payslip`)까지 돌린다.
2. 수정이면 `save_with_lock(obj, user, changed)`를 거친다.
3. 하위 항목(검사항목·관리계획 행·PPAP 요소·사진)을 쓸 때는 `child_editable(parent, user)`를 먼저 검사한다.
4. 여러 행을 저장하는 요청은 `transaction.atomic`으로 감싼다. 지금 admin `changeform_view`도 atomic이다.

### 6.6 오류 형식

- 모델 `ValidationError` → HTTP 400, `{"detail": "…", "fields": {"field": ["…"]}}`. 메시지는 모델이 만든 한국어 문장을 그대로 쓴다.
- 권한 → 403 `{"detail": "…"}`. `PermissionDenied`에 담긴 메시지("품질팀장만 승인할 수 있습니다." 등)를 유지한다.
- 잠금 → 409 `{"detail": "승인된 기록은 수정할 수 없습니다. …"}`. admin의 `LOCKED_MSG`와 같은 문구를 쓴다.
- 삭제 차단 → 409 `{"detail": "먼저 지워야 할 기록: …", "blockers": [...]}`

### 6.7 파일

| 종류 | 방식 |
| --- | --- |
| 첨부 업로드(부적합 사진·메모 사진·문서·증적) | `multipart/form-data`. 서버 검사는 모델 검사기(`validate_photo`: 확장자, 10MB)를 그대로 쓴다 |
| 첨부 다운로드 | 지금 `/media/` 그대로 |
| 개인 명세서 | `/api/personal/payslips/{id}/file/`. 소유자 확인은 지금 `payslip_file`과 같다 |
| 엑셀 양식·사진 ZIP·심사 자료 ZIP | 서버가 만들어 `Content-Disposition: attachment`로 보낸다. 지금 `excel_report`, `nc_photos_zip`, `audit_pack_zip`과 같다 |
| 엑셀 가져오기 | `POST /api/core/import/` (multipart). 권한·전체 되돌리기 규칙은 지금 `import_view`와 같다 |

### 6.8 변경 이력

- `GET /api/<app>/<model>/{id}/history/`는 simple-history 행을 돌려준다(시각, 사용자, 종류 `+`/`~`/`-`, 바뀐 필드 이전→이후 값).
  - 바뀐 필드는 `history.diff_against`로 계산한다.
  - 권한은 그 모델의 `view_` 권한이다.
- personal 모델은 이력이 없으므로 이 경로를 열지 않는다.

---

## 7. 단계별 마이그레이션 계획

**공통**

- 0~4단계에서는 기존 화면이 그대로 동작한다. React는 `/app/` 아래에서 따로 개발한다.
- 5단계에서만 기존 템플릿을 지우고 React를 `/`로 옮긴다. 이것이 사용자가 정한 "일괄 교체" 시점이다.
- 단계마다 아래 검증을 실제로 실행하고 결과를 보고한다(`docs/testing.md` 완료 기준).
  - `manage.py check`
  - `makemigrations --check --dry-run`
  - `manage.py test`
  - `scripts/e2e_check.py`
- 화면이 바뀌는 단계는 Python Playwright 점검도 실행한다. 대상은 PC·390px, 라이트·다크다.

### 0단계 — 공용 규칙 추출 (React·DRF 없음)

- **작업:**
  - `core/rules.py`, `qms/rules.py`를 만든다(3.2 표).
  - `BaseAdmin`, `NonconformanceForm`·`NonconformanceAdmin`, `InspectionAdmin`, `core/views.py` `approve`, `qms/views.py` `inspect_submit`이 새 함수를 부르도록 고친다.
- **완료 기준:**
  - 기존 155개 테스트와 e2e 76개가 그대로 통과한다.
  - 새 함수의 단위 테스트가 9.2 표의 규칙마다 "막아야 할 경우"와 "허용할 경우"를 모두 다룬다.
- **되돌리기:** 커밋 단위 `git revert`. 스키마 변경이 없다.
- **위험:** admin 동작이 미세하게 바뀔 수 있다. 예를 들어 메시지 문구나 승인 소모 시점이다. 그래서 기존 테스트를 하나도 고치지 않고 통과하는 것을 기준으로 둔다.

### 1단계 — DRF 기반 + 시범 화면 (중단 판단 지점)

- **작업:**
  - 패키지 승인 후 DRF를 설치하고, 인증 API(`/api/auth/*`)를 만든다.
  - `frontend/` 프로젝트와 공통 틀(사이드바·헤더·테마)을 만든다.
  - 시범 화면 2개를 만든다: `/app/overview`, `/app/todo`. 데이터는 `/api/qms/overview/`, `/api/qms/todo/`에서 온다.
  - 집계 함수의 URL 결합을 푼다. `qms/widgets.py` 등이 링크 대신 식별자를 돌려주게 하고, 기존 템플릿은 템플릿 쪽에서 URL을 만들게 한다.
- **완료 기준:**
  - 같은 사용자로 기존 `/overview/`와 `/app/overview`의 카드 숫자가 같다(테스트로 비교).
  - 검사원 계정으로 KPI·CAPA 카드가 API에서도 빠진다.
  - 비로그인 API 요청은 403이다.
  - 4.3의 배포 방식(가/나)이 정해지고, 운영 PC 방식으로 한 번 띄워 본다.
- **중단 판단:**
  - 사용자가 두 화면을 실제로 써 본다. 기존 화면보다 크게 나아졌다고 느끼지 못하면 전환을 멈춘다.
  - 멈추면 `/app/`과 `/api/`를 지우는 커밋 하나로 원래 상태가 된다. 0단계 공용 함수는 남겨도 된다.
- **되돌리기:** 기존 경로를 건드리지 않았으므로 새 파일과 설정 몇 줄만 지우면 된다.

### 2단계 — 업무 화면 묶음별 전환 (사무실 PC 화면)

- **순서:** 의존이 적고 규칙이 단순한 것부터 한다.
  1. 기준정보(품번·BOM·라우팅·공정·검사기준·관리계획서·고객 규칙)
  2. 생산(작업지시·실적·LOT·계보·출하·LOT 이력)
  3. 품질보증(부적합 상세·MRB 처분·보류·CAPA·4M·문서·내부심사·심사 증적)
  4. 고객·협력사(클레임·SCAR·PPAP·성적표)
  5. 분석(KPI·SPC·엑셀 양식)
  6. 공통 동작(승인 서명·삭제·수정 요청·이력·엑셀 가져오기·메모)은 1번 묶음에서 먼저 만들고 다른 묶음이 재사용한다.
- **묶음마다 완료 기준:**
  - API 테스트로 9.2 표의 해당 규칙을 모두 확인한다.
  - 같은 입력을 admin과 API로 저장했을 때 결과가 같다(동등성 테스트).
  - Playwright로 목록→상세→저장→이력 흐름을 확인한다.
- **되돌리기:** 묶음 단위 커밋. 기존 화면이 그대로 있으므로 React 쪽 링크만 빼면 된다.

### 3단계 — 현장 화면·인쇄

- **현장 화면:**
  - 검사 입력은 LOT 스캔(바코드 스캐너 = 키보드 입력 + Enter), 입고 등록, 측정값 즉시 확인, 판정, 성적서 인쇄까지 옮긴다.
  - 부적합 간편 등록은 휴대폰 사진(`<input type="file" accept="image/*" capture="environment">`)을 쓴다. 지금 admin 사진 입력과 같은 방식이다.
  - 현장 메모도 옮긴다.
- **인쇄:**
  - 대상: `print.html`(공통), `nc_print.html`(부적합 보고서), `audit_pack.html`(심사 자료)
  - React 인쇄 전용 경로와 `@media print` CSS로 다시 만든다.
  - 내용은 서버의 `print_table()` 등이 만든 표 데이터를 API로 받아 그린다. 표 내용이 기존 인쇄물과 같아야 한다.
- **완료 기준:**
  - 휴대폰 폭(390px)에서 검사 판정과 부적합 등록이 끝까지 된다.
  - 인쇄 미리보기가 A4 한 장 배치를 유지한다.
  - 스캐너 기종별 동작은 **미확인**이다. 실제 기기로 확인한다.

### 4단계 — PostgreSQL 이전

- **작업:**
  - psycopg와 PostgreSQL 서버를 설치한다(승인 필요).
  - `_nc_number`, `_capa_number`를 DB 시퀀스 또는 잠금 기반 번호로 바꾼다(스키마 변경, 승인 대상).
  - `backup`/`restore` 명령이 PostgreSQL에서 어떻게 동작해야 하는지 다시 설계한다. 지금은 SQLite 파일 기준이다. 세부 동작은 **미확인**이라 이 단계에서 코드를 읽고 정한다.
- **데이터:** 운영 전 데모 데이터라서 새 DB에 `migrate` 후 데모 데이터를 다시 만든다. 기존 행을 옮겨야 하면 `dumpdata`/`loaddata`를 사본 DB에서 먼저 해 본다.
- **완료 기준:**
  - 전체 테스트가 PostgreSQL에서 통과한다.
  - 같은 날 부적합을 동시에 등록하는 테스트(스레드 2개)에서 번호가 겹치지 않는다.
- **되돌리기:** `QMS_DB_NAME` 환경변수를 지우면 SQLite 설정으로 돌아간다(`config/settings.py` 분기).

### 5단계 — 일괄 교체 (템플릿 제거·admin 제한)

- **작업:**
  1. 교체 전 Git 태그를 만든다. 예: `pre-react-cutover`
  2. `/app/` 경로를 `/`로 옮긴다. 기존 전용 화면 URL(`/todo/`, `/inspect/` 등)은 새 경로로 넘긴다(북마크·알림 메일 링크 보호).
  3. 업무 템플릿·뷰·JS를 지운다(3.4).
  4. admin을 superuser 전용으로 바꾸고 `LOGIN_URL`도 바꾼다(보안 변경, 별도 승인).
  5. `scripts/e2e_check.py`를 API·React 경로 기준으로 정리한다.
  6. `README.md`, `docs/architecture.md`, `docs/business-rules.md`(위치 열), `docs/testing.md`, `DESIGN.md`를 같은 커밋 묶음에서 고친다.
- **완료 기준:**
  - 9.2 표의 모든 규칙에 API 테스트가 있다.
  - 9.2 표의 "전환 후 강제 위치" 열에 admin이 하나도 남지 않는다.
  - 사용자가 실제 업무 한 바퀴(입고→검사→불합격→부적합→MRB→출하 차단 확인)를 React로 끝낸다.
- **되돌리기:**
  - `git revert`로 교체 커밋 묶음을 되돌리거나, 태그 시점으로 배포한다.
  - 스키마 변경이 없으므로 DB는 그대로 둔다. 단, 4단계 번호 생성 변경은 별개다.

---

## 8. 예상 기술적 문제

| # | 문제 | 왜 생기나 | 대책 |
| --- | --- | --- | --- |
| 1 | admin과 API의 규칙 불일치 | 0~4단계 동안 저장 경로가 두 개다. admin에만 있는 규칙이 있다(9.2) | 0단계 공용 함수 + 동등성 테스트. API serializer는 `full_clean()` 필수(6.5) |
| 2 | `ModelSerializer`가 모델 검증을 건너뜀 | DRF는 모델 `clean()`/`full_clean()`을 부르지 않는다. `Evidence.clean`·`Payslip.clean`·필드 검사기는 `save()`가 부르지 않는다 | 공통 serializer 기반 클래스에서 `full_clean()` 호출. 해당 모델별 거부 테스트 |
| 3 | 삭제 권한 확대 | `DjangoModelPermissions`를 그대로 쓰면 `delete_measurement`가 있는 검사원이 판정된 검사의 측정값을 지울 수 있다. 지금은 admin 인라인 권한(`InspectionAdmin.has_change_permission`)이 막는다 | 삭제는 superuser만(6.3). 측정값 삭제는 판정 전 검사의 하위 항목 편집 안에서만 허용 |
| 4 | SQLite 동시 쓰기 | 사용자가 늘면 "database is locked"가 날 수 있다. 지금은 IMMEDIATE + timeout 20으로 순서를 맞춘다 | 4단계 PostgreSQL. 그 전까지는 지금 설정 유지 |
| 5 | PostgreSQL 차이 | 번호 생성(`_nc_number`·`_capa_number`), 문자열 정렬·대소문자(`icontains`) 결과가 SQLite와 다를 수 있다 | 4단계에서 전체 테스트를 PostgreSQL로 실행. 번호는 시퀀스 |
| 6 | 한글 IME 입력 | 조합 중 Enter가 폼 제출이나 스캔 처리로 잡힐 수 있다 | 입력 이벤트에서 `isComposing`을 확인한다. 실제 동작은 **미확인**, Playwright로는 재현이 어려워 사람이 확인한다 |
| 7 | 바코드 스캐너 | 스캐너는 키보드처럼 문자 + Enter를 보낸다. 포커스가 다른 칸에 있으면 엉뚱한 칸에 들어간다 | 검사 입력 첫 화면에서 스캔 칸에 자동 포커스한다. 기종·설정(접미 문자)은 **미확인** |
| 8 | 휴대폰 카메라 | `getUserMedia`(실시간 카메라)는 HTTPS가 필요하다. 사내망은 HTTP다 | `<input type="file" capture>` 방식 유지(지금과 같음, HTTPS 불필요). 실시간 바코드 카메라 인식은 범위 밖 |
| 9 | SPC 관리도 | 지금은 서버 SVG다 | API가 `control_chart` 결과(점·중심선·한계·경보)를 JSON으로 주고, React가 `<svg>`로 그린다. 차트 라이브러리는 넣지 않는다 |
| 10 | 인쇄 | 브라우저마다 여백·쪽 나눔이 다르다. 지금도 "PDF로 저장" 방식이다 | 인쇄 전용 경로 + `@media print`. Edge·Chrome 인쇄 미리보기로 확인 |
| 11 | 번들 크기 | antd 전체를 넣으면 첫 로딩이 무겁다 | Vite 코드 분할(화면별 `lazy`), antd는 쓰는 컴포넌트만 import. 사내망·로컬이라 영향은 작다고 보지만 수치는 **미확인** |
| 12 | 다크 모드 | 지금은 `prefers-color-scheme` + `data-theme` 속성이다 | antd `theme.darkAlgorithm` + 같은 판정 규칙. Fiori 다크 토큰 값을 옮긴다 |
| 13 | 캐시 | 지금 `core.middleware.no_store_pages`가 로그인 사용자 HTML에 `no-store`를 붙인다 | API 응답에도 `no-store`. 빌드 JS·CSS는 파일명 해시로 장기 캐시 |
| 14 | 1인 유지보수 부담 | Python + TypeScript 두 언어, 빌드 도구, npm 보안 업데이트를 혼자 관리해야 한다. React 경험도 적다 | 화면 패턴을 소수로 고정한다(목록·상세·폼·대화상자). 패키지 수를 4.2 표로 제한한다. AI 작업 지침(이 문서 + `AGENTS.md`)에 패턴을 적는다 |
| 15 | 알림 메일·Teams 링크 | `notify`가 보내는 링크가 기존 화면 주소를 가리킬 수 있다(**미확인**) | 5단계 리다이렉트로 보호하고, 1단계에서 링크를 만드는 코드를 확인한다 |
| 16 | 테스트 자산 재작성 | `scripts/e2e_check.py`(76개)와 템플릿 응답을 확인하는 단위 테스트는 5단계에서 깨진다 | 2~3단계에서 API 테스트로 같은 규칙을 먼저 덮는다. 5단계에서 템플릿 테스트를 지울 때 대응하는 API 테스트가 있는지 표로 대조한다 |

---

## 9. 데이터 및 업무 규칙 보존 대책

### 9.1 원칙

1. **규칙은 서버에서만 강제한다.** React의 버튼 숨김·입력 검사는 편의다.
2. **모든 저장은 `full_clean()` → 공용 규칙 함수 → `save()` 순서다.** 모델 `save()`의 `self.clean()`은 그대로 둔다.
3. **이력:** 업무 모델 39개의 `HistoricalRecords`를 유지한다.
   - API도 세션 인증 요청이라 `HistoryRequestMiddleware`가 사용자를 기록한다.
   - 여러 행 저장은 지금처럼 `bulk_create_with_history`·`bulk_update_with_history`를 쓴다.
4. **스키마는 바꾸지 않는다.** 예외는 4단계 번호 생성뿐이며, 승인 후 사본 DB에서 먼저 확인한다.
5. **DB 작업 전에는 백업한다.** `manage.py backup`을 먼저 실행한다. `data/` 삭제·초기화·덮어쓰기는 승인 없이 하지 않는다(`AGENTS.md`). 데모 데이터라도 마찬가지다.

### 9.2 규칙별 강제 위치 대조표

`docs/business-rules.md`의 장 번호를 따른다. **"지금 위치"가 모델이면 API도 자동으로 따른다.** admin·뷰이면 반드시 옮겨야 한다.

| 장 | 규칙 | 지금 강제 위치 | 전환 후 강제 위치 | 확인 테스트 |
| --- | --- | --- | --- | --- |
| 1 | 부적합 등록 → LOT·하위 계보 보류 | 모델 `Nonconformance.save` | 그대로 | API로 부적합 생성 → 하위 LOT 보류 수 |
| 1 | 보류 LOT 투입·실적·출하 차단 | 모델 `LotLink.clean`, `WorkResult.clean`, `Shipment.clean` | 그대로 | API 저장 400 + 메시지 |
| 1 | 계보 순환 금지, 실적 공정·수량 규칙 | 모델 | 그대로 | 기존 `InterlockTest`·`RoutingTest`와 같은 케이스를 API로 |
| 1 | 클레임 접수 → 부적합 자동 생성 | 모델 `CustomerClaim.save` | 그대로 | API로 클레임 생성 → 부적합·보류 |
| 2 | 처분은 등록 후에만, 품질팀장 승인자, 재검사 합격, 특채 승인번호 | 모델 `Nonconformance.clean` | 그대로 | API dispose 각 거부 케이스 |
| 2 | **처분 때 비밀번호 재입력** | admin `NonconformanceForm.clean` (모델은 승인자 자격만 본다) | `core/rules.py` `dispose_nc` + dispose 액션만 처분 가능 | 비밀번호 틀림 400, 일반 PATCH로 `disposition` 변경 시 거부 |
| 2 | **처분 전 보완 필수 칸** | admin `NonconformanceForm._post_clean` → `missing_fields` | `dispose_nc` | 빈 칸이 있으면 400 + "보완 필요: …" |
| 2 | 재작업·수리·특채만 보류 해제 | 모델 `Nonconformance.save` | 그대로 | 폐기 처분 후 보류 유지 |
| 2 | **종결된 부적합 잠금**(열린 칸은 `AFTER_APPROVAL`만, `INTERLOCK` 칸은 관리자도 불가) | admin `NonconformanceAdmin.get_readonly_fields` + `BaseAdmin.save_model`(`is_locked`) | `nc_editable_fields` + `save_with_lock` | 종결 후 `lot`·`disposition` PATCH 거부(superuser 포함), `cost` PATCH 허용 |
| 2 | **종결 부적합 사진 잠금** | admin `NcPhotoInline._open` | `child_editable` | 종결 후 사진 추가 거부 |
| 3 | **승인은 승인 서명으로만**(승인자, 비밀번호) | 뷰 `core/views.py` `approve` | `core/rules.py` `approve` + approve 액션. 승인 필드는 serializer 읽기 전용 | `approved_at` PATCH 무시·거부, 비승인자 403 |
| 3 | 승인 후 수정 불가(하위 항목 포함) | 모델 `Approvable.save`, `Characteristic.save`, `ControlPlanLine.save`, `PpapElement.save` | 그대로 + `save_with_lock`이 수정 승인 1회분만 해제 | 승인 후 PATCH 409, 수정 승인 후 1회 성공·2회째 409 |
| 3 | 4M 고객 승인번호, PPAP 증적 | 모델 `ChangeRequest.clean`, `PpapSubmission.clean` | 그대로 | approve 액션 400 |
| 4 | **삭제는 superuser만** | admin `BaseAdmin.has_delete_permission` + `ensure_roles`(delete 권한 없음) | `delete_as` | 품질팀장 DELETE 403, superuser 204 |
| 4 | 부적합 삭제 시 그 부적합의 보류만 삭제, PROTECT 참조 차단 | `core/records.py` `delete_record`, `blockers` | 그대로 호출 | 다른 부적합 보류 유지, 참조 있으면 409 |
| 4 | 삭제·수정 요청(비밀번호·사유), 승인 수정 1회 | 뷰 `edit_request`, 모델 `EditRequest.decide`, admin `save_model`(USED 처리) | 요청 API + `save_with_lock` | 기존 `EditRequestTest` 케이스를 API로 |
| 5 | 승인된 최신 기준으로만 검사, 품번 일치 | 모델 `Inspection.clean` | 그대로 | 지난 개정으로 submit 400 |
| 5 | 판정 규칙·불합격 → 부적합·검사원 자격 | 모델 `Inspection.finalize` | 그대로 | 불합격 submit → 부적합·보류 |
| 5 | 판정 후 수정 불가 | 모델 `Inspection.save`, `Measurement.clean` | 그대로 + 측정값 삭제 제한(8장 #3) | 판정 후 PATCH·DELETE 거부 |
| 5 | **검사원 = 요청 사용자, 승인 기준만 선택** | admin `InspectionAdmin.save_model`·`formfield_for_foreignkey`, 뷰 `inspect_submit` | `submit_inspection`. `inspector`는 읽기 전용 | 다른 사용자로 `inspector` 지정 무시 |
| 5 | 판정은 전부 저장 또는 전부 취소 | 뷰 `inspect_submit`(`transaction.atomic`) | `submit_inspection` | 중간 항목 오류 시 검사 행 0 |
| 6 | 교정 기한 지난·사용 중지 계측기 거부, NaN·무한대 거부 | 모델 `Measurement.clean`, `Gauge.usable_on`, 뷰 `_measurement` | 그대로 + `_measurement` 공용화 | 기한 지난 계측기 submit 400, `nan` 입력 400 |
| 7 | SPC 경보, 특별특성 경보 → 부적합 | `qms/spc.py`, `Inspection._special_spc_check` | 그대로 | 기존 테스트 + API submit 경로 |
| 8 | 4M 초품 합격 전 출하 차단 | 모델 `Shipment.clean` | 그대로 | API 출하 400 |
| 9 | 8D 기한·종결, SCAR 회신, CAPA 유효성, 내부심사 종결 | 모델 각 `clean` | 그대로 | API 종결 시도 400 |
| 10 | 역할·권한 | `ensure_roles` | 그대로. API는 모델 권한 사용 | 역할별 허용·거부 API 테스트 |
| 10 | **화면 권한**(KPI·협력사·SPC·검사 입력·내 할 일 목록) | 뷰 `qms/views.py` `_need`·`_can_inspect`, `qms/widgets.py` | 같은 검사 함수를 API에서 호출 | 검사원 KPI API 403 |
| 10 | **personal 본인 전용**(superuser 포함, 남의 것 404) | admin `OwnerAdmin`, 뷰 `personal/views.py` | personal API queryset `owner=request.user`, 없으면 404 | 다른 사용자 id로 404, superuser도 404 |
| 10 | 요청·인쇄·승인 경로에서 개인·시스템 앱 차단 | 뷰 `_get_record` | 그대로 import | `/api/…/approve/` 등에 `auth.user` 지정 시 404 |
| 10 | 엑셀 가져오기 권한·전체 되돌리기 | 뷰 `import_view`, `core/importer.py` | 그대로 호출 | 권한 없음 403, 오류 행 하나 → 0행 반영 |
| 10 | 엑셀 양식 `PRIVATE_APPS` 제외 | 모델 `ExcelTemplate.fill`, `report_safe` | 그대로 | 기존 테스트 |
| 10 | 첨부는 로그인 staff만 | `config/urls.py` `/media/` | 그대로 | 비로그인 403/302 |
| 11 | 변경 이력 | `HistoricalRecords`, `HistoryRequestMiddleware` | 그대로 + 이력 API | API 저장 후 이력 행의 `history_user` 확인 |

굵게 표시한 줄이 **지금 admin·뷰에만 있어서 옮겨야 하는 규칙**이다. 0단계에서 공용 함수로 먼저 옮긴다.

### 9.3 기존 미해결 사항

- 내 할 일 KPI 위젯 권한은 해결했다(2026-11-02, 사용자 결정). KPI는 소속 부서 것만 보이고, 품질팀장·시스템 관리자는 모든 부서 KPI를 본다(`qms/kpi.py` `can_see`, `docs/business-rules.md` 10장). `/api/qms/todo/`, `/api/qms/kpi/`는 같은 함수를 호출한다.
- 남은 한계: `/kpi/` 화면 권한이 `qms.view_customerclaim` 하나라서, 생산 부서가 수율만 보려 해도 클레임 보기 권한이 필요하다. 생산 부서를 추가할 때 KPI 영역별 권한으로 나눈다(`qms/views.py` `kpi_view`의 `shortcut:` 주석).

---

## 10. 기존 Django 구조 유지와 전환의 비용·위험 비교

### 10.1 선택지

- **A. 유지·개선:** 지금 구조(admin + 전용 템플릿 + htmx)를 유지한다. 불편한 화면만 전용 템플릿으로 다시 만든다.
- **B. 점진 전환(공존):** DRF + React 화면을 묶음별로 내놓고, 기존 화면과 오래 같이 운영한다. 다 옮긴 화면부터 기존 것을 지운다.
- **C. 일괄 교체(사용자 결정):** React 화면을 모두 만든 뒤 한 번에 교체한다. 기존 업무 템플릿은 지운다.

### 10.2 비교

| 기준 | A 유지·개선 | B 점진 전환 | C 일괄 교체 |
| --- | --- | --- | --- |
| 작업량 | 가장 적다. 화면 단위로 고친다 | 많다. API + 화면 전체 + 공존 기간의 이중 유지 | 많다. API + 화면 전체. 공존 기간의 사용자 지원은 없다 |
| 새 의존성 | 없음 | Python 1~3개 + npm 약 8개 + Node(개발 PC) | B와 같음 |
| 업무 규칙 회귀 위험 | 낮다. 경로가 그대로다 | 중간. 공존 기간 내내 두 경로라 9.2 굵은 줄의 불일치 위험이 있다. 동등성 테스트로 줄인다 | 중간~높음. 마지막 교체 시점에 한꺼번에 드러난다. 0~4단계 동등성 테스트가 없으면 높다 |
| 현장 입력·모바일·외관 (전환 동기) | 일부만 개선. admin 목록·폼의 한계가 남는다 | 화면마다 차례로 개선 | 교체 시점에 한 번에 개선 |
| 1인 + AI 유지보수 | 가장 쉽다. 언어 하나 | 어렵다. 공존 기간에는 세 가지(admin, 템플릿, React)를 관리한다 | 교체 후에는 두 가지(admin 최소, React). 교체 전 개발 기간은 B와 같다 |
| 되돌리기 | 해당 없음 | 쉽다. 화면 단위 | 교체 커밋 하나로 되돌릴 수 있게 설계해야 한다(7장 5단계 태그) |
| 중간 성과 확인 | 바로 | 묶음마다 | 원칙상 마지막에만. 이 계획은 1단계 시범으로 보완한다 |
| 사용자 교육 | 없음 | 화면마다 조금씩 | 교체 시점에 한 번에 |

### 10.3 객관적 평가

- **전면 재작성은 필요 없다.** 모델·규칙·집계·엑셀·관리 명령은 그대로 쓴다(3.1). 새로 쓰는 것은 **화면과 API 계층**뿐이다. 그래서 C도 "백엔드 재작성"이 아니라 "프런트 교체 + API 추가"다.
- **점진 전환은 기술적으로 가능하다.** 같은 출처·세션 인증이라 기존 화면과 React 화면이 로그인을 공유한다. URL만 나누면(`/app/`) 오래 공존할 수 있다.
- **C의 위험은 실재한다. 특히 1인 + React 경험이 적은 조건에서 그렇다.**
  1. 규칙 회귀가 교체 시점에 한꺼번에 드러난다.
  2. 개발 기간 동안 사용자 반응을 받기 어렵다.
  3. 교체 후에는 기존 화면이 없으니 문제가 생겨도 우회 경로가 admin뿐이다. 그런데 admin은 superuser 전용으로 바뀐다.
- **이 계획의 절충은 이렇다.** 사용자 결정(C)을 따르되, 개발은 B처럼 묶음별로 하고 화면 공개만 C처럼 한 번에 한다.
  - 1단계 시범 화면으로 전환 가치를 일찍 확인하고, 아니면 멈춘다.
  - 0단계 공용 함수 + 묶음별 동등성 테스트로 회귀를 교체 전에 잡는다.
  - 교체(5단계)는 태그와 되돌리기 절차를 갖춘 마지막 한 번으로 둔다.
  - 교체 직후 일정 기간 admin 제한을 늦추는 방안(비상 우회 경로 확보)도 5단계 승인 때 함께 검토한다.
- **A가 나은 경우:** 1단계 시범에서 사용자 반응이 기대에 못 미치면(사용자가 정한 중단 기준) A로 돌아간다. 그때 0단계 공용 함수는 admin 코드 정리 효과가 있어 버리지 않아도 된다.

---

## 부록 A. 승인이 필요한 항목

| 항목 | 단계 | 근거 (`AGENTS.md`) |
| --- | --- | --- |
| `djangorestframework` 설치 (`requirements.txt` 변경) | 1 | 새 의존성 |
| `django-filter`, `drf-spectacular` 설치 여부 | 1~2 | 새 의존성(선택) |
| npm 패키지(4.2), Node 개발 환경 사용 | 1 | 새 의존성 |
| Python Playwright를 개발 도구로 등록 | 1 | 새 의존성(개발용) |
| 빌드 결과물 배포 방식 (`dist` 커밋 / 배포 zip) | 1 | 저장소 운영 방식 |
| API 인증·권한 설계(세션·CSRF·`is_staff`·삭제 superuser) | 1 | 보안 관련 변경 |
| psycopg·PostgreSQL 서버 설치 | 4 | 새 의존성·소프트웨어 |
| 부적합·CAPA 번호 생성 방식 변경 | 4 | 스키마·마이그레이션 |
| admin superuser 전용, `LOGIN_URL` 변경 | 5 | 보안·권한 변경 |
| 업무 템플릿·뷰 삭제 | 5 | 되돌리기 어려운 구조 변경 |

## 부록 B. 미확인 사항

| 항목 | 확인 방법 | 시점 |
| --- | --- | --- |
| 운영 PC의 Node 설치 여부 | 이 계획에서는 필요 없음. 참고로만 확인 | 1단계 |
| DRF·antd 최신판의 Django 6.1·React 버전 호환 | 설치 전에 각 패키지 릴리스 노트 확인 | 1단계 |
| `notify` 메일·Teams 링크 경로 | `qms/management/commands/notify.py` 읽기 | 1단계 |
| 바코드 스캐너 기종·접미 문자 설정 | 실제 기기로 시험 | 3단계 |
| 한글 IME와 Enter 처리 | 실제 브라우저에서 사람이 확인 | 3단계 |
| 사내망 HTTPS 가능 여부 | 실시간 카메라 기능이 필요할 때만 | 범위 밖 |
| `backup`/`restore`의 PostgreSQL 대응 | 명령 코드 읽기 | 4단계 |
| antd 번들 크기·첫 로딩 시간 | 1단계 빌드 결과 측정 | 1단계 |
