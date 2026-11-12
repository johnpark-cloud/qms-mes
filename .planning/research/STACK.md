# 스택 조사: 모듈 켜기/끄기(A) + 범용 기록 화면(B)

**범위:** 새 의존성 없이 기존 스택만으로 A(서명 라이선스 + 미들웨어 게이트)와 B(기록 설명서 + 범용 records API + React 화면)를 만드는 방법
**조사일:** 2026-11-13
**전체 신뢰도:** HIGH (설치된 코드·lock 파일을 직접 읽어 확인). 개별 항목 신뢰도는 각 표에 표시.

## 결론 한 줄

새로 설치할 것은 없다. 서버는 Django 6.1.2의 `process_view` 미들웨어와 `ModelForm`, 기존 `core/rules.py`·`core/grid.py`를 쓰고, 화면은 antd 6 `Form`과 기존 `RecordPage`·`SaveBar`·`api()`를 쓴다. Ed25519 검증기만 표준 라이브러리(`hashlib`, 정수 연산)로 직접 쓴다.

## 설치된 버전 (requirements.txt, frontend/package-lock.json 기준)

| 구분 | 패키지 | 버전 |
|------|--------|------|
| 서버 | Python | 3.12.10 (.venv) |
| 서버 | Django | 6.1.2 |
| 서버 | djangorestframework | 3.18.3 |
| 서버 | django-simple-history | 3.13.0 |
| 서버 | django-filter / drf-spectacular | 26.2 / 0.30.0 |
| 서버 | psycopg / waitress / whitenoise | 3.3.8 / 3.0.2 / 6.12.0 |
| 화면 | antd / @ant-design/icons | 6.6.8 / ^6.3.4 |
| 화면 | react / react-dom | 19.3.1 |
| 화면 | react-router-dom | 7.18.5 (`BrowserRouter basename="/app"`, 선언형) |
| 화면 | @tanstack/react-query | 5.105.1 |
| 화면 | dayjs / typescript / vite | ^1.11.23 / 7.0.2 / 8.3.5 |

`cryptography`, `PyNaCl`, `ecdsa`, `rsa`는 .venv에 없다. 서명 검증은 직접 구현해야 한다.

---

## A. 모듈 켜기/끄기 + 라이선스

### 써야 할 기존 시설

| 시설 | 용도 | 왜 | 신뢰도 |
|------|------|----|--------|
| Django 미들웨어 `process_view` (클래스형) | 꺼진 모듈의 URL 차단 | `request.resolver_match`가 `process_view` 호출 전에 채워진다(`django/core/handlers/base.py:315-317`로 확인). 경로 문자열 대신 `url_name`·`namespaces`로 판정해 URL을 고쳐도 대응표가 안 깨진다. 기존 `core/middleware.py`는 함수형이므로 이 파일에 클래스를 추가한다. | HIGH |
| `MIDDLEWARE` 위치 | `AuthenticationMiddleware` 뒤, `no_store_pages` 근처 | 시스템 관리자 GET·종결 화이트리스트가 `request.user`를 봐야 한다. `HistoryRequestMiddleware` 뒤에 두면 차단 응답도 같은 요청 맥락을 쓴다. | HIGH |
| `django.urls.get_resolver().url_patterns` 재귀 순회 | 「URL 전수 매핑 테스트」 | 이름 붙은 모든 경로가 모듈에 매핑됐거나 명시적 면제인지 테스트로 강제한다. 새 경로가 빠지면 테스트가 실패한다. | HIGH |
| `admin.site._registry` | 관리 화면 URL → 모듈 대응표 생성 | 모델마다 `f'{app_label}_{model_name}_{changelist|add|change|delete|history}'` 이름을 만들어 수작업 목록을 없앤다. `_registry`는 비공개 이름이지만 `core/views.py`가 이미 `admin.site.is_registered`를 쓴다. 가능하면 `is_registered`와 `admin.site._registry` 순회 중 하나로 통일. | MEDIUM |
| `core/nav.py` `visible_nav(user)` | 사이드바·`/api/auth/me/` 메뉴 필터 | 두 곳이 이미 이 함수를 같이 쓴다. 여기서 `nav_url`의 url 이름으로 같은 대응표를 조회해 끈 모듈 항목을 뺀다. NAV 튜플에 4번째 칸을 더하지 않는다. | HIGH |
| `core/api/views.py` `me_payload` | 켜진 모듈 목록 전달 | React가 라우트·메뉴를 숨기는 데 쓴다. 숨김은 편의일 뿐 서버 미들웨어가 진짜 차단이다(AGENTS.md: 버튼 숨김만으로 막지 않는다). | HIGH |
| 모델 + `HistoricalRecords()` + `RunPython` 마이그레이션 | `ModuleSwitch` | 프로젝트 관례. 켜기/끄기 변경도 simple-history가 이력으로 남긴다(심사 증적). 데이터 마이그레이션은 「행 추가만」. | HIGH |
| `django.utils.timezone.now()` + `USE_TZ=True` | 만료일 비교 | 설정이 `Asia/Seoul`, `USE_TZ=True`. 만료일은 UTC 기준 aware datetime으로 저장·비교. | HIGH |

