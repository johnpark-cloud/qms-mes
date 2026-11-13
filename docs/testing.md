# 테스트와 검증

## 명령

모두 저장소 루트에서 PowerShell로 실행한다.

| 목적 | 명령 | 비고 |
| --- | --- | --- |
| 단위 테스트 전체 | `.\.venv\Scripts\python manage.py test` | core·qms·personal 모두. 테스트용 DB를 따로 만들므로 `data/`의 운영 DB는 건드리지 않는다. 2026-11-13 기준 468개(SQLite에서는 PostgreSQL 전용 2개 건너뜀) |
| PostgreSQL에서 전체 | `.\.venv\Scripts\python manage.py test --noinput` | 사용자 환경변수 `QMS_DB_NAME`·`QMS_DB_USER`·`QMS_DB_PASSWORD`가 있으면 위 명령도 PostgreSQL에서 돈다(SQLite로 돌리려면 그 창에서 `Remove-Item Env:QMS_DB_NAME`). e2e 두 스크립트는 `QMS_DB_NAME`을 빼고 임시 SQLite를 쓴다. 테스트 DB `test_qms`를 만들고 지우므로 **한 번에 하나만** 실행한다(두 실행이 겹치면 서로의 테스트 DB를 지워 연결 오류가 난다). `PgBackupRestoreTest`는 PostgreSQL에서만 돈다 |
| 앱 하나만 | `.\.venv\Scripts\python manage.py test qms` | 작업 중 빠른 확인용. 완료 판단에는 전체 실행이 필요하다 |
| 테스트 하나만 | `.\.venv\Scripts\python manage.py test core.tests.ShellTest.test_logged_in_pages_not_stored` | |
| 화면 흐름(e2e) | `.\.venv\Scripts\python scripts\e2e_check.py` | 임시 폴더에 새 DB를 만들고 포트 8765에 서버를 띄워 실제 HTTP로 인터록·화면을 점검한다. 2026-11-12 기준 76개 |
| 브라우저 흐름(React `/app/`) | `python scripts\e2e_browser.py` | **시스템 Python**(`.venv` 아님)으로 실행한다. Playwright가 `.venv`에 없고 의존성을 추가하지 않기 때문이다(`python -m playwright`). 번호 자동 부여(품번 등록)도 점검한다. 임시 폴더에 새 DB를 만들고 포트 8766에 서버를 띄워 실제 브라우저로 로그인, 종합현황 카드 수(API와 같은지), 내 할 일 "화면 편집" → 위젯 추가 후 새로고침, 390px 폭 가로 스크롤, 로고(없으면 글자·넣으면 왼쪽 위 그림), 다크 모드 배경색, 명령창(결과 없음 Enter·localStorage 차단), 검사기준서(새 기준서 → Rev.1, 목록 줄 수·엑셀 받기, 10줄 붙여넣기 저장, 잠긴 기준서 붙여넣기 거부, 새 개정, 인쇄 화면 PDF A4 1쪽·초안 표시), 감사 기록 화면, 검사 입력(검사 대기 목록, 품명 일부로 LOT 찾기 목록, 스캔 → 측정 화면, 입력 즉시 합격/규격 이탈, 판정 두 번 눌러도 1건, 불합격 → 부적합 번호, 없는 LOT → 입고 창), 검사 목록 탭 → 기록 페이지, 검사 기록 판정 띠·측정값 표 9열·「⋯」 메뉴의 삭제 한 곳, 메모 칸 크기 고정·사진 첨부 저장, 검사 기록 연결 탭(LOT)·첨부 탭 올리기, 검사 성적서 PDF A4 1쪽, 메뉴 → 새 화면, 검사 목록 요약·메뉴 강조, 즉시 확인 전 판정 → 불량유형 먼저, 기준정보(품번 BOM 붙여넣기 저장, 공정 표 줄 추가, 관리계획서 새 개정·검사기준 초안, 관리계획서 PDF A4 가로 1쪽, 엑셀 일괄 등록 미리보기→확정, 메뉴 → 기준정보 새 화면), 세션 끊김 시 로그인 이동을 점검한다. 2026-11-13 기준 44개(44/44 통과). Playwright는 `requirements.txt`에 넣지 않는다 |
| 설정 점검 | `.\.venv\Scripts\python manage.py check` | |
| 마이그레이션 누락 확인 | `.\.venv\Scripts\python manage.py makemigrations --check --dry-run` | 모델을 바꿨는데 마이그레이션이 없으면 실패한다 |

