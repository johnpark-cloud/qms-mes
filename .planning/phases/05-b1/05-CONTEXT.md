# Phase 5 (B1) CONTEXT — 기록 설명서와 records API, 첫 4종 이전

## 결정

- 미결 #6 (2026-11-13 사용자): 기록 화면의 변경 이력 탭은 그 모델의 `view_` 권한자에게 보인다. 전체 감사 기록(`/app/audit`)은 그대로 품질팀장 전용.
- 미결 #5 (2026-11-13 사용자, Phase 6에서 수행): `submit_edit_request`를 동작 변경 없이 `core/rules.py`로 옮긴다. 기존 테스트가 회귀망.
- 설명서는 `core/recordspec.py`(`core/records.py`는 삭제·잠금 규칙이라 건드리지 않음). core는 qms 모델을 import하지 않고 `'app.model'` 라벨만 쓴다.

## 범위

- `SPECS`: `qms.document`(하위 표: 개정 이력), `qms.documentrevision`(탭 초안/승인됨), `qms.gauge`(탭 사용/전체/사용 중지), `qms.qualification`(탭 유효/전체/만료).
- API: `/api/records/<label>/`(탭·q·page·`export=xlsx`), `<id>/`(칸·하위 표·오른쪽 열·관리 화면 주소), `<id>/history/`(최근 50건). 미등록 404, `view_` 없으면 403. `api/records/`는 `BASE_PATHS`에 두고 미들웨어가 label 인자로 모듈을 판정.
- `record_url`(core/relations.py)이 유일한 주소 기준: React 전용 화면 → 설명서 화면 → LOT은 추적 → 관리 화면. 검색·위젯·유사 건·메모·종합현황·타임라인·승인/요청 후 돌아가기가 모두 이것을 쓴다.
- 관리 화면 변경 페이지에 「새 화면으로」(`core/admin.py` `render_change_form`, `templates/admin/qms_change_form.html`).
- 프론트: `pages/records/RecordView.tsx`(RecordPage 재사용, 칸 링크는 /app/ 이면 라우터), `RecordList.tsx`(DataList, 열·탭은 첫 응답에서).

## 범위 밖

- 기록 화면에서 수정·저장·승인·요청(Phase 6). 지금 「수정」은 관리 화면으로 간다.
- 사이드바 메뉴를 새 화면으로 바꾸는 일(Phase 10 메뉴 정리).