### Ed25519 검증기 (표준 라이브러리만)

- Python 3.12 표준 라이브러리에는 Ed25519 서명 검증이 없다. `hashlib.sha512`와 정수 연산(`pow(x, -1, p)`)으로 RFC 8032 5.1절 검증을 구현한다. RFC 8032 6절의 참조 구현이 짧다(약 80줄). (HIGH: 표준 라이브러리 부재는 확인. MEDIUM-HIGH: RFC 코드 형태는 기억 기반이므로 구현 전 RFC 원문 확인.)
- 위치: `core/licensing.py` 같은 별도 파일 하나. 모듈 켜기/끄기 대응표(`core/modules.py`)와 분리해 검증기만 단독 테스트한다.
- 검증 규칙(반드시): `S < L` 검사(서명 변조 방지), 공개키·R 점 복원 실패 시 거부, 길이 정확히 64바이트·32바이트.
- 서명 대상은 JSON을 다시 직렬화한 값이 아니라 파일에 들어 있는 원본 바이트다. 파일 = base64(payload 바이트) + base64(서명). 서명이 맞은 뒤에만 payload를 `json.loads`한다.
- 테스트: RFC 8032 7.1절 테스트 벡터(빈 메시지, 1바이트, 2바이트, 1023바이트, SHA(abc))를 단위 테스트로 넣는다. 발급 스크립트로 서명 → 검증기로 확인하는 왕복 테스트와, 한 바이트 바꾸면 실패하는 부정 테스트도 넣는다.
- 발급(서명) 스크립트는 같은 구현을 쓴다. 비밀키는 저장소·고객 PC에 두지 않는다(저장소 밖 파일, `.gitignore` 확인). 비상수시간 서명이지만 벤더 PC 오프라인 도구라 허용한다. 공개키만 앱에 박는다.
- 파일 읽기 비용: 요청마다 파싱하지 말고 `(경로, st_mtime_ns, st_size)`를 키로 결과를 모듈 변수에 보관한다.
- 모듈 켜짐 상태는 요청마다 1회 쿼리(행 십여 개)로 읽는다. 캐시하지 않는다. 이유: 설정에 `CACHES`가 없어 LocMemCache이고, `manage.py`로 바꾼 값이 waitress 프로세스의 캐시에 반영되지 않는다. 쿼리 비용은 무시할 수준이다. (HIGH)

### 하지 말 것 (A)

