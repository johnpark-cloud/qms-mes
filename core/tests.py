from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Item, Lot, LotLink, Nonconformance, Process, RoutingStep, Shipment, WorkOrder, WorkResult


class RoutingTest(TestCase):
    def test_work_results_follow_routing(self):
        item = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        stack, weld = Process.objects.create(code='P10', name='적층'), Process.objects.create(code='P20', name='용접')
        s10 = RoutingStep.objects.create(item=item, seq=10, process=stack)
        s20 = RoutingStep.objects.create(item=item, seq=20, process=weld)
        wo = WorkOrder.objects.create(number='WO-1', item=item, planned_qty=100)
        with self.assertRaises(ValidationError):  # 적층 없이 용접
            WorkResult.objects.create(work_order=wo, step=s20, input_qty=10, good_qty=10)
        with self.assertRaises(ValidationError):  # 양품+불량 > 투입
            WorkResult.objects.create(work_order=wo, step=s10, input_qty=10, good_qty=9, defect_qty=2)
        WorkResult.objects.create(work_order=wo, step=s10, input_qty=60, good_qty=58, defect_qty=2)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrder.RUNNING)
        WorkResult.objects.create(work_order=wo, step=s20, input_qty=58, good_qty=50, defect_qty=8)
        self.assertEqual(wo.progress, 50.0)
        held = Lot.objects.create(number='L1', item=item)
        Nonconformance.objects.create(lot=held, description='x')
        with self.assertRaises(ValidationError):
            WorkResult.objects.create(work_order=wo, step=s20, lot=held, input_qty=1, good_qty=1)
        from qms.kpi import process_yield
        self.assertEqual([round(y['yield'], 2) for y in process_yield(1)], [round(58 / 60 * 100, 2), round(50 / 58 * 100, 2)])


class InterlockTest(TestCase):
    def setUp(self):
        raw = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        cell = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        self.raw = Lot.objects.create(number='RAW-1', item=raw)
        self.cell_a = Lot.objects.create(number='CELL-A', item=cell)
        self.cell_b = Lot.objects.create(number='CELL-B', item=cell)
        self.orphan = Lot.objects.create(number='CELL-X', item=cell)
        LotLink.objects.create(parent=self.raw, child=self.cell_a)
        LotLink.objects.create(parent=self.cell_a, child=self.cell_b)
        self.mrb = User.objects.create(username='mrb')
        self.mrb.groups.add(Group.objects.get(name='품질팀장'))

    def test_nc_holds_whole_lineage_and_blocks(self):
        Nonconformance.objects.create(lot=self.raw, description='이물')
        for lot in (self.raw, self.cell_a, self.cell_b):
            self.assertTrue(lot.on_hold)
        self.assertFalse(self.orphan.on_hold)
        with self.assertRaises(ValidationError):
            Shipment.objects.create(lot=self.cell_b, customer='A사', qty=1)
        with self.assertRaises(ValidationError):
            LotLink.objects.create(parent=self.cell_a, child=self.orphan)

    def test_release_rules(self):
        nc = Nonconformance.objects.create(lot=self.raw, description='이물')
        nc.disposition, nc.approved_by = Nonconformance.CONCESSION, User.objects.create(username='engineer')
        with self.assertRaises(ValidationError):  # 승인자가 품질팀장이 아님
            nc.save()
        nc.approved_by = self.mrb
        with self.assertRaises(ValidationError):  # 고객 승인 없음
            nc.save()
        nc.customer_approval_ref = 'CA-001'
        nc.save()
        self.assertFalse(self.cell_b.on_hold)
        Shipment.objects.create(lot=self.cell_b, customer='A사', qty=1)

    def test_scrap_keeps_hold(self):
        nc = Nonconformance.objects.create(lot=self.raw, description='이물')
        nc.disposition, nc.approved_by = Nonconformance.SCRAP, self.mrb
        nc.save()
        self.assertIsNotNone(nc.closed_at)
        self.assertTrue(self.cell_a.on_hold)

    def test_trace_page(self):
        Nonconformance.objects.create(lot=self.raw, description='이물')
        self.client.force_login(User.objects.create_superuser('admin'))
        html = self.client.get('/trace/', {'lot': 'CELL-A'}).content.decode()
        self.assertIn('RAW-1', html)
        self.assertIn('CELL-B', html)
        self.assertIn('보류 중', html)

    def test_cycle_and_gap(self):
        with self.assertRaises(ValidationError):
            LotLink.objects.create(parent=self.cell_b, child=self.raw)
        self.assertTrue(self.orphan.lineage_gap)
        self.assertFalse(self.raw.lineage_gap)


class ShellTest(TestCase):
    def test_logo_served_from_data_dir(self):
        import tempfile
        from pathlib import Path
        from django.test import override_settings
        self.client.force_login(User.objects.create_superuser('admin'))
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DATA_DIR=Path(tmp)):
                self.assertEqual(self.client.get('/brand/logo').status_code, 404)
                self.assertIn('QMS+MES', self.client.get('/todo/').content.decode())
                (Path(tmp) / 'brand').mkdir()
                (Path(tmp) / 'brand' / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\n')
                self.assertEqual(self.client.get('/brand/logo').status_code, 200)
                self.assertIn('src="/brand/logo"', self.client.get('/todo/').content.decode())

    def test_sidebar_filters_by_permission(self):
        def side(html):
            return html.split('id="qms-sidebar"')[1].split('</nav>')[0]
        insp = User.objects.create_user('insp', is_staff=True)
        insp.groups.add(Group.objects.get(name='검사원'))
        self.client.force_login(insp)
        html = side(self.client.get('/todo/').content.decode())
        self.assertIn('검사 입력', html)
        self.assertIn('전체 메뉴', html)
        self.assertIn('aria-current="page"', html)  # /todo/ = 내 할 일
        plain = User.objects.create_user('plain', is_staff=True)
        self.client.force_login(plain)
        html = side(self.client.get('/todo/').content.decode())
        self.assertNotIn('검사 입력', html)
        self.assertIn('LOT 이력', html)
        self.client.force_login(User.objects.create_superuser('root'))
        self.assertIn('검사 입력', side(self.client.get('/todo/').content.decode()))
