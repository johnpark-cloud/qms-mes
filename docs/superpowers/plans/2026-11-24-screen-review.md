# 화면 전수 검토 진행표 (W9, 2026-11-24)

기준: 「보기 불편하다」「한 눈에 안 들어온다」「조악하다」「전문적이지 못하다」, 옛 관리 화면이 뜨는 곳.
방법: `python scripts\screen_tour.py [캡처 폴더]` — 임시 DB + 예시 데이터로 메뉴·허브·상세·양식지·기록(목록·기록·새로 만들기·양식지) 132개 화면을 열어 캡처하고 `tour.json`에 옛 링크·콘솔 오류를 남긴다. 운영 DB는 건드리지 않는다.

## 모든 화면에 걸친 수정

- 목록 도구줄: 검색·거르기는 왼쪽, 「총 N건」·「엑셀 받기」·「새로 만들기」는 오른쪽 버튼으로.
- 양식지 머리줄: 「← 돌아가기」, 「.xlsx 받기」, 「인쇄」 버튼.
- 기록 화면: 필수 항목 `*` 표시, 관계·이력 칸이 없으면 본문을 넓게, 긴 값·여러 줄 값은 한 줄 전체.
- 표시 값: 소수 끝 0 없애고 천 단위 쉼표(2000.000 → 2,000), 사람은 아이디 대신 이름, 측정값 「특성 = 값」, 보류 「LOT 보류 (부적합 번호)」, 관계 묶음 이름을 화면 이름으로.
- 로고가 없을 때 매 화면 `/brand/logo` 404 요청을 내지 않음. 「최근 본 기록」 문구.
- 설정 기록(가져오기 설정)은 관계 칸 없이 이력만.
- 새로 만들 수 없는 기록(부적합·보류·PPAP 요소)은 빈 404 대신 어디서 만드는지 안내.

## 남긴 것

| 항목 | 이유 |
| --- | --- |
| 연차·급여 화면의 급여명세 「관리 화면」 링크 | 급여 본인만 열람 규칙·권한에 닿음 — 사용자 승인 후 |
| 기준정보 허브·메뉴의 「관리자 화면」(`/admin/`) | 시스템 관리자용으로 의도해 남김 |
| 사용자 화면 역할 체크에 「관리자」 없음 | 권한 변경(보안) — 사용자 승인 후 |
| 4M 변경 구분 선택지 일부 영문 | 선택지 값 변경은 기존 행을 바꾸는 마이그레이션 — 사용자 승인 후 |
| 허브·종합현황 마지막 줄 카드 하나만 남는 배치 | 카드 수에 따라 달라지는 사소한 배치 |

## 화면별 결과 (132개)