| 쓰지 않는다 | 이유 | 대신 |
|-------------|------|------|
| `cryptography`·`PyNaCl`·`PyJWT`·`python-jose` | 새 의존성 금지, 오프라인 고객 PC 설치 부담 | 표준 라이브러리 검증기 |
| `django-waffle`·`django-constance`·`django-flags` | 새 의존성. 켜기/끄기가 이력·마이그레이션·권한과 묶여야 한다 | `ModuleSwitch` 모델 |
| Django `Permission`/`Group` 박탈로 모듈 끄기 | `qms/apps.py` `ensure_roles`가 migrate마다 역할 권한을 다시 세팅해 되살아난다. 시스템 관리자(superuser)는 권한 박탈로 못 막는다. | 미들웨어 + 공용 `is_enabled()` |
| `ModelAdmin.has_module_permission` 오버라이드 37곳 | 화면별 구현, API·보고서·뷰는 못 막는다 | 미들웨어 한 곳 |
| 경로 접두사(`/admin/qms/…`) 문자열 매칭 | URL이 바뀌면 조용히 뚫린다 | `resolver_match.url_name`·`namespaces` + 전수 테스트 |
| 미들웨어만으로 끝내기 | 관리 명령(`notify`·`collect`)·위젯·검색·타임라인은 요청 경로가 아니다 | `core/modules.py`의 `is_enabled(key)` 하나를 미들웨어와 소비처(A4)가 함께 쓴다 |
| 기계 지문(MAC·디스크 번호) 묶기 | VM·PC 교체에서 정상 고객이 막힌다. 오프라인 파일 라이선스는 어차피 완전 방어가 불가능하다. | 고객명·발급일·만료일·모듈 목록만 서명 |

### 응답 모양 (A)

- `/api/` 요청이 차단되면 `JsonResponse({'detail': '…'}, status=404)`를 돌려준다. 그래야 `frontend/src/api/client.ts`가 `body.detail`을 읽는다. 일반 HTML 요청은 `Http404`를 raise한다.
- 읽기 전용(만료) 상태의 쓰기 거부는 403 JSON `{'detail': …}`. 403이면 `client.ts`가 `/api/auth/me/`로 로그인 여부를 한 번 더 확인하므로 로그인 상태에서는 그대로 오류 메시지가 뜬다.
- 읽기 전용 모드의 면제 목록(로그인·로그아웃·csrf·라이선스 갱신·**부적합 처분·보류 해제 등 인터록을 푸는 경로**)은 A3의 종결 화이트리스트와 같은 표를 쓴다. 인터록을 푸는 길을 막으면 안 된다(Core Value).

---

## B. 기록 설명서 + 범용 records API + React 화면

### 이름 충돌 (필수 확인)

`core/records.py`는 이미 있다. 삭제·잠금 규칙(`delete_record`, `blockers`, `edit_unlocked`, `can_edit_locked`, `is_locked`)이 들어 있고 `core/admin.py`, `core/views.py`, `core/rules.py`, `core/models.py`, `qms/admin.py`, `qms/api/specs.py`, `qms/api/plans.py`, `core/tests.py`가 가져다 쓴다. PROJECT.md B1의 「서버 기록 설명서 `core/records.py`」는 그대로 만들면 이 파일을 덮어쓰거나 깨뜨린다.

- **권고:** 설명서는 새 파일(예: `core/record_specs.py`)에 두고 기존 `core/records.py`는 건드리지 않는다. 설명서가 필요한 잠금·삭제 규칙은 `core.records`에서 가져온다. PROJECT.md·계획 문서의 파일명을 정정할 것. (HIGH)

### 서버: 써야 할 기존 시설

