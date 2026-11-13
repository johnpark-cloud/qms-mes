# Phase 7 (B3) CONTEXT — LOT·부적합·보류 기록 화면

## 결정

- 설명서(`core/recordspec.py` SPECS)에 `core.lot`·`core.nonconformance`·`core.hold`를 더한다. `record_url`이 설명서를 먼저 보므로 LOT·부적합·보류를 가리키는 링크(관계 패널·목록·개요·타임라인)는 새 기록 화면으로 간다. 통합 검색에서 LOT 번호를 치면 「LOT 이력(추적)」으로 가는 동작은 그대로 둔다(추적 기능).
- 부적합 처분(`disposition`·`customer_approval_ref`)은 `SIGN_FIELDS`에 넣어 범용 저장(PATCH)이 「승인 서명으로만 바꿀 수 있습니다」로 거부한다. 처분은 전용 API `POST /api/records/core.nonconformance/<id>/dispose/` {disposition, customer_approval_ref, cost, password} → 기존 `rules.dispose_nc`(MRB 비밀번호·필수칸·모델 clean 처분 규칙·보류 해제). 메시지는 모델·rules 그대로라 관리 화면과 같다.
- 보류는 읽기 전용: `Spec.edit` 비어 있음 → 상세 `can_change` false, 요청 버튼 없음(check_edit_request가 Hold 404). PATCH는 `edit`가 빈 설명서면 403.
- 부적합 범용 저장 칸: 내용·불량유형·수량·격리·선별·고객 통보·발생 유형·측정값·특별특성. LOT·발견 일시·발견 공정·발견자(외래키·인터록) 칸은 관리 화면.
- 종결(=MRB 승인)된 부적합은 잠금 → 수정 요청 흐름(Phase 6 그대로). 종결 뒤 열려 있는 칸(실패비용·고객 통보일)은 이번 범위에서 관리 화면.

## 범위 밖

- 부적합 사진 올리기(관리 화면·간편 등록 그대로), 새 부적합 등록 화면.
