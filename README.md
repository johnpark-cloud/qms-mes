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

```powershell
.\.venv\Scripts\python manage.py runserver
```

http://127.0.0.1:8000/ → **내 할 일** 화면이 열립니다.

| 화면 | 주소 |
| --- | --- |
| 내 할 일 (8D·SCAR 기한, 열린 부적합, 승인 대기) | /todo/ |
| 전체 메뉴 (모든 기록 입력·조회) | /admin/ |
| LOT 추적 (상위·하위 계보, 보류, 계보 미등록) | /trace/ |
| 엑셀 일괄 등록 (품번, 작업지시) | /import/ |
| SPC 관리도 | 검사기준 화면의 검사항목 옆 "관리도" 링크 |

## 모듈

- **MES**: 품번·BOM, 공정, 작업지시, LOT·계보(분할·병합), 출하
- **부적합**: 등록 즉시 LOT과 하위 계보 전체 자동 보류 → 투입·출하 차단. MRB 처분(재작업·수리는 재검사 합격 기록 필요, 특채는 고객 승인번호 필요, 폐기·반품은 보류 유지)
- **검사**: 검사기준(개정·승인 서명, 승인 후 잠금) → 검사 → "저장하고 판정하기" → 불합격이면 부적합 자동 등록
- **고객 클레임(8D)**: 접수 즉시 부적합·보류, 고객사별 D3·D5 기한, D1~D8 모두 채워야 종결
- **SCAR**: 협력사 시정요구, 회신 기한
- **문서**: 원본 파일 + 개정 + 승인 서명, 유효본 = 승인된 최신 개정
- **심사 증적**: 체크리스트 항목에 문서·기록 연결, 미비 항목 표시
- **보고서**: 각 기록 화면의 "출력" → 인쇄/PDF, 또는 등록한 고객 엑셀 양식(셀 매핑)으로 다운로드
- **SPC**: X̄-R 관리도, Cpk, 경보(관리한계 이탈, R 이탈, 연속 9점) → 부적합 등록 링크

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

30일이 지난 백업은 자동으로 지워집니다. 복구는 백업 폴더의 `db.sqlite3`와 `media`를 `data/`에 다시 복사하면 됩니다.

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

## PostgreSQL 전환 (2단계: 팀 확장 또는 셀 시리얼 도입 시)

1. PostgreSQL Windows 설치 파일로 설치하고 `.\.venv\Scripts\python -m pip install psycopg`
2. 기존 데이터 내보내기: `python manage.py dumpdata --natural-foreign -e contenttypes -e auth.permission -o all.json`
3. 환경변수 `QMS_DB_NAME`, `QMS_DB_USER`, `QMS_DB_PASSWORD` 지정 → `python manage.py migrate` → `python manage.py loaddata all.json`
4. 백업은 `pg_dump`로 바꿉니다.

## 테스트

```powershell
.\.venv\Scripts\python manage.py test core qms   # 단위 테스트
.\.venv\Scripts\python scripts\e2e_check.py      # 실제 서버를 띄워 화면 흐름 30개 점검 (임시 DB 사용)
```