| 시설 | 용도 | 왜 | 신뢰도 |
|------|------|----|--------|
| `rest_framework.views.APIView` (+ `schema = None`) | records API 뷰 | 기존 API 전체가 이 방식이다(`core/api/master.py`, `qms/api/specs.py`). `ModelViewSet`·`DefaultRouter`는 모든 칸을 자동 노출하고 잠금·승인 규칙을 건너뛴다. | HIGH |
| `core.api.permissions.require_perm`, `IsStaff` | 권한 | `view_`/`add_`/`change_` 권한을 서버가 검사. 삭제는 `delete_as`가 시스템 관리자만 허용. | HIGH |
| `core.rules.save_with_lock`, `begin_edit`/`finish_edit`, `delete_as`, `approve`, `approve_and_log`, `dispose_nc`, `sign_disposition`, `request_revision_log`, `Locked`, `Stale` | 저장·승인·처분·삭제 | 업무 규칙이 이미 여기 있고 admin·API가 함께 쓴다. 범용 API는 새 규칙을 만들지 않고 이 함수만 호출한다. | HIGH |
| `django.forms.modelform_factory` | 값 변환·검증 | 아래 「검증 방식」 참조. | MEDIUM-HIGH |
| `core.grid.record_version` / `table_version` | 동시 수정 감지(`version` → 409) | 모든 업무 모델에 `history`가 있어 그대로 쓴다. 기존 품번·검사기준·관리계획서와 같은 방식이라 화면 동작이 일관된다. | HIGH |
| `core/api/exceptions.py` `handler` | 오류 응답 | `ValidationError`→400 `{detail, fields}`, `Locked`→409, `PermissionDenied`→403, `ProtectedError`→409, 404가 이미 변환된다. `Stale`은 뷰가 직접 잡아 409로 바꾼다(기존 뷰와 같게). | HIGH |
| `core.relations` (`relations_for`, `is_registered`, `record_url`) | 연결 기록 패널, 주소 일원화 | `_meta`에서 파생하므로 설명서가 따로 관계를 선언하지 않는다. `record_url`의 `pages` 딕셔너리를 설명서 등록 여부로 대체해 일원화한다. | HIGH |
| `core.audit` (`audited_models`, `rows`, `row_payload`) | 기록별 변경 이력 탭 | 이미 기록별 조회(`model`, `id`)가 된다. 다만 `/api/audit-log/`는 품질팀장 전용이므로 상세 화면용은 `view_` 권한 기준의 별도 엔드포인트가 필요하다(권한 정책은 사용자 결정 사항). | MEDIUM |
| simple-history `HistoryRequestMiddleware` (이미 `MIDDLEWARE`에 있음) | 변경자 기록 | `HistoricalRecords.context.request`를 요청 단위로 설정한다. DRF 세션 인증도 같은 `request.user`이므로 추가 작업이 없다. 사유를 남기려면 저장 전 `obj._change_reason = '…'`. | HIGH |
| `dataclasses` / `NamedTuple` | 설명서 자료형 | `core/relations.py`가 `NamedTuple`을 이미 쓴다. | HIGH |
| `@functools.cache` 레지스트리 | 설명서 조회 | `relations_for`와 같은 방식. | HIGH |

### 검증 방식: `ModelForm`을 쓰고 `ModelSerializer`는 쓰지 않는다

- DRF `ModelSerializer`는 `Model.clean()`/`full_clean()`을 호출하지 않는다(DRF의 알려진 동작). 이 프로젝트의 업무 규칙(인터록, MRB, 특채 승인번호 등)은 모델 `clean()`/`save()`에 있다. 직렬화기로 저장하면 규칙이 조용히 빠질 수 있다. (MEDIUM-HIGH: 알려진 동작이지만 이번 조사에서 코드로 재확인하지 못했다. 구현 첫 테스트로 확인할 것.)
- `ModelForm`은 `_post_clean`에서 `instance.full_clean()`을 호출해 모델 `clean()`이 실행되고, 날짜·소수·선택지·외래키 변환과 한국어 오류 메시지(`LANGUAGE_CODE='ko-kr'`)를 공짜로 얻는다. `form.errors`를 `{'detail', 'fields'}`로 바꿔 400을 돌려주면 `client.ts`와 antd `Form.setFields`가 그대로 받는다.
- **함정:** `ModelForm`에 일부 칸만 넘기면 빠진 칸이 비워진다(불리언은 False). 요청에 들어온 키 ∩ 설명서의 편집 가능 칸으로만 `modelform_factory(fields=…)`를 만든다. 설명서에 없는 칸은 400이 아니라 무시하지 말고 거부한다.
- 저장은 반드시 `save_with_lock(obj, user)`로. `QuerySet.update()`·`bulk_*`(simple-history의 `bulk_update_with_history` 포함)는 `save()` 보호와 인터록 가드를 건너뛰므로 업무 기록에 쓰지 않는다.
- 사용자 정의 칸(`FieldDef`, `core/admin.py`의 `ExtraFieldsForm`: `extra__<키>` → `extra` JSON)은 admin에서만 처리된다. 범용 화면이 `extra`를 다루려면 같은 변환을 `core/`로 옮겨 공유해야 한다. B1에서 대상 모델의 `extra` 사용 여부를 먼저 확인할 것.
- admin 폼에 따로 있는 규칙(`NonconformanceForm`, `ApprovalAdminMixin.get_readonly_fields`, `nc_locked_fields`)은 설명서의 `readonly`/잠금 칸 계산으로 옮겨야 한다. 부적합(B3)은 처분 서명 전용 본문으로 가므로 범용 저장 경로에서 제외한다.

