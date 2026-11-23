"""옛 서버 화면 → 새 화면(W2-2): 모듈 설정, 부적합 메일, 심사 자료 출력, 검색 동작·메뉴 주소."""
import datetime

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Item, Lot, ModuleSwitch, Nonconformance
from core.nav import visible_nav


def perms(*codenames):
    return Permission.objects.filter(codename__in=codenames)


class ModuleSettingsApiTest(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root', password='pw')
        self.lead = User.objects.create_user('lead', password='pw', is_staff=True)
        self.lead.user_permissions.add(*Permission.objects.filter(codename__endswith='moduleswitch'))

    def post(self, data):
        return self.client.post('/api/core/modules/', data, content_type='application/json')

    def test_superuser_only(self):
        self.client.force_login(self.lead)  # 권한이 있어도 시스템 관리자가 아니면 못 연다
        self.assertEqual(self.client.get('/api/core/modules/').status_code, 403)
        self.assertEqual(self.post({'key': 'qms_kpi', 'enabled': False}).status_code, 403)
        self.assertFalse(ModuleSwitch.objects.exists())

    def test_list_and_toggle(self):
        self.client.force_login(self.root)
        rows = {r['key']: r for r in self.client.get('/api/core/modules/').json()['rows']}
        self.assertTrue(rows['qms_kpi']['enabled'])
        self.assertIn('시정조치(CAPA)', rows['qms_audit']['requires'])
        r = self.post({'key': 'qms_kpi', 'enabled': False})
        self.assertEqual(r.status_code, 200, r.content)
        row = ModuleSwitch.objects.get(key='qms_kpi')
        self.assertEqual((row.enabled, row.changed_by), (False, self.root))
        kpi = next(x for x in r.json()['rows'] if x['key'] == 'qms_kpi')
        self.assertEqual((kpi['enabled'], kpi['changed_by']), (False, 'root'))
        self.assertTrue(self.post({'key': 'qms_kpi', 'enabled': True}).json()['rows'])
        self.assertTrue(ModuleSwitch.objects.get(key='qms_kpi').enabled)

    def test_rules_kept(self):
        self.client.force_login(self.root)
        r = self.post({'key': 'qms_capa', 'enabled': False})  # 심사가 CAPA를 쓴다
        self.assertEqual(r.status_code, 400)
        self.assertIn('심사', r.json()['detail'])
        self.assertEqual(self.post({'key': 'base', 'enabled': False}).status_code, 400)

    def test_menu_opens_new_page(self):
        hrefs = [h for _, links in visible_nav(self.root) for _, h in links]
        self.assertIn('/admin/core/moduleswitch/', hrefs)  # NAV는 관리 주소, 화면으로 낼 때 새 화면
        from core.nav import app_href
        self.assertEqual(app_href('/admin/core/moduleswitch/'), '/app/modules')


@override_settings(SMTP_ENABLED=False)
class NcMailApiTest(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root', password='pw')
        self.user = User.objects.create_user('u', password='pw', is_staff=True)
        self.user.user_permissions.add(*perms('view_nonconformance'))
        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='L1', item=item)
        self.nc = Nonconformance.objects.create(lot=self.lot, description='찍힘', defect_qty=1)
        self.url = f'/api/core/nc-mail/{self.nc.pk}/'

    def approve(self):
        Nonconformance.objects.filter(pk=self.nc.pk).update(approved_by=self.root, approved_at=timezone.now())

    def test_only_approved(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_view_and_mark_sent(self):
        self.approve()
        self.client.force_login(self.user)
        d = self.client.get(self.url).json()
        self.assertEqual(d['subject'], f'[부적합 보고] {self.nc.number} L1')
        self.assertIn('<table', d['body'])
        self.assertIn('찍힘', d['body'])
        self.assertEqual((d['smtp'], d['mailed_at'], d['can_send']), (False, None, False))
        self.assertEqual(d['nc_url'], f'/app/r/core/nonconformance/{self.nc.pk}')
        post = lambda data: self.client.post(self.url, data, content_type='application/json')
        self.assertEqual(post({'action': 'mark_sent'}).status_code, 403)  # 보냈음 표시는 수정 권한
        self.user.user_permissions.add(*perms('change_nonconformance'))
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_login(self.user)
        r = post({'action': 'mark_sent'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['mailed_at'])
        self.nc.refresh_from_db()
        self.assertIsNotNone(self.nc.mailed_at)
        self.assertEqual(post({'action': 'send', 'to': 'a@b.c'}).status_code, 400)  # SMTP 없음

    @override_settings(SMTP_ENABLED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_send(self):
        self.approve()
        self.client.force_login(self.root)
        post = lambda data: self.client.post(self.url, data, content_type='application/json')
        self.assertEqual(post({'action': 'send', 'to': '잘못된 주소'}).status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
        r = post({'action': 'send', 'to': 'a@ex.com, d@ex.org'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(mail.outbox[0].to, ['a@ex.com', 'd@ex.org'])
        self.assertTrue(r.json()['mailed_at'])

    def test_todo_and_record_link_new_page(self):
        self.approve()
        self.client.force_login(self.root)
        self.client.post('/api/qms/dashboard/', [{'key': 'nc_mail_pending', 'size': 'wide'}], content_type='application/json')
        w = self.client.get('/api/qms/todo/').json()['widgets'][0]
        self.assertEqual(w['data']['rows'][0]['href'], f'/app/nc-mail/{self.nc.pk}')
        links = self.client.get(f'/api/records/core.nonconformance/{self.nc.pk}/').json()['links']
        self.assertIn({'label': '메일 보내기', 'url': f'/app/nc-mail/{self.nc.pk}'}, links)


class AuditPackApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='pw', is_staff=True)
        self.user.user_permissions.add(*perms('view_nonconformance', 'view_inspection', 'view_item'))
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        lot = Lot.objects.create(number='L1', item=self.item)
        Nonconformance.objects.create(lot=lot, description='찍힘', defect_qty=1)
        self.client.force_login(self.user)

    def test_permission(self):
        self.user.user_permissions.remove(*perms('view_inspection'))
        self.client.force_login(User.objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get('/api/qms/audit-pack/').status_code, 403)

    def test_pack(self):
        d = self.client.get('/api/qms/audit-pack/').json()
        self.assertIsNone(d['item'])
        self.assertIn({'id': self.item.pk, 'label': 'R1 양극재'}, d['items'])
        today = timezone.localdate()
        d = self.client.get(f'/api/qms/audit-pack/?item={self.item.pk}').json()
        self.assertEqual((d['item']['code'], d['from'], d['to']), ('R1', str(today - datetime.timedelta(days=90)), str(today)))
        self.assertEqual([n['description'] for n in d['ncs']], ['찍힘'])
        self.assertEqual(d['ncs'][0]['lot'], 'L1')
        self.assertIsNone(d['capas'])  # 보기 권한 없는 절은 None
        self.assertIn(f'/audit-pack/zip/?item={self.item.pk}', d['zip_url'])
        d = self.client.get(f'/api/qms/audit-pack/?item={self.item.pk}&from=2026-13-01').json()
        self.assertTrue(d['errors'])

    def test_menu_and_search_open_new_pages(self):
        from core.nav import app_href
        self.assertEqual(app_href('/audit-pack/'), '/app/audit-pack')
        self.assertEqual(app_href('/memo/new/'), '/app/memos')
        urls = {r['label']: r['url'] for r in self.client.get('/api/search/?q=심사').json()['results']}
        self.assertEqual(urls.get('심사 자료 출력'), '/app/audit-pack')
