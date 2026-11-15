# Phase 10 (B6) — 작업지시·실적·출하·기준정보 기록 화면과 메뉴 정리: 결정 메모

요구: REC-11. 방식은 Phase 5~9와 같다(설명서 `core/recordspec.py` 등록 → records API·기록 화면·`record_url`).

## 결정

- 설명서 추가: `core.workorder`(실적·LOT 하위 표), `core.workresult`, `core.shipment`, `core.partner`(인증서 하위 표),
  `core.department`, `core.codevalue`, `core.numberrule`, `core.fielddef`, `qms.exceltemplate`, `core.importprofile`.
- **인터록은 그대로**: LOT·작업지시·공정 같은 외래키는 기록 화면에서 못 고친다(범용 저장이 외래키를 받지 않음).
  새 작업지시·실적·출하 등록은 지금처럼 관리 화면 추가 폼이고, 보류 LOT 차단은 모델 `clean`/`save`가 같은 문구로 막는다.
  수량 정정 저장도 모델 `clean`(양품+불량 ≤ 투입, 이전 공정 실적)을 거친다.
- **메뉴**: `core/nav.py` NAV는 관리 화면 주소(url 이름)를 그대로 둔다 — 전체 메뉴 묶음(`core/admin.py`)과 모듈 판정이 이 주소를 쓴다.
  화면에 내보낼 때 `app_href`가 새 화면 주소로 바꾼다: 설명서가 있는 관리 목록 → `/app/r/<app>/<model>`,
  품번·공정·검사기준·관리계획서·클레임 설정·검사 목록 → 기존 React 화면. me API(React 메뉴)와 기존 화면 사이드바가 함께 쓴다.
  기존 화면 사이드바의 '현재 메뉴' 표시는 원래 관리 주소로 계속 판정한다.
- 사용자·모듈 켜기/끄기·전체 메뉴(관리 화면)는 시스템 관리자에게만 메뉴로 보인다. 관리 화면 주소·권한은 바꾸지 않는다.
- 가져오기 설정은 메뉴를 늘리지 않는다(엑셀 일괄 등록 화면이 쓴다). 기록 화면 주소로 열린다.
- 범위 밖: 새 기록 만들기 화면(추가는 관리 화면), React `MOVED` 표 정리(서버가 바꿔 보내므로 남아도 무해).
