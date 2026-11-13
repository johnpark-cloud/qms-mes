# Phase 8 (B4) — CAPA·클레임·SCAR·4M 변경 기록 화면: 결정 메모

요구: REC-09. 방식은 Phase 5~7과 같다(설명서 `core/recordspec.py` 등록 → records API·기록 화면·`record_url`이 따라온다).

## 결정

- 설명서 추가: `qms.capa`, `qms.customerclaim`, `qms.customerrule`(클레임 설정), `qms.scar`, `qms.changerequest`.
- **종결**: CAPA·클레임·SCAR은 관리 화면에서 종결일을 직접 넣던 것을 기록 화면 「종결」 버튼(`POST …/close/`, `change_` 권한)으로 한다.
  종결 일시는 서버가 넣고, 모델 `clean` 규칙(8D 전 단계, SCAR 회신, CAPA 유효)이 같은 문구로 막는다. `closed_at`은 계속 서명 칸이라 PATCH로 못 바꾼다.
  설명서 `Spec.close=True`인 기록만 연다.
- **서명 칸을 기록별로**: 고객 승인 문서번호는 부적합에선 MRB 처분 칸이지만 4M 변경에선 승인 전 입력 칸이다.
  공통 `SIGN_FIELDS`에서 `disposition`·`customer_approval_ref`를 빼고 부적합 설명서 `sign`에 둔다(`recordspec.sign_fields(spec)`).
- **출처 연결**: CAPA 칸에 `source_record`(출처 기록, 새 화면 링크). 클레임·SCAR·부적합에서 연결된 CAPA는 기존 관련 기록 탭(GENERIC)으로 보인다.
  「⋯ → CAPA 만들기」(관리 화면 추가 폼, 출처 채움)는 CAPA 모듈이 켜져 있을 때만 메뉴에 둔다. 서버가 `links`로 준다(LOT 이력 링크도 여기로 옮긴다).
- **8D 단계**: 클레임 칸에 현재 단계·D3/D5 기한·D1~D8 순서대로. D1~D8은 수정 칸.
- **4M 초품 상태**: 모델 속성 `first_article_state`(합격 검사 링크 / 승인 후 없으면 「미확인 (출하 차단)」). 출하 차단은 `Shipment.clean` 그대로.
- **꺼진 모듈 종결(MOD-07 연장)**: `CLOSING`에 `api/records/qms.capa/` 등 추가. 기록 API는 상세 저장(`<id>/`)과 `<id>/close/`만 허용, 요청·승인·삭제는 403.
- 수정 칸에서 뺀 것: 외래키(담당자·확인자·LOT·부적합·거래처·품번), 날짜시간(접수·적용 일시), 비어 있을 수 있는 예/아니오(CAPA 유효성) → 관리 화면.
- 범위 밖: 8D 별도 표 화면, CAPA 유효성 확인 전용 창, 새 기록 만들기.
