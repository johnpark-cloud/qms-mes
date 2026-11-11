# QMS·MES·ERP 상세 DB 칸 설계

- 작성일: 2026-11-11
- 상위 문서: `2026-11-11-data-foundation-design.md`. 단계 A~J는 상위 문서 7절과 같다.
- 화면 설계: `2026-11-11-ux-relations-design.md`
- 근거:
  - ISO 9001:2015, IATF 16949:2016, AS9100D, AS9102, ISO 10012의 일반 관행
  - 회사 계측기 대장 `KEN-SP-QC-07-01_설비_및_계측기_관리대장_v2.xlsx`의 계측기 시트(23열)와 교정이력 시트(8열)
- 상태: 초안이다. 단계마다 계획을 쓸 때 칸 이름과 필수 여부를 확정한다.
- 조항 번호는 규격 원문으로 확인해야 한다.

## 0. 읽는 법

**형**
| 표기 | 뜻 |
|---|---|
| 글(n) | 최대 n자 글 |
| 긴글 | 길이 제한 없는 글 |
| 정수 | 정수 |
| 수(p,s) | 소수. 수량은 수(14,3), 금액은 수(14,2) |
| 날짜 / 일시 | 날짜 / 날짜와 시각 |
| 예/아니오 | 참·거짓 |
| 선택[...] | 정해진 값 중 하나. 화면에는 한국어로 보인다 |
| 파일 | 첨부 파일 |
| JSON | 구조 데이터 |
| →모델 | 다른 표 한 행을 가리킨다(외래키) |
| ⇉모델 | 다른 표 여러 행을 가리킨다(다대다) |
| 계산 | DB에 저장하지 않고 조회할 때 계산한다 |

**구분**
| 표기 | 뜻 |
|---|---|
| **필** | 필수. 새로 저장하거나 고칠 때 `clean()`에서 강제한다 |
| 권 | 권장. 비어 있으면 "데이터 상태"(UX 문서 U7)에 표시한다 |
| 조 | 조건부 필수. 조건은 설명 칸에 적는다 |
| 선 | 선택 |

**기존 표에 칸을 더할 때**
- 새 칸은 모두 비어도 되는 칸으로 추가한다. 기존 행은 바뀌지 않는다.
- 필수 강제는 새로 저장하는 행부터 적용한다.
- 표 제목의 "(기존 +)"는 기존 표에 칸을 더한다는 뜻이다. 기존 칸은 적지 않는다.

## 1. 모든 새 표에 공통으로 넣는 칸

| 칸 | 형 | 설명 |
|---|---|---|
| `id` | 정수 | 자동 |
| `created_at` / `created_by` | 일시 / →User | 자동. 만든 때와 만든 사람 |
| `updated_at` | 일시 | 자동 |
| `history` | — | `HistoricalRecords()`. 변경 이력 |

**기준정보 표에만 더하는 칸**
| 칸 | 형 | 설명 |
|---|---|---|
| `active` | 예/아니오 | 사용 여부. 기준정보 행은 지우지 않고 사용 중지한다 |
| `note` | 긴글 | 비고 |
| `extra` | JSON | 사용자 정의 칸 값. 2절 |

**행이 길어지는 업무 기록의 하위 항목**
- 하위 표를 따로 둔다. 예: 발주 → 발주 품목.
- 같은 칸을 `_1`, `_2`처럼 늘리지 않는다.

**첨부·메모·이력**
- 첨부는 공통 `Attachment`에, 메모는 기존 `Memo`에, 신청 이력은 기존 `RevisionLog`에 둔다.
- 셋 다 일반 연결(`content_type` + `object_id`)로 어느 기록에나 붙는다. 그래서 각 표에 따로 칸을 두지 않는다.

## 2. 확장: 사용자 정의 칸

회사가 개발자 없이 칸을 더할 수 있게 한다. 예: 거래처의 "주거래 은행", 설비의 "전력 용량".

**`FieldDef` 사용자 정의 칸 (A단계, core)**
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| target | →ContentType | **필** | 대상 표. `extra` 칸이 있는 표만 고를 수 있다 |
| key | 글(40) | **필** | 영문 키. 대상 안에서 고유하다. 저장 뒤 바꿀 수 없다 |
| label | 글(60) | **필** | 화면 이름 |
| kind | 선택[글, 수, 날짜, 예/아니오, 선택, 거래처, 직원] | **필** | 값의 종류 |
| choices | JSON | 조 | 종류가 "선택"일 때 필수 |
| required | 예/아니오 | **필** | 기본값은 아니오 |
| sort | 정수 | 선 | 화면 순서 |
| active | 예/아니오 | **필** | |

**값 저장과 검사**
- 값은 대상 행의 `extra` JSON에 `{key: 값}`으로 저장한다.
- 대상 모델의 `clean()`이 `FieldDef`에 맞춰 종류와 필수를 검사한다.

**쓰는 곳**
- 목록 필터, 엑셀 내보내기·일괄 등록, 상세 화면 "상세" 탭에 자동으로 나온다.

**한계**
- 업무 규칙(인터록·판정)에 쓰는 값은 사용자 정의 칸에 두지 않는다. 그런 값은 정식 칸으로 만든다.
- shortcut: JSON 칸은 DB 색인이 없다. 수만 행에서 사용자 정의 칸으로 필터하면 느려진다. 그때 정식 칸으로 옮긴다.

## 3. A단계 — 기준정보 (core)

### 3.1 `Site` 사업장
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| code | 글(10) | **필** | 고유 |
| name | 글(60) | **필** | |
| address | 글(200) | 권 | |
| phone | 글(30) | 선 | |

### 3.2 `Department` 부서
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| code | 글(10) | **필** | 고유 |
| name | 글(60) | **필** | |
| site | →Site | **필** | |
| parent | →Department | 선 | 상위 부서. 순환 금지 |
| manager | →User | 권 | 부서장 |
| doc_code | →CodeValue(부서) | 조 | 문서 번호를 매기는 부서만 |
| sort | 정수 | 선 | |

