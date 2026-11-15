# Phase 9 (B5) — 내부심사·체크리스트·심사 항목·PPAP 기록 화면: 결정 메모

요구: REC-10. 방식은 Phase 5~8과 같다(설명서 `core/recordspec.py` 등록 → records API·기록 화면·`record_url`이 따라온다).

## 결정

- 설명서 추가: `qms.internalaudit`, `qms.auditfinding`, `qms.auditchecklist`, `qms.audititem`, `qms.ppapsubmission`, `qms.ppapelement`.
- **내부심사 종결**: `close=True`. 「종결」 버튼이 종결일을 넣고 모델 `clean`(실시일 필요, CAPA 없는 중·경부적합 지적)이 같은 문구로 막는다.
  지적은 하위 표로 보이고 행이 지적 기록 화면으로 간다.
- **지적 → CAPA**: 지적 화면 「⋯ → CAPA 만들기」(출처 `AUDIT`, 관리 화면 추가 폼). CAPA 저장 때 모델이 지적에 연결한다(`Capa.save`). 연결된 CAPA는 지적의 「CAPA」 칸 링크로 보인다.
- **PPAP 요소 표**: PPAP 화면 하위 표(번호·요소·요구·문서·증적 기록·비고). 요소 화면에서 요구·비고만 고친다(문서·증적 기록 연결은 외래키라 관리 화면).
- **승인 후 요소 잠금**: 설명서 `lock_parent='submission'` — 부모가 승인되면 요소는 잠김으로 보이고(`locked`, `can_change` 거짓) PATCH는 409.
  시스템 관리자도 기록 화면에서는 못 고친다(모델 `PpapElement.save`가 막는 것과 같다. 관리 화면 수정 승인 흐름은 그대로).
- PPAP 제출일·고객 승인일(승인 후 기록 칸)은 승인 후 잠금 때문에 기록 화면에서 못 고친다 → 관리 화면.
- **꺼진 모듈 종결**: `CLOSING['qms_audit']`에 `api/records/qms.internalaudit/`, `api/records/qms.auditfinding/` 추가.
- 범위 밖: 증적(Evidence) 화면, 새 기록 만들기, 메뉴 주소 변경(Phase 10).
