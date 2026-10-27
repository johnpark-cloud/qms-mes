# QMS+MES (localhost)

품질엔지니어 1인이 어느 회사에서든 다시 세울 수 있는 QMS+MES 틀. 비용 0원(Python, Django, SQLite).

## 처음 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py createsuperuser
```

## 실행

프로젝트 폴더의 **`서버시작.bat`을 더블클릭**하면 DB 갱신(migrate) 후 서버가 켜지고 브라우저가 열립니다. 끌 때는 그 검은 창에서 `Ctrl+C`를 누르거나 창을 닫습니다.

터미널에서 직접 켤 때:

```powershell
.\.venv\Scripts\python manage.py runserver
```

http://127.0.0.1:8000/ → **내 할 일** 화면이 열립니다.

| 화면 | 주소 |
| --- | --- |
| 내 할 일 (8D·SCAR 기한, 열린 부적합, 승인 대기, 교정 임박, 초품 미확인, SPC 경보) | /todo/ |
| 검사 입력 (검사원용 큰 화면, 바코드 스캔) | /inspect/ |
| 품질 KPI (고객 PPM, 직행률, 8D 기한 준수, 실패비용, 불량 파레토) | /kpi/ |
| 협력사 성적표 (수입검사 불합격률, PPM, SCAR 회신 준수) | /suppliers/ |
| 전체 메뉴 (모든 기록 입력·조회) | /admin/ |
| LOT 추적 (상위·하위 계보, 보류, 계보 미등록) | /trace/ |
| 엑셀 일괄 등록 (품번, 작업지시) | /import/ |
| SPC 관리도 | 검사기준 화면의 검사항목 옆 "관리도" 링크 |

## 사내망 서비스 (팀 공유)

혼자 쓸 때는 위의 `runserver`로 충분합니다. 팀원이 각자 PC에서 접속하게 하려면 아래처럼 띄웁니다(waitress, 무료).

```powershell
powershell -ExecutionPolicy Bypass -File scripts\serve.ps1 -HostName QA-PC01   # QA-PC01 = 이 PC 이름 또는 IP
```

- 팀원은 `http://QA-PC01:8000`으로 접속합니다. Windows 방화벽이 묻으면 "개인/도메인 네트워크 허용"을 선택합니다.
- 서명·세션용 비밀키는 처음 실행할 때 `data/secret_key.txt`에 자동으로 만들어집니다(Git에 올라가지 않음). 이 파일을 지우면 모두 다시 로그인해야 합니다.
- 첨부파일(문서 원본)은 로그인한 사용자만 내려받을 수 있습니다.

## 휴대폰에서 사진 찍기

QMS > "부적합 등록"(`/nc/new/`)에서 휴대폰 카메라로 바로 찍어 올릴 수 있습니다. 먼저 **회사 보안 정책(사내망 포트 개방 가능 여부)을 확인**하세요.

1. `QMS_ALLOWED_HOSTS=<PC IP>` 환경변수를 설정합니다.
2. `python manage.py runserver 0.0.0.0:8000`으로 띄웁니다(또는 `scripts\serve.ps1`의 host를 바꿉니다).
3. 관리자 PowerShell에서 방화벽을 엽니다.
   `New-NetFirewallRule -DisplayName QMS -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`
4. 휴대폰(같은 사내망)에서 `http://<PC IP>:8000/nc/new/`로 접속합니다.

## 모듈

