# 시스템 구조

QMS+MES는 Django 관리 화면(admin)을 기반으로 하고, 매일 쓰는 업무는 전용 화면 몇 개를 덧붙인 단일 Django 프로젝트다. 사내 PC 한 대에서 오프라인으로 돌아간다. 사용법과 모듈별 기능 설명은 `README.md`에 있다.

## 기술 스택

| 구분 | 사용 | 위치 |
| --- | --- | --- |
| 언어·프레임워크 | Python 3.12, Django 6.1 | `requirements.txt` |
| 변경 이력 | django-simple-history (`HistoricalRecords`) | 각 모델의 `history` 필드 |
| 엑셀 | openpyxl (가져오기 `core/importer.py`, 양식 출력 `qms.ExcelTemplate`) | |
| 서버 | `runserver`(개인), waitress(사내망, `scripts/serve.ps1`) | |
| 정적 파일 | whitenoise | `config/settings.py` |
| 화면 부분 갱신 | htmx (동봉, 외부 로드 없음) | `templates/admin/base_site.html` |
| DB | SQLite 기본, `QMS_DB_NAME` 지정 시 PostgreSQL | `config/settings.py` |
| PDF | 별도 라이브러리 없음. 인쇄용 HTML → 브라우저 "PDF로 저장" | `core/templates/core/print.html` |

## 폴더와 앱

```
config/      설정(settings.py), URL(urls.py)
core/        MES 기본 + 부적합·보류·승인·삭제 요청 (다른 앱이 기대는 바탕)
qms/         검사·SPC·계측기·CAPA·심사·PPAP·문서·클레임·메모·대시보드
personal/    본인 연차·급여 (본인만 열람)
frontend/    새 화면(React) 소스와 빌드 결과 dist/
templates/   관리 화면 틀(base_site.html), 사이드바, 공통 빈 화면
scripts/     e2e 점검, 서버·백업·알림 작업 등록 PowerShell
data/        운영 데이터 (Git 제외): DB, media/, private/, brand/, inbox/, secret_key.txt
docs/        구조·업무 규칙·테스트 문서, superpowers/ 설계·계획 이력
```

### core (`core/`)

| 파일 | 역할 |
| --- | --- |
| `models.py` | `Approvable`(승인 필드·잠금 기반 클래스), 품번 `Item`·공정 `Process`·BOM `BomLine`·라우팅 `RoutingStep`, 작업지시 `WorkOrder`·실적 `WorkResult`, LOT `Lot`·계보 `LotLink`, 부적합 `Nonconformance`·사진 `NonconformancePhoto`, 보류 `Hold`, 출하 `Shipment`, 삭제·수정 요청 `EditRequest`, 엑셀 가져오기 설정 `ImportProfile` |
| `admin.py` | `BaseAdmin`(삭제는 시스템 관리자만, 승인 잠금, 요청 링크, 상세 화면 관련 기록 `related_panel`), 부적합 폼(MRB 처분 시 비밀번호·보완 필수 칸 검사) |
| `records.py` | 삭제(`delete_record`), 잠금(`is_locked`), 잠금 해제 확인(`can_edit_locked`) 규칙 |
| `views.py` | LOT 추적, 통합 검색, 부적합 간편 등록, 승인 서명, 삭제·수정 요청, 출력, 부적합 메일·사진 ZIP, 엑셀 가져오기 |
| `timeline.py`, `search.py`, `nav.py`, `context_processors.py` | LOT 타임라인, 검색, 사이드바 메뉴(권한별, 업무 영역 7묶음). 전체 메뉴(`/admin/`)도 `core/admin.py` `grouped_app_list`가 같은 묶음으로 정렬한다 |
| `middleware.py` | 로그인 사용자 HTML 화면에 `no-store` 헤더(뒤로가기 때 최신 내용) |
| `importer.py` | 엑셀/CSV 일괄 등록 |
| `rules.py` | admin·기존 뷰·API가 함께 쓰는 업무 규칙(잠금·삭제·승인 등). 규칙 본문은 한 곳에만 둔다 |
| `api/` | DRF 기반 JSON API: 로그인·`/api/auth/me/`, 오류 응답 형식(`exceptions.py`), 모델 권한(`permissions.py`). 업무 규칙은 `core/rules.py`·모델 `save()`를 그대로 쓴다 |
| `management/commands/` | `backup`, `restore` |
| `static/qms/` | `fiori.css`(디자인 토큰, `DESIGN.md`), `shell.js`, `dashboard.js`, `nc_form.js`, `copy_mail.js` |

### qms (`qms/`)

| 파일 | 역할 |
| --- | --- |
| `models.py` | 검사기준 `InspectionSpec`·항목 `Characteristic`, 검사 `Inspection`·측정값 `Measurement`, 계측기 `Gauge`, 검사원 자격 `Qualification`, 관리계획서 `ControlPlan`·`ControlPlanLine`, 4M 변경 `ChangeRequest`, 고객 규칙 `CustomerRule`·클레임(8D) `CustomerClaim`, `Scar`, 문서 `Document`·`DocumentRevision`, 심사 증적 `AuditChecklist`·`AuditItem`·`Evidence`, `Capa`, 내부심사 `InternalAudit`·`AuditFinding`, PPAP `PpapSubmission`·`PpapElement`, 엑셀 양식 `ExcelTemplate`, 현장 메모 `Memo`·`MemoPhoto`, 대시보드 배치 `DashboardLayout` |
| `apps.py` | `ensure_roles`: migrate 후 역할 그룹(품질엔지니어·품질팀장·검사원)과 권한 재설정 |
| `views.py` | 내 할 일·대시보드, 공장 종합현황, KPI, 협력사 성적표, 검사 입력, SPC, 현장 메모, 심사 자료 출력, 엑셀 양식 출력 |
| `rules.py` | 검사 판정·입고 업무 규칙(기존 `views.py`에서 옮김). 화면과 API가 함께 쓴다 |
| `api/` | 공장 종합현황 `GET /api/qms/overview/`, 내 할 일 `GET /api/qms/todo/`, 위젯 배치 저장 `POST /api/qms/dashboard/` |
| `overview.py` | 공장 종합현황 카드 계산 (`/overview/` 화면과 API가 공유) |
| `due.py` | 기한·대기 항목 계산 (내 할 일과 `notify`가 공유) |
| `widgets.py` | 대시보드 위젯 목록·역할별 기본 배치·격자 자리 잡기(`place`) |
| `spc.py`, `kpi.py`, `similar.py`, `memo.py` | 관리도·Cpk, KPI 집계, 재발 방지 유사 사례, 메모 연결 |
| `management/commands/` | `collect`(CSV 측정값 자동 수집), `notify`(기한 알림 메일·Teams) |

