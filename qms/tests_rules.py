from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import Item, Lot
from qms.models import Characteristic, Inspection, InspectionSpec, Qualification
from qms.rules import RECEIVE_MSG, measurement, receive_lot, submit_inspection


class InspectionRulesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('lead', password='pw-lead-123', is_staff=True)
        self.user.groups.add(Group.objects.get(name='품질팀장'))
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='RAW-1', item=self.item)
        self.spec = InspectionSpec.objects.create(item=self.item, inspection_type=InspectionSpec.INCOMING)
        self.char = Characteristic.objects.create(spec=self.spec, name='두께', lsl=Decimal('9'), usl=Decimal('11'))
        self.spec.approved_by, self.spec.approved_at = self.user, timezone.now()
        self.spec.save()
        Qualification.objects.create(user=self.user, inspection_type=InspectionSpec.INCOMING,
                                     valid_until=date(2999, 1, 1), basis='테스트')

    def test_pass(self):
        insp = submit_inspection(self.lot, self.spec, self.user, None, {self.char.pk: '10'})
        self.assertEqual(insp.result, Inspection.PASS)

    def test_fail_creates_nc_with_defect(self):
        insp = submit_inspection(self.lot, self.spec, self.user, None, {self.char.pk: '12'}, '치수', '-3')
        self.assertEqual(insp.result, Inspection.FAIL)
        self.assertEqual(insp.nonconformance.defect_type, '치수')
        self.assertEqual(insp.nonconformance.defect_qty, 0)
        self.assertTrue(self.lot.on_hold)

    def test_missing_value_rolls_back(self):
        with self.assertRaisesMessage(ValidationError, '값을 입력하세요'):
            submit_inspection(self.lot, self.spec, self.user, None, {})
        self.assertFalse(Inspection.objects.exists())

    def test_nan_rejected(self):
        self.assertIsNone(measurement(self.char, 'nan'))

    def test_receive(self):
        lot, created = receive_lot('NEW-1', self.item, '5', '협력사A')
        self.assertTrue(created)
        with self.assertRaisesMessage(ValidationError, RECEIVE_MSG):
            receive_lot('NEW-2', self.item, '0', '')