- **MES**: 품번·BOM·공정 라우팅, 작업지시·작업 실적(투입·양품·불량, 이전 공정 실적 없으면 등록 차단, 진도율), LOT·계보(분할·병합), 출하
- **CAPA**: 8D·SCAR·부적합·심사 지적 화면의 "CAPA 만들기" → 담당·기한 → 조치 완료 → 유효성 확인("유효")해야 종결
- **내부심사**: 계획·실시·지적(중부적합/경부적합/관찰/개선기회). 중·경부적합은 CAPA가 연결돼야 심사 종결
- **PPAP**: 제출을 만들면 AIAG 18요소가 수준(1~5)에 맞게 생성되고 관리계획서·출하검사가 자동 연결. 제출(S) 요소에 문서·기록이 모두 있어야 PSW 승인 서명 가능, "인쇄/PDF"가 PSW 요소표
- **부적합**: 등록 즉시 LOT과 하위 계보 전체 자동 보류 → 투입·출하 차단. MRB 처분(재작업·수리는 재검사 합격 기록 필요, 특채는 고객 승인번호 필요, 폐기·반품은 보류 유지)
- **검사**: 검사기준(개정·승인 서명, 승인 후 잠금) → 검사 → "저장하고 판정하기" → 불합격이면 부적합 자동 등록
- **고객 클레임(8D)**: 접수 즉시 부적합·보류, 고객사별 D3·D5 기한, D1~D8 모두 채워야 종결
- **SCAR**: 협력사 시정요구, 회신 기한
- **문서**: 원본 파일 + 개정 + 승인 서명, 유효본 = 승인된 최신 개정
- **심사 증적**: 체크리스트 항목에 문서·기록 연결, 미비 항목 표시
- **보고서**: 각 기록 화면의 "출력" → 인쇄/PDF, 또는 등록한 고객 엑셀 양식(셀 매핑)으로 다운로드
- **출하성적서(COA)**: 출하 화면의 "인쇄/PDF"가 성적서가 됩니다(최신 합격 출하검사, 없으면 공정검사). 고객 엑셀 양식은 대상 기록을 "출하"로 하고 매핑에 `{"A10": "coa_rows"}`처럼 표 시작 셀을 적으면 항목·특별특성·LSL·USL·단위·측정값·판정이 아래로 채워집니다
- **재발 방지**: 부적합·클레임 화면에 같은 품번(계보 포함)·같은 불량유형·비슷한 설명의 과거 종결 사례와 그 8D의 D4·D7을 표시
- **검사 입력 화면**: LOT 바코드를 스캔하면 승인된 현재 검사기준이 뜨고, 값을 넣는 즉시 규격 이탈을 빨간색으로 표시. "판정"은 전부 저장되거나(자격·교정·기준 검사 통과) 아무것도 저장되지 않습니다
- **KPI 입력**: 부적합에 불량유형·불량 수량·실패비용, 클레임에 불량 수량, 구매 자재 LOT에 협력사를 적어야 KPI와 협력사 성적표가 채워집니다
- **SPC**: 부분군 n=1이면 I-MR, 2~10이면 X̄-R 관리도, Cpk, 경보(관리한계 이탈, R/MR 이탈, 연속 9점). 특별특성(CC·SC)은 경보 시 부적합 자동 등록·보류, 일반 항목은 내 할 일에 경보 표시
- **계측기**: 교정 대장. 측정값에 계측기를 적으면 교정 기한이 지난 계측기는 거부. 교정 14일 전부터 내 할 일에 표시
- **검사원 자격**: 검사구분별 자격·유효기한. 그 검사구분에 자격 기록이 하나라도 생기면 그때부터 자격자만 판정 가능 (자동수집 `collect`은 검사자가 없어 판정되지 않으므로, 자격을 쓰는 검사구분은 자동수집 대신 직접 입력)
- **관리계획서(PFMEA)**: 공정·특성·특별특성·규격·S/O/D·조치우선순위(AP). 승인 후 "검사기준 초안 만들기"로 검사기준 생성
- **4M 변경**: 고객 통보 대상은 고객 승인번호가 있어야 승인. 승인 후 적용 일시부터 그 품번의 합격 검사(초품)가 나올 때까지 출하 차단

## 사용자와 역할

전체 메뉴 → 사용자에서 계정을 만들고 **스태프 권한**을 체크한 뒤 그룹을 지정합니다.

| 그룹 | 권한 |
| --- | --- |
| 품질엔지니어 | 모든 기록 작성·수정 (삭제 불가) |
| 품질팀장 | 품질엔지니어 권한 + 승인 서명, MRB 처분 |
| 검사원 | LOT·계보·출하 등록, 검사·측정값 입력 |

## 회사 데이터와 백업

회사 데이터(DB, 첨부파일)는 `data/` 폴더에만 저장되며 Git에 올라가지 않습니다. 위치를 바꾸려면 환경변수 `QMS_DATA_DIR`을 지정합니다.

```powershell
# 수동 백업
.\.venv\Scripts\python manage.py backup "\\NAS\quality\qms-backup"
# 매일 18:00 자동 백업 등록 (Windows 작업 스케줄러)
powershell -ExecutionPolicy Bypass -File scripts\register_backup_task.ps1 -Dest "\\NAS\quality\qms-backup"
```

30일이 지난 백업은 자동으로 지워집니다.

복구는 먼저 리허설로 백업이 쓸 만한지 확인한 뒤 실행합니다. 분기마다 리허설을 한 번 해 두면 "백업은 있는데 복구가 안 되는" 일을 막을 수 있습니다.

```powershell
.\.venv\Scripts\python manage.py restore "\\NAS\quality\qms-backup\qms-20261026-180000"           # 리허설: 무결성 검사 + 건수 확인
.\.venv\Scripts\python manage.py restore "\\NAS\quality\qms-backup\qms-20261026-180000" --apply   # 실제 복원 (서버를 먼저 끄세요)
```