### 3.3 `Employee` 직원
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| user | →User (1:1) | **필** | 로그인 계정 |
| emp_no | 글(20) | 권 | 사번. 값이 있으면 고유 |
| department | →Department | **필** | |
| position | 글(30) | 권 | 직위 |
| job | 글(60) | 선 | 직무 |
| phone_ext / mobile | 글(30) | 선 | 내선 / 휴대전화 |
| signature | 파일 | 선 | 출력물 서명 이미지 |

입사일은 `personal.LeaveProfile.hired_on`에 있으므로 두지 않는다.

### 3.4 `Partner` 거래처
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| code | 글(20) | **필** | 고유 |
| name | 글(100) | **필** | 상호 |
| name_en | 글(100) | 선 | 영문 상호 |
| is_supplier / is_customer / is_outsource / is_calibrator | 예/아니오 | **필** | 구분. 하나 이상 참이어야 한다 |
| biz_no | 글(12) | 권 | 사업자등록번호. 값이 있으면 고유 |
| ceo | 글(30) | 선 | 대표자 |
| address | 글(200) | 권 | |
| phone / email | 글(30) / 글(100) | 권 / 선 | |
| status | 선택[신규 평가, 승인, 조건부 승인, 거래 중지] | **필** | 기본값은 신규 평가. "승인"으로 바꾸는 것은 품질팀장·관리자만 한다 |
| grade | 선택[A, B, C, D] | 선 | 최근 평가 등급. D단계 평가가 갱신한다 |
| evaluated_on | 날짜 | 선 | D단계 평가가 갱신한다 |
| payment_terms | 글(60) | 선 | ERP 결제 조건 |
| currency | 글(3) | 선 | 기본값 KRW |
| customer_code_prefix | →CodeValue(고객사) | 조 | 고객사이면서 품번 번호에 쓰는 경우 |

### 3.5 `PartnerContact` 거래처 담당자
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| partner | →Partner | **필** | |
| name | 글(30) | **필** | |
| role | 선택[영업, 품질, 구매, 기술, 기타] | **필** | |
| phone / email | 글 | 권 | |
| primary | 예/아니오 | 선 | 같은 역할 안에서 대표 담당자 |

### 3.6 `PartnerCertificate` 거래처 인증
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| partner | →Partner | **필** | |
| standard | 선택[ISO 9001, IATF 16949, AS9100, ISO 17025, ISO 14001, NADCAP, 기타] | **필** | |
| cert_no | 글(60) | 권 | |
| issuer | 글(100) | 선 | 인증기관 |
| scope | 글(200) | 선 | |
| valid_until | 날짜 | **필** | 30일 전부터 "내 할 일"에 나온다 |
| file | 파일 | 권 | 인증서 |

### 3.7 `Attachment` 공통 첨부
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| content_type / object_id | 일반 연결 | **필** | 대상 기록 |
| kind | 선택[사진, 사양서, 도면, 매뉴얼, 구매서류, 성적서, 보증서, 인증서, 기타] | **필** | |
| file | 파일 | **필** | 저장 위치는 `data/` 아래 |
| title | 글(100) | 선 | 기본값은 파일 이름 |
| uploaded_by / uploaded_at | 자동 | | |

- 열람·내려받기는 대상 기록을 볼 수 있는 사람만 한다. 서버 뷰에서 검사한다.
- `personal` 앱 기록에는 붙일 수 없다. `Evidence`와 같은 규칙이다.

### 3.8 기존 표의 연결 칸 (정제 대상)
| 표 | 새 칸 | 가리키는 대상 | 정제 출처 |
|---|---|---|---|
| Lot | partner | →Partner(협력사) | `supplier` |
| Scar | partner | →Partner(협력사) | `supplier` |
| Shipment | partner | →Partner(고객사) | `customer` |
| CustomerRule | partner | →Partner(고객사) | `customer` |
| CustomerClaim | partner | →Partner(고객사) | `customer` |
| PpapSubmission | partner | →Partner(고객사) | `customer` |
| InternalAudit | auditee_dept | →Department | `auditee` |
| InternalAudit | auditor_user | →User | `auditor`. 외부 심사원이면 글자만 둔다 |

## 4. B단계 — 문서 체계 (qms)

### 4.1 `Document` 문서 (기존 +)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| level | 선택[1 매뉴얼, 2 절차서, 3 지침서, 4 양식, 외부 문서] | **필** | 기존 행에는 데이터 마이그레이션 없이 빈 값을 허용한다 |
| parent | →Document | 권 | 상위 문서. 예: 절차서 → 매뉴얼. 순환 금지 |
| owner_dept | →Department | **필** | 소관 부서 |
| owner | →User | 권 | 문서 담당자 |
| status | 선택[작성 중, 시행, 개정 중, 폐기] | **필** | 첫 개정을 승인하면 시행 |
| clauses | ⇉Clause | 권 | 관련 규격 조항(C단계) |
| processes | ⇉Process | 선 | 관련 공정. 작업표준 연결 |
| items | ⇉Item | 선 | 관련 품번. 품번별 지침서 |
| review_months | 정수 | **필** | 정기 검토 주기. 기본값 12 |
| next_review_on | 날짜 | 계산 | 최근 시행일 + 주기. 30일 전부터 "내 할 일" |
| retention_years | 정수 | 조 | 양식이면 필수. 그 양식으로 만든 기록의 보존 연한 |
| issuer / ext_version | 글(100) / 글(30) | 조 | 외부 문서면 필수. 발행처와 판번 |
| obsoleted_on | 날짜 | 조 | 폐기 상태면 필수 |
| doc_type | (기존) | | 글자 칸은 그대로 둔다. level과 함께 쓴다 |

