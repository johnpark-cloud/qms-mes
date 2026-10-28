# 핵심 업무 규칙

이 문서의 규칙은 품질 체계(IATF 16949 대응)의 근거다. 사용자 승인 없이 약화·우회·삭제하지 않는다. 규칙은 화면이 아니라 모델(`clean()`/`save()`), 관리 화면 권한 메서드, 서버 뷰에서 강제한다. 새 화면이나 입력 경로(API, 엑셀 가져오기, 자동 수집)를 추가해도 같은 모델 검증을 거쳐야 한다.

위치는 2026-10-28 기준 코드에서 확인했다. 규칙을 바꾸면 이 문서와 테스트도 함께 고친다.

## 1. LOT 추적과 보류 인터록

| 규칙 | 위치 |
| --- | --- |
| 부적합이 새로 등록되면 그 LOT과 모든 하위 계보 LOT(`Lot.descendants()`)에 보류(`Hold`)를 만든다. | `core/models.py` `Nonconformance.save` |
| 보류 중인 LOT은 다른 LOT에 투입(`LotLink`)할 수 없다. | `LotLink.clean` → `Lot.assert_usable('투입')` |
| 보류 중인 LOT으로 작업 실적을 등록할 수 없다. | `WorkResult.clean` → `assert_usable('실적 등록')` |
| 보류 중인 LOT은 출하할 수 없다. | `Shipment.clean` → `assert_usable('출하')` |
| 계보는 자기 자신 투입과 순환을 허용하지 않는다. | `LotLink.clean` |
| 작업 실적: 라우팅에 있는 공정만, 양품+불량 ≤ 투입, 이전 공정 양품 실적이 있어야 다음 공정 등록, LOT 품번 = 작업지시 품번. | `WorkResult.clean` |
| 고객 클레임 접수는 부적합을 자동 생성한다(→ 보류). | `qms/models.py` `CustomerClaim.save` |
| 원자재가 아닌 LOT에 투입 LOT이 없으면 "계보 미등록"으로 표시한다. | `Lot.lineage_gap` |

## 2. 부적합 처분 (MRB)

| 규칙 | 위치 |
| --- | --- |
| 처분은 등록과 동시에 입력할 수 없다(먼저 등록·보류). | `Nonconformance.clean` |
| 처분하려면 품질팀장(또는 시스템 관리자)이 승인자이고, 처분 저장 때 본인 비밀번호를 다시 입력한다. | `Nonconformance.clean`, `core/admin.py` 부적합 폼 `clean` |
| 처분 전에 보완 필수 칸(불량유형·선별 결과·격리 수량, 공정 내부·출하검사는 발견 공정까지)을 채워야 한다. | `Nonconformance.missing_fields`, 부적합 폼 `_post_clean` |
| 재작업·수리는 부적합 발견 이후 그 LOT의 재검사 합격 기록이 있어야 한다. | `Nonconformance.clean` |
| 특채는 고객 승인 문서번호가 필요하다. | `Nonconformance.clean` |
| 재작업·수리·특채(`RELEASING`)만 보류를 해제한다. 폐기·반품은 보류를 유지한다. | `Nonconformance.RELEASING`, `save` |
| 처분하면 종결 일시가 기록되고, 종결된 부적합은 잠긴다(수정 요청 승인 또는 시스템 관리자만 수정). | `Nonconformance.save`, `core/admin.py` `_open` |

## 3. 승인 서명과 잠금

| 규칙 | 위치 |
| --- | --- |
| 승인 대상(`Approvable`: 검사기준, 관리계획서, 4M 변경, 문서 개정, PPAP)은 승인 서명 화면에서만 승인된다. 승인자는 품질팀장 그룹이나 시스템 관리자이고, 비밀번호를 다시 입력한다. | `core/views.py` `approve`, `core/models.py` `is_approver` |
| 승인된 기록은 수정할 수 없다. 새 개정을 만든다. | `Approvable.save`, `Characteristic.save`, `ControlPlanLine` 저장 |
| 검사·문서 기준은 "승인된 최신 개정"이 유효본이다. | `InspectionSpec.current` |
| 4M 변경 중 고객 통보 대상은 고객 승인 문서번호가 있어야 승인할 수 있다. | `ChangeRequest.clean` |
| PPAP: 제출(S) 요소마다 증적이 있어야 PSW를 승인할 수 있다. 승인 후에는 제출일·고객 승인일만 기록할 수 있다. | `PpapSubmission.clean`/`save`, `PpapElement` 저장 |

## 4. 삭제와 수정 요청

| 규칙 | 위치 |
| --- | --- |
| 관리 화면에서 삭제는 시스템 관리자(슈퍼유저)만 할 수 있다. 역할 그룹에도 core·qms의 `delete_` 권한이 없다(검사원의 측정값 삭제만 예외). | `core/admin.py` `BaseAdmin.has_delete_permission`, `qms/apps.py` `ensure_roles` |
| 일반 사용자는 본인 비밀번호와 사유로 삭제·수정 요청을 하고, 시스템 관리자가 승인한다. 승인된 수정은 1회만 잠금을 푼다. | `core/models.py` `EditRequest.decide`, `core/views.py` `edit_request`, `core/records.py` |
| 부적합을 삭제하면 그 부적합이 만든 보류만 함께 지운다. 같은 LOT의 다른 부적합 보류는 남는다. | `core/records.py` `delete_record` |
| 다른 기록이 참조(PROTECT)하는 기록은 지울 수 없다. | `EditRequest.decide`, `records.blockers` |
| 시스템 관리자는 요청 없이 바로 수정·삭제한다. 모든 변경은 simple-history 이력에 남는다. | `records.can_edit_locked` |

