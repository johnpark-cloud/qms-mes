"""모듈 대응표·켜기/끄기 문(MOD-01~05, 09)."""
import datetime

from django.apps import apps
from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver

from . import modules
from .models import Item, Lot, ModuleSwitch, Nonconformance, Shipment
from .relations import is_registered


def _routes(patterns, prefix=''):
    for p in patterns:
        route = prefix + str(p.pattern).replace('^', '').replace('$', '')
        if isinstance(p, URLResolver):
            yield from _routes(p.url_patterns, route)
        elif isinstance(p, URLPattern):
            yield route


def switch_off(*keys):
    for key in keys:
        ModuleSwitch.objects.update_or_create(key=key, defaults={'enabled': False})


def switch_off_all():
    """다른 모듈이 필요로 하는 모듈은 뒤에 끈다."""
    needed = {r for m in modules.MODULES.values() for r in m.requires}
    switch_off(*[k for k in modules.MODULES if k not in needed], *[k for k in modules.MODULES if k in needed])


class CoverageTest(TestCase):
    def test_every_url_pattern_is_mapped(self):
        missing = [r for r in _routes(get_resolver().url_patterns) if modules.module_of_path(r) is None]
        self.assertEqual(missing, [], '모듈 대응표(core/modules.py)에 없는 주소')

    def test_every_registered_model_is_mapped(self):
        labels = [m._meta.label_lower for m in apps.get_models()]
        missing = [label for label in labels if is_registered(label) and modules.module_of_model(label) is None]
        self.assertEqual(missing, [], '모듈 대응표(core/modules.py)에 없는 업무 모델')

    def test_admin_paths_follow_model(self):
        self.assertEqual(modules.module_of_path('admin/qms/capa/3/change/'), 'qms_capa')
        self.assertEqual(modules.module_of_path('admin/core/workorder/'), 'mes')
        self.assertEqual(modules.module_of_path('admin/core/lot/'), modules.BASE)
        self.assertEqual(modules.module_of_path('admin/personal/payslip/'), modules.BASE)
        self.assertEqual(modules.module_of_path('admin/qms/'), modules.BASE)


class SwitchRuleTest(TestCase):
    def test_missing_row_means_on(self):
        self.assertEqual(modules.active_set(), {modules.BASE, *modules.MODULES})

    def test_base_cannot_be_switched(self):
        for key in ('base', 'core', 'lot'):
            with self.assertRaises(ValidationError):
                ModuleSwitch.objects.create(key=key, enabled=False)

    def test_requires_blocks_disable_and_enable(self):
        with self.assertRaises(ValidationError):  # 켜진 내부심사가 CAPA를 필요로 한다
            switch_off('qms_capa')
        switch_off('qms_audit', 'qms_capa')
        self.assertFalse(modules.active('qms_capa'))
        audit = ModuleSwitch.objects.get(key='qms_audit')
        audit.enabled = True
        with self.assertRaises(ValidationError):  # CAPA가 꺼져 있어 내부심사를 켤 수 없다
            audit.save()
        with self.assertRaises(ValidationError):  # 행을 지워도(=켜기) 같다
            audit.delete()
        ModuleSwitch.objects.filter(key='qms_capa').update(enabled=True)
        audit.save()
        self.assertTrue(modules.active('qms_audit'))

    def test_hold_interlock_with_all_modules_off(self):
        switch_off_all()
        self.assertEqual(modules.active_set(), {modules.BASE})
        lot = Lot.objects.create(number='L-1', item=Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED))
        Nonconformance.objects.create(lot=lot, description='이물')
        self.assertTrue(lot.on_hold)
        with self.assertRaises(ValidationError):
            Shipment.objects.create(lot=lot, customer='A사', qty=1)


class GateTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('lead', password='pw', is_staff=True)
        self.user.groups.add(Group.objects.get(name='품질팀장'))
        self.admin = User.objects.create_superuser('root', password='pw')

    def as_user(self):
        self.client.force_login(self.user)

    def as_admin(self):
        self.client.force_login(self.admin)

    def test_html_screen_404_for_user_get_only_for_admin(self):
        switch_off('qms_kpi')
        self.as_user()
        self.assertEqual(self.client.get('/kpi/').status_code, 404)
        self.as_admin()
        self.assertEqual(self.client.get('/kpi/').status_code, 200)

    def test_api_returns_module_inactive(self):
        switch_off('qms_change', 'qms_inspection')
        self.as_user()
        r = self.client.get('/api/qms/specs/')
        self.assertEqual((r.status_code, r.json()['code']), (404, 'module_inactive'))
        self.as_admin()
        self.assertEqual(self.client.get('/api/qms/specs/').status_code, 200)
        r = self.client.post('/api/qms/inspect/receive/', {}, content_type='application/json')
        self.assertEqual((r.status_code, r.json()['code']), (403, 'module_inactive'))

    def test_admin_screens_and_label_routes(self):
        switch_off('qms_change', 'qms_inspection')
        g = apps.get_model('qms', 'gauge').objects.create(number='G-1', name='캘리퍼스', last_calibrated=datetime.date.today())
        self.as_user()
        for url in ('/admin/qms/gauge/', f'/admin/qms/gauge/{g.pk}/change/', f'/api/relations/qms.gauge/{g.pk}/',
                    f'/print/qms/gauge/{g.pk}/', '/admin/autocomplete/?app_label=qms&model_name=inspection&field_name=lot',
                    f'/api/attachments/?ct=qms.gauge&id={g.pk}', f'/api/qms/memos/?ct=qms.gauge&id={g.pk}'):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.get('/admin/core/lot/').status_code, 200)  # 기본 플랫폼은 열려 있다
        self.as_admin()
        self.assertEqual(self.client.get(f'/admin/qms/gauge/{g.pk}/change/').status_code, 200)
        self.assertEqual(self.client.post(f'/admin/qms/gauge/{g.pk}/change/', {}).status_code, 403)
        self.assertEqual(self.client.get(f'/api/attachments/?ct=qms.gauge&id={g.pk}').status_code, 200)

    def test_spa_shell_stays_open(self):
        switch_off('qms_change', 'qms_inspection')
        self.as_user()
        self.assertEqual(self.client.get('/app/specs').status_code, 200)

    def test_only_superuser_switches(self):
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='core', codename__endswith='moduleswitch'))
        self.as_user()
        self.assertEqual(self.client.get('/admin/core/moduleswitch/').status_code, 403)
        self.assertEqual(self.client.post('/admin/core/moduleswitch/add/', {'key': 'qms_kpi'}).status_code, 403)
        self.assertFalse(ModuleSwitch.objects.exists())
        self.as_admin()
        self.assertEqual(self.client.post('/admin/core/moduleswitch/add/', {'key': 'qms_kpi'}).status_code, 302)
        row = ModuleSwitch.objects.get()
        self.assertEqual((row.enabled, row.changed_by), (False, self.admin))
        r = self.client.post('/admin/core/moduleswitch/add/', {'key': 'qms_capa'})  # 내부심사가 켜져 있다
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '끌 수 없습니다')

    def test_menu_and_me_drop_inactive_module(self):
        self.as_user()
        hrefs = lambda: [i['href'] for g in self.client.get('/api/auth/me/').json()['nav'] for i in g['items']]
        self.assertIn('/admin/qms/capa/', hrefs())
        switch_off('qms_audit', 'qms_capa')
        me = self.client.get('/api/auth/me/').json()
        self.assertFalse(me['modules']['qms_capa'])
        self.assertTrue(me['modules']['mes'])
        self.assertNotIn('/admin/qms/capa/', hrefs())
        self.assertNotIn('/admin/qms/internalaudit/', hrefs())
        self.assertIn('/admin/core/lot/', hrefs())
        sidebar = self.client.get('/todo/').content.decode().partition('id="qms-sidebar"')[2].partition('</nav>')[0]
        self.assertIn('/admin/core/lot/', sidebar)
        self.assertNotIn('/admin/qms/capa/', sidebar)  # 위젯·할 일 목록 필터는 A4