e2e를 Git Bash에서 실행할 때 한글이 깨지면 `PYTHONIOENCODING=utf-8`을 앞에 붙인다.

## 테스트 파일

| 파일 | 다루는 것 |
| --- | --- |
| `core/tests.py` | `RoutingTest`(라우팅·실적), `InterlockTest`(보류·처분 인터록), `EditRequestTest`(삭제·수정 요청·잠금), `NcQuickTest`·`NcReportTest`·`NcMailTest`(부적합 간편 등록·보고서·메일), `SearchTest`, `ShellTest`(로고·사이드바·전체 메뉴 묶음·캐시 헤더), `PgBackupRestoreTest`(PostgreSQL 전용: `pg_dump` 백업·복원 예행연습·동시 저장 시 부적합 번호 중복 없음) |
| `qms/tests.py` | `QmsTest`(검사 판정·계측기·자격·SPC·4M·클레임·SCAR·CAPA·심사·PPAP·엑셀 가져오기·양식·백업·복원·알림 등), `TimelineTest`, `MemoTest`, `AuditPackTest`, `DashboardTest` |
| `personal/tests.py` | `LeaveTests`(연차 계산), `PayTests`(급여), `OwnerOnlyTests`(본인만 열람) |
| `core/tests_rules.py`, `qms/tests_rules.py` | 공통 업무 규칙(`rules.py`): 잠금·처분·승인, 검사 판정·입고 |
| `core/api/tests.py`, `qms/api/tests.py` | API: 로그인·권한·오류 형식·SPA 서빙(`AuthApiTest`·`SpaTest`·`CommonApiTest`: 검색·품번 조회·감사 기록·개정 이력 승인), 공장 종합현황·내 할 일·배치 저장, 검사기준서 API(`SpecApiTest`) |
| `core/tests_rules.py` `RevisionLogTest` | 개정 이력: 신청·승인자 비밀번호 확정·확정 후 수정·삭제 불가 |
| `qms/tests_rules.py` `SpecRulesTest` | `save_spec`·`spec_version`·이전 개정 비교 |
| `qms/tests.py` `SpecDocumentTest` | 문서 구조·엑셀 내보내기(A4 한 시트·초안 표시·수식 문자 방어)·양식 여러 줄 매핑 |
| `core/tests_numbering.py` | 번호 부여: `CodeValueTest`(코드값 검사)·`NumberRuleTest`(틀 검사·규칙 잠금)·`NumberingTest`(번호 계산·풀이) |
| `core/tests_masters.py` | 기준정보: `MasterTest`(상위 부서 순환 거부, 사번·사업자번호는 입력했을 때만 중복 검사, 품질팀장만 추가·수정, 등록자 자동 기록, 메뉴), `PartnerTest`(거래처 구분 필수, 품질엔지니어는 인증서만 수정, 만료 임박 인증서가 기한 목록에 나옴), `FieldDefTest`(키 잠금, 선택지 필수, 종류별 값 검사, 사용 중지 칸 값 유지, 관리 화면 입력 칸·칸 배치), `AttachmentTest`(개인 기록 거부, 받기에 대상 기록 권한 필요, API 올리기·목록, 모르는 종류 거부, 백업에 첨부 포함), `LinkMastersTest`(미리보기는 안 바꿈, `--apply`는 백업 폴더 필수·백업 후 연결, 여러 후보·구분 불일치·못 찾음 보고, 이미 채운 칸 유지, 승인된 PPAP도 이력 남김, 심사원 이름 순서) |
| `core/api/tests_relations.py` | `RelationsApiTest`: 연결 패널 API 묶음·권한 없는 묶음 숨김·기록 권한·개인 앱 제외·관리 화면 없는 기록(url 없음)·쪽 나누기·쿼리 수 |
| `qms/tests.py` `DocumentNumberingTest` | 관리 화면 문서 추가의 자동 번호·개정 자동 채움 |
| `scripts/e2e_browser.py` | React 화면을 브라우저로: 번호 자동 부여(품번 등록), 로그인, 카드 수, 화면 편집·위젯 추가 유지, 휴대폰 폭, 로고, 다크 모드, 명령창, 검사기준서(붙여넣기·새 개정·인쇄), 감사 기록, 검사 입력(LOT 찾기·스캔·측정·판정·입고), 검사 목록·성적서 인쇄, 메모 사진 첨부, 메뉴, 기준정보(품번 BOM·공정 표·관리계획서·엑셀 일괄 등록), 세션 끊김 |
| `scripts/e2e_check.py` | 로그인부터 화면별 HTTP 흐름, 정적 파일·디자인 토큰 제공 |

