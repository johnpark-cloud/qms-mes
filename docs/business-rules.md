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
| 위 세 검사(와 4M 초품 출하 차단)는 새로 만들 때뿐 아니라 기존 기록의 LOT을 바꿔 저장할 때도 한다. LOT을 바꾸지 않는 정정(수량·메모)은 LOT이 보류여도 허용한다. | `core/models.py` `lot_changed` |
| 계보는 자기 자신 투입과 순환을 허용하지 않는다. | `LotLink.clean` |
| 작업 실적: 라우팅에 있는 공정만, 양품+불량 ≤ 투입, 이전 공정 양품 실적이 있어야 다음 공정 등록, LOT 품번 = 작업지시 품번. | `WorkResult.clean` |
| 고객 클레임 접수는 부적합을 자동 생성한다(→ 보류). | `qms/models.py` `CustomerClaim.save` |
| 원자재가 아닌 LOT에 투입 LOT이 없으면 "계보 미등록"으로 표시한다. | `Lot.lineage_gap` |

## 2. 부적합 처분 (MRB)

| 규칙 | 위치 |
| --- | --- |
| 처분은 등록과 동시에 입력할 수 없다(먼저 등록·보류). | `Nonconformance.clean` |
| 처분하려면 품질팀장(또는 시스템 관리자)이 승인자이고, 처분 저장 때 본인 비밀번호를 다시 입력한다. | `Nonconformance.clean`, `core/rules.py` `sign_disposition`(비밀번호 확인, admin 폼 `clean`이 호출)·`dispose_nc`(처분 없는 서명 거부) |
| 처분 전에 보완 필수 칸(불량유형·선별 결과·격리 수량, 공정 내부·출하검사는 발견 공정까지)을 채워야 한다. | `Nonconformance.missing_fields`, 부적합 폼 `_post_clean` |
| 재작업·수리는 부적합 발견 이후 그 LOT의 재검사 합격 기록이 있어야 한다. | `Nonconformance.clean` |
| 특채는 고객 승인 문서번호가 필요하다. | `Nonconformance.clean` |
| 재작업·수리·특채(`RELEASING`)만 보류를 해제한다. 폐기·반품은 보류를 유지한다. | `Nonconformance.RELEASING`, `save` |
| 처분하면 종결 일시가 기록되고, 종결된 부적합은 잠긴다(수정 요청 승인 또는 시스템 관리자만 수정). 실패비용·고객 통보일·시정조치 필요·메일 발송 일시(`AFTER_APPROVAL`)는 종결 뒤에도 기록한다. | `Nonconformance._check_closed_lock`(모델 save), 화면은 `core/rules.py` `nc_locked_fields`·`core/admin.py` `_open` |
| 종결된 부적합의 보류 인터록 칸(LOT·발견 일시·처분·특채 승인번호, `INTERLOCK`)은 시스템 관리자·수정 승인으로도 바꿀 수 없다. | `Nonconformance._check_closed_lock` |

## 3. 승인 서명과 잠금

| 규칙 | 위치 |
| --- | --- |
| 승인 대상(`Approvable`: 검사기준, 관리계획서, 4M 변경, 문서 개정, PPAP)은 승인 서명 화면에서만 승인된다. 승인자는 품질팀장 그룹이나 시스템 관리자이고, 비밀번호를 다시 입력한다. | `core/views.py` `approve`, `core/models.py` `is_approver` |
| 승인된 기록은 수정할 수 없다. 새 개정을 만든다. | `Approvable.save`, `Characteristic.save`, `ControlPlanLine` 저장 |
| 검사·문서 기준은 "승인된 최신 개정"이 유효본이다. | `InspectionSpec.current` |
| 검사기준 저장은 `qms.rules.save_spec`이 한다(admin과 같은 잠금: `save_with_lock`). 기준서 속성과 검사항목 줄을 한꺼번에 저장하고 하나라도 잘못이면 아무것도 저장하지 않는다. 다른 기준서의 항목 id는 400으로 거부한다. 동시 수정은 `spec_version`(기준서·항목 이력 중 가장 큰 `history_id`)이 달라지면 409 `다른 사람이 먼저 고쳤습니다. 다시 불러오세요.`다. 항목 삭제는 `delete_characteristic` 권한이 필요하다(역할 그룹에는 없어 사실상 시스템 관리자만). | `qms/rules.py` `save_spec`·`spec_version`, `qms/api/specs.py` |
| 4M 변경 중 고객 통보 대상은 고객 승인 문서번호가 있어야 승인할 수 있다. | `ChangeRequest.clean` |
| PPAP: 제출(S) 요소마다 증적이 있어야 PSW를 승인할 수 있다. 승인 후에는 제출일·고객 승인일만 기록할 수 있다. | `PpapSubmission.clean`/`save`, `PpapElement` 저장 |