### 4.2 `DocumentRevision` 문서 개정 (기존 +)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| effective_on | 날짜 | **필** | 시행일. 승인일 이후여야 한다 |
| reviewed_by / reviewed_at | →User / 일시 | 권 | 검토자. 승인자와 다른 사람 |
| summary | 긴글 | **필** | 개정 내용. 기존 `change_note`와 같은 뜻이면 그 칸을 쓴다 |
| source_file | 파일 | 선 | 원본(docx 등). 기존 `file`은 배포본(PDF) |
| read_required | 예/아니오 | **필** | 배포 대상자의 읽음 확인이 필요한지 |

### 4.3 `DocumentDistribution` 배포
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| revision | →DocumentRevision | **필** | |
| department / user | →Department / →User | 조 | 둘 중 하나는 필수 |
| copy_no | 글(10) | 선 | 종이 관리본 번호 |
| distributed_at | 일시 | 자동 | |
| withdrawn_at | 일시 | 조 | 다음 개정이 시행되면 회수 표시 |

### 4.4 `DocumentRead` 읽음 확인
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| revision | →DocumentRevision | **필** | |
| user | →User | **필** | revision과 함께 고유 |
| read_at | 일시 | 자동 | 본인만 기록한다 |

### 4.5 `RetentionRule` 기록 보존 규칙
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| target | →ContentType | **필** | 기록 종류. 예: 검사, 부적합 |
| years | 정수 | **필** | 보존 연한 |
| basis | 글(200) | 권 | 근거. 예: 고객 CSR, IATF 7.5.3.2.1 |
| form | →Document(양식) | 선 | |
| disposal | 선택[보관 계속, 폐기 검토] | **필** | 연한이 지나도 자동 삭제하지 않는다. 목록에만 표시한다 |

## 5. C단계 — 규격·심사 대응 (qms)

### 5.1 `Standard` 규격
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| code | 글(30) | **필** | 예: ISO9001:2015, IATF16949:2016, AS9100D, CSR-<고객> |
| name | 글(100) | **필** | |
| kind | 선택[인증 규격, 고객 요구사항(CSR), 법규, 내부] | **필** | |
| partner | →Partner | 조 | CSR이면 필수 |
| edition_date | 날짜 | 선 | |

### 5.2 `Clause` 조항
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| standard | →Standard | **필** | |
| number | 글(20) | **필** | 예: 8.5.1.3. standard와 함께 고유 |
| title | 글(200) | **필** | |
| parent | →Clause | 선 | 상위 조항 |
| summary | 긴글 | 선 | 회사가 정리한 요구 요약. 규격 원문 전체는 넣지 않는다(저작권) |
| applicable | 예/아니오 | **필** | 적용 제외면 아니오 |
| exclusion_reason | 긴글 | 조 | 적용 제외면 필수 |
| owner_dept | →Department | 권 | 대응 책임 부서 |
| sort | 정수 | 선 | |

### 5.3 조항 매트릭스 (기존 표 연결)
| 표 | 새 칸 | 설명 |
|---|---|---|
| Document | clauses ⇉Clause | 4.1. 조항 → 문서 |
| AuditItem | clause_ref →Clause | 선. 기존 `clause` 글자 칸은 그대로 둔다. 조항 → 체크리스트 항목 |
| Evidence | (변경 없음) | 체크리스트 항목 → 문서·기록. 기존 그대로 |
| AuditFinding | clause_ref →Clause | 선. 조항 → 지적사항 |

- **매트릭스 계산:** 조항마다 연결 문서 수, 최근 12개월 증적 수, 열린 지적 수를 센다.
- **표시 상태:**
  - 빈칸: 문서 0건
  - 근거 부족: 증적 0건
  - 지적 있음: 열린 지적이 있음
  - 충족: 위 셋에 해당하지 않음

### 5.4 `ExternalAudit` 외부심사
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| number | 글(30) | **필** | 자동 번호 |
| kind | 선택[최초 인증, 사후, 갱신, 고객 심사, 공정 심사(고객), 특별] | **필** | |
| standards | ⇉Standard | **필** | |
| body | →Partner / 글(100) | **필** | 인증기관 또는 고객 |
| lead_auditor | 글(60) | 권 | |
| planned_from / planned_to | 날짜 | **필** | |
| performed_from / performed_to | 날짜 | 조 | 종료할 때 필수 |
| scope | 긴글 | 권 | |
| result | 선택[권고, 조건부 권고, 불권고, 해당 없음] | 조 | 종료할 때 필수 |
| report | 파일 | 권 | |
| closed_at | 일시 | 선 | 열린 지적이 있으면 종료할 수 없다 |

### 5.5 `AuditFinding` 심사 지적 (기존 +)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| external_audit | →ExternalAudit | 조 | 기존 `audit`(내부심사)와 둘 중 정확히 하나 |
| clause_ref | →Clause | 권 | |
| due_date | 날짜 | **필** | 새 지적부터 강제 |
| status | 계산 | | CAPA 종료 여부로 정한다. 열림 / 조치 중 / 종료 |

### 5.6 `Certificate` 회사 인증서
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| standard | →Standard | **필** | |
| body | →Partner | **필** | |
| cert_no | 글(60) | **필** | |
| site | →Site | 권 | |
| scope | 긴글 | 권 | |
| issued_on / valid_until | 날짜 | **필** | 만료 90일 전부터 "내 할 일" |
| file | 파일 | 권 | |

### 5.7 심사 증적 묶음 (표 없음)
- 조항 범위와 기간을 고르면 다음을 한 묶음으로 만든다.
  - 매트릭스 표(.xlsx)
  - 연결 문서의 시행 개정 파일
  - 증적 기록의 문서 출력 모음
- 기존 P6 문서 구조를 쓴다. 파일은 zip 하나로 내려준다. zip은 표준 라이브러리 `zipfile`이다.

## 6. D단계 — 공급자·입고·수입검사

