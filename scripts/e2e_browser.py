"""React 화면(/app/)을 실제 브라우저로 끝까지 확인한다 (임시 DB 사용).
시스템 Python의 Playwright가 필요하다: python scripts\\e2e_browser.py
"""
import os, subprocess, sys, tempfile, time, urllib.request

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(PROJ, '.venv', 'Scripts', 'python.exe')
BASE = 'http://127.0.0.1:8766'
env = dict(os.environ, QMS_DATA_DIR=tempfile.mkdtemp(), DJANGO_SUPERUSER_PASSWORD='e2e-pass-123')

def manage(*args):
    return subprocess.run([PY, 'manage.py', *args], cwd=PROJ, env=env, check=True, capture_output=True)

manage('migrate')
manage('createsuperuser', '--noinput', '--username', 'boss', '--email', 'boss@example.com')
server = subprocess.Popen([PY, 'manage.py', 'runserver', '8766', '--noreload'], cwd=PROJ, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

results = []
def check(name, ok, detail=''):
    results.append(ok)
    print(('PASS' if ok else 'FAIL'), name, detail)

def api_get(page, path):
    return page.evaluate("p => fetch(p, {credentials: 'same-origin'}).then(r => r.json())", path)

try:
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + '/api/auth/csrf/'); break
        except Exception:
            time.sleep(0.3)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:  # 내려받은 Chromium이 없으면 PC에 깔린 Edge를 쓴다
            browser = p.chromium.launch(channel='msedge')
        page = browser.new_context(base_url=BASE).new_page()
        page.set_default_timeout(8000)

        page.goto('/app/login')
        page.get_by_label('아이디').fill('boss')
        page.get_by_label('비밀번호').fill('e2e-pass-123')
        page.get_by_role('button', name='로그인').click()
        try:
            page.wait_for_url('**/app/todo'); ok = True
        except Exception:
            ok = False
        check('로그인 → 내 할 일로 이동', ok, page.url)

        page.goto('/app/overview')
        want = sum(len(s['cards']) for s in api_get(page, '/api/qms/overview/')['sections'])
        try:
            page.locator('[data-card]').first.wait_for()
        except Exception:
            pass
        got = page.locator('[data-card]').count()
        check('종합현황 카드 수가 API와 같음', want > 0 and got == want, f'API {want}, 화면 {got}')

        page.goto('/app/todo')
        try:
            page.locator('[data-widget]').first.wait_for()
        except Exception:
            pass
        before = page.locator('[data-widget]').count()
        shown = {w.get_attribute('data-widget') for w in page.locator('[data-widget]').all()}
        todo = api_get(page, '/api/qms/todo/')
        pick = next((a for a in todo['available'] if a['key'] not in shown), None)
        added = False
        if pick:
            try:
                page.get_by_label('위젯 추가').click()
                page.locator('.ant-select-item-option', has_text=pick['title']).first.click()
                page.wait_for_function('n => document.querySelectorAll("[data-widget]").length === n', before + 1)
            except Exception:
                pass
            page.reload()
            try:
                page.locator('[data-widget]').first.wait_for()
            except Exception:
                pass
            added = page.locator(f'[data-widget="{pick["key"]}"]').count() == 1 and page.locator('[data-widget]').count() == before + 1
        check('내 할 일: 위젯 추가 후 새로고침해도 남음', added, f'{before}개 → {page.locator("[data-widget]").count()}개')

        for path in ('/app/overview', '/app/todo'):
            page.set_viewport_size({'width': 390, 'height': 800})
            page.goto(path)
            page.locator('[data-card], [data-widget]').first.wait_for()
            w = page.evaluate('document.documentElement.scrollWidth')
            check(f'390px 폭 가로 스크롤 없음 {path}', w <= 390, f'scrollWidth {w}')
        page.set_viewport_size({'width': 1280, 'height': 800})

        # 로고: data/brand 에 없으면 글자, 넣으면 새로고침만으로 왼쪽 위에 그림이 보인다
        page.goto('/app/todo')
        try:  # 그림 요청이 404 로 끝나야 글자로 바뀐다
            page.locator('header strong', has_text='QMS+MES').wait_for(); text_ok = True
        except Exception:
            text_ok = False
        os.makedirs(os.path.join(env['QMS_DATA_DIR'], 'brand'), exist_ok=True)
        with open(os.path.join(env['QMS_DATA_DIR'], 'brand', 'logo.svg'), 'w') as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="32"><rect width="120" height="32" fill="#0057d2"/></svg>')
        page.reload()
        img = page.locator('header img.shell-brand')
        try:
            img.wait_for()
            page.wait_for_function('() => document.querySelector("header img.shell-brand")?.naturalWidth > 0')
            box = img.bounding_box()
            img_ok = box['x'] < 40 and box['y'] < 40
        except Exception:
            img_ok, box = False, None
        check('로고: 없으면 글자, 넣으면 왼쪽 위 그림', text_ok and img_ok, f'글자 {text_ok}, 그림 {box}')

        bg = lambda: page.evaluate('getComputedStyle(document.body).backgroundColor')
        page.emulate_media(color_scheme='light')
        page.wait_for_timeout(300)
        light = bg()
        page.emulate_media(color_scheme='dark')
        page.wait_for_timeout(300)
        dark = bg()
        check('다크 모드 배경색이 라이트와 다름', light != dark, f'{light} / {dark}')
        page.emulate_media(color_scheme='light')

        manage('shell', '-c', "from core.models import Item, Lot; i=Item.objects.create(code='E2E-R1', name='E2E 양극재', item_type='RAW'); Lot.objects.create(number='RAW-2611-001', item=i)")
        page.goto('/app/todo')
        page.get_by_role('button', name='명령창 열기').wait_for()  # 화면이 뜬 뒤에 단축키를 누른다
        page.keyboard.press('Control+k')
        page.get_by_placeholder('LOT·품번·번호 또는 동작').fill('2611')
        page.locator('[data-palette-item]').first.wait_for()
        page.keyboard.press('Enter')
        page.wait_for_url('**/trace/?lot=RAW-2611-001')
        check('명령창: LOT 일부 + Enter → 그 기록', '/trace/?lot=RAW-2611-001' in page.url, page.url)

        page.goto('/app/todo')
        page.get_by_role('button', name='명령창 열기').wait_for()  # 화면이 뜬 뒤에 단축키를 누른다
        page.keyboard.press('Control+k')
        page.get_by_placeholder('LOT·품번·번호 또는 동작').fill('없는번호-zz')
        page.get_by_text('찾는 기록이 없습니다').wait_for()
        page.keyboard.press('Enter'); page.wait_for_timeout(300)
        check('명령창 결과 없음 Enter → 이동 안 함', page.url.endswith('/app/todo'), page.url)

        ctx2 = browser.new_context(base_url=BASE, storage_state=page.context.storage_state())
        ctx2.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked') }})")
        p2 = ctx2.new_page(); p2.goto('/app/todo')
        try:
            p2.locator('[data-widget]').first.wait_for(); ok = True
        except Exception:
            ok = False
        check('localStorage 차단에도 화면 정상', ok)
        ctx2.close()

        page.goto('/app/specs')
        try:
            page.get_by_role('button', name='새 기준서').click()
            page.get_by_label('품번').fill('E2E-R1')
            page.locator('.ant-select-item-option', has_text='E2E-R1').click()
            page.get_by_label('검사 구분').click()
            page.locator('.ant-select-item-option', has_text='수입검사').click()
            page.get_by_role('button', name='만들기').click()
        except Exception:
            pass
        try:
            page.wait_for_url('**/app/specs/*')
        except Exception:
            pass
        spec_id = page.url.rstrip('/').split('/')[-1]
        try:
            ok = api_get(page, f'/api/qms/specs/{spec_id}/')['revision'] == 1
        except Exception:
            ok = False
        check('새 기준서 → Rev.1 초안 페이지', ok, page.url)

        page.goto('/app/specs')
        try:
            page.locator('[data-row]').first.wait_for(timeout=5000)
        except Exception:
            pass
        want = api_get(page, '/api/qms/specs/?tab=all')['count']
        check('검사기준 목록 줄 수가 API와 같음', want > 0 and page.locator('[data-row]').count() == want, f'API {want}')
        try:
            with page.expect_download(timeout=5000) as dl:
                page.get_by_role('link', name='엑셀로').click()
            check('목록 엑셀로 받기', open(dl.value.path(), 'rb').read(2) == b'PK', dl.value.suggested_filename)
        except Exception as e:
            check('목록 엑셀로 받기', False, str(e)[:80])

        # 기록 페이지: 엑셀 붙여넣기 → 저장 → 승인 → 새 개정
        tsv = '\n'.join(f'항목{i}\t{i},000.5\t{i + 1},000.9\tmm' if i != 3 else f'항목{i}\t\t\t' for i in range(1, 11))
        try:
            page.goto(f'/app/specs/{spec_id}')
            first = page.locator('[data-grid] [data-grid-row] input').first
            first.click()
            page.evaluate("t => { const dt = new DataTransfer(); dt.setData('text/plain', t);"
                          " document.activeElement.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true})) }", tsv)
            page.get_by_text('변경 10건').wait_for(timeout=5000)
            page.keyboard.press('Control+s')
            page.get_by_text('저장했습니다').wait_for(timeout=5000)
            chars = api_get(page, f'/api/qms/specs/{spec_id}/')['characteristics']
            check('검사항목 10줄 붙여넣기 → 저장 → 서버 10개', len(chars) == 10 and chars[0]['lsl'] == '1000.5', f'{len(chars)}개')
        except Exception as e:
            check('검사항목 10줄 붙여넣기 → 저장 → 서버 10개', False, str(e)[:80])

        draft_id = ''
        try:
            page.get_by_role('button', name='승인 서명').click()
            page.get_by_label('비밀번호').fill('e2e-pass-123')
            page.get_by_role('button', name='서명', exact=True).click()
            page.get_by_text('승인됨').first.wait_for(timeout=5000)
            page.get_by_role('button', name='새 개정').wait_for(timeout=5000)
            before = page.locator('[data-grid] [data-grid-row] input').first.input_value()
            page.locator('[data-grid] [data-grid-row] input').first.click()
            page.evaluate("t => { const dt = new DataTransfer(); dt.setData('text/plain', t);"
                          " document.activeElement.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true})) }", 'X1\tX2\nY1\tY2')
            page.wait_for_timeout(300)
            after = page.locator('[data-grid] [data-grid-row] input').first.input_value()
            check('잠긴 기준서 붙여넣기 → 변경 없음', page.get_by_text('변경 ').count() == 0 and after == before, f'{before!r} → {after!r}')
            page.get_by_role('button', name='새 개정').click()
            page.wait_for_function(f"() => !location.pathname.endsWith('/{spec_id}')", timeout=5000)
            draft_id = page.url.rstrip('/').split('/')[-1]  # 감사 기록·문서 점검이 쓴다
            new = api_get(page, f'/api/qms/specs/{draft_id}/')
            ok = new['revision'] == 2 and len(new['characteristics']) == 10
        except Exception:
            ok = False
        check('승인본 → 새 개정 → Rev.2 초안, 항목 복사', ok, page.url)

        # 인쇄 화면(PDF)·감사 기록
        try:
            page.goto(f'/app/specs/{spec_id}/print')
            page.locator('.doc-page').wait_for(timeout=5000)
            page.emulate_media(media='print')
            pdf = page.pdf(format='A4', print_background=True)
            pages = pdf.count(b'/Type /Page') - pdf.count(b'/Type /Pages')
            bar = page.locator('.print-bar').is_visible()
            check('승인본 인쇄 화면 → PDF A4 1쪽', pages == 1 and not bar, f'{pages}쪽, 인쇄 막대 보임={bar}')
        except Exception as e:
            check('승인본 인쇄 화면 → PDF A4 1쪽', False, str(e)[:80])
        page.emulate_media(media='screen')
        try:
            page.goto(f'/app/specs/{draft_id}/print')
            page.locator('.doc-page').wait_for(timeout=5000)
            check('초안 인쇄 화면에 "초안 — 승인 전"', page.get_by_text('초안 — 승인 전').count() >= 1)
        except Exception as e:
            check('초안 인쇄 화면에 "초안 — 승인 전"', False, str(e)[:80])
        try:
            page.goto(f'/app/audit?model=qms.inspectionspec&id={spec_id}')
            page.locator('[data-audit-row]').first.wait_for(timeout=5000)
            n = page.locator('[data-audit-row]').count()
            check('감사 기록: 저장 이력이 보임', n >= 2, f'{n}줄')
        except Exception as e:
            check('감사 기록: 저장 이력이 보임', False, str(e)[:80])

        # 검사 입력(/app/inspect)·측정·검사 목록·성적서
        manage('shell', '-c', (
            "import datetime; from django.contrib.auth import get_user_model; from django.utils import timezone;"
            "from core.models import Item, Lot; from qms.models import Characteristic, Gauge, InspectionSpec;"
            "i=Item.objects.create(code='E2E-I1', name='E2E 검사 자재', item_type='RAW');"
            "s=InspectionSpec.objects.create(item=i, inspection_type='INCOMING', revision=1, sampling='n=1');"
            "Characteristic.objects.create(spec=s, name='두께', lsl='9.9', usl='10.1', unit='mm');"
            "Characteristic.objects.create(spec=s, name='외관');"
            "InspectionSpec.objects.filter(pk=s.pk).update(approved_at=timezone.now(), approved_by=get_user_model().objects.get(username='boss'));"
            "Gauge.objects.create(number='E2E-G1', name='E2E 마이크로미터', last_calibrated=datetime.date.today());"
            "Lot.objects.create(number='E2E-IN-1', item=i); Lot.objects.create(number='E2E-IN-2', item=i)"))
        scan_ph = 'LOT 번호를 스캔하거나 입력하고 Enter'

        try:
            page.goto('/app/inspect')
            page.locator('[data-row]', has_text='E2E-IN-1').wait_for(timeout=5000)
            ok = page.locator('[data-row]', has_text='E2E-IN-2').count() == 1
        except Exception:
            ok = False
        check('검사 대기에 미검사 LOT', ok)

        try:
            page.get_by_placeholder(scan_ph).fill('E2E-IN-1')
            page.keyboard.press('Enter')
            page.get_by_role('button', name='수입검사').click()
            page.get_by_text('두께', exact=True).wait_for(timeout=5000)
            ok = page.get_by_text('9.9 ~ 10.1 mm').count() == 1
        except Exception:
            ok = False
        check('스캔 → 측정 화면', ok, page.url)

        try:
            page.locator('.ant-select').first.click()
            page.locator('.ant-select-item-option', has_text='E2E-G1').click()
            thick = page.locator('tbody tr', has_text='두께').locator('input')
            thick.fill('10.0')
            page.get_by_text('합격', exact=True).wait_for(timeout=5000)
            thick.fill('11')
            page.get_by_text('규격 이탈', exact=True).wait_for(timeout=5000)
            ok = page.get_by_text('합격', exact=True).count() == 0
        except Exception:
            ok = False
        check('입력 즉시 색', ok)

        try:
            page.get_by_role('button', name='OK', exact=True).click()
            page.get_by_role('button', name='판정').dblclick()
            page.get_by_text('판정 결과').wait_for(timeout=5000)
            n = api_get(page, '/api/qms/inspections/?tab=INCOMING&q=E2E-IN-1')['count']
            check('판정 두 번 눌러도 1건', n == 1, f'{n}건')
        except Exception as e:
            check('판정 두 번 눌러도 1건', False, str(e)[:80])

        try:
            alert = page.locator('.ant-alert', has_text='부적합')
            alert.wait_for(timeout=5000)
            txt = alert.inner_text()
            ok = any(ch.isdigit() for ch in txt)
        except Exception:
            ok, txt = False, ''
        check('불합격 → 부적합 번호', ok, txt[:60])

        try:
            page.goto('/app/inspect')
            page.get_by_placeholder(scan_ph).fill('E2E-NEW-1')
            page.keyboard.press('Enter')
            page.get_by_text('입고 등록').first.wait_for(timeout=5000)
            page.locator('.ant-modal .ant-select').first.click()
            page.locator('.ant-select-item-option', has_text='E2E-I1').click()
            page.get_by_label('입고수량').fill('5')
            page.get_by_role('button', name='저장').click()
            page.get_by_role('button', name='수입검사').wait_for(timeout=5000)
            ok, why = True, ''
        except Exception as e:
            ok, why = False, str(e)[:200]
        check('없는 LOT → 입고 창', ok, why)

        insp_id = ''
        try:
            page.goto('/app/inspections?tab=INCOMING')
            row = page.locator('[data-row]', has_text='E2E-IN-1')
            row.wait_for(timeout=5000)
            row.click()
            page.get_by_role('button', name='전체 화면으로').click()
            page.wait_for_url('**/app/inspections/*')
            insp_id = page.url.rstrip('/').split('/')[-1]
            ok = insp_id.isdigit()
        except Exception:
            ok = False
        check('검사 목록 탭', ok, page.url)

        try:  # 요약 타일 = API 요약, ?tab 없이도 수입검사 메뉴가 강조된다
            page.goto('/app/inspections')
            page.locator('[data-summary]').wait_for(timeout=5000)
            s = api_get(page, '/api/qms/inspections/?tab=INCOMING')['summary']
            shown = page.locator('[data-summary]').inner_text()
            sel = page.locator('.ant-menu-item-selected').inner_text()
            ok = '합격률' in shown and str(s['total']) in shown and '수입검사' in sel
            why = f"{s} / 메뉴 {sel!r}"
        except Exception as e:
            ok, why = False, str(e)[:80]
        check('검사 목록 요약·메뉴 강조', ok, why)

        try:
            page.goto(f'/app/inspections/{insp_id}/print')
            page.locator('.doc-page').wait_for(timeout=5000)
            page.emulate_media(media='print')
            pdf = page.pdf(format='A4', print_background=True)
            pages = pdf.count(b'/Type /Page') - pdf.count(b'/Type /Pages')
            bar = page.locator('.print-bar').is_visible()
            check('성적서 A4 1쪽', pages == 1 and not bar, f'{pages}쪽, 인쇄 막대 보임={bar}')
        except Exception as e:
            check('성적서 A4 1쪽', False, str(e)[:80])
        page.emulate_media(media='screen')

        try:
            page.goto('/app/todo')
            page.locator('.ant-menu-submenu-title', has_text='품질관리').click()
            page.get_by_role('menuitem', name='검사 입력', exact=True).click()
            page.wait_for_url('**/app/inspect')
            ok = page.url.endswith('/app/inspect')
            page.get_by_role('menuitem', name='수입검사', exact=True).click()
            page.wait_for_url('**/app/inspections?tab=INCOMING')
            ok = ok and page.url.endswith('/app/inspections?tab=INCOMING')
        except Exception:
            ok = False
        check('메뉴 → 새 화면', ok, page.url)

        try:  # 즉시 확인(300ms) 전에 판정 → 불량유형 칸을 보여 주고 저장하지 않는다
            page.goto('/app/inspect')
            page.get_by_placeholder(scan_ph).fill('E2E-IN-2')
            page.keyboard.press('Enter')
            page.get_by_role('button', name='수입검사').click()
            page.locator('.ant-select').first.click()
            page.locator('.ant-select-item-option', has_text='E2E-G1').click()
            page.locator('tbody tr', has_text='외관').get_by_role('button', name='OK', exact=True).click()
            page.locator('tbody tr', has_text='두께').locator('input').fill('11')
            page.get_by_role('button', name='판정').click()
            page.get_by_text('불합격 항목이 있습니다').wait_for(timeout=5000)
            n = api_get(page, '/api/qms/inspections/?tab=INCOMING&q=E2E-IN-2')['count']
            ok = n == 0 and page.get_by_placeholder('불량유형').count() + page.get_by_text('불량유형').count() > 0
        except Exception as e:
            ok, n = False, str(e)[:80]
        check('바로 판정 → 불량유형 먼저', ok, f'{n}')

        # 세션이 끊기면 API를 부르는 화면이 로그인으로 보내야 한다 (client.ts 의 403 처리)
        page.context.clear_cookies()
        page.goto('/app/overview')
        try:
            page.wait_for_url('**/app/login?next=*')
        except Exception:
            pass
        check('세션 끊김 → 로그인 화면으로 이동', page.url.endswith('/app/login?next=%2Fapp%2Foverview'), page.url)
        browser.close()
finally:
    server.terminate()

print(f'\n{sum(results)}/{len(results)} 통과')
sys.exit(0 if results and all(results) else 1)