### 개정 이력(RevisionLog)

| 규칙 | 위치 |
| --- | --- |
| 개정 이력은 신청자가 변경 내용·사유(둘 다 필수)로 신청하면 "대기"이고, 승인자(`is_approver`)가 비밀번호를 다시 입력하면 "확정"이다. | `core/rules.py` `request_revision_log`·`confirm_revision_log`, API `POST /api/revision-log/<id>/approve/` |
| 확정된 개정 이력은 수정·삭제할 수 없다. 오류 문구는 `확정된 개정 이력은 수정할 수 없습니다.` | `core/models.py` `RevisionLog.save`·`delete` |
| 승인 서명과 확정 이력을 함께 남기는 경우(`approve_and_log`)는 한 트랜잭션이라 한쪽이 실패하면 둘 다 취소된다. | `core/rules.py` `approve_and_log` |
| `RevisionLog`도 `history = HistoricalRecords()`로 변경을 남긴다. | `core/models.py` |

## 4. 삭제와 수정 요청

| 규칙 | 위치 |
| --- | --- |
| 관리 화면에서 삭제는 시스템 관리자(슈퍼유저)만 할 수 있다. 역할 그룹에도 core·qms의 `delete_` 권한이 없다(검사원의 측정값 삭제만 예외). | `core/admin.py` `BaseAdmin.has_delete_permission`, `qms/apps.py` `ensure_roles` |
| 일반 사용자는 본인 비밀번호와 사유로 삭제·수정 요청을 하고, 시스템 관리자가 승인한다. 승인된 수정은 1회만 잠금을 푼다. | `core/models.py` `EditRequest.decide`, `core/rules.py` `check_edit_request`·`submit_edit_request`(관리 화면 요청 화면과 records API가 함께 씀), `core/records.py` |
| 부적합을 삭제하면 그 부적합이 만든 보류만 함께 지운다. 같은 LOT의 다른 부적합 보류는 남는다. | `core/records.py` `delete_record` |
| 다른 기록이 참조(PROTECT)하는 기록은 지울 수 없다. | `EditRequest.decide`, `records.blockers` |
| 시스템 관리자는 요청 없이 바로 수정·삭제한다. 모든 변경은 simple-history 이력에 남는다. | `records.can_edit_locked` |

## 5. 검사 판정

| 규칙 | 위치 |
| --- | --- |
| 승인된 검사기준으로만 검사할 수 있고, 검사기준 품번 = LOT 품번이어야 한다. 새 검사는 그 품번·검사구분의 승인된 최신 개정(`InspectionSpec.current`)으로만 만든다(지난 개정 금지). | `qms/models.py` `Inspection.clean` |
| 검사항목과 관리계획서 항목은 하한(LSL)이 상한(USL)보다 크면 저장하지 않는다(`하한이 상한보다 클 수 없습니다.`). 같으면 허용한다. 모델 `clean()`에서 검사하므로 admin과 API 모두 적용된다. 이미 저장된 행은 바뀌지 않는다. | `qms/models.py` `check_limits`, `Characteristic.clean`, `ControlPlanLine.clean` |
| 판정은 모든 검사항목에 측정값이 있어야 한다. 하나라도 규격(LSL/USL) 밖이면 불합격이다. | `Inspection.finalize`, `Measurement.passed` |
| 불합격이면 부적합을 자동 생성한다(→ 계보 보류). | `Inspection.finalize` |
| 판정된 검사와 그 측정값은 수정할 수 없다. | `Inspection.save`, `Measurement.clean` |
| 검사원 자격: 그 검사구분에 자격 기록이 하나라도 있으면, 유효기한 안의 자격자만 판정할 수 있다. | `Inspection.finalize` |
| 같은 LOT·같은 검사구분에 판정된 검사가 있으면 새 검사를 만들 수 없다. 처분 전인 부적합(`closed_at` 없음)이 있을 때만 재검사(재작업·수리 후)를 허용한다. 판정 전 검사는 세지 않는다. | `Inspection.clean` |
| 검사 입력 화면의 "판정"은 전부 저장되거나 아무것도 저장되지 않는다. | `qms/rules.py` `submit_inspection`(뷰 `inspect_submit`이 호출), `Inspection.finalize`(`transaction.atomic`) |

