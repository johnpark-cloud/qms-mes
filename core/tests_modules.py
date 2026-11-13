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
        r = self.client.post('/api/qms/specs/', {}, content_type='application/json')  # 검사 입력은 종결 허용(A3)이라 기준서로 본다
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
        self.assertNotIn('/admin/qms/capa/', sidebar)


class OffSafetyTest(TestCase):
    """A3: 끄기 전 열린 기록 검사(MOD-06), 시스템 관리자 종결 허용(MOD-07), 인터록 원인 표시(MOD-08)."""

    def setUp(self):
        self.admin = User.objects.create_superuser('root', password='pw')
        self.item = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)

    def capa(self, **kw):
        return apps.get_model('qms', 'Capa').objects.create(title='재발 방지', source='OTHER', action='조치', owner=self.admin,
                                                            due_date=datetime.date.today(), **kw)

    def change(self):
        cr = apps.get_model('qms', 'ChangeRequest').objects.create(
            number='CR-1', item=self.item, category='MATERIAL', description='원료 변경', customer_notice=False,
            effective_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC))
        type(cr).objects.filter(pk=cr.pk).update(approved_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC), approved_by=self.admin)
        return cr

    def test_open_records_block_disable(self):
        capa = self.capa()
        switch_off('qms_audit')
        with self.assertRaisesMessage(ValidationError, capa.number):
            switch_off('qms_capa')
        apps.get_model('qms', 'Capa').objects.filter(pk=capa.pk).update(closed_at=datetime.date.today())
        switch_off('qms_capa')
        self.assertFalse(modules.active('qms_capa'))

    def test_open_4m_and_work_order_block_disable(self):
        self.change()
        with self.assertRaisesMessage(ValidationError, 'CR-1'):
            switch_off('qms_change')
        apps.get_model('core', 'WorkOrder').objects.create(number='WO-1', item=self.item, planned_qty=1)
        with self.assertRaisesMessage(ValidationError, 'WO-1'):
            switch_off('mes')

    def test_open_list_shows_in_admin_form(self):
        self.capa()
        switch_off('qms_audit')
        self.client.force_login(self.admin)
        r = self.client.post('/admin/core/moduleswitch/add/', {'key': 'qms_capa'})
        self.assertContains(r, '열린 기록')

    def test_superuser_closing_whitelist(self):
        capa = self.capa()
        ModuleSwitch.objects.create(key='qms_audit', enabled=False)
        ModuleSwitch.objects.filter(pk=ModuleSwitch.objects.create(key='qms_kpi').pk).update(key='qms_capa', enabled=False)  # 검사 우회: 이미 꺼진 상태
        self.assertFalse(modules.active('qms_capa'))
        self.client.force_login(self.admin)
        r = self.client.post(f'/admin/qms/capa/{capa.pk}/change/', {})
        self.assertNotEqual(r.status_code, 403)  # 종결 화면은 열린다(빈 값이라 폼 오류)
        self.assertEqual(self.client.post('/admin/qms/capa/add/', {}).status_code, 403)
        self.assertEqual(self.client.post(f'/admin/qms/capa/{capa.pk}/delete/', {}).status_code, 403)
        user = User.objects.create_user('lead', password='pw', is_staff=True)
        user.groups.add(Group.objects.get(name='품질팀장'))
        self.client.force_login(user)
        self.assertEqual(self.client.post(f'/admin/qms/capa/{capa.pk}/change/', {}).status_code, 404)

    def test_superuser_can_judge_inspection_when_off(self):
        switch_off('qms_change', 'qms_inspection')
        self.client.force_login(self.admin)
        r = self.client.post('/api/qms/inspect/submit/', {}, content_type='application/json')
        self.assertNotEqual(r.status_code, 403)
        self.assertEqual(self.client.post('/api/qms/specs/', {}, content_type='application/json').status_code, 403)

    def test_interlock_messages_name_cause(self):
        lot = Lot.objects.create(number='L-1', item=self.item)
        nc = Nonconformance.objects.create(lot=lot, description='이물')
        with self.assertRaisesMessage(ValidationError, f'[부적합] {nc.number}'):
            Shipment.objects.create(lot=lot, customer='A사', qty=1)
        self.change()
        with self.assertRaisesMessage(ValidationError, '[4M 변경] CR-1'):
            Shipment.objects.create(lot=Lot.objects.create(number='L-2', item=self.item), customer='A사', qty=1)


def force_off(*keys):
    """열린 기록 검사(MOD-06)를 건너뛰고 끈다: 끈 뒤에 남은 기록이 화면에서 어떻게 보이는지 보려는 테스트용."""
    ModuleSwitch.objects.bulk_create([ModuleSwitch(key=k, enabled=False) for k in keys])


