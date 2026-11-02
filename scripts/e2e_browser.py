"""React 화면(/app/)을 실제 브라우저로 끝까지 확인한다 (임시 DB 사용).
시스템 Python의 Playwright가 필요하다: python scripts\\e2e_browser.py
"""
import os, subprocess, sys, tempfile, time, urllib.request

from playwright.sync_api import sync_playwright

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

        bg = lambda: page.evaluate('getComputedStyle(document.body).backgroundColor')
        page.emulate_media(color_scheme='light')
        page.wait_for_timeout(300)
        light = bg()
        page.emulate_media(color_scheme='dark')
        page.wait_for_timeout(300)
        dark = bg()
        check('다크 모드 배경색이 라이트와 다름', light != dark, f'{light} / {dark}')
        page.emulate_media(color_scheme='light')

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