## 6. 계측기 교정

| 규칙 | 위치 |
| --- | --- |
| 다음 교정일 = 최근 교정일 + 교정 주기(일). | `Gauge.next_due` |
| 측정값에 계측기를 적으면, 검사일이 다음 교정일을 지났거나 사용 중지된 계측기는 거부한다. | `Gauge.usable_on`, `Measurement.clean` |
| 계측기를 하나라도 등록한 뒤부터, 검사 입력 화면(기존·React)의 판정은 계량형 항목이 있으면 계측기를 골라야 한다. 설비 수집(`collect`)과 관리 화면 입력은 제외. | `qms/rules.py` `submit_inspection` |
| 교정 14일 전부터 내 할 일·알림에 표시한다. | `qms/due.py` |

측정값 입력(검사 입력 화면, `collect` 자동 수집)은 NaN·무한대 값을 거부한다. `collect`는 읽을 수 없는 CSV를 `error/` 폴더로 옮기고 다음 파일을 계속 처리한다(`qms/rules.py` `measurement`, `qms/management/commands/collect.py`).

## 7. SPC

| 규칙 | 위치 |
| --- | --- |
| 부분군 n=1이면 I-MR, 2~10이면 X̄-R. 경보는 관리한계 이탈, R/MR 이탈, 중심선 한쪽 연속 9점이다. | `qms/spc.py` `control_chart` |
| 부분군 크기가 섞이면 가장 최근 부분군과 같은 크기의 부분군만 관리도에 쓴다(섞인 채로는 관리도를 못 그려 경보가 꺼지므로). | `Characteristic.spc_series` |
| 특별특성(CC·SC)은 합격 검사라도 그 검사에서 경보가 나면 부적합을 등록한다(→ 보류). 일반 항목은 내 할 일에만 표시한다. | `Inspection._special_spc_check`, `qms/due.py` |

## 8. 4M 변경과 초품