### 서버: 설명서와 API 설계 결정

- **허용 목록 방식.** 설명서에 등록된 모델만 열린다. `relations.is_registered`는 제외 목록 방식이라 읽기에는 괜찮지만 쓰기 API에는 부족하다. `personal`(연차·급여)과 이력 표는 설명서에 없으므로 자연히 막힌다. `apps.get_model`에 입력 문자열을 바로 넣지 않는다.
- **칸 종류는 `_meta`에서 파생한다.** `CharField`→text, `TextField`→textarea, `DateField`/`DateTimeField`→date, `DecimalField`/`IntegerField`→number, `BooleanField`→bool, `choices`→select(`field.choices`), `ForeignKey`→원격 검색 선택. 설명서는 예외(읽기 전용 칸, 칸 묶음 순서, 목록 열, 검색 칸, 사용자 정의 본문)만 선언한다. 28종을 손으로 쓰지 않게 하려는 목적이다.
- **외래키 선택지 API.** `/api/records/<app.model>/options/?q=` 는 대상 모델의 `view_` 권한을 확인한 뒤 `[:20]`만 돌려준다(`RelationsView`·`ItemLookupView`와 같은 방식). 권한 확인이 없으면 볼 수 없는 기록 목록이 새어 나간다.
- **목록 응답 모양.** 기존 `{count, page, has_more, results}`와 `PAGE_SIZE = 50`을 따른다. 필터는 설명서가 선언한 칸만 `qs.filter()`로 적용하고 검색은 설명서의 검색 칸에 대한 `icontains` OR로 처리한다. DRF 페이지네이션 클래스·`django-filter`(기본 백엔드로 설치돼 있지만 기존 수작업 `APIView`는 쓰지 않는다)·`drf-spectacular` 문서화에는 의존하지 않는다.
- **URL 규칙.** `/api/records/<str:label>/` , `/<int:pk>/` 로 `relations`의 `app.model` 라벨 규칙과 맞춘다. 화면은 `/app/r/:app/:model/:id`.
- **삭제·수정 요청·승인.** 지금은 HTML 뷰(`core/views.py`의 `edit_request`, `approve`, `edit_request_decide`)가 로직을 인라인으로 갖고 있다. API가 쓰려면 `EditRequest` 생성+`decide` 부분을 `core/rules.py` 함수(예: `request_edit`)로 빼서 뷰와 API가 함께 호출하게 해야 한다. 이 최소 리팩터링은 B2 범위로 보고 계획에 명시한다(AGENTS.md의 「요청받지 않은 리팩터링 금지」 예외로 사용자 확인).

### 화면: 써야 할 기존 시설

| 시설 | 버전 | 용도 | 왜 | 신뢰도 |
|------|------|------|----|--------|
| antd `Form`, `Form.Item`, `Input`/`Input.TextArea`/`InputNumber`/`DatePicker`/`Select`/`Switch` | 6.6.8 | 설명서 기반 폼 렌더링 | 새 폼 라이브러리 없이 모든 칸 종류가 있다. 서버 오류 `fields`는 `form.setFields([{name, errors}])`로 칸에 붙인다(`useForm.d.ts`에서 `scrollToField` 등 확인). | HIGH |
| antd `Select` (`showSearch`, `filterOption={false}`, `onSearch`) | 6.6.8 | 외래키 원격 검색 | 위 options API와 짝. | HIGH |
| antd `Descriptions` 또는 기존 `RecordPage`의 `prop-cards` | 6.6.8 | 읽기 모드 본문 | B0가 `RecordShell`로 바꾸는 틀을 그대로 쓴다. | HIGH |
| dayjs | ^1.11.23 | `DatePicker` 값 변환 | 이미 `main.tsx`에서 `ko` 로케일 설정. 서버에는 ISO 문자열로 보낸다. | HIGH |
| `@tanstack/react-query` | 5.105.1 | 설명서·상세·목록 조회, 저장 뒤 무효화 | `useQuery`+`useMutation`. 키는 `['record', app, model, id]`. | HIGH |
| `react-router-dom` | 7.18.5 | `/app/r/:app/:model/:id` 라우트 | `main.tsx`의 `<Route>` 한 줄 추가와 `useParams`. 기존 `AppLayout` 아래에 둔다. | HIGH |
| `src/api/client.ts` `api()` | - | HTTP | CSRF 처리, 403 시 로그인 확인, `ApiError(detail, fields)` 변환이 이미 있다. | HIGH |
| `SaveBar`, `SignModal`, `EditGrid`, `DataList`, `RelationsPanel`, `MemoPanel`, `AttachmentPanel`, `AuditLog` | - | 본문·옆 열·서명 | 프로젝트가 이미 갖고 있다. 범용 화면은 이것들을 조립만 한다. | HIGH |

