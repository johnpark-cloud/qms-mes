# Phase 6 (B2) CONTEXT — 기록 화면에서 수정·승인·요청

## 결정

- 미결 #5 (2026-11-13 사용자): 수정·삭제 요청 로직을 동작 변경 없이 `core/rules.py`로 옮긴다 — `check_edit_request`(대상·권한), `submit_edit_request`(사유·비밀번호·요청 생성·관리자 즉시 승인). `core/views.edit_request`와 records API가 함께 쓴다. 기존 테스트가 회귀망.
- 고칠 수 있는 칸은 설명서 `Spec.edit`에 적은 칸뿐이다. 그 밖의 칸을 보내면 400. 서명 칸(`SIGN_FIELDS`: 승인자·승인 일시·판정 등)은 설명서에 넣을 수 없고(테스트가 검사) 보내면 「승인 서명으로만 바꿀 수 있습니다」.
- 저장은 ModelForm(`full_clean`·고유 검사, 칸별 오류) → `rules.save_with_lock`(승인 잠금·수정 승인 소모). 변경 이력은 simple-history 미들웨어가 사용자와 함께 남긴다. `version`(record_version)이 다르면 409.
- 파일 칸(교정 성적서·원본 파일·교육 기록)은 이번 범위에서 기록 화면 수정 대상이 아니다 — 첨부 패널이나 관리 화면을 쓴다.

## 범위

- API: `PATCH /api/records/<label>/<id>/` {values, version}(change_ 권한), `POST .../approve/` {password}(Approvable만, 품질팀장), `POST .../request/` {kind, reason, password}.
- 상세 응답에 `version`·`edit`(칸 종류·선택지·원래 값)·`can_change`·`locked`·`can_approve`·`requests`.
- 프론트 RecordView: 수정 모드(칸별 오류), 승인(SignModal), 수정/삭제 요청 창.

## 범위 밖

- 새 기록 추가 화면(목록의 「새로」는 관리 화면 그대로).