| 규칙 | 위치 |
| --- | --- |
| 승인되고 적용 일시가 지난 4M 변경은, 적용 일시 이후 그 품번의 합격 검사(초품)가 나올 때까지 출하를 막는다. | `ChangeRequest.awaiting_first_article`, `core/models.py` `Shipment.clean`, 내 할 일 표시는 같은 기준으로 `qms/due.py` |

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
| LOT 이력 조회(`/trace/`)는 `core.view_lot` 권한이 있어야 본다. | `core/views.py` `trace`, `core/nav.py` |
| `/media/` 아래 파일(부적합 사진·메모 사진·거래처 인증서 등)은 로그인한 스태프만 받을 수 있다. | `config/urls.py` `/media/` |
| 기록 첨부(`Attachment`)는 `/media/` 밖(`data/attachments/`)에 두고 `/attachments/<id>/`로만 받는다. 받으려면 `core.view_attachment` 권한과 첨부가 붙은 기록의 보기 권한이 모두 있어야 하고, 그 기록이 있어야 한다. 개인 앱(`PRIVATE_APPS`) 기록에는 붙일 수도 받을 수도 없다. 올리기(`/api/attachments/`)는 `core.add_attachment`와 대상 기록 보기 권한이 필요하다. 관리 화면에서는 첨부를 추가하지 않고, 삭제는 시스템 관리자만 한다. 첨부 행을 지우면 파일도 지운다. | `core/views.py` `can_view_target`·`attachment_download`, `core/api/attachments.py`, `core/models.py` `attachment_storage` |
| 부서·거래처·사용자 정의 칸의 추가·수정은 품질팀장(과 시스템 관리자)만 한다. 품질엔지니어·검사원은 보기만 한다. | `qms/apps.py` `TEAM_LEAD_ONLY`, `ensure_roles` |
| 새 기록 화면(`/app/r/<app>/<model>/<id>`)과 records API는 설명서(`core/recordspec.py` `SPECS`)에 등록된 모델만 연다(그 밖은 404). 목록·상세·변경 이력 탭은 그 모델의 `view_` 권한으로 서버가 검사한다(변경 이력 탭은 `view_` 권한자에게 보인다, 2026-11-13 사용자 결정). 전체 감사 기록 화면(`/app/audit`)은 그대로 품질팀장 전용이다. | `core/api/records.py`, `core/recordspec.py` |
| 기록 화면의 범용 저장(`PATCH /api/records/<label>/<id>/`)은 `change_` 권한, 설명서 `Spec.edit` 칸만 받는다. 서명 칸(`SIGN_FIELDS`: 승인자·승인 일시·판정 등)은 설명서에 넣을 수 없고(테스트가 검사) 보내면 400이다. 저장은 ModelForm 검증 + `validate_constraints` → `rules.save_with_lock`(승인 잠금·수정 승인 1회 소모)이고, 이력 번호(`version`)가 다르면 409다. 승인은 `rules.approve`(품질팀장·비밀번호)로만 한다. | `core/api/records.py`, `core/recordspec.py` `SIGN_FIELDS`, `core/rules.py` |
| 기록 화면의 부적합 처분은 `POST /api/records/core.nonconformance/<id>/dispose/`(`change_nonconformance` 권한)로만 하고, 관리 화면과 같은 `rules.dispose_nc`(MRB 비밀번호·필수칸·모델 `clean` 처분 규칙·보류 해제)를 거친다. 처분·특채 승인번호·보류 해제 일시는 `SIGN_FIELDS`라 범용 저장으로 보낼 수 없다(400). 보류는 설명서 `edit`가 비어 있어 범용 저장이 403이고, 수정·삭제 요청은 404다. | `core/api/records.py` `RecordDisposeView`, `core/rules.py` `dispose_nc`, `core/recordspec.py` |
| 연결 패널(`/api/relations/<app.model>/<id>/`)은 그 기록 보기 권한이 있어야 열리고, 사용자가 볼 권한이 없는 표의 묶음은 개수도 알리지 않는다. 개인 앱·이력 표·사용자 계정은 연결 대상이 아니다. | `core/api/views.py` `RelationsView`, `core/relations.py` |
| 엑셀 일괄 등록은 대상(품번·작업지시)의 추가·변경 권한이 모두 있어야 올릴 수 있다(기존 행을 덮어쓰므로). 각 행은 모델 검증(`full_clean`)을 거치고, 한 행이라도 틀리면 전체를 되돌린다. | `core/views.py` `import_view`, `core/importer.py` |
| 인쇄·승인·삭제 요청 경로는 개인 자료와 계정·세션 등 시스템 기록(`personal`, `auth`, `admin`, `sessions`, `contenttypes`)을 열지 않는다. | `core/views.py` `_get_record` |
| 엑셀 양식 출력은 읽기 전용 메서드만 호출한다. 개인·인증 앱(`PRIVATE_APPS`)은 양식 대상과 심사 증적·PPAP 요소의 기록 종류에서 제외하고, 값을 따라가다 그 앱 기록에 닿으면 칸을 비운다. | `qms/models.py` `PRIVATE_APPS`, `ExcelTemplate.fill`, `report_safe` |
| 품질 KPI(실패비용 포함)는 `qms.view_customerclaim`, 협력사 성적표는 `qms.view_scar`, SPC 관리도는 `qms.view_measurement`, 내 할 일 목록 위젯은 `core.view_nonconformance` 권한이 있어야 본다. 검사원은 KPI·협력사 화면을 볼 수 없다. | `qms/views.py`, `qms/widgets.py`, `core/nav.py` |
| KPI는 소속 부서 것만 본다(`/kpi/` 화면과 내 할 일 KPI 위젯 모두). 부서는 역할 그룹 묶음이고 지금은 `품질`(품질엔지니어·품질팀장·검사원)뿐이다. PPM·직행률·8D·실패비용·불량유형 파레토는 품질, 공정 수율은 품질·생산 부서 KPI다. 품질팀장·시스템 관리자는 모든 부서 KPI를 본다. KPI 위젯은 `/kpi/`와 같은 `qms.view_customerclaim` 권한도 있어야 보인다. 부서를 늘리려면 `DEPARTMENTS`에 그룹을 더한다. | `qms/kpi.py` `DEPARTMENTS`·`KPI_DEPARTMENTS`·`can_see`, `qms/views.py` `kpi_view`, `qms/widgets.py` `kpi_allowed` |