실제 복원 전의 데이터는 `data/pre-restore-날짜/`에 따로 보관됩니다.

## 기한 알림 (메일 · Teams)

"내 할 일"과 같은 기준(8D·SCAR·CAPA 기한, 교정, 초품, 심사, PPAP, SPC 경보)으로 매일 아침 요약을 보냅니다. 보낼 항목이 없으면 보내지 않습니다.

1. Windows 검색 → "시스템 환경 변수 편집" → 환경 변수 → **사용자 변수**에 추가합니다.

   | 변수 | 예 | 설명 |
   | --- | --- | --- |
   | `QMS_NOTIFY_EMAILS` | `qa1@회사.com,qa2@회사.com` | 메일 받는 사람 (쉼표로 구분) |
   | `QMS_SMTP_HOST` / `QMS_SMTP_PORT` | `smtp.회사.com` / `587` | 회사 메일 서버 (IT팀에 문의) |
   | `QMS_SMTP_USER` / `QMS_SMTP_PASSWORD` | | 발송 계정 |
   | `QMS_MAIL_FROM` | `qms@회사.com` | 보내는 사람 주소 |
   | `QMS_TEAMS_WEBHOOK` | `https://...` | Teams 채널 → 워크플로 → "웹후크 요청 수신 시 채널에 게시" URL |

2. 내용만 먼저 확인: `.\.venv\Scripts\python manage.py notify --dry-run`
3. 매일 08:30 자동 발송 등록: `powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Command notify -Time 08:30`

## 화면 디자인

SAP Fiori Horizon(SAP Digital Manufacturing·QM의 디자인 시스템)의 색·간격·카드·상태 배지 규칙을 참고해 `core/static/qms/fiori.css` 한 파일로 만들었습니다(상표·전용 폰트 미사용, 인터넷 불필요). 오른쪽 위 반달 아이콘으로 라이트·다크·자동을 바꿉니다. 회사 색으로 바꾸려면 파일 맨 위의 `--f-brand`, `--f-link` 값만 고치면 됩니다.

## 측정 데이터 자동 수집 (3단계)

`data/inbox/`에 아래 형식의 CSV를 넣고 `collect`를 실행하면 검사 기록이 만들어지고 판정됩니다. 결과 파일은 `done/` 또는 `error/`로 옮겨집니다.

```csv
lot,type,characteristic,value
RAW-1,수입검사,두께,10.1
RAW-1,수입검사,외관,OK
```

```powershell
.\.venv\Scripts\python manage.py collect
```

## 새 회사로 옮길 때

코드만 가져가고 `data/`는 두고 갑니다. 회사와 무관한 설정(심사 체크리스트 등)은 아래 명령으로 가져갈 수 있습니다.

```powershell
.\.venv\Scripts\python manage.py dumpdata qms.AuditChecklist qms.AuditItem --indent 2 -o kit.json   # 내보내기
.\.venv\Scripts\python manage.py loaddata kit.json                                                  # 새 회사에서 가져오기
```

### 개인 연차·급여 자료

`/me/`의 연차·급여는 본인만 열람합니다(관리자도 다른 사람 것은 볼 수 없음). 다만 같은 DB에 저장되므로 서버 백업에는 포함됩니다. 회사를 옮길 때는 내보낸 뒤 지우세요. 명세서 파일은 `data/media/personal/`에 있습니다.

```powershell
.\.venv\Scripts\python manage.py dumpdata personal --indent 2 -o my-personal.json   # 내보내기
# 이후 /admin/ 에서 본인 기록을 삭제하고, data\media\personal 폴더를 지웁니다.
```

## PostgreSQL 전환 (2단계: 팀 확장 또는 셀 시리얼 도입 시)

1. PostgreSQL Windows 설치 파일로 설치하고 `.\.venv\Scripts\python -m pip install psycopg`
2. 기존 데이터 내보내기: `python manage.py dumpdata --natural-foreign -e contenttypes -e auth.permission -o all.json`
3. 환경변수 `QMS_DB_NAME`, `QMS_DB_USER`, `QMS_DB_PASSWORD` 지정 → `python manage.py migrate` → `python manage.py loaddata all.json`
4. 백업은 `pg_dump`로 바꿉니다.

## 테스트

```powershell
.\.venv\Scripts\python manage.py test core qms   # 단위 테스트
.\.venv\Scripts\python scripts\e2e_check.py      # 실제 서버를 띄워 화면 흐름 55개 점검 (임시 DB 사용)
```
