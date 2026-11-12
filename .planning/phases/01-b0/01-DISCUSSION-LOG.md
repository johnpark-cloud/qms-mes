# Phase 1: 기록 화면 공통 틀과 검사 상세 (B0) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-11-13
**Phase:** 01-b0
**Mode:** --auto (모든 회색 지대 선택, 권장안 자동 채택)
**Areas discussed:** 공통 틀, 버튼, 검사 상세 API, 숫자 표시, 판정 띠, 기존 동작 유지

---

## 공통 틀

| Option | Description | Selected |
|--------|-------------|----------|
| RecordPage 겉모양 교체, props 유지 | 호출 4곳 그대로, 4화면 동시에 새 모양 | ✓ |
| 새 RecordShell만 만들고 화면별 이전 | 화면마다 따로 고침 | |

[auto] 공통 틀 — Q: "RecordPage를 어떻게 바꿀까?" → Selected: "겉모양 교체, props 유지" (recommended default, 승인된 계획 B0)

## 버튼

| Option | Description | Selected |
|--------|-------------|----------|
| 주요 1 · 이력 · ⋯(엑셀·양식·삭제) | 삭제 한 곳, 서버 권한 규칙 그대로 | ✓ |
| 기존 버튼 나열 유지 | 변경 없음 | |

[auto] 버튼 — Q: "버튼 배치?" → Selected: "주요 1 · 이력 · ⋯" (recommended default)

## 검사 상세 API

| Option | Description | Selected |
|--------|-------------|----------|
| 읽기 전용 키 추가, 기존 키 유지 | 호환 유지, 테스트 먼저 | ✓ |
| 응답 형식 재설계 | 기존 소비처 깨짐 | |

[auto] API — Q: "응답을 어떻게 넓힐까?" → Selected: "읽기 전용 키 추가" (recommended default)

## 숫자 표시

| Option | Description | Selected |
|--------|-------------|----------|
| 하한·상한 자릿수 기준 + 중앙값 회색 | 모델 변경 없음 | ✓ |
| 모델에 nominal·decimals 칸 추가 | 스키마 변경, v2 | |

[auto] 숫자 — Q: "자릿수·기준값?" → Selected: "하한·상한 기준 + 중앙값" (recommended default)

## 판정 띠

[auto] 판정 띠 — Q: "판정 표시?" → Selected: "28px/500, 토큰 색 + 글자" (recommended default, DESIGN.md Lead)

## 기존 동작 유지

[auto] 유지 — Q: "e2e 선택자·소급 추가·_finalize?" → Selected: "유지, 소급 추가·_finalize는 B2까지 관리 화면" (recommended default)

## Claude's Discretion

- 컴포넌트 파일 분리, CSS 클래스 이름, 위치 막대 구현, ⋯ 메뉴 순서, 검사기준·관리계획서 주요 버튼 선택.

## Deferred Ideas

- 삭제 → 무효 처리(V2-01), nominal·decimals 모델 칸(V2-02), records API·GenericRecordPage(B1), 편집·소급 추가 이전(B2).