### 모듈 켜기/끄기

| 규칙 | 위치 |
| --- | --- |
| 모듈은 시스템 관리자만 켜고 끈다(명시 권한이 있어도 일반 사용자는 불가). 기본 플랫폼(홈·LOT·부적합·보류·기준정보·시스템·개인)은 끌 수 없고, 스위치 행은 지우지 않는다. | `core/admin.py` `ModuleSwitchAdmin`, `core/models.py` `ModuleSwitch.clean` |
| 의존 모듈: 4M 변경은 검사, 내부심사는 CAPA가 켜져 있어야 켠다. 켜진 의존 모듈이 있으면 그 대상은 끌 수 없다. | `core/modules.py` `requires`, `ModuleSwitch.clean` |
| 꺼진 모듈의 화면·API는 일반 사용자에게 404(API는 `code: module_inactive`), 시스템 관리자는 GET만 되고 쓰기는 403이다. 첨부·메모·관련 기록·인쇄·자동완성도 대상 기록의 모듈로 판정한다. | `core/middleware.py` `ModuleGate`, `core/modules.py` `check_label` |
| 열린 기록이 있는 모듈은 끌 수 없고 기록 번호를 보인다: 완료 안 된 작업지시, 미판정 검사, 초품 합격 전 4M(승인된 것), 미종결 CAPA·클레임·SCAR·내부심사, 미승인 PPAP. | `core/modules.py` `open_records`, `ModuleSwitch.clean` |
| 꺼진 모듈에서도 시스템 관리자는 열린 기록을 닫을 수 있다: CAPA·클레임·SCAR·내부심사(지적) 관리 화면 변경 폼, 검사 입력(4M 초품 판정·재작업 재검사). 그 밖의 쓰기(추가·삭제 포함)는 403이다. 초품 수동 해제 규칙은 없다. | `core/modules.py` `CLOSING`, `blocked` |
| 인터록 거부 메시지 앞에 원인 모듈과 기록 번호를 붙인다: `[부적합] NC-…`, `[4M 변경] CR-…`. | `core/models.py` `Lot.assert_usable`, `Shipment.clean` |
| 꺼진 모듈 기록은 할 일·기한·알림·위젯·종합현황에서 빠지고, LOT 이력·검색·관련 기록에는 「비활성 모듈 기록 N건」으로만 보인다. 엑셀 보고서(404)·엑셀 일괄 등록(거부)·`collect`(거부, 파일 유지)·심사 대응 묶음(구역 제외)도 모듈 상태를 따른다. | `qms/due.py` `DUE_MODULE`, `qms/widgets.py`, `qms/overview.py`, `core/timeline.py`, `core/search.py`, `core/relations.py`, `qms/views.py`, `core/importer.py` |
| 모듈 설정은 업무 규칙을 바꾸지 않는다. 모든 모듈을 꺼도 LOT 보류 인터록은 동작한다. | `core/tests_modules.py` `test_hold_interlock_with_all_modules_off` |

## 11. 이력

감사 기록 화면(`/app/audit`, API `GET /api/audit-log/`)은 승인자(`is_approver`: 품질팀장·시스템 관리자)만 본다. 개인정보 앱(`PRIVATE_APPS`, `personal` 등)의 이력은 보여 주지 않고, `password` 필드 변경은 가린다(`core/api/views.py` `AuditLogView`, `core/audit.py` `audited_models`·`SECRET_FIELDS`). 사이드바의 "감사 기록" 메뉴도 승인자에게만 나온다(`core/nav.py`).