## 변경 종류별 검증

| 변경 | 해야 할 검증 |
| --- | --- |
| 모델 필드·제약 | `makemigrations` 결과 확인, 단위 테스트 전체. 기존 행이 남는지 마이그레이션 코드로 확인한다. 데이터 마이그레이션이면 운영 DB 사본에서 `migrate`를 먼저 해 본다(아래) |
| 업무 규칙 (`docs/business-rules.md`) | 규칙이 막아야 할 경우와 허용할 경우를 모두 테스트한다. 기존 인터록 테스트가 계속 통과해야 한다 |
| 권한·역할 | 허용된 역할과 거부되는 역할을 모두 서버 응답(상태 코드, `PermissionDenied`)으로 확인한다 |
| React 화면(`frontend/`) | `npm run build`가 성공해야 하고(`tsc` 타입 검사 포함), `frontend/dist/`를 다시 만들어 함께 커밋한 뒤 `scripts\e2e_browser.py`를 실행한다 |
| 화면·템플릿·CSS | 단위 테스트 + e2e. 디자인 변경은 브라우저에서 PC·휴대폰 폭, 라이트·다크 모드를 직접 확인한다(`DESIGN.md`) |
| 관리 명령(`backup`, `restore`, `collect`, `notify`) | 임시 폴더나 `--dry-run`으로 실행하고 결과 파일·출력을 확인한다 |
| 문서만 | 테스트 불필요. 문서에 적은 명령·경로가 실제로 있는지 확인한다 |

## 운영 DB 사본으로 미리 확인

마이그레이션이나 데이터가 많은 화면을 바꿀 때는 운영 DB를 직접 쓰지 않고 사본으로 확인한다.

```powershell
.\.venv\Scripts\python manage.py backup C:\temp\qms-copy             # 운영 DB의 일관된 사본을 만든다
$env:QMS_DATA_DIR = "C:\temp\qms-copy\qms-<날짜-시각>"                # 이 PowerShell 창에서만 사본을 쓴다
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver 8001                      # 운영 서버(8000)와 다른 포트
```

사본 폴더에 `secret_key.txt`가 없으면 새로 만들어지므로, 사본에서는 다시 로그인해야 한다. 끝나면 `Remove-Item Env:QMS_DATA_DIR`로 환경변수를 지운다.

## 완료 기준

아래를 모두 만족해야 "완료"로 보고한다.

1. 단위 테스트 전체가 실제로 실행되어 `OK`로 끝났다.
2. 화면·URL·권한·인터록에 닿는 변경이면 e2e(`e2e_check.py`, React 화면이면 `e2e_browser.py`도)가 실제로 실행되어 전부 통과했다.
3. 모델을 바꿨다면 마이그레이션 파일이 함께 있고, `makemigrations --check`가 통과한다.
4. 새 동작이나 바뀐 규칙을 확인하는 테스트가 추가되었다.
5. 바뀐 동작·명령·규칙이 `README.md`·`docs/`에 반영되었다.
6. 보고에 실행한 명령과 실제 결과(통과 수·실패 내용)를 적었다. 실행하지 못한 검증은 "미검증"으로 따로 적는다.
