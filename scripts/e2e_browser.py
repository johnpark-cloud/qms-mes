"""React 화면(/app/)을 실제 브라우저로 끝까지 확인한다 (임시 DB 사용).
시스템 Python의 Playwright가 필요하다: python scripts\\e2e_browser.py
"""
import re
import os, subprocess, sys, tempfile, time, urllib.request

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(PROJ, '.venv', 'Scripts', 'python.exe')
BASE = 'http://127.0.0.1:8766'
env = dict(os.environ, QMS_DATA_DIR=tempfile.mkdtemp(), DJANGO_SUPERUSER_PASSWORD='e2e-pass-123')
env.pop('QMS_DB_NAME', None)  # 운영 PostgreSQL이 아니라 임시 폴더의 SQLite를 쓴다

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
                page.get_by_role('button', name='화면 편집').click()  # 위젯 추가는 편집 중에만 보인다
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
        page.wait_for_url('**/app/trace?lot=RAW-2611-001')
        check('명령창: LOT 일부 + Enter → 그 기록', '/app/trace?lot=RAW-2611-001' in page.url, page.url)

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
                page.get_by_role('link', name='엑셀 받기').click()
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
            draft_id = page.url.rstrip('/').split('/')[-1]  # 변경 이력 조회·문서 점검이 쓴다
            new = api_get(page, f'/api/qms/specs/{draft_id}/')
            ok = new['revision'] == 2 and len(new['characteristics']) == 10
        except Exception:
            ok = False
        check('승인본 → 새 개정 → Rev.2 초안, 항목 복사', ok, page.url)

        # 인쇄 화면(PDF)·변경 이력 조회
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
            check('변경 이력 조회: 저장 이력이 보임', n >= 2, f'{n}줄')
        except Exception as e:
            check('변경 이력 조회: 저장 이력이 보임', False, str(e)[:80])

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
            thick = page.locator('tbody tr', has_text='두께').locator('input[inputmode="decimal"]')
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
            # 품목은 입고 창 안 검색칸에 쳐서 고른다(닫히는 중인 LOT 찾기 목록에도 같은 품번이 보일 수 있다).
            page.locator('.ant-modal .ant-select input').first.fill('E2E 검사 자재')
            page.locator('.ant-select-item-option-active', has_text='E2E-I1').wait_for(timeout=5000)
            page.keyboard.press('Enter')
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
            drawer = page.locator('.ant-drawer-body')
            drawer.get_by_text('측정 결과').wait_for(timeout=5000)  # 미리보기: 검사 정보 표 + 측정 결과 표
            peek = drawer.inner_text()
            if os.environ.get('E2E_SHOTS'):
                page.wait_for_timeout(600)  # 서랍이 다 열린 뒤
                page.screenshot(path=os.path.join(os.environ['E2E_SHOTS'], 'inspection-peek.png'))
            check('검사 미리보기 구성', all(w in peek for w in ('검사 정보', '품번 · 품명', '측정 결과', '판정')), peek[:60])
            page.get_by_role('button', name='전체 화면으로').click()
            page.wait_for_url('**/app/inspections/*')
            insp_id = page.url.rstrip('/').split('/')[-1]
            ok = insp_id.isdigit()
        except Exception:
            ok = False
        check('검사 목록 탭', ok, page.url)

        try:  # 요약 타일 = API 요약, 검사 실적은 검사 입력의 하위 탭이라 사이드바는 「검사 입력」이 강조된다(core/nav.py SUB)
            page.goto('/app/inspections')
            page.locator('[data-summary]').wait_for(timeout=5000)
            s = api_get(page, '/api/qms/inspections/?tab=INCOMING')['summary']
            shown = page.locator('[data-summary]').inner_text()
            sel = page.locator('.ant-menu-item-selected').inner_text()
            ok = '합격률' in shown and str(s['total']) in shown and sel == '검사 입력'
            why = f"{s} / 메뉴 {sel!r}"
        except Exception as e:
            ok, why = False, str(e)[:80]
        check('검사 목록 요약·메뉴 강조', ok, why)

        try:  # 검사 관리대장: 새 줄에서 LOT 스캔 → 품목 열 자동 → 측정값·OK·계측기 → 판정 → 대장 맨 위 줄
            page.goto('/app/ledger?type=INCOMING')
            page.get_by_label('LOT 번호').fill('E2E-NEW-1')
            page.keyboard.press('Enter')
            thick = page.get_by_label('두께', exact=True)
            thick.wait_for(timeout=5000)
            thick.fill('10.0')
            thick.press('Enter')
            page.get_by_label('외관').click()
            page.locator('.ant-select-item-option', has_text='OK').last.click()
            page.get_by_label('계측기').click()
            page.locator('.ant-select-item-option', has_text='E2E-G1').click()
            page.get_by_test_id('ledger-judge').click()
            page.get_by_role('status').filter(has_text='E2E-NEW-1 합격').wait_for(timeout=5000)
            row = page.locator('tbody tr', has_text='E2E-NEW-1')
            row.wait_for(timeout=5000)
            heads = page.locator('thead th').all_inner_texts()
            sel = page.locator('.ant-menu-item-selected').inner_text()
            if os.environ.get('E2E_SHOTS'):
                page.screenshot(path=os.path.join(os.environ['E2E_SHOTS'], 'ledger.png'), full_page=True)
            ok = any(h.startswith('두께') for h in heads) and '10' in row.inner_text() and sel == '검사 입력'
            why = f'머리글 {heads}, 메뉴 {sel!r}'
        except Exception as e:
            ok, why = False, str(e)[:120]
        check('검사 관리대장: 새 줄 스캔→판정→대장 줄', ok, why)

        try:  # 검사 기록 머리 띠: 판정 글자, 측정값 표 머리글, 「⋯」 메뉴에 삭제 1번만
            page.goto(f'/app/inspections/{insp_id}')
            verdict = page.locator('.verdict')
            verdict.wait_for(timeout=5000)
            heads = page.locator('.record-main thead th').all_inner_texts()
            want = ['항목', '하한', '기준(중앙)', '상한', '단위', '측정값', '위치', '판정', '계측기']
            page.get_by_role('button', name='더보기').click()
            menu = page.locator('.ant-dropdown-menu')
            menu.wait_for(timeout=5000)
            deletes = menu.get_by_role('menuitem', name='삭제').count()  # 「삭제」와 「삭제 요청」 모두 잡힌다
            outside = page.get_by_role('button', name='삭제').count()
            primary = page.get_by_role('button', name='인쇄/PDF').count()
            page.keyboard.press('Escape')
            ok = verdict.inner_text() in ('합격', '불합격', '미판정') and heads == want and deletes == 1 and outside == 0 and primary == 1
            why = f'판정 {verdict.inner_text()!r}, 머리글 {heads}, 메뉴 삭제 {deletes}, 버튼 삭제 {outside}, 인쇄 {primary}'
        except Exception as e:
            ok, why = False, str(e)[:80]
        check('검사 기록: 판정 띠·측정값 표·⋯ 메뉴', ok, why)

        try:  # 검사 기록 오른쪽 '연결' 탭: 이 검사가 가리키는 LOT 묶음
            page.goto(f'/app/inspections/{insp_id}')
            page.get_by_role('tab', name='연결').click()
            panel = page.get_by_role('region', name='연결')
            panel.get_by_role('heading', name='LOT').wait_for(timeout=5000)
            ok, why = panel.get_by_role('link', name='E2E-IN-1').count() >= 1, panel.inner_text()[:80]
        except Exception as e:
            ok, why = False, str(e)[:80]
        check('검사 기록: 연결 탭에 LOT', ok, why)

        try:  # '첨부' 탭: 파일 올리기 → 목록 1줄, 제목은 내려받기 링크
            page.get_by_role('tab', name='첨부').click()
            page.get_by_label('첨부 파일').set_input_files({'name': 'e2e-cert.pdf', 'mimeType': 'application/pdf',
                                                         'buffer': b'%PDF-1.4 e2e'})
            page.get_by_role('button', name='올리기').click()
            row = page.locator('[data-attachment]', has_text='e2e-cert.pdf')
            row.wait_for(timeout=5000)
            href = row.get_by_role('link').first.get_attribute('href') or ''
            ok, why = page.locator('[data-attachment]').count() == 1 and '/attachments/' in href, href
        except Exception as e:
            ok, why = False, str(e)[:80]
        check('검사 기록: 첨부 올리기', ok, why)

        try:  # 메모 칸은 크기 고정, 사진 첨부 → 미리보기 → 저장하면 메모에 사진
            import base64
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
            page.goto('/app/memos')
            box = page.get_by_label('메모 내용')
            box.wait_for(timeout=5000)
            resize = box.evaluate('e => getComputedStyle(e).resize')
            page.get_by_label('사진').set_input_files({'name': 'e2e.png', 'mimeType': 'image/png', 'buffer': png})
            preview = page.get_by_alt_text('첨부할 사진 1').count()
            box.fill('E2E 사진 메모')
            page.get_by_role('button', name='메모 저장').click()
            item = page.locator('.memo-item', has_text='E2E 사진 메모')
            item.wait_for(timeout=5000)
            shown = item.get_by_alt_text('메모 사진').count()
            ok, why = resize == 'none' and preview == 1 and shown == 1, f'resize={resize}, 미리보기 {preview}, 저장 후 {shown}'
        except Exception as e:
            ok, why = False, str(e)[:80]
        check('메모: 크기 고정·사진 첨부 저장', ok, why)

        try:  # 급여명세: 「항목⇥금액」 붙여넣기 → 공제 자동 분류·기본급 칸 이동 → 저장하면 표에 한 줄
            page.goto('/app/me')
            page.get_by_role('button', name='급여명세 등록').click()
            drawer = page.locator('.ant-drawer')
            drawer.get_by_label('급여월').fill('2026-03')
            drawer.locator('input[aria-label="항목"]').first.click()
            page.evaluate("t => { const dt = new DataTransfer(); dt.setData('text/plain', t);"
                          " document.activeElement.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true})) }",
                          '기본급\t3000000\n식대\t200000\n국민연금\t135000')
            drawer.get_by_text('실수령 3,065,000원').wait_for(timeout=5000)
            drawer.get_by_role('button', name='저장').click()
            page.get_by_role('button', name='2026-03').wait_for(timeout=5000)
            ok, why = page.locator('td', has_text='3,065,000').count() >= 1, ''
        except Exception as e:
            ok, why = False, str(e)[:80]
        check('급여명세: 붙여넣기 등록', ok, why)

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
            page.get_by_role('tab', name='검사 실적', exact=True).click()  # 하위 메뉴는 화면 위 탭
            page.wait_for_url('**/app/inspections')
            ok = ok and page.url.endswith('/app/inspections')
        except Exception:
            ok = False
        check('메뉴 → 새 화면', ok, page.url)

        try:  # 즉시 확인(300ms) 전에 판정 → 부적합 유형 칸을 보여 주고 저장하지 않는다
            page.goto('/app/inspect')
            page.get_by_placeholder(scan_ph).fill('E2E-IN-2')
            page.keyboard.press('Enter')
            page.get_by_role('button', name='수입검사').click()
            page.locator('.ant-select').first.click()
            page.locator('.ant-select-item-option', has_text='E2E-G1').click()
            page.locator('tbody tr', has_text='외관').get_by_role('button', name='OK', exact=True).click()
            page.locator('tbody tr', has_text='두께').locator('input[inputmode="decimal"]').fill('11')
            page.get_by_role('button', name='판정').click()
            page.get_by_text('불합격 항목이 있습니다').wait_for(timeout=5000)
            n = api_get(page, '/api/qms/inspections/?tab=INCOMING&q=E2E-IN-2')['count']
            ok = n == 0 and page.get_by_placeholder('부적합 유형').count() + page.get_by_text('부적합 유형').count() > 0
        except Exception as e:
            ok, n = False, str(e)[:80]
        check('바로 판정 → 부적합 유형 먼저', ok, f'{n}')

        # 기준정보 새 화면: 품목·BOM, 공정 표, 관리계획서, 엑셀 일괄 등록, 메뉴
        manage('shell', '-c', (
            "from django.contrib.auth import get_user_model; from django.utils import timezone;"
            "from core.models import ImportProfile, Item; from qms.models import ControlPlan, ControlPlanLine;"
            "Item.objects.create(code='E2E-C1', name='E2E 자품1', item_type='RAW');"
            "Item.objects.create(code='E2E-C2', name='E2E 자품2', item_type='RAW');"
            "i=Item.objects.create(code='E2E-CP', name='E2E 계획 품번', item_type='FIN');"
            "p=ControlPlan.objects.create(item=i, stage='PRODUCTION', revision=1);"
            "ControlPlanLine.objects.create(plan=p, characteristic='외경', lsl='9.9', usl='10.1', unit='mm', inspection_type='INCOMING');"
            "ControlPlan.objects.filter(pk=p.pk).update(approved_at=timezone.now(), approved_by=get_user_model().objects.get(username='boss'));"
            "ImportProfile.objects.create(name='E2E 품번', target='item', mapping={'code': '품번', 'name': '품명', 'item_type': '구분'})"))
        paste = ("t => { const dt = new DataTransfer(); dt.setData('text/plain', t);"
                 " document.activeElement.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true})) }")

        try:
            page.goto('/app/items')
            page.get_by_role('button', name='새 품번').click()
            page.get_by_role('dialog').get_by_role('switch', name='자동 번호').click()  # 직접 입력 경로
            page.get_by_role('dialog').get_by_label('품번').fill('E2E-B1')
            page.get_by_role('dialog').get_by_label('품명').fill('E2E 새 품번')
            page.get_by_role('dialog').get_by_label('구분').click()
            page.locator('.ant-select-item-option', has_text='완제품').click()
            page.get_by_role('button', name='만들기').click()
            page.wait_for_url('**/app/items/*')
            item_id = page.url.rstrip('/').split('/')[-1]
            page.locator('[data-grid]').first.locator('[data-grid-row] input').first.wait_for(timeout=5000)
            page.locator('[data-grid]').first.locator('[data-grid-row] input').first.click()
            page.evaluate(paste, 'E2E-C1 E2E 자품1\t2\nE2E-C2 E2E 자품2\t3')  # 선택 칸은 화면에 보이는 이름 그대로 붙여 넣는다
            page.get_by_text('변경 2건').wait_for(timeout=5000)
            page.keyboard.press('Control+s')
            page.get_by_text('저장했습니다').wait_for(timeout=5000)
            bom = api_get(page, f'/api/core/items/{item_id}/')['bom']
            check('품번 BOM 붙여넣기 저장', len(bom) == 2, f'{len(bom)}줄')
        except Exception as e:
            check('품번 BOM 붙여넣기 저장', False, str(e)[:80])

        # 규칙 기반 자동 품번: 제품코드 → 도면 품번
        import re

        def pick_auto(label, text):
            dlg = page.get_by_role('dialog')
            dlg.get_by_label(label, exact=True).click()
            page.locator('.ant-select-dropdown:visible .ant-select-item-option', has_text=re.compile('^' + re.escape(text) + '( |$)')).first.click()

        try:
            page.goto('/app/items')
            page.get_by_role('button', name='새 품번').click()
            dlg = page.get_by_role('dialog')
            pick_auto('규칙', '제품코드')
            pick_auto('품목분류', '1')
            pick_auto('산업분류', 'V')
            pick_auto('고객사', 'DC')
            pv = dlg.get_by_test_id('number-preview')
            pv.wait_for(timeout=5000)
            num = re.search(r'(1VDC\d{3})', pv.inner_text()).group(1)
            dlg.get_by_label('품명', exact=True).fill('E2E 자동 번호')
            dlg.get_by_role('button', name='만들기').click()
            page.wait_for_url('**/app/items/*')
            page.get_by_label('품번', exact=True).wait_for(timeout=5000)
            code_ok = page.get_by_label('품번', exact=True).input_value() == num
            parts = page.get_by_test_id('code-parts').inner_text()
            check('자동 번호 제품코드 등록·풀이', code_ok and '디피코' in parts, f'{num} {parts}')

            page.goto('/app/items')
            page.get_by_role('button', name='새 품번').click()
            pick_auto('규칙', '도면 품번')
            pick_auto('제품코드', num)
            pick_auto('설계자료분류', 'AS')
            dlg.get_by_test_id('number-preview').wait_for(timeout=5000)
            dlg.get_by_label('품명', exact=True).fill('E2E 자동 도면')
            dlg.get_by_role('button', name='만들기').click()
            page.wait_for_url('**/app/items/*')
            page.get_by_label('품번', exact=True).wait_for(timeout=5000)
            c2 = page.get_by_label('품번', exact=True).input_value()
            check('자동 번호 도면 품번', bool(re.match(r'^1VDC\d{3}-AS\d{3}$', c2)), c2)
        except Exception as e:
            check('자동 번호 품번 등록', False, str(e)[:120])

        try:  # 원자재 Connector 경로: 중분류 코드가 Capacitor 것으로 섞이지 않아야 한다
            page.goto('/app/items')
            page.get_by_role('button', name='새 품번').click()
            dlg = page.get_by_role('dialog')
            pick_auto('규칙', '원자재')
            pick_auto('품목분류', '3')
            pick_auto('자재분류', '2')
            page.wait_for_timeout(500)  # 앞 목록이 닫히는 동안 같은 코드 옵션이 겹쳐 잡힌다
            pick_auto('자재 대분류', '1')
            page.wait_for_timeout(500)
            dlg.get_by_label('자재 중분류', exact=True).click()
            page.wait_for_timeout(500)
            mids = page.locator('.ant-select-dropdown:visible .ant-select-item-option').all_inner_texts()
            page.locator('.ant-select-dropdown:visible .ant-select-item-option', has_text=re.compile('^0( |$)')).first.click()
            page.wait_for_timeout(500)
            pick_auto('자재 소분류', '0')
            dlg.get_by_test_id('number-preview').wait_for(timeout=5000)
            check('자동 번호 원자재 Connector 경로', any(t.startswith('0 ') for t in mids), f'{mids} {dlg.get_by_test_id("number-preview").inner_text()}')
        except Exception as e:
            check('자동 번호 원자재 Connector 경로', False, str(e)[:400])

        try:
            page.goto('/app/processes')
            page.locator('[data-grid] [data-grid-row]').first.wait_for(timeout=5000)
            rows = page.locator('[data-grid] [data-grid-row]')
            inputs = rows.nth(rows.count() - 1).locator('input')  # 입력하면 빈 줄이 또 생기므로 줄을 먼저 고정한다
            inputs.nth(0).fill('E2E-P9')
            inputs.nth(1).fill('E2E 공정')
            page.get_by_role('button', name='저장 (Ctrl+S)').click()
            page.get_by_text('저장했습니다').wait_for(timeout=5000)
            page.reload()
            page.locator('[data-grid] [data-grid-row] input[value="E2E-P9"]').wait_for(timeout=5000)
            ok = any(r['code'] == 'E2E-P9' for r in api_get(page, '/api/core/processes/')['rows'])
        except Exception as e:
            ok = False
        check('공정 표 줄 추가', ok)

        plan_id = ''
        try:
            page.goto('/app/plans')
            page.locator('[data-row]', has_text='E2E-CP').click()
            page.get_by_role('button', name='전체 화면으로').click()
            page.wait_for_url('**/app/plans/*')
            plan_id = page.url.rstrip('/').split('/')[-1]
            page.get_by_role('button', name='더보기').click()  # 주요 버튼 밖의 동작은 「⋯」 메뉴에 있다
            page.get_by_role('menuitem', name='검사기준 초안 만들기').click()
            page.locator('.ant-alert a[href*="/app/specs/"]').first.wait_for(timeout=5000)
            links = page.locator('.ant-alert a[href*="/app/specs/"]').count()
            page.get_by_role('button', name='새 개정').click()
            page.wait_for_function(f"() => !location.pathname.endsWith('/{plan_id}')", timeout=5000)
            rev = api_get(page, f'/api/qms/plans/{page.url.rstrip("/").split("/")[-1]}/')['revision']
            ok = links >= 1 and rev == 2
            detail = f'링크 {links}개, Rev.{rev}'
        except Exception as e:
            ok, detail = False, str(e)[:80]
        check('관리계획서 새 개정·검사기준 초안', ok, detail)

        try:
            page.goto(f'/app/plans/{plan_id}/print')
            page.locator('.doc-page').wait_for(timeout=5000)
            page.emulate_media(media='print')
            pdf = page.pdf(format='A4', landscape=True, print_background=True)
            pages = pdf.count(b'/Type /Page') - pdf.count(b'/Type /Pages')
            check('관리계획서 PDF A4 가로 1쪽', pages == 1, f'{pages}쪽')
        except Exception as e:
            check('관리계획서 PDF A4 가로 1쪽', False, str(e)[:80])
        page.emulate_media(media='screen')

        try:
            page.goto('/app/import')
            page.get_by_label('가져오기 설정').click()
            page.locator('.ant-select-item-option', has_text='E2E 품번').click()
            csv_path = os.path.join(env['QMS_DATA_DIR'], 'import.csv')
            with open(csv_path, 'w', encoding='utf-8-sig') as f:
                f.write('품번,품명,구분\nE2E-IM1,가져온1,원자재\nE2E-IM2,가져온2,완제품\n')
            page.get_by_label('파일 선택').set_input_files(csv_path)
            page.get_by_role('button', name='미리보기').click()
            page.locator('.ant-table-tbody tr[data-row-key]').first.wait_for(timeout=5000)
            n = page.locator('.ant-table-tbody tr[data-row-key]').count()
            page.get_by_role('button', name='확정').click()
            page.get_by_text('2건 등록했습니다.').wait_for(timeout=5000)
            check('엑셀 일괄 등록 미리보기→확정', n == 2, f'미리보기 {n}줄')
        except Exception as e:
            check('엑셀 일괄 등록 미리보기→확정', False, str(e)[:80])

        try:  # 3단계 ②: 빈 양식을 받아 채워 올리면 설정 없이 들어간다
            page.goto('/app/import')
            page.get_by_label('가져오기 설정').click()
            page.keyboard.type('품목')
            page.locator('.ant-select-item-option[title="품목"]').click()
            with page.expect_download() as dl:
                page.get_by_text('CSV', exact=True).click()  # 엑셀 양식 옆 CSV 단추
            with open(dl.value.path(), encoding='utf-8-sig') as f:
                head = f.read().strip()
            csv_path = os.path.join(env['QMS_DATA_DIR'], 'template.csv')
            with open(csv_path, 'w', encoding='utf-8-sig') as f:
                f.write(head + '\nE2E-TP1,빈 양식,원자재\n')
            page.get_by_label('파일 선택').set_input_files(csv_path)
            page.get_by_role('button', name='미리보기').click()
            page.locator('.ant-table-tbody tr[data-row-key]').first.wait_for(timeout=5000)
            page.get_by_role('button', name='확정').click()
            page.get_by_text('1건 등록했습니다.').wait_for(timeout=5000)
            check('빈 양식 받기 → 채워 올리기', head == '품번,품명,구분', head)
        except Exception as e:
            check('빈 양식 받기 → 채워 올리기', False, str(e)[:80])

        try:
            page.goto('/app/todo')
            page.locator('.ant-menu-submenu-title', has_text='기준정보').click()
            page.get_by_role('menuitem', name='품목·BOM·라우팅', exact=True).click()
            page.wait_for_url('**/app/items')
            ok = page.url.endswith('/app/items')
        except Exception:
            ok = False
        check('메뉴 → 기준정보 새 화면', ok, page.url)

        # REC-03: 설명서 목록 → 기록 화면(칸·변경 이력 탭)
        try:
            page.goto('/app/r/qms/gauge')
            page.locator('.ant-table-tbody tr', has_text='E2E-G1').click()
            page.wait_for_url('**/app/r/qms/gauge/*')
            page.locator('.record-sections', has_text='E2E 마이크로미터').wait_for(timeout=5000)
            page.get_by_role('tab', name='변경 이력').click()
            page.get_by_text('생성').first.wait_for(timeout=5000)
            ok = True
        except Exception as e:
            ok, page_err = False, str(e)[:80]
        check('기록 화면: 계측기 목록 → 상세·변경 이력', ok, page.url if ok else page_err)

        # REC-05: 기록 화면에서 수정 → 저장 → 칸에 반영·변경 이력
        try:
            page.get_by_role('button', name='수정').click()
            name = page.locator('#name')
            name.fill('E2E 마이크로미터 2')
            page.get_by_role('button', name='저장').click()
            page.locator('.record-sections', has_text='E2E 마이크로미터 2').wait_for(timeout=5000)
            page.get_by_role('tab', name='변경 이력').click()
            page.locator('.record-side li', has_text='· 변경').first.wait_for(timeout=5000)
            ok = True
        except Exception as e:
            ok, page_err = False, str(e)[:80]
        check('기록 화면: 수정 → 저장', ok, page.url if ok else page_err)

        # REC-08: 부적합 기록 화면에서 MRB 처분(비밀번호) → 종결, 폐기는 보류 유지
        manage('shell', '-c', (
            "from core.models import Item, Lot, Nonconformance;"
            "i=Item.objects.create(code='E2E-NC', name='E2E 부적합 자재', item_type='RAW');"
            "Nonconformance.objects.create(lot=Lot.objects.create(number='E2E-NC-1', item=i), origin='INCOMING',"
            " description='E2E 찍힘', defect_type='외관', sorting_result='전수', contained_qty=1)"))
        try:
            page.goto('/app/r/core/nonconformance')
            page.locator('.ant-table-tbody tr', has_text='E2E-NC-1').click()
            page.wait_for_url('**/app/r/core/nonconformance/*')
            page.get_by_role('button', name='처분').click()
            page.locator('.ant-modal .ant-select').first.click()
            page.locator('.ant-select-item-option', has_text='폐기').click()
            page.locator('.ant-modal input[type=password]').fill('e2e-pass-123')
            page.get_by_role('button', name='처분 승인').click()
            page.locator('.record-sections', has_text='폐기').wait_for(timeout=5000)
            page.locator('.ant-table-tbody tr', has_text='E2E-NC-1').first.wait_for(timeout=5000)  # 보류 표
            ok, page_err = page.get_by_role('button', name='처분', exact=True).count() == 0, '처분 버튼이 남음'
        except Exception as e:
            ok, page_err = False, str(e)[:80]
        check('기록 화면: 부적합 MRB 처분', ok, page.url if ok else page_err)

        # W3: 기록 양식지(A4 한 장) — 상세의 버튼과 옛 /print/ 주소 둘 다 새 양식지로
        try:
            rec = re.search(r'/app/r/core/nonconformance/(\d+)', page.url).group(1)
            page.get_by_role('button', name='양식지 · 인쇄').click()
            page.wait_for_url(f'**/app/r/core/nonconformance/{rec}/print')
            page.locator('.doc-title', has_text='부적합 보고서').wait_for(timeout=5000)
            page.locator('.doc-h2', has_text='① ').first.wait_for(timeout=5000)
            page.goto(f'/print/core/nonconformance/{rec}/')
            page.wait_for_url(f'**/app/r/core/nonconformance/{rec}/print')
            page.locator('.doc-page', has_text='E2E 찍힘').wait_for(timeout=5000)
            ok, page_err = True, ''
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        if os.environ.get('E2E_SHOTS'):
            page.screenshot(path=os.path.join(os.environ['E2E_SHOTS'], 'nc-sheet.png'), full_page=True)
        check('기록 양식지: 부적합 보고서(구역 표) · 옛 인쇄 주소 → 새 양식지', ok, page.url if ok else page_err)

        # W4: PPAP 요소에 문서·증적 기록을 새 화면에서 잇고, 요소 표에서 양식지로 연다
        out = manage('shell', '-c', (
            "from django.contrib.auth import get_user_model; from django.utils import timezone;"
            "from core.models import Item; from qms.models import ControlPlan, Document, PpapSubmission;"
            "i=Item.objects.create(code='E2E-PP', name='E2E PPAP 품번', item_type='FIN');"
            "ControlPlan.objects.create(item=i, stage='PRODUCTION', revision=1);"
            "Document.objects.create(number='E2E-DOC', title='E2E 외관 승인 보고서', doc_type='보고서');"
            "s=PpapSubmission.objects.create(item=i, customer='E2E 고객', reason='신규', level=1);"
            "print(s.pk, s.elements.get(number=13).pk)")).stdout.decode().split()
        try:
            sub_pk, el_pk = out[-2], out[-1]
            page.goto(f'/app/r/qms/ppapelement/{el_pk}')
            page.get_by_role('button', name='수정').click()
            page.locator('#document').click()
            page.locator('.ant-select-item-option', has_text='E2E-DOC').click()
            page.locator('#record').click()
            page.locator('.ant-select-item-option', has_text='관리계획서 · E2E-PP').click()
            page.get_by_role('button', name='저장').click()
            page.locator('.record-sections', has_text='E2E-DOC').wait_for(timeout=5000)
            page.goto(f'/app/r/qms/ppapsubmission/{sub_pk}')
            row = page.locator('.ant-table-tbody tr', has_text='외관 승인 보고서(AAR)')
            row.get_by_role('link', name='기록').wait_for(timeout=5000)
            with page.expect_popup() as pop:
                row.get_by_role('link', name='문서').click()
            sheet = pop.value
            sheet.wait_for_url('**/app/r/qms/document/*/print')
            sheet.locator('.doc-page', has_text='E2E 외관 승인 보고서').wait_for(timeout=5000)
            if os.environ.get('E2E_SHOTS'):
                page.screenshot(path=os.path.join(os.environ['E2E_SHOTS'], 'ppap-elements.png'), full_page=True)
            sheet.close()
            ok, page_err = True, ''
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        check('PPAP 요소: 문서·증적 기록 잇기 → 요소 표에서 양식지 열기', ok, page.url if ok else page_err)

        # 한눈에 보기(P3): 기한 지난 CAPA → 상태 보드 CAPA 줄의 빨간 「지연 N」 칸 → 누르면 지연 탭
        manage('shell', '-c', (
            "import datetime; from django.contrib.auth import get_user_model; from django.utils import timezone;"
            "from qms.models import Capa;"
            "Capa.objects.create(title='E2E 늦은 대책', source='OTHER', action='x', owner=get_user_model().objects.get(username='boss'),"
            " due_date=timezone.localdate() - datetime.timedelta(days=5))"))
        try:
            page.goto('/app/hub/품질보증 및 개선')
            page.locator('.hub-tile-late', has_text='시정조치(CAPA)').wait_for(timeout=8000)
            if os.environ.get('E2E_SHOTS'):
                page.screenshot(path=os.path.join(os.environ['E2E_SHOTS'], 'hub.png'), full_page=True)
            row = page.locator('.hub-row', has_text='시정조치(CAPA)')
            row.locator('.hub-chip-late').click(timeout=8000)
            page.wait_for_url('**/app/r/qms/capa?tab=late')
            page.locator('.ant-table-tbody tr', has_text='E2E 늦은 대책').wait_for(timeout=5000)
            ok, page_err = True, ''
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        check('한눈에 보기: 지연 칸·상태 보드 「지연 N」 → 지연 탭', ok, page.url if ok else page_err)

        # 문서 열람 확인: 승인된 개정 → 「읽었음」 → 열람 확인 표에 내 이름, 버튼 사라짐
        rev_pk = manage('shell', '-c', (
            "from django.contrib.auth import get_user_model; from django.utils import timezone;"
            "from qms.models import Document, DocumentRevision;"
            "d = Document.objects.create(number='E2E-WI-01', title='E2E 작업표준');"
            "r = DocumentRevision.objects.create(document=d, change_note='제정', body='본문',"
            " approved_by=get_user_model().objects.get(username='boss'), approved_at=timezone.now());"
            "print(r.pk)")).stdout.decode().split()[-1]  # shell이 앞에 자동 import 안내를 찍는다
        try:
            page.goto(f'/app/r/qms/documentrevision/{rev_pk}')
            page.get_by_role('button', name='읽었음 (열람 확인)').click(timeout=8000)
            page.locator('section', has_text='열람 확인').locator('.ant-table-tbody tr', has_text='boss').wait_for(timeout=5000)
            ok = page.get_by_role('button', name='읽었음 (열람 확인)').count() == 0
            page_err = '' if ok else '버튼이 남음'
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        check('문서 열람 확인: 「읽었음」 → 열람 확인 표', ok, page.url if ok else page_err)

        # 문서 체계(P6a): 부서별 결재서 × 입력·출력 양식 칩 → 대장 연결 칩을 누르면 관리대장(수입검사)
        manage('shell', '-c', (
            "from core.models import Department; from qms.models import Document, DocumentForm;"
            "dep = Department.objects.create(code='E2E-QA', name='E2E 품질팀');"
            "d = Document.objects.create(number='E2E-PQ-07', title='E2E 수입검사 절차', department=dep);"
            "DocumentForm.objects.create(document=d, code='E2E-PQ-07-01', name='수입검사 의뢰서', direction='IN',"
            " fields=[{'name': '의뢰 내용', 'kind': 'text', 'required': True}, {'name': '수량', 'kind': 'number'}]);"
            "DocumentForm.objects.create(document=d, code='E2E-PQ-07-02', name='수입검사 관리대장', direction='OUT', target='ledger:INCOMING')"))
        try:
            page.goto('/app/documents')
            card = page.locator('.ant-card', has_text='E2E 품질팀')
            card.locator('.form-chip', has_text='E2E-PQ-07-01').wait_for(timeout=8000)
            if os.environ.get('E2E_SHOTS'):
                page.screenshot(path=os.path.join(os.environ['E2E_SHOTS'], 'documents.png'), full_page=True)
            menu = page.locator('.ant-menu-item-selected').first.inner_text().strip()
            card.locator('.form-chip', has_text='E2E-PQ-07-02').click()
            page.wait_for_url('**/app/ledger?type=INCOMING', timeout=8000)
            ok, page_err = menu == '문서 체계', f'메뉴 {menu!r}'
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        check('문서 체계: 부서 카드·양식 칩 → 관리대장', ok, page.url if ok else page_err)

        # 양식 기록(P6b): 연결 기록 없는 양식 칩 → 양식 대장 → 새 기록 → 항목대로 입력·저장 → 대장에 한 줄
        try:
            page.goto('/app/documents')
            page.locator('.form-chip', has_text='E2E-PQ-07-01').click()
            page.wait_for_url(re.compile(r'/app/documents/forms/\d+$'), timeout=8000)
            page.get_by_role('button', name='새 기록').click()
            page.get_by_label('의뢰 내용').fill('E2E 의뢰')
            page.get_by_label('수량').fill('3')
            page.locator('.ant-drawer-footer').get_by_role('button', name='저장').click()
            page.locator('.ant-table-row', has_text='E2E 의뢰').wait_for(timeout=8000)
            if os.environ.get('E2E_SHOTS'):
                page.screenshot(path=os.path.join(os.environ['E2E_SHOTS'], 'form-ledger.png'), full_page=True)
            menu = page.locator('.ant-menu-item-selected').first.inner_text().strip()
            ok, page_err = menu == '문서 체계', f'메뉴 {menu!r}'
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        check('양식 기록: 양식 칩 → 대장 → 새 기록 저장', ok, page.url if ok else page_err)

        # 기록 화면 새로 만들기: 목록 「새로 만들기」 → 입력 → 저장 → 새 기록 화면
        try:
            page.goto('/app/r/core/department')
            page.get_by_role('link', name='새로 만들기').click()
            page.wait_for_url('**/app/r/core/department/new')
            page.locator('#code').fill('E2E-DEPT')
            page.locator('#name').fill('E2E 부서')
            page.get_by_role('button', name='저장').click()
            page.wait_for_url(re.compile(r'/app/r/core/department/\d+$'))
            page.locator('.record-sections', has_text='E2E 부서').wait_for(timeout=5000)
            ok = True
        except Exception as e:
            ok, page_err = False, str(e)[:80]
        check('기록 화면: 새로 만들기', ok, page.url if ok else page_err)

        # 메뉴 「부적합 등록」 → 새 화면 → 등록 → 보류 안내와 상세 링크
        try:
            page.goto('/app/todo')
            page.locator('.ant-menu-submenu-title', has_text='품질보증').click()
            page.get_by_role('menuitem', name='부적합(NCR)', exact=True).click()
            page.get_by_role('tab', name='부적합 등록', exact=True).click()  # 하위 메뉴는 화면 위 탭
            page.wait_for_url('**/app/nc-new')
            page.get_by_placeholder('스캔하거나 번호·품번 일부 입력').fill('RAW-2611-001')
            page.get_by_label('부적합 내용').fill('E2E 간편 등록')
            page.get_by_role('button', name='등록', exact=True).click()
            page.get_by_text('LOT RAW-2611-001 보류').wait_for(timeout=5000)
            page.get_by_role('link', name='부적합 상세 열기').click()
            page.wait_for_url(re.compile(r'/app/r/core/nonconformance/\d+$'))
            ok, page_err = True, ''
        except Exception as e:
            ok, page_err = False, str(e)[:80]
        check('부적합 등록 새 화면 → 보류 → 상세', ok, page.url if ok else page_err)

        # 사용자 정의 칸: 새 기록 화면에서 선택지를 Enter로 넣어 저장 (1단계 시스템 관리)
        try:
            page.goto('/app/r/core/fielddef/new')
            page.locator('#target').click()
            page.keyboard.type('부서')
            page.keyboard.press('Enter')
            page.locator('#key').fill('e2e_bank')
            page.locator('#label').fill('E2E 은행')
            page.locator('#kind').click()
            page.keyboard.type('선택')
            page.keyboard.press('Enter')
            page.locator('#choices').click()
            for t in ('국민', '신한'):
                page.keyboard.type(t)
                page.keyboard.press('Enter')
            page.get_by_role('button', name='저장').click()
            page.wait_for_url(re.compile(r'/app/r/core/fielddef/\d+$'))
            page.get_by_text('국민, 신한').wait_for(timeout=5000)
            ok, page_err = True, ''
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        check('사용자 정의 칸 새로 만들기 → 선택지 Enter 입력 → 상세 "국민, 신한"', ok, page.url if ok else page_err)

        # 옛 서버 화면을 대신한 새 화면(W2-2): 모듈 설정 표, 심사 자료 출력 품번 선택
        try:
            page.goto('/app/modules')
            page.get_by_role('switch', name='심사 켜짐').wait_for(timeout=5000)
            page.goto('/app/audit-pack')
            page.get_by_text('품번을 고르면').wait_for(timeout=5000)
            item = api_get(page, '/api/qms/audit-pack/')['items'][0]['id']
            page.goto(f'/app/audit-pack?item={item}')
            page.get_by_role('heading', name='1. 검사 요약').wait_for(timeout=5000)
            ok, page_err = True, ''
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        if os.environ.get('E2E_SHOTS'):
            page.screenshot(path=os.path.join(os.environ['E2E_SHOTS'], 'audit-pack.png'), full_page=True)
        check('모듈 설정·심사 자료 출력 새 화면', ok, page.url if ok else page_err)

        # 파일·JSON 칸 양식도 관리 화면 대신 새 화면에서 만든다(W2-3): 엑셀 보고서 양식
        try:
            page.goto('/app/r/qms/exceltemplate/new')
            page.locator('#name').fill('E2E 양식')
            page.locator('#target').click()
            page.keyboard.type('부적합')
            page.keyboard.press('Enter')
            page.locator('input[type=file]').set_input_files({'name': 'e2e-template.xlsx', 'buffer': b'x',
                                                              'mimeType': 'application/octet-stream'})
            page.locator('#mapping').fill('{"B3": "number"}')
            page.get_by_role('button', name='저장').click()
            page.wait_for_url(re.compile(r'/app/r/qms/exceltemplate/\d+$'))
            page.get_by_text('e2e-template').first.wait_for(timeout=5000)
            ok, page_err = True, ''
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        check('엑셀 보고서 양식 새로 만들기 → 파일·셀 매핑 저장', ok, page.url if ok else page_err)

        # 사용자·조직도(W5·P4): 새 부서(오른쪽 창) → 새 사용자 → 관리자 비밀번호 확인 → 조직도 상자에 나타남
        try:
            page.goto('/app/users')
            page.locator('.org-chart').wait_for(timeout=5000)
            page.get_by_role('button', name='부서 추가').click()
            page.get_by_label('부서 이름', exact=True).fill('E2E 검사팀')
            page.get_by_label('부서 코드', exact=True).fill('E2EQC')
            page.get_by_role('button', name='만들기').click()
            page.locator('.org-node', has_text='E2E 검사팀').wait_for(timeout=5000)
            page.keyboard.press('Escape')  # 오른쪽 창을 닫아야 위 단추를 누를 수 있다
            if os.environ.get('E2E_SHOTS'):
                page.locator('.ant-drawer-open').wait_for(state='detached', timeout=5000)
                page.screenshot(path=os.path.join(os.environ['E2E_SHOTS'], 'org-chart.png'), full_page=True)
            page.get_by_role('button', name='사용자 추가').click()
            page.get_by_label('아이디', exact=True).fill('e2e-kim')
            page.get_by_label('성', exact=True).fill('김')
            page.get_by_label('이름', exact=True).fill('검사')
            page.get_by_label('초기 비밀번호', exact=True).fill('Qms!2026long')
            page.get_by_label('검사원').check()
            page.get_by_role('button', name='만들기').click()
            page.locator('.ant-modal input[type=password]').fill('e2e-pass-123')
            page.get_by_role('button', name='서명').click()
            page.wait_for_url(re.compile(r'/app/users/\d+$'))
            page.locator('.org-chart', has_text='김검사').wait_for(timeout=5000)
            page.get_by_text('계정 생성 (역할: 검사원)').wait_for(timeout=5000)
            # 조직도에서 사람을 끌어 부서 상자에 놓으면 그 부서로 옮겨진다
            page.goto('/app/users')
            page.locator('.org-chart').wait_for(timeout=5000)
            box = page.locator('.org-node', has_text='E2E 검사팀')
            assert box.locator('.org-person', has_text='김검사').count() == 0
            # 마우스로 끌기: Chromium은 놓을 곳 위에서 한 번 더 움직여야 dragover가 난다
            page.locator('.org-person', has_text='김검사').hover()
            page.mouse.down()
            box.locator('.org-dept').hover()
            box.locator('.org-dept').hover(position={'x': 12, 'y': 8})
            page.mouse.up()
            try:
                box.locator('.org-person', has_text='김검사').wait_for(timeout=5000)
            except Exception:
                raise AssertionError('끌어 옮기기 실패: ' + ' '.join(page.locator('.ant-message').all_inner_texts()))
            ok, page_err = True, ''
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        if os.environ.get('E2E_SHOTS'):
            page.screenshot(path=os.path.join(os.environ['E2E_SHOTS'], 'users.png'), full_page=True)
        check('사용자·조직도: 새 부서·새 사용자 만들기(관리자 비밀번호 확인) → 조직도·변경 기록 → 끌어서 부서 옮기기', ok, page.url if ok else page_err)

        # P2: 출하 기록 → 출하 여정·검사 근거·투입 LOT과 「출하성적서」 주 버튼
        manage('shell', '-c', (
            "from core.models import Item, Lot, Shipment;"
            "i=Item.objects.create(code='E2E-SH', name='E2E 출하품', item_type='FIN');"
            "print(Shipment.objects.create(lot=Lot.objects.create(number='E2E-SH-1', item=i), customer='E2E고객', qty=3).pk)"))
        try:
            page.goto('/app/r/core/shipment')
            page.locator('.ant-table-tbody tr', has_text='E2E-SH-1').click()
            page.wait_for_url('**/app/r/core/shipment/*')
            page.get_by_role('heading', name='출하 여정').wait_for(timeout=5000)
            page.locator('.flow-box', has_text='출하검사').get_by_text('없음').wait_for(timeout=5000)
            page.get_by_role('button', name='출하성적서').click()
            page.wait_for_url('**/app/r/core/shipment/*/print')
            page.get_by_text('검사 근거').first.wait_for(timeout=5000)
            ok, page_err = True, ''
        except Exception as e:
            ok, page_err = False, str(e)[:120]
        check('출하 기록: 출하 여정(빠진 출하검사 「없음」) → 출하성적서 양식지', ok, page.url if ok else page_err)

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