### 6.1 `ApprovedSource` 승인 공급처
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| partner | →Partner | **필** | 협력사·외주가공만 |
| item | →Item | 조 | item과 process 중 하나는 필수 |
| process | →Process | 조 | 외주 특수공정 승인이면 필수 |
| status | 선택[승인, 조건부, 중지] | **필** | |
| approved_on | 날짜 | 권 | |
| basis | 선택[PPAP, FAI, 초품, 감사, 고객 지정, 기타] | 권 | |
| customer_directed | 예/아니오 | 선 | 고객 지정 공급처(IATF 8.4.1.3) |
| valid_until | 날짜 | 선 | |

### 6.2 `SupplierEvaluation` 공급자 평가
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| partner | →Partner | **필** | |
| period_from / period_to | 날짜 | **필** | |
| received_qty / rejected_qty | 수(14,3) | 계산 | 입고와 수입검사에서 센다 |
| ppm | 수 | 계산 | |
| otd_rate | 수(5,2) | 계산 | 발주 납기 대비 입고 |
| quality_score / delivery_score / response_score / system_score | 정수 | **필** | 각 0~100 |
| total / grade | 정수 / 선택[A, B, C, D] | 계산 | 가중치는 설정값으로 둔다 |
| evaluator | →User | **필** | |
| approved_by / approved_at | 승인 서명 | 권 | 승인하면 거래처 `grade`와 `evaluated_on`을 갱신한다 |
| comment | 긴글 | 선 | |

### 6.3 `SupplierAudit` 공급자 감사
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| partner | →Partner | **필** | |
| kind | 선택[시스템, 공정, 제품, 특수공정] | **필** | |
| performed_on | 날짜 | **필** | |
| auditor | →User | **필** | |
| score | 정수 | 선 | |
| result | 선택[적합, 조건부, 부적합] | **필** | |
| findings | 긴글 | 권 | 조치가 필요하면 기존 SCAR로 연결한다 |
| report | 파일 | 권 | |

### 6.4 `FlowDown` 하향 전개 요구 (AS 8.4.3)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| code | 글(20) | **필** | |
| title | 글(100) | **필** | 예: 위조품 방지, 기록 보존 10년, KC 관리, 변경 사전 통보, 고객 출입권 |
| text | 긴글 | **필** | 발주서에 찍히는 문구 |
| clause | →Clause | 선 | |
| default_for | 선택[전체, 항공 품번만, 지정] | **필** | |

발주(9.3)에 ⇉FlowDown으로 붙는다.

### 6.5 `Lot` LOT (기존 +) — 입고 LOT 칸
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| partner | →Partner | 조 | 구매품이면 필수 |
| po_line | →PurchaseOrderLine | 선 | I단계 |
| delivery_note_no | 글(40) | 권 | 납품서 번호 |
| received_on | 날짜 | 조 | 구매품이면 필수 |
| supplier_lot | 글(60) | 권 | 협력사 LOT |
| mfg_date / expiry_date | 날짜 | 선 / 조 | 유효기한은 품번에 `shelf_life_days`가 있으면 필수 |
| coc_received | 예/아니오 | 권 | 적합성 증명서(CoC) 받음 |
| received_by | →User | 자동 | |
| location | →Location | 선 | I단계 |

### 6.6 `Inspection` 검사 (기존 +) — 수입·공정·출하 공통
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| lot_size | 수(14,3) | 권 | 기본값은 LOT 수량 |
| sample_size | 정수 | 권 | 샘플링 기준으로 미리 채운다 |
| inspection_level | 선택[보통, 까다로운, 수월한, 전수] | 선 | |
| aql | 글(10) | 선 | |
| accepted_qty / rejected_qty | 수(14,3) | 권 | 불합격 수량은 부적합 자동 등록에 넘긴다 |
| coc_checked | 예/아니오 | 조 | 수입검사이고 품번이 CoC 요구일 때 필수 |
| counterfeit_check | →CounterfeitCheck | 조 | 항공 품번 수입검사면 필수 |
| comment | 긴글 | 선 | |
| reviewed_by / reviewed_at | →User / 일시 | 권 | 검토자 |

판정 후 수정 불가 규칙은 새 칸에도 똑같이 적용한다.

### 6.7 `CounterfeitCheck` 위조품 방지 확인 (AS 8.1.4)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| lot | →Lot | **필** | |
| source_type | 선택[제조사 직접, 공인 대리점, 승인 공급처, 기타] | **필** | "기타"면 추가 검증이 필수 |
| traceability_docs | 예/아니오 | **필** | 제조사까지의 유통 서류 |
| visual_ok / marking_ok / package_ok | 예/아니오 | **필** | |
| extra_test | 긴글 | 조 | 출처가 "기타"면 필수 |
| suspect | 예/아니오 | **필** | 의심이면 부적합 자동 등록과 LOT 보류. 기존 인터록 경로를 쓴다 |
| checked_by / checked_at | 자동 | | |

## 7. E단계 — 계측기 (qms)

### 7.1 `Gauge` 계측기 (기존 +) — 회사 대장의 계측기 시트 23열
| 대장 열 | 칸 | 형 | 구분 | 설명 |
|---|---|---|---|---|
| 관리번호 | number | (기존) | **필** | |
| 계측기명 | name | (기존) | **필** | |
| 형식/규격 | model_spec | 글(100) | 권 | |
| 제조처 | maker | 글(100) | 권 | |
| 기기번호(S/N) | serial_no | 글(60) | 권 | |
| 등록일 | registered_on | 날짜 | 권 | |
| 관리부서 | department | →Department | **필** | |
| 사용장소 | use_area | 글(60) | 권 | |
| 상세위치 | location_detail | 글(100) | 선 | |
| 자산코드 / 자산 비고 | asset_code / asset_note | 글(40) / 글(200) | 선 | |
| 관리구분 | control_kind | 선택[교정 대상, 점검 대상, 비교정(참고용)] | **필** | |
| 기본 / 확정 교정주기(개월) | base_interval_months / interval_months | 정수 | **필** | 확정 주기가 기존 `interval_days`를 대신한다. 이행은 아래 참고 |
| 관리상태 | status | 선택[사용, 사용 중지, 불용, 폐기, 이관] | **필** | "사용"이 아니면 측정에 쓸 수 없다. 기존 `active`와 같은 뜻으로 맞춘다 |
| 최근 교정일 / 최근 판정 | last_calibrated / last_result | (기존) / 선택[합격, 불합격, 조건부] | 계산 | 교정 이력의 최신 행 |
| 차기 교정일 / 남은 일수 / 교정 상태 | — | 계산 | | 기존 `usable_on` 규칙 그대로 |
| 기능 상태(O/X) | functional | 예/아니오 | **필** | X면 측정에 쓸 수 없다 |
| 비고 / 확인 필요 | note / needs_check | 긴글 / 예/아니오 | 선 | |
| (추가) | resolution / range | 글(30) | 권 | 분해능, 측정 범위. MSA와 검사 특성 적합성 확인용 |
| (추가) | calibrator | →Partner(교정기관) | 권 | 기본 교정기관 |
| (추가) | approval | 승인 서명 | 선 | 등록 승인. 기록용이다. `usable_on`에는 넣지 않는다 |