업무 모델은 `history = HistoricalRecords()`로 모든 변경을 남긴다. 새 업무 모델에도 붙이고, 기존 모델에서 제거하지 않는다. 여러 행을 한꺼번에 저장할 때는 `bulk_create`·`update()` 대신 이력을 남기는 `simple_history.utils.bulk_create_with_history`·`bulk_update_with_history`를 쓴다(보류 생성·해제, 부적합 메일 발송 표시가 이 방식이다: `core/models.py` `Nonconformance.save`, `core/views.py` `_mark_mailed`).

기준정보(부서·거래처)는 지우지 않고 "사용"을 끈다. 사용자 정의 칸(`FieldDef`)은 저장 뒤 키와 대상을 바꿀 수 없다(`FieldDef.LOCKED_MSG`). 사용을 끈 칸의 값은 `extra`에 그대로 남는다(`core/models.py` `validate_extra`).

`link_masters --apply`는 기존 기록의 비어 있는 연결 칸만 채우고 글자 칸은 바꾸지 않는다. 실행 전에 `backup`을 먼저 실행하며 백업 폴더가 없으면 멈춘다. 모델 `save()`·`clean()`을 거치지 않으므로 잠금·인터록 검사는 적용되지 않지만, `bulk_update_with_history`로 변경 이력(사유 "기준정보 연결(link_masters)")은 남는다(`core/management/commands/link_masters.py`).

## 12. 번호 부여

품번(`Item.code`)과 문서번호(`qms.Document.number`)를 규칙(틀 문자열)으로 자동 부여한다. 코드값은 `core.CodeValue`, 규칙은 `core.NumberRule`이다. 둘 다 `BaseAdmin`·변경 이력(simple-history)을 쓰고, 삭제는 시스템 관리자만 한다.

### 틀 문법

중괄호 밖 글자는 그대로 들어가는 고정 글자다.

| 토큰 | 뜻 | 예 |
| --- | --- | --- |
| `{코드 묶음}` | 그 묶음의 활성 코드값 중 하나. 자릿수는 묶음별 고정 | `{고객사}` → `DC` |
| `{코드 묶음:A,B}` | 허용 값을 A, B로 제한 | `{품목분류:1,2}` |
| `{품번:규칙}` / `{문서:규칙}` | 그 규칙 모양에 맞는 기존 품번·문서번호 하나 | `{품번:제품코드}` → `1TRT038` |
| `{품번:규칙:뒤N}` | 고른 번호의 뒤 N글자. N은 토큰 경계에 맞아야 함 | `{품번:제품코드:뒤6}` → `TRT038` |
| `{일련N}` | N자리 일련번호. 정확히 1개, 맨 끝 | `{일련3}` → `001` |

- 부모가 있는 묶음(자재 대·중·소분류)은 바로 앞 코드 토큰의 값의 자식에서 고른다. 바로 앞 코드 토큰이 부모 묶음이 아니면 규칙을 저장할 수 없다.
- 저장 때 검사: 묶음·규칙 이름이 있는지, 허용 값이 코드표에 있는지, 참조 대상(품번/문서)이 참조 규칙의 대상과 맞는지, 자기 참조·순환이 없는지, `뒤N`이 경계에 맞는지, 일련 토큰이 맨 끝에 1개인지(`core/numbering.py` `check_rule`).

### 초기 규칙 7개

데이터 마이그레이션으로 추가만 한다.

| sort | 이름 | 대상 | 틀 | 예 |
| --- | --- | --- | --- | --- |
| 1 | 관리표준 | 문서 | `KEN-{관리표준 문서구분}{부서}-{일련2}` | `KEN-PQ-01` |
| 2 | 양식 | 문서 | `{문서:관리표준}-{일련2}` | `KEN-PQ-01-01` |
| 3 | 제품코드 | 품번 | `{품목분류:1,2}{산업분류}{고객사}{일련3}` | `1VDC001` |
| 4 | 원자재 | 품번 | `{품목분류:3}{자재분류}{자재 대분류}{자재 중분류}{자재 소분류}-{일련5}` | `31111-00001` |
| 5 | 기술문서 | 문서 | `{품번:제품코드}-{설계자료분류}{일련3}` | `1TDS001-BM001` |
| 6 | 도면 품번 | 품번 | `{품번:제품코드}-{설계자료분류:AS,SU,DT,PA,BA}{일련3}` | `1TRT038-AS001` |
| 7 | 표준품 | 품번 | `{품목분류:3}{품번:제품코드:뒤6}-{일련4}` | `3TRT038-0001` |