## 5. 검사 판정

| 규칙 | 위치 |
| --- | --- |
| 승인된 검사기준으로만 검사할 수 있고, 검사기준 품번 = LOT 품번이어야 한다. | `qms/models.py` `Inspection.clean` |
| 판정은 모든 검사항목에 측정값이 있어야 한다. 하나라도 규격(LSL/USL) 밖이면 불합격이다. | `Inspection.finalize`, `Measurement.passed` |
| 불합격이면 부적합을 자동 생성한다(→ 계보 보류). | `Inspection.finalize` |
| 판정된 검사와 그 측정값은 수정할 수 없다. | `Inspection.save`, `Measurement.clean` |
| 검사원 자격: 그 검사구분에 자격 기록이 하나라도 있으면, 유효기한 안의 자격자만 판정할 수 있다. | `Inspection.finalize` |
| 검사 입력 화면의 "판정"은 전부 저장되거나 아무것도 저장되지 않는다. | `qms/views.py` `inspect_submit`, `Inspection.finalize`(`transaction.atomic`) |

## 6. 계측기 교정

| 규칙 | 위치 |
| --- | --- |
| 다음 교정일 = 최근 교정일 + 교정 주기(일). | `Gauge.next_due` |
| 측정값에 계측기를 적으면, 검사일이 다음 교정일을 지났거나 사용 중지된 계측기는 거부한다. | `Gauge.usable_on`, `Measurement.clean` |
| 교정 14일 전부터 내 할 일·알림에 표시한다. | `qms/due.py` |

## 7. SPC

| 규칙 | 위치 |
| --- | --- |
| 부분군 n=1이면 I-MR, 2~10이면 X̄-R. 경보는 관리한계 이탈, R/MR 이탈, 중심선 한쪽 연속 9점이다. | `qms/spc.py` `control_chart` |
| 특별특성(CC·SC)은 합격 검사라도 그 검사에서 경보가 나면 부적합을 등록한다(→ 보류). 일반 항목은 내 할 일에만 표시한다. | `Inspection._special_spc_check`, `qms/due.py` |

## 8. 4M 변경과 초품

| 규칙 | 위치 |
| --- | --- |
| 승인되고 적용 일시가 지난 4M 변경은, 적용 일시 이후 그 품번의 합격 검사(초품)가 나올 때까지 출하를 막는다. | `ChangeRequest.awaiting_first_article`, `core/models.py` `Shipment.clean` |

## 9. 클레임·SCAR·CAPA·내부심사

| 규칙 | 위치 |
| --- | --- |
| 8D 기한은 고객사별 규칙(봉쇄 D3 시간, 대책 D5 일)을 따르고, D1~D8이 모두 채워져야 종결한다. | `CustomerRule`, `CustomerClaim.clean` |
| SCAR는 협력사 회신 없이 종결할 수 없다. | `Scar.clean` |
| CAPA 유효성은 조치 완료 후 확인일·확인자와 함께 기록하고, "유효"여야 종결한다. | `Capa.clean` |
| 내부심사는 실시일이 있어야 하고, CAPA가 연결되지 않은 중·경부적합 지적이 있으면 종결할 수 없다. | `InternalAudit.clean` |

## 10. 권한과 개인정보

| 규칙 | 위치 |
| --- | --- |
| 역할 그룹(품질엔지니어·품질팀장·검사원)과 권한은 migrate 때마다 다시 설정된다. 권한을 바꾸려면 이 함수를 고친다. | `qms/apps.py` `ensure_roles` |
| 품질팀장 그룹이 승인자다. | `core/models.py` `APPROVER_GROUP`, `is_approver` |
| 연차·급여(`personal`)는 본인 기록만 조회·다운로드한다. 시스템 관리자도 남의 것은 볼 수 없다. 명세서 파일은 `/media/` 밖(`data/private/`)에 둔다. 연차 사용 표는 합계와 같은 입사 기념일 기간으로 보여 준다. 명세서를 지우거나 파일을 바꾸면 옛 파일도 지운다. 화면 이름(`__str__`)에는 날짜·일수를 넣지 않는다(삭제 확인 화면·변경 로그 노출 방지). | `personal/views.py`, `personal/admin.py`, `personal/models.py` `private_storage`, `Payslip.save`, `_delete_payslip_file` |
| 첨부 파일은 로그인한 스태프만 받을 수 있다. | `config/urls.py` `/media/` |
| 엑셀 양식 출력은 읽기 전용 메서드만 호출한다. 개인 앱·인증 모델은 대상에서 제외한다. | `qms/models.py` `ExcelTemplate`, `report_safe` |

## 11. 이력

업무 모델은 `history = HistoricalRecords()`로 모든 변경을 남긴다. 새 업무 모델에도 붙이고, 기존 모델에서 제거하지 않는다.
