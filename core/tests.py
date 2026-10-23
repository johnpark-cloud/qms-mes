from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Item, Lot, LotLink, Nonconformance, Shipment


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
