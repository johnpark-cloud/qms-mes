from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import EditRequest, Item, Lot, Nonconformance, Process
from core.rules import Locked, child_editable, delete_as, dispose_nc, nc_locked_fields, save_with_lock
from qms.models import Characteristic, InspectionSpec


class LockRulesTest(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user('boss', password='pw-boss-123', is_staff=True)
        self.boss.groups.add(Group.objects.get(name='품질팀장'))
        self.eng = User.objects.create_user('eng', password='pw-eng-123', is_staff=True)
        self.eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.root = User.objects.create_superuser('root', password='pw-root-123')
        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='RAW-1', item=item)
        self.spec = InspectionSpec.objects.create(item=item, inspection_type=InspectionSpec.INCOMING)
        Characteristic.objects.create(spec=self.spec, name='두께', lsl=Decimal('9.5'), usl=Decimal('10.5'))
        self.spec.approved_by, self.spec.approved_at = self.boss, timezone.now()
        self.spec.save()

    def test_locked_record_rejects_save(self):
        self.spec.note = '바꿈'
        with self.assertRaises(Locked):
            save_with_lock(self.spec, self.eng)

    def test_edit_request_unlocks_once(self):
        req = EditRequest.objects.create(kind=EditRequest.EDIT, target=self.spec, object_repr='x', reason='r',
                                         requested_by=self.eng, status=EditRequest.APPROVED)
        self.spec.note = '1차'
        save_with_lock(self.spec, self.eng)
        req.refresh_from_db()
        self.assertEqual(req.status, EditRequest.USED)
        self.spec.note = '2차'
        with self.assertRaises(Locked):
            save_with_lock(self.spec, self.eng)

    def test_child_failure_rolls_back_and_keeps_request(self):
        req = EditRequest.objects.create(kind=EditRequest.EDIT, target=self.spec, object_repr='x', reason='r',
                                         requested_by=self.eng, status=EditRequest.APPROVED)
        ch = self.spec.characteristics.first()
        self.spec.note = '롤백'
        with mock.patch.object(Characteristic, 'save', side_effect=ValidationError('항목 오류')):
            with self.assertRaises(ValidationError) as cm:
                save_with_lock(self.spec, self.eng, children=[ch])
        self.assertNotIsInstance(cm.exception, Locked)
        req.refresh_from_db()
        self.assertEqual(req.status, EditRequest.APPROVED)
        self.assertEqual(InspectionSpec.objects.get(pk=self.spec.pk).note, '')

    def test_superuser_edits_locked(self):
        self.spec.note = '관리자'
        save_with_lock(self.spec, self.root)
        self.spec.refresh_from_db()
        self.assertEqual(self.spec.note, '관리자')

    def test_children_follow_parent_unlock(self):
        ch = self.spec.characteristics.first()
        ch.usl = ch.usl + 1
        with self.assertRaises(Locked):
            save_with_lock(self.spec, self.eng, children=[ch])
        save_with_lock(self.spec, self.root, children=[ch])
        ch.refresh_from_db()
        self.assertEqual(ch.usl, Decimal('11.5'))

    def test_delete_only_superuser(self):
        with self.assertRaises(PermissionDenied):
            delete_as(self.spec, self.boss)
        self.assertTrue(InspectionSpec.objects.filter(pk=self.spec.pk).exists())

    def test_child_editable(self):
        self.assertFalse(child_editable(self.spec, self.eng))
        self.assertTrue(child_editable(self.spec, self.root))
        nc = Nonconformance.objects.create(lot=self.lot, description='x')
        self.assertTrue(child_editable(nc, self.eng))


class DisposeRulesTest(TestCase):
    def setUp(self):
        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='RAW-1', item=item)
        self.mrb = User.objects.create_user('mrb', password='pw')
        self.mrb.groups.add(Group.objects.get(name='품질팀장'))
        self.eng = User.objects.create_user('eng', password='pw-eng-123', is_staff=True)
        self.eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.root = User.objects.create_superuser('root', password='pw-root-123')
        self.nc = Nonconformance.objects.create(lot=self.lot, description='이물', defect_type='이물',
                                                process=Process.objects.create(code='P10', name='적층'),
                                                sorting_result='전수 선별', contained_qty=Decimal('5'))

    def test_wrong_password(self):
        with self.assertRaisesMessage(ValidationError, 'MRB 승인 비밀번호가 맞지 않습니다.'):
            dispose_nc(self.nc, self.mrb, 'bad', {'disposition': Nonconformance.SCRAP})
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.disposition, '')

    def test_missing_fields_block(self):
        self.nc.sorting_result = ''
        with self.assertRaisesMessage(ValidationError, '보완 필요:'):
            dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP})

    def test_dispose_ok_keeps_hold_for_scrap(self):
        dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP})
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.approved_by, self.mrb)
        self.assertTrue(self.lot.on_hold)

    def test_other_fields_rejected(self):
        with self.assertRaises(ValidationError):
            dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP, 'lot': 99})

    def test_closed_nc_locked_fields(self):
        dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP})
        self.nc.refresh_from_db()
        self.assertIn('lot', nc_locked_fields(self.nc, self.eng))
        self.assertNotIn('cost', nc_locked_fields(self.nc, self.eng))
        self.assertEqual(sorted(nc_locked_fields(self.nc, self.root)), sorted(Nonconformance.INTERLOCK))
        with self.assertRaises(Locked):
            dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.REWORK})

    def test_empty_disposition_rejected_without_signature(self):
        for data in ({}, {'cost': 1}, {'disposition': ''}):
            with self.subTest(data=data):
                with self.assertRaisesMessage(ValidationError, '처분을 선택하세요.'):
                    dispose_nc(self.nc, self.mrb, 'pw', data)
                self.assertIsNone(self.nc.approved_by)
                self.nc.refresh_from_db()
                self.assertIsNone(self.nc.approved_by)
                self.assertIsNone(self.nc.approved_at)

    def test_non_approver_rejected(self):
        with self.assertRaises(ValidationError):
            dispose_nc(self.nc, self.eng, 'pw-eng-123', {'disposition': Nonconformance.SCRAP})
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.disposition, '')
        self.assertIsNone(self.nc.approved_by)
        self.assertIsNone(self.nc.closed_at)
