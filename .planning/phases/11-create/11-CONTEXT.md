# Phase 11 — 기록 화면에서 새로 만들기 (CONTEXT)

2026-11-16. Phase 10 뒤 남은 일: 작업지시·실적·출하·기준정보 등록이 관리 화면 추가 폼에만 있었다.

## 결정

- 설명서 `Spec.create`(칸 이름 튜플)에 있는 모델만 새로 만들기를 연다. 비어 있으면 지금처럼 관리 화면 추가 폼.
- 대상: 작업지시·작업 실적·출하·거래처·부서·번호 코드값·번호 규칙. 사용자 정의 칸·엑셀 양식·가져오기 설정은 대상·JSON·파일 칸이라 관리 화면에 둔다. Phase 1~9 기록(문서·부적합 등)은 이번 범위 밖.
- API: `GET /api/records/<label>/new/`(입력 칸), `POST /api/records/<label>/`(만들기). `add_` 권한. 외래키는 선택지(폼 queryset, 최대 500개, limit_choices_to 반영).
- 저장은 modelform full_clean → `rules.save_with_lock`. 보류 LOT 실적·출하 차단, 양품+불량 ≤ 투입, 라우팅 순서는 모델 clean/save가 그대로 막는다(업무 규칙 변경 없음).
- 만든 사람: 기준정보 `created_by`, 작업 실적 `operator`가 비어 있으면 요청 사용자로 넣는다(관리 화면 MasterAdmin과 같음).
- 화면: `/app/r/<app>/<model>/new`. 목록의 「새로 만들기」가 설명서에 create가 있으면 이 화면으로, 없으면 관리 화면 추가 폼으로 간다.
