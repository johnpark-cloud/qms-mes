"""관리 화면에 실제 HTTP 요청을 보내 인터록을 끝까지 확인한다 (임시 DB 사용)."""
import http.cookiejar, os, re, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(PROJ, '.venv', 'Scripts', 'python.exe')
BASE = 'http://127.0.0.1:8765'
env = dict(os.environ, QMS_DATA_DIR=tempfile.mkdtemp(), DJANGO_SUPERUSER_PASSWORD='e2e-pass-123')

def manage(*args, **kw):
    return subprocess.run([PY, 'manage.py', *args], cwd=PROJ, env=env, check=True, capture_output=True, **kw)

manage('migrate')
manage('createsuperuser', '--noinput', '--username', 'mrb', '--email', 'mrb@example.com')
server = subprocess.Popen([PY, 'manage.py', 'runserver', '8765', '--noreload'], cwd=PROJ, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None
post_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)

def get(path):
    return opener.open(BASE + path).read().decode()

def post(path, data):
    get(path)  # CSRF 쿠키 확보
    token = next(c.value for c in jar if c.name == 'csrftoken')
    body = urllib.parse.urlencode({'csrfmiddlewaretoken': token, **data}).encode()
    try:
        r = post_opener.open(BASE + path, body)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def post_only(path, data):
    """GET이 없는 주소(htmx 판정 등)용: 이미 받은 CSRF 쿠키로 바로 POST."""
    token = next(c.value for c in jar if c.name == 'csrftoken')
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, body, headers={'X-CSRFToken': token, 'HX-Request': 'true'})
    try:
        r = post_opener.open(req)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def errors(html):
    return re.findall(r'<ul class="errorlist[^"]*"[^>]*>(.*?)</ul>', html, re.S)

results = []
def check(name, ok, detail=''):
    results.append(ok)
    print(('PASS' if ok else 'FAIL'), name, detail)

now = {'_0': '2026-10-23', '_1': '09:00:00'}
def dt(field):
    return {field + k: v for k, v in now.items()}

no_inline = {'parent_links-TOTAL_FORMS': 0, 'parent_links-INITIAL_FORMS': 0,
             'parent_links-MIN_NUM_FORMS': 0, 'parent_links-MAX_NUM_FORMS': 1000}
def with_input(parent_id):
    return {**no_inline, 'parent_links-TOTAL_FORMS': 1, 'parent_links-0-parent': parent_id, 'parent_links-0-qty': 1}