| # | 화면 | 주소 | 결과 |
| --- | --- | --- | --- |
| 1 | 허브 통합 업무 홈 | `/app/hub/통합 업무 홈` | 확인 |
| 2 | 메뉴 통합 업무 홈 > 내 할 일 | `/app/todo` | 확인 |
| 3 | 메뉴 통합 업무 홈 > 공장 종합현황 | `/app/overview` | 확인 |
| 4 | 메뉴 통합 업무 홈 > 미분류 메모 | `/app/memos` | 확인 |
| 5 | 메뉴 통합 업무 홈 > 연차·급여 | `/app/me` | 보류 — 급여명세 「관리 화면」 링크는 급여 본인만 열람 규칙·권한에 닿아 승인 필요 |
| 6 | 허브 생산관리 (MES) | `/app/hub/생산관리 (MES)` | 확인 |
| 7 | 메뉴 생산관리 (MES) > 작업지시 | `/app/r/core/workorder` | 확인 |
| 8 | 메뉴 생산관리 (MES) > 생산실적 | `/app/r/core/workresult` | 확인 |
| 9 | 메뉴 생산관리 (MES) > LOT | `/app/r/core/lot` | 확인 |
| 10 | 메뉴 생산관리 (MES) > LOT 추적 | `/app/trace` | 고침 — 빈 화면에 안내 문구 |
| 11 | 메뉴 생산관리 (MES) > 출하 | `/app/r/core/shipment` | 확인 |
| 12 | 허브 품질관리 (QMS) | `/app/hub/품질관리 (QMS)` | 확인 |
| 13 | 메뉴 품질관리 (QMS) > 검사 입력 | `/app/inspect` | 확인 |
| 14 | 메뉴 품질관리 (QMS) > 검사 실적 | `/app/inspections` | 확인 |
| 15 | 메뉴 품질관리 (QMS) > 계측기 관리 | `/app/r/qms/gauge` | 확인 |
| 16 | 메뉴 품질관리 (QMS) > 교정 이력 | `/app/r/qms/gaugecalibration` | 확인 |
| 17 | 메뉴 품질관리 (QMS) > 검사원 자격 | `/app/r/qms/qualification` | 확인 |
| 18 | 허브 품질보증 및 개선 | `/app/hub/품질보증 및 개선` | 확인 |
| 19 | 메뉴 품질보증 및 개선 > 부적합(NCR) | `/app/r/core/nonconformance` | 확인 |
| 20 | 메뉴 품질보증 및 개선 > 부적합 등록 | `/app/nc-new` | 고침 — 영문 파일 칸 → 「사진 찍기·고르기」 버튼 |
| 21 | 메뉴 품질보증 및 개선 > 보류 | `/app/r/core/hold` | 확인 |
| 22 | 메뉴 품질보증 및 개선 > 시정조치(CAPA) | `/app/r/qms/capa` | 확인 |
| 23 | 메뉴 품질보증 및 개선 > 변경점 관리(4M) | `/app/r/qms/changerequest` | 확인 |
| 24 | 메뉴 품질보증 및 개선 > 문서 관리 | `/app/r/qms/document` | 확인 |
| 25 | 메뉴 품질보증 및 개선 > 심사 관리 | `/app/r/qms/internalaudit` | 확인 |
| 26 | 메뉴 품질보증 및 개선 > 체크리스트·증적 | `/app/r/qms/auditchecklist` | 확인 |
| 27 | 메뉴 품질보증 및 개선 > 심사 자료 출력 | `/app/audit-pack` | 확인 |
| 28 | 허브 고객 및 공급자 | `/app/hub/고객 및 공급자` | 확인 |
| 29 | 메뉴 고객 및 공급자 > 거래처 | `/app/r/core/partner` | 확인 |
| 30 | 메뉴 고객 및 공급자 > 프로젝트 | `/app/r/core/project` | 확인 |
| 31 | 메뉴 고객 및 공급자 > 고객 클레임(8D) | `/app/r/qms/customerclaim` | 확인 |
| 32 | 메뉴 고객 및 공급자 > 고객사별 8D 기한 | `/app/customer-rules` | 확인 |
| 33 | 메뉴 고객 및 공급자 > 공급자 평가 | `/app/suppliers` | 확인 |
| 34 | 메뉴 고객 및 공급자 > 공급자 시정조치(SCAR) | `/app/r/qms/scar` | 확인 |
| 35 | 메뉴 고객 및 공급자 > PPAP | `/app/r/qms/ppapsubmission` | 확인 |
| 36 | 허브 분석 및 보고서 | `/app/hub/분석 및 보고서` | 확인 |
| 37 | 메뉴 분석 및 보고서 > 품질 KPI | `/app/kpi` | 확인 |
| 38 | 메뉴 분석 및 보고서 > 엑셀 보고서 양식 | `/app/r/qms/exceltemplate` | 확인 |
| 39 | 허브 기준정보 및 시스템 관리 | `/app/hub/기준정보 및 시스템 관리` | 의도 — 「관리자 화면」 메뉴는 시스템 관리자용으로 남김 |
| 40 | 메뉴 기준정보 및 시스템 관리 > 품목·BOM·라우팅 | `/app/items` | 확인 |
| 41 | 메뉴 기준정보 및 시스템 관리 > 공정 | `/app/processes` | 확인 |
| 42 | 메뉴 기준정보 및 시스템 관리 > 검사기준서 | `/app/specs` | 확인 |
| 43 | 메뉴 기준정보 및 시스템 관리 > 관리계획서 | `/app/plans` | 확인 |
| 44 | 메뉴 기준정보 및 시스템 관리 > 채번 규칙 | `/app/r/core/numberrule` | 확인 |
| 45 | 메뉴 기준정보 및 시스템 관리 > 채번 코드값 | `/app/r/core/codevalue` | 확인 |
| 46 | 메뉴 기준정보 및 시스템 관리 > 엑셀 일괄 등록 | `/app/import` | 고침 — 영문 파일 칸 → 「파일 고르기」 버튼 |
| 47 | 메뉴 기준정보 및 시스템 관리 > 부서 | `/app/r/core/department` | 확인 |
| 48 | 메뉴 기준정보 및 시스템 관리 > 사용자 정의 필드 | `/app/r/core/fielddef` | 확인 |
| 49 | 메뉴 기준정보 및 시스템 관리 > 사용자·조직도 | `/app/users` | 확인 |
| 50 | 메뉴 기준정보 및 시스템 관리 > 감사 추적 | `/app/audit` | 확인 |
| 51 | 메뉴 기준정보 및 시스템 관리 > 모듈 설정 | `/app/modules` | 확인 |
| 52 | 메뉴 기준정보 및 시스템 관리 > 관리자 화면 | `/admin/` | 의도 — Django 관리자 화면(시스템 관리자 전용) |
| 53 | items 상세 | `/app/items/1` | 확인 |
| 54 | specs 상세 | `/app/specs/1` | 확인 |
| 55 | specs 양식지 | `/app/specs/1/print` | 확인 |
| 56 | plans 상세 | `/app/plans/1` | 확인 |
| 57 | plans 양식지 | `/app/plans/1/print` | 확인 |
| 58 | inspections 상세 | `/app/inspections/1` | 확인 |
| 59 | inspections 양식지 | `/app/inspections/1/print` | 확인 |
| 60 | spc 화면 | `/app/spc/1` | 고침 — 관리도가 카드 폭 전체를 씀 |
| 61 | nc 화면 | `/app/nc-mail/1` | 확인 |
| 62 | users 화면 | `/app/users/1` | 확인 |
| 63 | qms.document 기록 | `/app/r/qms/document/1` | 확인 |
| 64 | qms.document 새로 만들기 | `/app/r/qms/document/new` | 확인 |
| 65 | qms.documentrevision 목록 | `/app/r/qms/documentrevision` | 확인 |
| 66 | qms.documentrevision 기록 | `/app/r/qms/documentrevision/1` | 확인 |
| 67 | qms.documentrevision 새로 만들기 | `/app/r/qms/documentrevision/new` | 확인 |
| 68 | qms.documentrevision 양식지 | `/app/r/qms/documentrevision/1/print` | 확인 |
| 69 | qms.gauge 기록 | `/app/r/qms/gauge/1` | 확인 |
| 70 | qms.gauge 새로 만들기 | `/app/r/qms/gauge/new` | 확인 |
| 71 | qms.gaugecalibration 기록 | `/app/r/qms/gaugecalibration/1` | 확인 |
| 72 | qms.gaugecalibration 새로 만들기 | `/app/r/qms/gaugecalibration/new` | 확인 |
| 73 | qms.qualification 기록 | `/app/r/qms/qualification/1` | 확인 |
| 74 | qms.qualification 새로 만들기 | `/app/r/qms/qualification/new` | 확인 |
| 75 | core.lot 기록 | `/app/r/core/lot/1` | 확인 |
| 76 | core.lot 새로 만들기 | `/app/r/core/lot/new` | 확인 |
| 77 | core.nonconformance 기록 | `/app/r/core/nonconformance/1` | 확인 |
| 78 | core.nonconformance 새로 만들기 | `/app/r/core/nonconformance/new` | 고침 — 빈 404 대신 「부적합 등록으로」 안내 |
| 79 | core.hold 기록 | `/app/r/core/hold/1` | 확인 |
| 80 | core.hold 새로 만들기 | `/app/r/core/hold/new` | 고침 — 빈 404 대신 「보류는 부적합 등록으로 걸림」 안내 |
| 81 | qms.capa 기록 | `/app/r/qms/capa/1` | 확인 |
| 82 | qms.capa 새로 만들기 | `/app/r/qms/capa/new` | 확인 |
| 83 | qms.capa 양식지 | `/app/r/qms/capa/1/print` | 확인 |
| 84 | qms.customerclaim 기록 | `/app/r/qms/customerclaim/1` | 확인 |
| 85 | qms.customerclaim 새로 만들기 | `/app/r/qms/customerclaim/new` | 확인 |
| 86 | qms.customerclaim 양식지 | `/app/r/qms/customerclaim/1/print` | 확인 |
| 87 | qms.customerrule 목록 | `/app/r/qms/customerrule` | 확인 |
| 88 | qms.customerrule 기록 | `/app/r/qms/customerrule/1` | 확인 |
| 89 | qms.customerrule 새로 만들기 | `/app/r/qms/customerrule/new` | 확인 |
| 90 | qms.scar 기록 | `/app/r/qms/scar/1` | 확인 |
| 91 | qms.scar 새로 만들기 | `/app/r/qms/scar/new` | 확인 |
| 92 | qms.scar 양식지 | `/app/r/qms/scar/1/print` | 확인 |
| 93 | qms.changerequest 기록 | `/app/r/qms/changerequest/1` | 확인 |
| 94 | qms.changerequest 새로 만들기 | `/app/r/qms/changerequest/new` | 확인 |
| 95 | qms.changerequest 양식지 | `/app/r/qms/changerequest/1/print` | 확인 |
| 96 | qms.internalaudit 기록 | `/app/r/qms/internalaudit/1` | 확인 |
| 97 | qms.internalaudit 새로 만들기 | `/app/r/qms/internalaudit/new` | 확인 |
| 98 | qms.internalaudit 양식지 | `/app/r/qms/internalaudit/1/print` | 확인 |
| 99 | qms.auditfinding 목록 | `/app/r/qms/auditfinding` | 확인 |
| 100 | qms.auditfinding 기록 | `/app/r/qms/auditfinding/1` | 확인 |
| 101 | qms.auditfinding 새로 만들기 | `/app/r/qms/auditfinding/new` | 확인 |
| 102 | qms.auditchecklist 기록 | `/app/r/qms/auditchecklist/1` | 확인 |
| 103 | qms.auditchecklist 새로 만들기 | `/app/r/qms/auditchecklist/new` | 확인 |
| 104 | qms.audititem 목록 | `/app/r/qms/audititem` | 확인 |
| 105 | qms.audititem 기록 | `/app/r/qms/audititem/1` | 확인 |
| 106 | qms.audititem 새로 만들기 | `/app/r/qms/audititem/new` | 확인 |
| 107 | qms.ppapsubmission 기록 | `/app/r/qms/ppapsubmission/1` | 확인 |
| 108 | qms.ppapsubmission 새로 만들기 | `/app/r/qms/ppapsubmission/new` | 확인 |
| 109 | qms.ppapelement 목록 | `/app/r/qms/ppapelement` | 확인 |
| 110 | qms.ppapelement 기록 | `/app/r/qms/ppapelement/1` | 확인 |
| 111 | qms.ppapelement 새로 만들기 | `/app/r/qms/ppapelement/new` | 고침 — 빈 404 대신 「PPAP 제출을 만들면 생김」 안내 |
| 112 | core.workorder 기록 | `/app/r/core/workorder/1` | 확인 |
| 113 | core.workorder 새로 만들기 | `/app/r/core/workorder/new` | 확인 |
| 114 | core.workresult 기록 | `/app/r/core/workresult/1` | 확인 |
| 115 | core.workresult 새로 만들기 | `/app/r/core/workresult/new` | 확인 |
| 116 | core.shipment 기록 | `/app/r/core/shipment/1` | 확인 |
| 117 | core.shipment 새로 만들기 | `/app/r/core/shipment/new` | 확인 |
| 118 | core.partner 기록 | `/app/r/core/partner/1` | 확인 |
| 119 | core.partner 새로 만들기 | `/app/r/core/partner/new` | 확인 |
| 120 | core.project 기록 | `/app/r/core/project/1` | 확인 |
| 121 | core.project 새로 만들기 | `/app/r/core/project/new` | 확인 |
| 122 | core.department 기록 | `/app/r/core/department/1` | 확인 |
| 123 | core.department 새로 만들기 | `/app/r/core/department/new` | 확인 |
| 124 | core.codevalue 기록 | `/app/r/core/codevalue/1` | 확인 |
| 125 | core.codevalue 새로 만들기 | `/app/r/core/codevalue/new` | 확인 |
| 126 | core.numberrule 기록 | `/app/r/core/numberrule/1` | 확인 |
| 127 | core.numberrule 새로 만들기 | `/app/r/core/numberrule/new` | 확인 |
| 128 | core.fielddef 기록 | `/app/r/core/fielddef/1` | 확인 |
| 129 | core.fielddef 새로 만들기 | `/app/r/core/fielddef/new` | 확인 |
| 130 | core.importprofile 목록 | `/app/r/core/importprofile` | 확인 |
| 131 | core.importprofile 기록 | `/app/r/core/importprofile/1` | 고침 — 관계 404 없앰, 매핑을 「열: 항목」 줄로 |
| 132 | core.importprofile 새로 만들기 | `/app/r/core/importprofile/new` | 확인 |