**교정 주기 이행 (기존 데이터 보호)**
- `interval_days`는 남긴다.
- 확정 주기가 비어 있으면 지금처럼 `interval_days`를 쓴다.
- 확정 주기가 있으면 개월 단위로 계산한다.
- 둘이 다른 행은 "데이터 상태"에 표시한다.

### 7.2 `CalibrationRecord` 교정 이력 — 교정이력 시트 8열 + 보강
| 대장 열 | 칸 | 형 | 구분 | 설명 |
|---|---|---|---|---|
| 관리번호 | gauge | →Gauge | **필** | |
| 교정일 | calibrated_on | 날짜 | **필** | gauge와 함께 고유. 대장의 "조회 키"에 해당한다 |
| 교정 구분 | kind | 선택[외부 교정, 사내 교정, 점검, 수리 후 교정] | **필** | |
| 교정기관 | calibrator | →Partner / 글(100) | 권 | |
| 성적서 번호 | cert_no | 글(60) | 권 | |
| 판정 | result | 선택[합격, 불합격, 조건부] | **필** | |
| 비고 | note | 긴글 | 선 | |
| (추가) | certificate | 파일 | 권 | 성적서 |
| (추가) | as_found / as_left | 긴글 | 선 | 교정 전후 값 요약 |
| (추가) | traceable_to | 글(100) | 선 | 국가 표준 소급 근거 |

**저장할 때**
- 계측기의 `last_calibrated`를 갱신한다.
- 불합격이면 계측기를 사용 중지하고 영향 조사(7.4)를 만든다. 인터록을 강화하는 방향이다.

### 7.3 `GaugeMaintenance` 수리·점검 이력
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| gauge | →Gauge | **필** | |
| kind | 선택[수리, 일상 점검, 부품 교체, 이상 신고] | **필** | |
| occurred_on / done_on | 날짜 | **필** / 권 | |
| symptom / action | 긴글 | **필** / 권 | |
| vendor | →Partner | 선 | |
| cost | 수(14,2) | 선 | |
| needs_recalibration | 예/아니오 | **필** | 예이면 교정 전까지 측정에 쓸 수 없다 |

### 7.4 `CalibrationImpact` 교정 불합격 영향 조사 (IATF 7.1.5.2.1, AS 7.1.5.2)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| calibration | →CalibrationRecord | **필** | 불합격 교정 |
| inspection | →Inspection | **필** | 직전 합격 교정 이후 이 계측기로 측정한 검사. 자동으로 목록을 만든다 |
| decision | 선택[영향 없음, 재검사, 고객 통보, 부적합 등록] | **필** | |
| decided_by / decided_at | 자동 | | |
| note | 긴글 | 조 | "영향 없음"이면 근거가 필수 |

### 7.5 `MsaStudy` 측정시스템 분석
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| gauge | →Gauge | **필** | |
| characteristic | →Characteristic | 권 | |
| kind | 선택[GR&R, 편의, 선형성, 안정성, 계수형] | **필** | |
| performed_on | 날짜 | **필** | |
| grr_percent / ndc | 수(6,2) / 정수 | 조 | GR&R이면 필수 |
| result | 선택[적합, 조건부, 부적합] | **필** | |
| data | 파일 | 권 | 원 데이터 |

## 8. F단계 — 품번·공정·설비 (core)

### 8.1 `Item` 품번 (기존 +)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| spec | 글(200) | 권 | 규격 |
| unit | →CodeValue(단위) | **필** | 새 코드 묶음 "단위". 기존 행은 비어도 된다 |
| material | 글(100) | 선 | |
| drawing_no | 글(60) | 권 | |
| current_rev | →ItemRevision | 계산 | 시행 중인 형상 |
| customer | →Partner(고객사) | 조 | 제품이면 필수 |
| customer_part_no | 글(60) | 조 | 고객사가 있으면 권장 |
| default_supplier | →Partner(협력사) | 조 | 구매품이면 권장 |
| weight_kg | 수(10,4) | 선 | |
| incoming_inspection | 예/아니오 | **필** | 수입검사 대상. 기본값 예 |
| coc_required | 예/아니오 | **필** | |
| aerospace | 예/아니오 | **필** | 항공 품번. 참이면 FAI·위조품 확인·하향 전개를 적용한다 |
| safety_critical | 예/아니오 | **필** | 제품 안전(IATF 4.4.1.2, AS 8.1.3) |
| shelf_life_days | 정수 | 선 | |
| lot_control | 선택[LOT, 시리얼, 없음] | **필** | 기본값 LOT |
| safety_stock / lead_time_days | 수 / 정수 | 선 | ERP |
| std_cost | 수(14,2) | 선 | 부적합 비용 계산용 |