try:
    for _ in range(50):
        try:
            get('/admin/login/'); break
        except Exception:
            time.sleep(0.3)
    s, _ = post('/admin/login/?next=/admin/', {'username': 'mrb', 'password': 'e2e-pass-123', 'next': '/admin/'})
    check('로그인', s == 302)

    bom = {f'{p}-{k}': v for p in ('bom_lines', 'routing')
           for k, v in (('TOTAL_FORMS', 0), ('INITIAL_FORMS', 0), ('MIN_NUM_FORMS', 0), ('MAX_NUM_FORMS', 1000))}
    s, html = post('/admin/core/item/add/', {'code': 'R1', 'name': '양극재', 'item_type': 'RAW', **bom})
    check('품번 R1(원자재) 등록', s == 302, errors(html) or re.findall(r'ManagementForm[^<]*', html))
    s, _ = post('/admin/core/item/add/', {'code': 'C1', 'name': '셀', 'item_type': 'FIN', **bom})
    check('품번 C1(완제품) 등록', s == 302)

    s, _ = post('/admin/core/lot/add/', {'number': 'RAW-1', 'item': 1, 'qty': 100, **dt('created_at'), **no_inline})
    check('LOT RAW-1 등록', s == 302)
    s, _ = post('/admin/core/lot/add/', {'number': 'CELL-A', 'item': 2, 'qty': 1, **dt('created_at'), **with_input(1)})
    check('LOT CELL-A 등록 (투입: RAW-1)', s == 302)
    s, _ = post('/admin/core/lot/add/', {'number': 'CELL-Z', 'item': 2, 'qty': 1, **dt('created_at'), **no_inline})
    check('LOT CELL-Z 등록 (무관한 LOT, 계보 없음)', s == 302)

    kpi = {'defect_type': '이물', 'defect_qty': 3, 'cost': 50000}  # 브라우저는 기본값 0을 채워 보낸다
    kpi.update({'origin': 'INCOMING', 'photos-TOTAL_FORMS': 0, 'photos-INITIAL_FORMS': 0, 'photos-MIN_NUM_FORMS': 0,
                'photos-MAX_NUM_FORMS': 1000})
    s, _ = post('/admin/core/nonconformance/add/', {'lot': 1, 'description': '이물 혼입', **dt('detected_at'), **kpi})
    check('부적합 등록 (RAW-1)', s == 302)

    html = get('/trace/?lot=CELL-A')
    check('추적: CELL-A 자동 보류됨', '보류 중' in html)
    check('추적: 상위 계보에 RAW-1 표시', 'RAW-1' in html)
    html = get('/trace/?lot=CELL-Z')
    check('추적: 무관한 CELL-Z는 보류 아님', '보류 중' not in html)
    check('추적: CELL-Z는 계보 미등록 표시', '계보 미등록' in html)

    s, html = post('/admin/core/shipment/add/', {'lot': 2, 'customer': 'A사', 'qty': 1, **dt('shipped_at')})
    check('출하 차단 (보류된 CELL-A)', s == 200 and '보류 중' in html, errors(html))
    s, html = post('/admin/core/lot/add/', {'number': 'MOD-1', 'item': 2, 'qty': 1, **dt('created_at'), **with_input(2)})
    check('투입 차단 (보류된 CELL-A를 MOD-1에 투입)', s == 200 and '보류 중' in html, errors(html))
    s, _ = post('/admin/core/shipment/add/', {'lot': 3, 'customer': 'A사', 'qty': 1, **dt('shipped_at')})
    check('무관한 CELL-Z는 출하 가능', s == 302)

    nc = {'lot': 1, 'description': '이물 혼입', **dt('detected_at'), **kpi, 'password': 'e2e-pass-123'}
    s, html = post('/admin/core/nonconformance/1/change/', {**nc, 'disposition': 'SCRAP'})
    check('긴급 조치 비어 있음 → 처분 거부 (보완 필요)', s == 200 and '보완 필요' in html, errors(html))
    nc.update({'contained_qty': 3, 'sorting_result': '재고 전수 선별'})
    s, html = post('/admin/core/nonconformance/1/change/', {**nc, 'disposition': 'CONCESSION', 'password': 'wrong',
                                                            'customer_approval_ref': 'CA-001'})
    check('MRB 비밀번호 틀림 → 거부', s == 200 and '비밀번호' in html, errors(html))
    s, html = post('/admin/core/nonconformance/1/change/', {**nc, 'disposition': 'CONCESSION'})
    check('특채인데 고객 승인번호 없음 → 거부', s == 200 and '고객 승인' in html, errors(html))
    s, html = post('/admin/core/nonconformance/1/change/', {**nc, 'disposition': 'REWORK'})
    check('재작업인데 재검사 미합격 → 거부', s == 200 and '재검사' in html, errors(html))
    s, html = post('/admin/core/nonconformance/1/change/', {**nc, 'disposition': 'CONCESSION', 'customer_approval_ref': 'CA-001'})
    check('특채 + 고객 승인번호 → 처분 저장', s == 302, errors(html))

    check('추적: CELL-A 보류 해제됨', '보류 중' not in get('/trace/?lot=CELL-A'))
    s, _ = post('/admin/core/shipment/add/', {'lot': 2, 'customer': 'A사', 'qty': 1, **dt('shipped_at')})
    check('보류 해제 후 CELL-A 출하 가능', s == 302)

    html = get('/admin/core/nonconformance/1/history/')
    check('변경 이력 기록됨', 'CONCESSION' in html or '특채' in html)

    # 검사기준 작성 → 승인 서명 → 검사 → 판정(불합격) → 부적합·보류 자동
    s, html = post('/admin/qms/inspectionspec/add/', {
        'item': 1, 'inspection_type': 'INCOMING', 'revision': 1, 'sampling': 'n=1', 'note': '',
        'characteristics-TOTAL_FORMS': 1, 'characteristics-INITIAL_FORMS': 0, 'characteristics-MIN_NUM_FORMS': 0,
        'characteristics-MAX_NUM_FORMS': 1000, 'characteristics-0-name': '두께',
        'characteristics-0-lsl': '9.5', 'characteristics-0-usl': '10.5', 'characteristics-0-unit': 'mm'})
    check('검사기준 등록 (두께 9.5~10.5)', s == 302, errors(html))
    s, html = post('/admin/qms/inspection/add/', {'lot': 1, 'spec': 1, **dt('inspected_at'), **{
        'measurements-TOTAL_FORMS': 0, 'measurements-INITIAL_FORMS': 0,
        'measurements-MIN_NUM_FORMS': 0, 'measurements-MAX_NUM_FORMS': 1000}})
    check('미승인 기준으로 검사 → 거부', s == 200, errors(html))
    s, _ = post('/approve/qms/inspectionspec/1/', {'password': 'wrong'})
    check('승인 서명: 비밀번호 틀림 → 미승인', s == 200)
    s, _ = post('/approve/qms/inspectionspec/1/', {'password': 'e2e-pass-123'})
    check('승인 서명: 비밀번호 맞음 → 승인', s == 302)
    s, html = post('/admin/qms/inspection/add/', {'lot': 1, 'spec': 1, **dt('inspected_at'), **{
        'measurements-TOTAL_FORMS': 1, 'measurements-INITIAL_FORMS': 0, 'measurements-MIN_NUM_FORMS': 0,
        'measurements-MAX_NUM_FORMS': 1000, 'measurements-0-characteristic': 1, 'measurements-0-value': '11.2',
        'measurements-0-ok': 'unknown'}})
    check('검사 등록 (RAW-1 두께 11.2)', s == 302, errors(html))
    s, html = post('/admin/qms/inspection/1/change/', {'_finalize': '1', **{
        'measurements-TOTAL_FORMS': 1, 'measurements-INITIAL_FORMS': 1, 'measurements-MIN_NUM_FORMS': 0,
        'measurements-MAX_NUM_FORMS': 1000, 'measurements-0-id': 1, 'measurements-0-inspection': 1,
        'measurements-0-characteristic': 1, 'measurements-0-value': '11.2', 'measurements-0-ok': 'unknown'}})
    check('판정하기', s == 302, errors(html))
    html = get('/trace/?lot=CELL-A')
    check('불합격 → 부적합 자동 등록, CELL-A 다시 보류', '보류 중' in html)
    check('내 할 일에 열린 부적합 표시', 'RAW-1' in get('/todo/'))
    check('SPC 화면 열림', 'SPC' in get('/spc/1/'))

    # 검사원 입력 화면 + 계측기 교정 인터록
    check('검사 입력 화면이 동봉된 htmx를 불러옴', 'htmx.min.js' in get('/inspect/') and 'htmx' in get('/static/htmx.min.js'))
    check('LOT 스캔 → 수입검사 선택지 표시', '수입검사' in get('/inspect/lot/?lot=RAW-1'))
    gauge = {'name': '마이크로미터', 'interval_days': 365, 'active': 'on'}
    s, html = post('/admin/qms/gauge/add/', {**gauge, 'number': 'MC-OLD', 'last_calibrated': '2024-01-01'})
    check('계측기 등록 (교정 만료)', s == 302, errors(html))
    s, html = post('/admin/qms/gauge/add/', {**gauge, 'number': 'MC-NEW', 'last_calibrated': '2026-10-01'})
    check('계측기 등록 (교정 유효)', s == 302, errors(html))
    s, html = post_only('/inspect/1/1/submit/', {'c1': '10.0', 'gauge': 1})
    check('교정 만료 계측기로 판정 → 거부, 저장 안 됨', '교정 기한' in html and '저장하지 않았습니다' in html)
    s, html = post_only('/inspect/1/1/submit/', {'c1': '10.0', 'gauge': 2})
    check('유효 계측기로 판정 → 합격', 'RAW-1 합격' in html, html[:200])

    # 4M 변경: 승인 후 초품 합격 전 출하 차단
    s, html = post('/admin/qms/changerequest/add/', {
        'number': '4M-1', 'item': 2, 'category': 'MACHINE', 'description': '조립 설비 교체',
        'customer_notice': 'on', 'customer_approval_ref': 'CA-4M', **dt('effective_at')})
    check('4M 변경 등록', s == 302, errors(html))
    s, _ = post('/approve/qms/changerequest/1/', {'password': 'e2e-pass-123'})
    check('4M 변경 승인 서명', s == 302)
    s, html = post('/admin/core/shipment/add/', {'lot': 3, 'customer': 'A사', 'qty': 1, **dt('shipped_at')})
    check('초품 전 CELL-Z 출하 차단', s == 200 and '초품' in html, errors(html))
    s, html = post('/admin/qms/inspectionspec/add/', {
        'item': 2, 'inspection_type': 'OUTGOING', 'revision': 1, 'sampling': '', 'note': '',
        'characteristics-TOTAL_FORMS': 1, 'characteristics-INITIAL_FORMS': 0, 'characteristics-MIN_NUM_FORMS': 0,
        'characteristics-MAX_NUM_FORMS': 1000, 'characteristics-0-name': '용량',
        'characteristics-0-lsl': '95', 'characteristics-0-usl': '105', 'characteristics-0-special': 'CC'})
    check('셀 출하검사 기준 등록', s == 302, errors(html))
    post('/approve/qms/inspectionspec/2/', {'password': 'e2e-pass-123'})
    s, html = post_only('/inspect/3/2/submit/', {'c2': '100'})
    check('CELL-Z 초품 검사 합격', 'CELL-Z 합격' in html, html[:200])
    s, html = post('/admin/core/shipment/add/', {'lot': 3, 'customer': 'A사', 'qty': 1, **dt('shipped_at')})
    check('초품 합격 후 CELL-Z 출하 가능', s == 302, errors(html))
    check('출하성적서에 용량 결과', '용량' in get('/print/core/shipment/3/'))

    # 대시보드 · 디자인
    check('품질 KPI 화면 (불량유형 파레토)', '이물' in get('/kpi/'))
    check('협력사 성적표 화면', '협력사 성적표' in get('/suppliers/'))
    check('Fiori 디자인 CSS 적용·제공', 'qms/fiori.css' in get('/todo/') and '--f-brand' in get('/static/qms/fiori.css'))

    # 공정 라우팅 · 작업 실적: 공정 건너뛰기 차단
    post('/admin/core/process/add/', {'code': 'P10', 'name': '적층'})
    post('/admin/core/process/add/', {'code': 'P20', 'name': '용접'})
    routing = {**bom, 'routing-TOTAL_FORMS': 2, 'routing-0-seq': 10, 'routing-0-process': 1,
               'routing-1-seq': 20, 'routing-1-process': 2}
    s, html = post('/admin/core/item/2/change/', {'code': 'C1', 'name': '셀', 'item_type': 'FIN', **routing})
    check('셀 라우팅 등록 (10 적층 → 20 용접)', s == 302, errors(html))
    s, html = post('/admin/core/workorder/add/', {'number': 'WO-1', 'item': 2, 'planned_qty': 100, 'status': 'PLANNED',
                                                  'results-TOTAL_FORMS': 0, 'results-INITIAL_FORMS': 0,
                                                  'results-MIN_NUM_FORMS': 0, 'results-MAX_NUM_FORMS': 1000})
    check('작업지시 등록', s == 302, errors(html))
    result = {'work_order': 1, 'input_qty': 10, 'good_qty': 10, 'defect_qty': 0, 'operator': 1, **dt('started_at')}
    s, html = post('/admin/core/workresult/add/', {**result, 'step': 2})
    check('적층 없이 용접 실적 → 차단', s == 200 and '이전 공정' in html, errors(html))
    s, html = post('/admin/core/workresult/add/', {**result, 'step': 1})
    check('적층 실적 등록', s == 302, errors(html))
    s, html = post('/admin/core/workresult/add/', {**result, 'step': 2})
    check('적층 후 용접 실적 등록', s == 302, errors(html))

    # CAPA: 유효성 확인 없이 종결 차단
    capa = {'number': 'CAPA-E2E-1', 'title': '재발 방지', 'source': 'NC', 'action': '조치', 'owner': 1,
            'due_date': '2026-11-30', 'effective': 'unknown'}
    s, html = post('/admin/qms/capa/add/', capa)
    check('CAPA 등록', s == 302, errors(html))
    s, html = post('/admin/qms/capa/1/change/', {**capa, 'closed_at': '2026-10-26'})
    check('유효성 확인 없이 CAPA 종결 → 차단', s == 200 and '유효' in html, errors(html))

    # PPAP: 제출(S) 증적 없으면 PSW 서명 거부
    s, html = post('/admin/qms/ppapsubmission/add/', {'item': 2, 'customer': 'A사', 'level': 1, 'reason': '신규',
                                                      'elements-TOTAL_FORMS': 0, 'elements-INITIAL_FORMS': 0,
                                                      'elements-MIN_NUM_FORMS': 0, 'elements-MAX_NUM_FORMS': 1000})
    check('PPAP 제출 등록 → PSW 인쇄에 요소표', s == 302 and '외관 승인 보고서' in get('/print/qms/ppapsubmission/1/'), errors(html))
    s, html = post('/approve/qms/ppapsubmission/1/', {'password': 'e2e-pass-123'})
    check('외관승인(S) 증적 없이 PSW 서명 → 거부', s == 200 and '증적이 없습니다' in html)
finally:
    server.terminate()

print(f'\n{sum(results)}/{len(results)} 통과')
sys.exit(0 if all(results) else 1)

