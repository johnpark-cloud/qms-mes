from decimal import Decimal

from django.test import TestCase

from core.grid import collect_rows, record_version, table_version
from core.models import BomLine, Item, RoutingStep

FIELDS = {'component': 'fk', 'qty': 'number'}


class GridTests(TestCase):
    def setUp(self):
        self.item = Item.objects.create(code='P1', name='제품', item_type=Item.FINISHED)
        self.a = Item.objects.create(code='A', name='가', item_type=Item.RAW)
        self.b = Item.objects.create(code='B', name='나', item_type=Item.RAW)

    def collect(self, rows, own=None, unique=()):
        return collect_rows(rows, own or {}, lambda: BomLine(parent=self.item), FIELDS, 'bom',
                            exclude=['parent'], unique=unique)

    def test_number_cells(self):
        new, _, _, errors = self.collect([
            {'id': None, 'component': self.a.pk, 'qty': ' 1,000 '},
            {'id': None, 'component': self.b.pk, 'qty': 'abc'}])
        self.assertEqual(new[0].qty, Decimal('1000'))
        self.assertIn('bom.1.qty', errors)
        self.assertNotIn('bom.0.qty', errors)

    def test_foreign_id_rejected(self):
        other = Item.objects.create(code='P2', name='다른', item_type=Item.FINISHED)
        line = BomLine.objects.create(parent=other, component=self.a)
        _, _, _, errors = self.collect([{'id': line.pk, 'qty': 2}])
        self.assertEqual(errors['bom.0.id'], ['다른 기록의 항목입니다.'])

    def test_blank_and_delete(self):
        line = BomLine.objects.create(parent=self.item, component=self.a)
        new, changed, deleted, errors = self.collect(
            [{'id': None, 'component': None, 'qty': ''}, {'id': line.pk, 'delete': True}], {line.pk: line})
        self.assertEqual((new, changed, errors), ([], [], {}))
        self.assertEqual(deleted, [line])

    def test_missing_fk_error_key(self):
        _, _, _, errors = self.collect([{'id': None, 'component': None, 'qty': '3'}])
        self.assertIn('bom.0.component', errors)

    def test_duplicate_in_request(self):
        _, _, _, errors = self.collect([
            {'id': None, 'component': self.a.pk, 'qty': 1},
            {'id': None, 'component': self.a.pk, 'qty': 2}], unique=('component',))
        self.assertEqual(errors['bom.1.component'], ['같은 값이 두 번 있습니다.'])
        self.assertNotIn('bom.0.component', errors)

    def test_versions(self):
        v0 = record_version(self.item, [(BomLine, 'parent')])
        self.item.name = '바뀜'
        self.item.save()
        v1 = record_version(self.item, [(BomLine, 'parent')])
        self.assertGreater(v1, v0)
        BomLine.objects.create(parent=self.item, component=self.a)
        v2 = record_version(self.item, [(BomLine, 'parent')])
        self.assertGreater(v2, v1)
        self.assertGreater(table_version(BomLine, parent_id=self.item.pk), 0)
        self.assertEqual(table_version(BomLine, parent_id=999999), 0)

    def test_stale_reexport(self):
        from core.rules import Stale as S2
        from qms.rules import Stale
        self.assertIs(Stale, S2)

    def test_text_cells_stripped(self):
        new, _, _, errors = collect_rows([{'id': None, 'code': ' P10 ', 'name': '공정'}], {}, Item,
                                         {'code': 'text', 'name': 'text'}, 'rows', exclude=['item_type'])
        self.assertEqual((new[0].code, errors), ('P10', {}))

    def test_duplicate_keeps_cell_error_and_skips_none(self):
        make = lambda: RoutingStep(item=self.item)
        fields = {'seq': 'int'}
        _, _, _, errors = collect_rows([{'id': None, 'seq': 'abc'}, {'id': None, 'seq': 'abc'}], {}, make, fields, 'r',
                                       exclude=['item', 'process'], unique=('seq',))
        self.assertEqual(errors['r.0.seq'], ['정수를 입력하세요.'])
        self.assertEqual(errors['r.1.seq'], ['정수를 입력하세요.'])