- 관리표준의 문서구분: M 매뉴얼, P 절차서, F 플로우차트, G 지침서. 부서: A 관리, O 구매자재, D 연구소, P 생산, M 마케팅, Q 품질, S 고객지원.
- 양식 번호 뒤 `(Rev.0)`은 번호가 아니라 개정 표기다. 번호에는 넣지 않는다.
- 도면 품번·표준품은 GD-02에 정의가 없다(GD-02 미정의). 실제 BOM의 현장 관행을 반영한 규칙이다.
- 도면코드: `AS` 기구 조립도면, `SU` 기구 부분 조립도면, `DT` 기구 상세도면, `PA` 단품도면, `BA` 반제품 보드.

### 지켜야 할 규칙

- **규칙 잠금:** 저장된 규칙의 이름·대상·틀은 바꿀 수 없다. 바꾸려면 새 규칙을 만들고 옛 규칙을 사용 중지한다. 옛 번호 풀이와 다른 규칙의 참조가 깨지지 않게 하려는 것이다(`NumberRule.clean`). 틀 검사는 새 규칙을 저장할 때만 한다. 그래서 참조하던 규칙이 지워진 규칙도 사용 중지는 할 수 있다.
- **도면 품번 = 도면 문서번호:** 같은 번호를 품번과 도면 문서가 함께 쓴다. 그래서 일련번호는 `Item.code`와 `Document.number` 양쪽의 최댓값 + 1로 계산한다.
- **일련번호:** 일련 토큰 앞 글자(prefix)가 같고 모양이 정확히 맞는(prefix 뒤에 N자리 숫자만) 번호만 센다. 지워진 번호는 다시 쓰지 않는다. 직접 입력한 번호도 모양이 같으면 계산에 들어간다(`core/numbering.py` `next_serial`).
- **끝 번호 초과:** 끝 번호(99, 999, 99999 등)를 넘으면 "일련번호가 다 찼습니다." 오류를 낸다.
- **저장 순간 번호 겹침:** 관리 화면에서 자동 번호로 문서를 저장할 때 같은 순간 다른 사용자가 같은 번호를 먼저 저장했으면, 그다음 빈 번호로 다시 저장한다(최대 20번, `qms/admin.py` `DocumentAdmin.save_model`). 번호 겹침이 아닌 다른 저장 오류는 그대로 낸다.
- **사용 중지:** 사용 중지된 규칙이나 코드값으로는 새 번호를 받을 수 없다(서버 `next_number`가 거부). 풀이(`describe`)에는 계속 쓰인다.
- **직접 입력:** 번호를 직접 적는 것은 허용하고 모양 검사는 하지 않는다(기존 번호가 규칙과 다르기 때문).
- **문서 참조 규칙의 권한:** `qms.view_document` 권한이 없는 사용자에게는 `{문서:…}` 토큰이 있는 품번 규칙을 숨긴다. 규칙 목록(`/api/core/numbering/item-options/`)에서 빠지고, 미리보기(`item-preview/`)와 자동 번호 저장(`POST /api/core/items/`의 `auto`)은 "번호 규칙을 찾을 수 없습니다."(400)로 거부한다. 문서번호·제목과 문서 존재 여부 노출을 막기 위해서다(`core/api/master.py` `_hides_docs`).
- **개정 자동 채움:** 문서 개정의 `개정`을 비우면 그 문서의 기존 개정값 중 숫자만인 값(앞의 `Rev.`, `Rev`는 떼고 비교)의 최댓값 + 1로 채운다. `A` 같은 문자 개정은 무시하고, 숫자 개정이 없으면 0이다(`core/numbering.py` `next_revision`).

코드 위치: `core/numbering.py`, `core/models.py`(`CodeValue`·`NumberRule`), `core/api/master.py`(`ItemOptionsView`·`ItemPreviewView`), `qms/admin.py`(`DocumentAdmin.get_form`), `qms/models.py`(`DocumentRevision`).