- **React Router 제약.** 앱은 `<BrowserRouter>`(선언형 모드)다. `useBlocker`, `loader`/`action`, `createBrowserRouter`는 쓸 수 없다. 저장 안 한 변경 경고는 `window`의 `beforeunload`와 기존 `SaveBar`로 처리한다. 라우터를 바꾸는 일은 이번 범위 밖이다. (HIGH: `main.tsx`와 grep으로 확인)
- **주소 이중 관리.** `AppLayout.tsx`의 `MOVED` 표(옛 관리 화면 주소 → `/app/…`)가 따로 하드코딩돼 있다. B에서 메뉴가 `/app/r/…`로 옮겨 가면 서버 `record_url`/`visible_nav`와 이 표가 어긋난다. 메뉴 href는 서버가 최종 주소를 내려주게 하고 `MOVED`는 점차 줄인다.
- **빌드 산출물.** `frontend/dist`가 커밋되고 Django `spa` 뷰가 `dist/index.html`을 읽는다. 화면 변경 단계마다 `npm run build`(`tsc -b && vite build`, TypeScript 7.0.2) 결과를 함께 커밋한다.
- **모듈 끔과 화면.** 꺼진 모듈의 `/app/r/:app/:model/:id`는 records API가 미들웨어에서 404로 막히므로 화면은 404 안내만 보이면 된다. API 경로(`/api/records/…`)도 A의 대응표에 등록해야 한다. 범용 경로 하나가 모듈 게이트를 우회하는 구멍이 되지 않도록, **모델 → 모듈 대응**을 `url_name`이 아니라 `app.model` 라벨로 판정하는 분기가 미들웨어에 필요하다(`resolver_match.kwargs['label']` 사용).

### 하지 말 것 (B)

| 쓰지 않는다 | 이유 | 대신 |
|-------------|------|------|
| `ModelViewSet`, `DefaultRouter`, 모델별 `ModelSerializer` | 칸 전체 노출, `clean()` 미호출, 잠금·승인·인터록 우회 | `APIView` + `ModelForm` + `core.rules` |
| `drf-spectacular` 스키마로 폼 생성(`schema` 직접 사용) | 기존 API가 모두 `schema = None`. 스키마가 잠금·권한 상태를 모른다 | 서버 설명서 JSON |
| `react-hook-form`, `formik`, `@rjsf/*`(JSON Schema 폼), `@ant-design/pro-components`, AG Grid, `axios`, `zustand`/`redux` | 새 의존성 금지, antd `Form` + react-query로 충분 | antd `Form`, `api()`, react-query |
| `jsonschema`·`attrs`·`PyYAML`을 코드에서 직접 import | requirements에 있지만 drf-spectacular의 전이 의존성이다. 직접 쓰면 숨은 의존이 생긴다 | `dataclasses`, 손으로 쓴 검사 |
| `queryset.update()`, `bulk_create/update` | `save()` 가드와 이력 우회 | `save_with_lock` |
| React Router 데이터 라우터 기능 | 현재 `BrowserRouter`. 전환은 범위 밖 | `beforeunload` + `SaveBar` |
| 외부 CDN·폰트·아이콘 | 오프라인 동작 원칙 | `@ant-design/icons`(이미 설치) |

---

## 대안 검토