class ConsumerTest(TestCase):
    """A4: 일상 화면에서 빠지고(MOD-10), 추적 화면은 건수로 남고(MOD-11), 일괄 작업은 거부(MOD-12), 클레임 설정 메뉴(MOD-13)."""

    def setUp(self):
        self.admin = User.objects.create_superuser('root', password='pw')
        self.user = User.objects.create_user('lead', password='pw', is_staff=True)
        self.user.groups.add(Group.objects.get(name='품질팀장'))
        self.item = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        self.lot = Lot.objects.create(number='L-1', item=self.item)
        self.capa = apps.get_model('qms', 'Capa').objects.create(
            title='재발 방지', source='OTHER', action='조치', owner=self.admin, due_date=datetime.date.today())

    def test_todo_widgets_overview_drop_off_module(self):
        from qms.due import digest, due_items
        from qms.overview import sections
        from qms.widgets import WIDGETS
        self.assertEqual(due_items()['capas'], [self.capa])
        force_off('qms_audit', 'qms_capa')
        d = due_items()
        self.assertEqual((d['capas'], d['findings']), ([], []))
        self.assertNotIn('CAPA', [t for t, _ in digest(d)])
        self.assertFalse(WIDGETS['capa'].allowed(self.admin))
        self.assertTrue(WIDGETS['held_lots'].allowed(self.admin))
        titles = [c['title'] for _, cards in sections(self.admin) for c in cards]
        self.assertIn('열린 부적합', titles)
        self.assertNotIn('진행 중 CAPA', titles)
        self.client.force_login(self.user)
        todo = self.client.get('/api/qms/todo/').json()
        self.assertNotIn('capa', [w['key'] for w in todo['available']])
        lists = [w['data'] for w in todo['widgets'] if w['key'] == 'todo_lists']
        self.assertEqual([x['capas'] for x in lists], [[]] * len(lists))

    def test_trace_relations_search_count_inactive(self):
        from .relations import relations_payload
        from .search import search
        from .timeline import lot_timeline
        Shipment.objects.bulk_create([Shipment(lot=self.lot, customer='A사', qty=1)])  # 출하 규칙은 이 테스트의 관심 밖
        force_off('mes', 'qms_audit', 'qms_capa')
        events = lot_timeline(self.lot)
        self.assertNotIn('shipment', [e['kind'] for e in events])
        self.assertEqual(events[-1]['label'], '비활성 모듈 기록 1건')
        rel = relations_payload(self.admin, self.lot)
        self.assertNotIn('core.shipment', [g['model'] for g in rel['incoming']])
        self.assertEqual(rel['inactive'], 1)
        found = search(self.admin, self.capa.number)
        self.assertEqual([r['label'] for r in found], ['비활성 모듈 기록 1건'])
        self.assertIn('KPI', [r['label'] for r in search(self.admin, 'KPI')])
        force_off('qms_kpi')
        self.assertNotIn('KPI', [r['label'] for r in search(self.admin, 'KPI')])  # 꺼진 모듈의 동작은 검색에서 뺀다

    def test_bulk_paths_follow_module(self):
        import tempfile

        from django.contrib.contenttypes.models import ContentType
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.management import CommandError, call_command

        from .importer import preview_import
        from .models import ImportProfile
        tpl = apps.get_model('qms', 'ExcelTemplate').objects.create(
            name='CAPA 양식', target=ContentType.objects.get_for_model(self.capa), file='templates/x.xlsx', mapping={})
        profile = ImportProfile.objects.create(name='작업지시', target='work_order', mapping={'number': 'A'})
        force_off('mes', 'qms_change', 'qms_inspection', 'qms_audit', 'qms_capa')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f'/report/{tpl.pk}/{self.capa.pk}/').status_code, 404)
        r = preview_import(profile, SimpleUploadedFile('a.csv', b'A\nWO-1\n'))
        self.assertIn('꺼져', r['errors'][0])
        with tempfile.TemporaryDirectory() as inbox, self.assertRaisesMessage(CommandError, '꺼져'):
            call_command('collect', inbox=inbox)

    def test_audit_pack_hides_off_sections(self):
        self.client.force_login(self.admin)
        force_off('qms_audit', 'qms_capa')
        r = self.client.get(f'/audit-pack/?item={self.item.pk}')
        self.assertEqual(r.status_code, 200)  # 시스템 관리자는 조회
        self.assertIsNone(r.context['capas'])

    def test_claim_settings_menu(self):
        from .nav import visible_nav
        groups = dict(visible_nav(self.user))
        self.assertIn(('클레임 설정', '/admin/qms/customerrule/'), groups['고객 및 협력사'])
        self.assertNotIn('/admin/qms/customerrule/', [h for _, h in groups['기준정보 및 시스템 관리']])
        force_off('qms_claim')
        self.assertNotIn('/admin/qms/customerrule/', [h for links in dict(visible_nav(self.user)).values() for _, h in links])