### frontend (`frontend/`)

React 19·TypeScript·Vite·Ant Design 새 화면. 개발 PC에서 `npm run build`로 `frontend/dist/`를 만들고 그 결과를 저장소에 함께 넣는다. Django는 `/app/` 아래 모든 주소에 `dist/index.html`을 내려 주고(`core/views.py` `spa`), JS·CSS는 whitenoise가 `/static/app/`에서 제공하므로 운영 PC에는 Node가 필요 없다. 지금은 `/app/overview`·`/app/todo`만 있고 데이터는 위 API로만 받는다.

| 위치 | 역할 |
| --- | --- |
| `src/main.tsx` | 라우터(`basename="/app"`)·테마·쿼리 클라이언트 |
| `src/api/` | `client.ts`(CSRF·오류 형식·세션 만료 시 로그인 이동), `auth.ts` |
| `src/layout/AppLayout.tsx`, `src/theme.ts` | 상단 바·사이드 메뉴, Fiori 색 토큰(라이트·다크) |
| `src/pages/`, `src/components/` | 화면(`Login`, `Overview`, `Todo`)과 공통 타일(`Tile`) |

전환 검토와 단계 계획은 `docs/architecture-migration-plan.md`에 있다.

### personal (`personal/`)

`LeaveProfile`·`LeaveUse`(연차), `Payslip`·`PayLine`(급여). 화면은 `/me/`. 명세서 파일은 `data/private/`(MEDIA_ROOT 밖)에 저장하며, 소유자 전용 뷰에서만 내려받을 수 있다.

## 의존 방향

- `qms` → `core`: qms 모델이 `Lot`, `Nonconformance`, `Approvable` 등을 참조한다.
- `core` → `qms`: 모듈 수준에서 import하지 않는다. 필요한 곳에서만 `apps.get_model('qms', ...)`(`Shipment.clean`의 4M 확인)이나 함수 안 지연 import(`core/admin.py`의 CAPA 링크·유사 사례·관련 기록)로 참조한다.
- `personal`: core·qms 모델을 import하지 않는다. 권한 부여만 `qms/apps.py`의 `ensure_roles`가 한다.

## 요청 흐름과 화면

- 모든 화면이 `templates/admin/base_site.html`(회색 상단 바 + `qms_sidebar.html` 사이드바)을 상속한다. 예외는 인쇄용 화면(`print.html`, `nc_print.html`, `audit_pack.html`)과 htmx 조각 템플릿이다.
- 새 React 화면은 `/app/`, JSON API는 `/api/`(`core/api`·`qms/api`)에 있다. 기존 화면과 같은 로그인 세션·권한을 쓴다.
- URL은 `config/urls.py` 한 곳에 있다. `/admin/`은 기준정보·전체 기록이고, `/todo/`·`/overview/`·`/inspect/`·`/trace/`·`/nc/new/`·`/kpi/`·`/suppliers/`·`/audit-pack/`·`/memo/*`·`/me/`·`/search/`가 전용 화면이다.
- 첨부 파일(`/media/`)은 `staff_member_required`로 로그인한 스태프만 받을 수 있다.

## 데이터와 설정

| 항목 | 위치 / 환경변수 |
| --- | --- |
| 데이터 폴더 | `data/` (`QMS_DATA_DIR`로 변경) |
| DB | `data/db.sqlite3`, PostgreSQL은 `QMS_DB_NAME`·`QMS_DB_USER`·`QMS_DB_PASSWORD`·`QMS_DB_HOST`·`QMS_DB_PORT`. SQLite는 `transaction_mode='IMMEDIATE'`, `timeout=20`으로 쓰기를 순서대로 처리한다(동시 저장 시 부적합 번호 중복·"database is locked" 방지). PostgreSQL로 옮기면 부적합 번호(`core/models.py` `_nc_number`)를 DB 시퀀스로 바꿔야 한다 |
| 첨부 | `data/media/`, 개인 명세서는 `data/private/` |
| 로고 | `data/brand/logo.svg|png|jpg` |
| 비밀키 | `data/secret_key.txt` 자동 생성, 또는 `QMS_SECRET_KEY` |
| 서버 | `QMS_DEBUG`(기본 1), `QMS_ALLOWED_HOSTS` |
| 메일 | `QMS_SMTP_HOST`·`QMS_SMTP_PORT`·`QMS_SMTP_USER`·`QMS_SMTP_PASSWORD`·`QMS_SMTP_TLS`·`QMS_MAIL_FROM`, 알림 대상 `QMS_NOTIFY_EMAILS`, `QMS_TEAMS_WEBHOOK` |

마이그레이션은 `core/migrations`, `qms/migrations`, `personal/migrations`에 있다. `서버시작.bat`이 켤 때마다 `migrate --noinput`을 실행한다.
