from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import EditRequest, Item, Lot, Nonconformance
from core.rules import Locked, child_editable, delete_as, save_with_lock
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