| 항목 | 권고 | 대안 | 대안을 쓰지 않는 이유 |
|------|------|------|----------------------|
| Ed25519 검증 | 표준 라이브러리 순수 구현 | `cryptography` | 새 의존성 금지. 오프라인 설치 부담 |
| Ed25519 검증 | 순수 구현 | HMAC(`hmac`)으로 대칭 서명 | 고객 PC에 비밀키가 있어야 해서 위조 가능. 비대칭이어야 의미가 있다 |
| 모듈 상태 보관 | DB `ModuleSwitch` + 이력 | 설정 파일/환경변수 | 변경 이력·시스템 관리자 화면·마이그레이션과 맞지 않는다 |
| 켜짐 판정 캐시 | 요청마다 1쿼리 | LocMemCache | 별도 프로세스(`manage.py`)의 변경이 반영되지 않는다 |
| 저장 검증 | `ModelForm` | `ModelSerializer`, `collect_rows`(`core/grid.py`) | 전자는 `clean()` 미호출. 후자는 칸 종류가 text/fk/number/int뿐이라 날짜·불리언·선택지가 없다(하위 줄 표에는 계속 사용) |
| 목록 필터 | 설명서 선언 칸 + 수작업 `filter()` | `django-filter` `FilterSet` | 기존 수작업 뷰와 일관성. 필터 종류가 늘면 `filterset_factory`를 재검토 |
| 동시 수정 | `record_version`(이력 최대 id 합) | 행 `updated_at` 칸 추가 | 스키마 변경 필요. 이력 방식이 이미 검증됨 |

## 호환성 메모

| 조합 | 메모 |
|------|------|
| Django 6.1.2 + simple-history 3.13.0 | 이미 운영 중. 신규 모델 추가 시 `history = HistoricalRecords()` 유지, `makemigrations --check --dry-run` 통과 필요 |
| DRF 3.18.3 + 세션 인증 | `SessionAuthentication`이 CSRF를 강제한다. 새 쓰기 뷰도 `client.ts`의 `X-CSRFToken` 경로를 그대로 탄다 |
| antd 6.6.8 + React 19.3.1 | 이미 빌드·운영 중. 새 antd 컴포넌트는 `Alert`의 `title`처럼 v6 속성명을 확인하고 쓴다(`AppLayout`이 v6 방식 사용) |
| TypeScript 7.0.2 | `tsc -b`가 빌드 게이트. 설명서 응답 타입을 `src/api/`에 선언한다 |

## 설치

없음. `requirements.txt`, `frontend/package.json`은 변경하지 않는다.

## 출처 및 신뢰도

- 읽은 코드(HIGH): `requirements.txt`, `frontend/package.json`, `frontend/package-lock.json`, `config/settings.py`, `config/urls.py`, `core/middleware.py`, `core/records.py`, `core/rules.py`, `core/grid.py`, `core/nav.py`, `core/relations.py`, `core/audit.py`, `core/api/{urls,views,master,permissions,exceptions}.py`, `qms/api/{urls,specs}.py`, `core/views.py`(approve·edit_request), `core/admin.py`(구조), `frontend/src/{main.tsx,api/client.ts,layout/AppLayout.tsx,components/RecordPage.tsx,components/SaveBar.tsx}`
- `.venv/Lib/site-packages/django/core/handlers/base.py` — `resolver_match` 설정 시점(HIGH)
- `.venv/Lib/site-packages/simple_history/middleware.py` — 요청 맥락 설정(HIGH)
- `frontend/node_modules/antd/es/form/hooks/useForm.d.ts` — Form 인스턴스 API(HIGH)
- RFC 8032 구조·테스트 벡터, DRF `ModelSerializer`의 `clean()` 미호출: 기존 지식 기반(MEDIUM-HIGH). 구현 첫 단계에서 RFC 원문과 작은 테스트로 확인.

## 한계

- 이번 조사에서 셸(Bash 도구)이 동작하지 않아 `manage.py`·테스트를 실행하지 못했다. 위 내용은 코드 읽기와 grep에 근거한다.
- 설명서가 `FieldDef` 사용자 정의 칸과 admin 전용 폼 규칙을 어디까지 따라가야 하는지는 B1·B3 단계에서 모델별로 다시 확인해야 한다.
- 만료 시 시계 되돌리기 방지(마지막 확인 시각을 DB에 기록)는 권고 수준이며 완전 방어가 아니다.