### 8.2 `ItemRevision` 형상 (AS 8.1.2)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| item | →Item | **필** | |
| rev | 글(10) | **필** | item과 함께 고유 |
| drawing | →Document | 권 | 도면 문서 |
| change_request | →ChangeRequest | 조 | 첫 형상이 아니면 필수 |
| effective_from | 날짜 | **필** | |
| approved_by / approved_at | 승인 서명 | **필** | 승인 뒤에는 잠긴다 |
| fai_required | 예/아니오 | 계산 | 항공 품번의 새 형상이면 참 |

작업지시, LOT, 검사기준, FAI가 →ItemRevision을 선택 칸으로 가진다. 어느 형상으로 만들었는지 남긴다.

### 8.3 `Process` 공정 (기존 +)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| kind | 선택[가공, 조립, 열처리, 표면처리, 용접, 비파괴검사, 검사, 포장, 외주] | **필** | |
| special | 예/아니오 | **필** | 특수공정(AS 8.5.1.2). 열처리·표면처리·용접·비파괴검사면 기본값 예 |
| department | →Department | 권 | |
| work_center | →WorkCenter | 권 | |
| outsource_partner | →Partner | 조 | 종류가 외주면 필수 |
| cycle_sec | 수(10,2) | 선 | 표준 사이클 타임 |
| instruction | →Document(지침서) | 권 | 작업표준 |
| skill_required | 정수(1~4) | 선 | 작업자에게 필요한 최소 역량 등급(H단계) |

### 8.4 `ProcessParameter` 공정 조건 기준
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| process | →Process | **필** | |
| item | →Item | 선 | 비우면 공정 공통 |
| name | 글(60) | **필** | 예: 온도, 시간, 전류 |
| lsl / usl / unit | 수 / 수 / 글(20) | 권 | |
| equipment | →Equipment | 선 | |

### 8.5 `WorkCenter` 작업장·라인
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| code / name | 글 | **필** | |
| site | →Site | **필** | |
| department | →Department | 권 | |
| kind | 선택[라인, 셀, 작업대, 검사실, 창고] | **필** | |

### 8.6 `Equipment` 설비·금형·치공구
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| code | 글(30) | **필** | |
| name | 글(100) | **필** | |
| kind | 선택[생산 설비, 금형, 지그, 공구, 유틸리티] | **필** | |
| work_center | →WorkCenter | 권 | |
| maker / model / serial_no | 글 | 권 | |
| installed_on | 날짜 | 권 | |
| status | 선택[가동, 정지, 수리 중, 폐기] | **필** | |
| pm_interval_days | 정수 | 권 | 예방보전 주기 |
| last_pm_on / next_pm_on | 날짜 | 계산 | |
| owner_partner | →Partner | 선 | 고객 소유 금형(IATF 7.1.5.3·8.5.3) |
| cavity / shot_life / shot_count | 정수 | 조 | 금형이면 권장. 수명의 90%가 되면 경고 |

### 8.7 `PmRecord` 설비 보전 이력
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| equipment | →Equipment | **필** | |
| kind | 선택[예방, 사후, 예지, 개선] | **필** | |
| done_on | 날짜 | **필** | |
| done_by | →User | **필** | |
| content | 긴글 | **필** | |
| parts | 긴글 | 선 | |
| downtime_min | 정수 | 권 | |
| cost | 수(14,2) | 선 | |

## 9. I단계 — ERP 일부

### 9.1 `Location` 보관 위치
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| code / name | 글 | **필** | |
| site | →Site | **필** | |
| kind | 선택[원자재, 재공, 제품, 보류, 불량, 외주] | **필** | |
| parent | →Location | 선 | 창고 → 랙 → 칸 |

### 9.2 `SalesOrder` 수주 / `SalesOrderLine` 수주 품목
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| number | 글(30) | **필** | 자동 번호 |
| customer | →Partner(고객사) | **필** | |
| customer_po_no | 글(60) | 권 | 고객 발주 번호 |
| ordered_on | 날짜 | **필** | |
| status | 선택[접수, 확정, 생산 중, 일부 출하, 완료, 취소] | **필** | 대체로 품목에서 계산한다 |
| sales_rep | →User | 권 | |
| currency | 글(3) | 선 | |
| contract_review | 승인 서명 | 권 | 계약 검토(8.2.3). 확정 전에 한다 |
| **품목** line_no, item, item_rev | 정수, →Item, →ItemRevision | **필**, **필**, 권 | |
| qty / unit_price | 수(14,3) / 수(14,2) | **필** / 권 | |
| requested_on / promised_on | 날짜 | **필** / 권 | 고객 요구 납기 / 회신 납기 |
| shipped_qty | 수 | 계산 | 출하 합계 |
| otd | 선택[정시, 지연, 미출하] | 계산 | 회신 납기(없으면 요구 납기) 대비 출하 완료일 |

### 9.3 `PurchaseOrder` 발주 / `PurchaseOrderLine` 발주 품목
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| number | 글(30) | **필** | 자동 번호 |
| supplier | →Partner(협력사·외주) | **필** | "거래 중지" 거래처는 발주할 수 없다 |
| ordered_on | 날짜 | **필** | |
| buyer | →User | 권 | |
| status | 선택[작성, 발행, 일부 입고, 완료, 취소] | **필** | |
| flow_downs | ⇉FlowDown | 조 | 항공 품번이 있으면 기본 항목을 자동으로 붙인다 |
| issued_at | 일시 | 조 | 발행하면 잠긴다 |
| **품목** line_no, item, item_rev | | **필** | |
| qty / unit_price / due_on | | **필** / 권 / **필** | |
| approved_source | →ApprovedSource | 계산 | 없으면 경고. 항공 품번이면 발행을 막는다(AS 8.4.1) |
| fai_required / source_inspection / coc_required | 예/아니오 | 선 | |
| received_qty | 수 | 계산 | |

