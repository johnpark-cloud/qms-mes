# Phase 2 (A1) 맥락 — 모듈 대응표와 켜기/끄기 게이트

요구사항: MOD-01~05, MOD-09. 연구: `.planning/research/ARCHITECTURE.md` Pattern 1·2.

## 결정

- **대응표는 `core/modules.py` 한 곳.** 순수 파이썬 상수와 함수. qms 모델을 import하지 않고 `'app.model'` 라벨만 쓴다.
- **모듈 키** (BASE는 끌 수 없음):
  - `mes` 작업지시·실적·출하
  - `qms_inspection` 검사기준·관리계획서·검사·계측기·검사원 자격, `inspect*`·`spc`, 검사 API
  - `qms_change` 4M 변경 — requires `qms_inspection` (초품 해제가 검사 판정)
  - `qms_capa` CAPA
  - `qms_claim` 고객 클레임·고객사별 8D 기한
  - `qms_supplier` SCAR·협력사 평가
  - `qms_ppap` PPAP 제출·요소
  - `qms_audit` 내부심사·지적·체크리스트·심사 항목·증적·심사 자료 출력 — requires `qms_capa` (지적 → CAPA 외래키)
  - `qms_document` 문서·문서 개정
  - `qms_kpi` 품질 KPI 화면
  - BASE: LOT·부적합·보류·기준정보·시스템·홈·메모·첨부·개인(personal)·엑셀 양식
- **스위치 저장:** `core.ModuleSwitch`(key 고유, enabled, 변경자, 변경 시각, 이력). **행이 없으면 켜짐.** 시드·데이터 마이그레이션 없음(새 테이블만).
- **바꾸기:** 시스템 관리자만(관리 화면 권한 함수가 superuser만 True). requires 검사는 모델 `clean()`.
- **문(미들웨어 `module_gate`, `process_view`):** 요청 → 모듈 판정 → 꺼져 있으면
  - 일반 사용자: 404. `/api/`는 JSON `{"detail", "code": "module_inactive"}`.
  - 시스템 관리자: GET/HEAD만 통과, 그 밖은 403. (종결 화이트리스트는 A3)
  - SPA 껍데기 `/app/*`는 막지 않는다. React가 `me.modules`로 「비활성 모듈」 안내를 보인다.
- **판정 순서:** 뷰 kwargs(`app_label`/`model_name`, `label`) → 관리 url_name(`admin:<app>_<model>_…`) → 관리 자동완성 GET 인자 → url_name 표 → `/api/` 경로 접두 표.
- **쿼리 인자 경로**(`/api/attachments/?ct=`, `/api/qms/memos/?ct=`)는 뷰 안에서 라벨 모듈을 확인한다.
- **메뉴:** 항목 url 이름에서 모듈을 도출(관리 목록 → 모델 → 모듈). 별도 nav 키 없음. `me`에 `modules: {key: bool}` 추가.
- **ModuleSwitch 상태는 캐시하지 않는다.** 요청마다 한 쿼리, `request` 객체에 메모.

## 하지 않는 것 (뒤 단계)

- 끄기 전 열린 기록 검사, 종결 허용 목록 (A3)
- 할 일·위젯·알림·검색 필터, `excel_report`·`media/`·`audit_pack`의 대상 모듈 검사 (A4)
- 라이선스 (범위 밖)
