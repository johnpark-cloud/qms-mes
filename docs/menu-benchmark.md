# 메뉴 구성 레퍼런스 조사 (2026-10-29)

사이드바·전체 메뉴 재구성을 위해 국내외 QMS·MES 제품의 모듈 구성을 공개 자료로 조사한 결과다. 대부분 제품 소개·브로셔·고객 사례이며, 실제 화면의 메뉴 트리는 공개 자료로 확인하지 못했다.

## 제품별 모듈

| 제품 | 확인된 모듈 | 출처 |
| --- | --- | --- |
| SAP S/4HANA QM | 품질계획(검사계획·검사특성), 검사로트 관리·결과 입력·사용결정(합격/불합격/부분 합격 → 재고 상태 전환), 품질통지(발생한 문제·원인·조치), 품질 과제, 품질엔지니어 개요 화면 | erpresearch.com, learning.sap.com, SAP KBA |
| Siemens Opcenter Quality | 검사계획 관리, 생산 품질(검사 결과·이탈 처리), SPC, 불만·클레임 관리(고객·협력사·내부, 8D 자동 작성), 조치 관리, FMEA, APQP, 관리계획서·공정흐름도, 계측기 관리, 심사 관리(VDA 6.3), 협력사 평가·포털(PPA) | plm.sw.siemens.com, resources.sw.siemens.com, blogs.sw.siemens.com |
| ETQ(Octave) Reliance | 부적합, CAPA, 고객 불만, 심사, 문서 관리, 교육, 변경 관리, 협력사 품질(심사·시정조치·성적표), 자산·교정·보전 | etq.com, erpresearch.com |
| Rockwell Plex QMS | 관리계획서·디지털 체크시트, 초품·최종 검사, SPC(Cp/Cpk), 계측기 연동, CAPA(재고·LOT·출하 연계), 협력사 시정조치 포털, APQP·PPAP·FMEA | plex.rockwellautomation.com |
| DELMIA Apriso | Quality Planning(특성·규격·검사계획), Quality(검사 실행·처분), Containment(의심품 격리), Issue Management, Advanced SPC, Global Traceability(계보) | 3ds.com, andea.com |
| Critical Manufacturing MES | 품질 관리, 추적·계보(배치·LOT·시리얼), 자재 관리 | criticalmanufacturing.com |
| 미라콤 Nexplant MESplus QMS | SPC(Cp/Cpk), DMS(불량 분류·이미지 분석), YMS(수율·LOT 분석). 검사 구분은 IQC·PQC·OQC 용어를 씀 | miracom-inc.com, fajournal.com |
| 한솔PNS I'MFACTO | MES·QMS·WMS를 모듈로 분리. QMS 세부 메뉴는 공개 자료 없음 | venturesquare.net |
| 국내 중소기업용 MES 일반 | 기준정보관리(코드·조직·표준), 생산관리(계획·작업지시·실적·공정일보), 품질관리(공정검사·SPC), 설비관리(대장·보전 이력·치공구), 자재관리(입출고·재고·선입선출), 영업관리(수주·출하) | hankook-networks.com, wimir.co.kr, robotzine.co.kr |

## 공통 구조

1. 기준정보·품질계획: 품목·공정·라우팅, 검사기준·검사계획, 관리계획서, (FMEA·APQP)
2. 생산 실행: 작업지시, 실적, LOT 추적·계보, 출하
3. 검사: 수입·공정·출하·초품 검사, 판정(사용결정)
4. SPC: 대부분 별도 모듈로 둔다(미라콤, Opcenter, Apriso, Plex)
5. 부적합·격리: 부적합과 보류(격리)를 함께 둔다(Apriso Containment, SAP 사용결정의 보류 재고)
6. 조치: CAPA·시정조치
7. 고객 클레임: 고객·협력사·내부 불만을 한 흐름으로 다루고 8D를 만든다(Opcenter)
8. 협력사 품질: 평가·성적표, SCAR, PPAP/PPA
9. 계측기·교정
10. 심사: 계획·실행·보고
11. 문서·교육·변경관리
12. 분석·보고서

## 이 시스템과의 대응

| 공통 구조 | 이 시스템 | 없는 것 |
| --- | --- | --- |
| 기준정보·품질계획 | 품번, 공정, BOM, 라우팅, 검사기준, 관리계획서, 고객 규칙 | FMEA, APQP |
| 생산 실행 | 작업지시, 실적, LOT·계보, 출하, LOT 이력 | 자재 입출고·재고, 공정일보 |
| 검사 | 검사(수입·공정·출하 구분 있음), 초품 | |
| SPC | 관리도·Cpk, 경보 → 부적합 | |
| 부적합·격리 | 부적합, 보류 | |
| 조치 | CAPA | |
| 고객 클레임 | 고객 클레임(8D) | |
| 협력사 품질 | 협력사 성적표, SCAR, PPAP | |
| 계측기 | 계측기·교정 | |
| 심사 | 내부심사·지적사항, 심사 체크리스트·증적, 심사 자료 출력 | |
| 문서·교육·변경 | 문서, 검사원 자격, 4M 변경 | 교육 계획·이력 |
| 분석 | 품질 KPI | |
| (해당 없음) | 설비관리 | 설비 대장·보전 |

## 출처

- https://erpresearch.com/en-gb/sap-s4-hana-quality-management-qms
- https://learning.sap.com/learning-journeys/configuring-sap-s-4hana-quality-management/perfoming-usage-decisions
- https://plm.sw.siemens.com/en-US/opcenter/quality/concern-complaint-management
- https://plm.sw.siemens.com/en-US/opcenter/quality/failure-mode-effects-analysis-fmea
- https://resources.sw.siemens.com/en-US/case-study-georg-fischer-automotive
- https://resources.sw.siemens.com/sv-SE/case-study-schlote-germany/
- https://resources.sw.siemens.com/sv-SE/case-study-naf/
- https://blogs.sw.siemens.com/opcenter/?p=3088
- https://www.etq.com/app/uploads/2021/06/2020-academy-course-list-web.pdf
- https://erpresearch.com/erp-add-ons/healthcare/etq-reliance
- https://plex.rockwellautomation.com/en-us/products/quality-management-system.html
- https://plex.rockwellautomation.com/en-us/resources/10010-plex-q-m-s-brochure.html
- https://www.3ds.com/ja/products/delmia/apriso/quality-control
- https://www.andea.com/resources/blog/quality-management-in-delmia-apriso/
- https://www.criticalmanufacturing.com/wp-content/uploads/2025/03/Brochure-V11_Medical_EN_digital.pdf
- https://www.miracom-inc.com/common/index.do?jpath=%2Feng%2Fsolution%2Fqms
- https://www.miracom-inc.com/upload/userUpload/brochure/en/Nexplant%20MESplus%20QMS_EN.pdf
- https://www.fajournal.com/news/articleView.html?idxno=21440
- https://www.venturesquare.net/918159/
- https://www.hankook-networks.com/ko/business/smart-factory-mes.do
- https://wimir.co.kr/product/standard-mes
- https://robotzine.co.kr/entry/256469?locPos=2M5&ts=1621930835&page=6