### 9.4 `StockMove` 재고 이동
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| moved_at | 일시 | **필** | |
| kind | 선택[입고, 생산 투입, 생산 완료, 출하, 이동, 조정, 폐기, 반품] | **필** | |
| item | →Item | **필** | |
| lot | →Lot | 조 | LOT 관리 품번이면 필수 |
| qty | 수(14,3) | **필** | 0보다 크다 |
| from_loc / to_loc | →Location | 조 | 종류에 따라 하나 또는 둘 |
| ref_type / ref_id | 일반 연결 | 권 | 원인 기록. 예: 입고 LOT, 작업 실적, 출하 |
| by | →User | 자동 | |
| reason | 글(200) | 조 | 조정·폐기면 필수 |

- **현재고는 계산한다.** 품번·LOT·위치별 합계다. 별도 재고 표는 두지 않는다.
  - shortcut: 이동이 수십만 건이 되어 느려지면 월마감 잔액 표를 더한다.
- **보류 인터록:** 보류 LOT은 "보류"와 "불량" 위치 밖으로 옮길 수 없다. 출하·투입 차단과 같은 쪽으로 강하게 하는 방향이다.
- **자동 생성:** 기존 입고·실적·출하를 저장하면 이동 행을 자동으로 만든다. 사람이 직접 쓰는 것은 이동·조정·폐기뿐이다.

### 9.5 `Shipment` 출하 (기존 +)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| so_line | →SalesOrderLine | 권 | |
| partner | →Partner | 3.8 | |
| delivery_no | 글(40) | 권 | |
| shipped_by | →User | 자동 | |
| coc_issued | 예/아니오 | 조 | 고객 요구면 필수 |
| from_loc | →Location | 선 | |

## 10. J단계 — MES 강화 (core)

### 10.1 `WorkOrder` 작업지시 (기존 +)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| so_line | →SalesOrderLine | 선 | |
| item_rev | →ItemRevision | 권 | |
| work_center | →WorkCenter | 권 | |
| priority | 선택[보통, 긴급] | 선 | |
| released_at / started_at / finished_at | 일시 | 자동 | |

### 10.2 `WorkResult` 작업 실적 (기존 +)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| equipment | →Equipment | 권 | 금형이면 타수를 더한다 |
| shift | 선택[주간, 야간, 3교대-1/2/3] | 선 | |
| setup_min | 정수 | 선 | |
| rework_qty | 수(14,3) | 선 | |
| operator_skill_ok | 예/아니오 | 계산 | 저장할 때 역량 매트릭스를 확인한다. 기본은 경고만 한다. 차단으로 바꾸려면 승인을 받는다 |
| instruction_rev | →DocumentRevision | 자동 | 그때 시행 중이던 작업표준 |

### 10.3 `DefectEntry` 실적 불량 내역
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| work_result | →WorkResult | **필** | |
| defect_code | →CodeValue(불량유형) | **필** | 새 코드 묶음 |
| qty | 수(14,3) | **필** | 합계가 실적의 `defect_qty`와 같아야 한다 |

### 10.4 `SpecialProcessRecord` 특수공정 조건 기록
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| work_result | →WorkResult | **필** | |
| parameter | →ProcessParameter | **필** | |
| value | 수(14,4) | **필** | 범위를 벗어나면 기존 부적합 자동 등록 경로를 쓴다 |
| recorded_at | 일시 | 자동 | |
| equipment | →Equipment | 선 | |

### 10.5 `Downtime` 비가동
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| equipment / work_center | →Equipment / →WorkCenter | 조 | 둘 중 하나는 필수 |
| started_at / ended_at | 일시 | **필** / 조 | |
| reason | →CodeValue(비가동 사유) | **필** | 새 코드 묶음 |
| work_order | →WorkOrder | 선 | |
| note | 긴글 | 선 | |

### 10.6 `FodCheck` 이물(FOD) 점검 (AS 8.5.1)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| work_center | →WorkCenter | **필** | |
| checked_on | 날짜 | **필** | |
| checked_by | →User | **필** | |
| tool_count_ok / area_clean_ok / parts_cover_ok | 예/아니오 | **필** | |
| finding | 긴글 | 조 | 하나라도 아니오면 필수 |
| nonconformance | →Nonconformance | 선 | |

## 11. G·H단계 — 제품 실현·지원 (qms)

### 11.1 `FaiReport` 초도품 검사 (AS9102)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| number | 글(30) | **필** | |
| item / item_rev | →Item / →ItemRevision | **필** | 양식 1 |
| lot | →Lot | **필** | 시리얼이면 시리얼 LOT |
| reason | 선택[신규, 설계 변경, 공정·설비 변경, 공급처 변경, 2년 미생산, 고객 요구] | **필** | |
| kind | 선택[전체, 부분] | **필** | 부분이면 바뀐 특성만 본다 |
| supplier | →Partner | 선 | 협력사 FAI를 받을 때 |
| baseline | →FaiReport | 조 | 부분 FAI면 필수 |
| result | 선택[합격, 불합격] | 계산 | 특성이 하나라도 불합격이면 불합격 |
| approved_by / approved_at | 승인 서명 | **필** | |

**`FaiMaterial` 양식 2 — 자재·특수공정·기능시험**
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| fai | →FaiReport | **필** | |
| kind | 선택[자재, 특수공정, 기능시험] | **필** | |
| name / spec_no | 글 | **필** | |
| partner | →Partner | 권 | |
| cert_no | 글 | 권 | |
| approved_source | →ApprovedSource | 계산 | |

**`FaiCharacteristic` 양식 3 — 특성**
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| fai | →FaiReport | **필** | |
| char_no | 글(10) | **필** | 도면 풍선 번호 |
| location | 글(20) | 선 | 도면 위치 |
| designator | 선택[일반, KC, 특별특성] | **필** | |
| requirement | 글(200) | **필** | |
| lsl / usl | 수 | 선 | |
| result_value | 글(60) | **필** | |
| ok | 예/아니오 | **필** | |
| gauge | →Gauge | 권 | 교정 인터록을 적용한다 |
| nonconformance | →Nonconformance | 조 | 불합격이면 자동 등록 |
| characteristic | →Characteristic | 선 | 검사기준 특성과 연결 |

