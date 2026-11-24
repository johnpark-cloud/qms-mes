"""새 화면(/app/)을 예시 데이터로 하나씩 열어 캡처한다 (임시 DB 사용, 화면 전수 검토용).
시스템 Python의 Playwright가 필요하다: python scripts\\screen_tour.py [캡처 폴더]
캡처 폴더에 화면마다 PNG와 tour.json(주소·제목·옛 관리 화면 링크·콘솔 오류)을 남긴다.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(PROJ, '.venv', 'Scripts', 'python.exe')
BASE = 'http://127.0.0.1:8767'
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), 'qms-tour'))
os.makedirs(OUT, exist_ok=True)
env = dict(os.environ, QMS_DATA_DIR=tempfile.mkdtemp(), DJANGO_SUPERUSER_PASSWORD='tour-pass-123')
env.pop('QMS_DB_NAME', None)  # 운영 DB가 아니라 임시 폴더의 SQLite를 쓴다

# 캡처할 기록 번호: 화면마다 예시 데이터의 첫 기록
IDS = r'''
import json
from django.apps import apps
from django.contrib.auth import get_user_model
from core.recordspec import SPECS
out = {}
for label in SPECS:
    pk = apps.get_model(label).objects.order_by('pk').values_list('pk', flat=True).first()
    if pk: out[label] = pk
for key, label in (('items', 'core.item'), ('specs', 'qms.inspectionspec'), ('plans', 'qms.controlplan'),
                   ('inspections', 'qms.inspection'), ('spc', 'qms.characteristic'), ('requests', 'core.editrequest'),
                   ('nc', 'core.nonconformance')):
    pk = apps.get_model(label).objects.order_by('pk').values_list('pk', flat=True).first()
    if pk: out[key] = pk
out['users'] = get_user_model().objects.order_by('pk').values_list('pk', flat=True).first()
print(json.dumps(out))
'''


def manage(*args):
    return subprocess.run([PY, 'manage.py', *args], cwd=PROJ, env=env, check=True, capture_output=True, text=True,
                          encoding='utf-8')


manage('migrate')
manage('createsuperuser', '--noinput', '--username', 'boss', '--email', 'boss@example.com')
manage('demo_data')
ids = json.loads(manage('shell', '-c', IDS).stdout.strip().splitlines()[-1])
server = subprocess.Popen([PY, 'manage.py', 'runserver', '8767', '--noreload'], cwd=PROJ, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def routes(nav):
    seen, out = set(), []

    def add(name, path):
        if path not in seen:
            seen.add(path)
            out.append((name, path))
    for g in nav:
        add(f'허브 {g["group"]}', f'/app/hub/{g["group"]}')
        for i in g['items']:
            add(f'메뉴 {g["group"]} > {i["label"]}', i['href'])
    for key in ('items', 'specs', 'plans', 'inspections'):
        if key in ids:
            add(f'{key} 상세', f'/app/{key}/{ids[key]}')
            if key != 'items':
                add(f'{key} 양식지', f'/app/{key}/{ids[key]}/print')
    for key, path in (('spc', '/app/spc/{}'), ('requests', '/app/requests/{}'), ('nc', '/app/nc-mail/{}'),
                      ('users', '/app/users/{}')):
        if ids.get(key):
            add(f'{key} 화면', path.format(ids[key]))
    for path in ('/app/me', '/app/audit-pack', '/app/nc-new', '/app/trace', '/app/memos', '/app/modules'):
        add(path, path)
    from_docs = set(json.loads(manage('shell', '-c', 'import json; from core.recordspec import DOCS; '
                                                    'print(json.dumps(list(DOCS)))').stdout.strip().splitlines()[-1]))
    for label, pk in ids.items():
        if '.' not in label:
            continue
        a, m = label.split('.')
        add(f'{label} 목록', f'/app/r/{a}/{m}')
        add(f'{label} 기록', f'/app/r/{a}/{m}/{pk}')
        add(f'{label} 새로 만들기', f'/app/r/{a}/{m}/new')
        if label in from_docs:
            add(f'{label} 양식지', f'/app/r/{a}/{m}/{pk}/print')
    return out


try:
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + '/api/auth/csrf/')
            break
        except Exception:
            time.sleep(0.3)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:  # 내려받은 Chromium이 없으면 PC에 깔린 Edge를 쓴다
            browser = p.chromium.launch(channel='msedge')
        page = browser.new_context(base_url=BASE, viewport={'width': 1440, 'height': 900}).new_page()
        page.set_default_timeout(8000)
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('response', lambda r: errors.append(f'{r.status} {r.url}') if r.status >= 400 else None)
        page.goto('/app/login')
        page.get_by_label('아이디').fill('boss')
        page.get_by_label('비밀번호').fill('tour-pass-123')
        page.get_by_role('button', name='로그인').click()
        page.wait_for_url('**/app/todo')
        nav = page.evaluate("fetch('/api/auth/me/').then(r => r.json())")['nav']
        report = []
        for n, (name, path) in enumerate(routes(nav), 1):
            errors.clear()
            page.goto(path)
            try:
                page.wait_for_load_state('networkidle', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            shot = f'{n:03d}.png'
            page.screenshot(path=os.path.join(OUT, shot), full_page=True)
            old = page.evaluate("""[...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))
                .filter(h => h.startsWith('/admin') || (h.startsWith('/') && !h.startsWith('/app') && !h.startsWith('/api')))""")
            row = {'n': n, 'name': name, 'path': path, 'url': page.url, 'shot': shot,
                   'title': page.locator('h1').first.inner_text() if page.locator('h1').count() else '',
                   'old_links': sorted(set(old)), 'errors': errors[:5]}
            report.append(row)
            flag = ' 옛링크' if old else ''
            flag += ' 오류' if errors else ''
            print(f'{n:03d} {name} {path}{flag}')
        with open(os.path.join(OUT, 'tour.json'), 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print(f'{len(report)}개 화면 → {OUT}')
        browser.close()
finally:
    server.terminate()