### 11.2 핵심특성(KC)
- 별도 표는 두지 않는다.
- 기존 `Characteristic.special`과 `ControlPlanLine.special`의 선택값에 "KC(항공)"를 더한다.
- KC도 특별특성과 같은 SPC 경보 → 부적합 규칙을 적용한다. 규칙을 강하게 하는 방향이다.

### 11.3 `Risk` 리스크·기회 등록부 (6.1, AS 8.1.1)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| number | 글(30) | **필** | |
| kind | 선택[리스크, 기회] | **필** | |
| area | 선택[경영, 공정, 제품, 공급자, 운영(AS), 안전, 기타] | **필** | |
| process / department / item / partner | → | 선 | 연결 대상 |
| description / cause | 긴글 | **필** / 권 | |
| likelihood / severity | 정수(1~5) | **필** | |
| score | 정수 | 계산 | 가능성 × 심각도 |
| level | 선택[낮음, 보통, 높음] | 계산 | |
| action | 긴글 | 조 | 높음이면 필수 |
| owner | →User | **필** | |
| due_on | 날짜 | 조 | |
| capa | →Capa | 선 | |
| status | 선택[열림, 조치 중, 수용, 종료] | **필** | |
| reviewed_on | 날짜 | 권 | 다음 검토는 경영검토 주기에 맞춘다 |

### 11.4 `QualityObjective` 품질목표 / `ObjectiveResult` 실적
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| year | 정수 | **필** | |
| department | →Department | **필** | |
| title | 글(100) | **필** | |
| metric | 선택[수동 입력, 공정 불량률, 고객 PPM, 납기율, 클레임 수, 교정 준수율] | **필** | 자동 지표면 실적을 계산한다 |
| target | 수 | **필** | |
| unit | 글(10) | **필** | |
| direction | 선택[이상, 이하] | **필** | |
| **실적** objective, period(YYYY-MM), actual, achieved, comment | | **필** | achieved는 계산한다 |

### 11.5 `ManagementReview` 경영검토 (9.3)
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| held_on | 날짜 | **필** | |
| chair | →User | **필** | |
| attendees | ⇉User | **필** | |
| inputs | JSON | **필** | 9.3.2 입력 항목별 글. 화면은 항목별 칸으로 보인다. 지표 요약을 자동으로 채운다 |
| outputs | 긴글 | **필** | |
| actions | 하위 표 | 권 | 할 일, 담당, 기한, 완료일 |
| approved_by / approved_at | 승인 서명 | **필** | |

### 11.6 `Competency` 역량 매트릭스 / `Training` 교육
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| **역량** employee, process 또는 skill명, level(1~4), assessed_on, assessor, valid_until | | **필** | 기존 검사원 자격 `Qualification`은 그대로 둔다 |
| **교육** title, kind[입사, 직무, 규격, 안전, 외부], held_on, hours, trainer, document(→교재) | | **필** | |
| **참석** training, employee, result[이수, 미이수], score, effectiveness(유효성 평가) | | **필** / 권 | |

### 11.7 `CustomerScore` 고객만족
| 칸 | 형 | 구분 | 설명 |
|---|---|---|---|
| partner | →Partner | **필** | |
| period | 글(7) | **필** | |
| source | 선택[고객 포털 성적, 설문, 방문 평가] | **필** | |
| score / rank | 수 / 글 | 권 | |
| file | 파일 | 선 | |
| otd / ppm / claims | 계산 | | 같은 기간의 수주·클레임에서 계산한다 |

## 12. 관계 지도 (연관성의 중심 축)

모든 기록은 아래 일곱 축 가운데 하나 이상에 닿는다. 화면의 "연결" 패널과 관계 지도(UX U2·U3)는 이 축을 따라 펼친다.

| 축 | 닿는 기록 |
|---|---|
| **거래처** | 승인 공급처, 평가, 감사, SCAR, 입고 LOT, 발주, 수주, 출하, 클레임, PPAP, CSR 규격, 고객 금형 |
| **품번(형상)** | BOM, 라우팅, 검사기준, 관리계획서, 작업지시, LOT, FAI, 4M, PPAP, 승인 공급처, 관련 문서 |
| **LOT** | 계보, 검사, 부적합, 보류, 실적, 재고 이동, 출하, 클레임, 위조품 확인, 교정 영향 조사 |
| **공정·설비** | 라우팅, 공정 조건, 특수공정 기록, 보전, 비가동, 지침서, 역량 |
| **부서·직원** | 문서 소관, 조항 책임, 품질목표, 역량, 교육, 리스크 담당 |
| **문서·조항** | 문서 위계, 개정, 배포, 읽음, 조항, 증적, 지적 |
| **계측기** | 교정, 수리, MSA, 측정값, 영향 조사, FAI 특성 |

**구현**
- 서버에 관계 목록을 따로 손으로 적지 않는다. Django 모델 `_meta`에서 외래키·역방향·일반 연결을 읽어 자동으로 만든다(`core/relations.py`). 새 표를 만들면 연결 패널에 바로 나온다.
- 권한 거르기는 기존 `core.search`와 `qms` 열람 함수(`can_see`)를 쓴다.
- `personal` 앱은 관계 지도에서 뺀다.

## 13. 보호 규칙과의 관계

**약하게 하는 변경: 없음.**

**강하게 하는 변경** (각 단계 계획에 표시하고, 승인 대상인지 묻는다)
- 교정 불합격 → 계측기 사용 중지와 영향 조사
- 기능 상태 X 또는 수리 후 재교정 필요 → 측정 차단
- 위조품 의심 → 부적합 등록과 LOT 보류
- 보류 LOT의 재고 이동 제한
- 항공 품번 발주의 승인 공급처 확인
- KC에 SPC 경보 적용
- 작업자 역량 확인(기본은 경고)

**권한**
- 새 표의 역할별 권한은 단계 계획마다 표로 적는다.
- 사람이 직접 쓰는 기록은 지우지 않는다. 삭제는 시스템 관리자만 한다.
