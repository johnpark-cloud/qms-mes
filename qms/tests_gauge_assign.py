"""검사 입력: 검사항목의 계측기 종류에 맞는, 교정 기한 안의 계측기를 자동으로 고른다."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Item, Lot
from qms.models import Characteristic, ControlPlan, ControlPlanLine, Gauge, InspectionSpec
from qms.rules import new_spec_revision, save_spec


class GaugeAssignTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('insp', password='x', is_staff=True)
        self.user.groups.add(Group.objects.get(name='검사원'))
        lead = User.objects.create_user('lead', password='x', is_staff=True)
        item = Item.objects.create(code='D-1', name='강판', item_type=Item.RAW)
        self.spec = InspectionSpec.objects.create(item=item, inspection_type=InspectionSpec.INCOMING)
        plan = ControlPlan.objects.create(item=item)
        line = ControlPlanLine.objects.create(plan=plan, characteristic='폭', method='버니어캘리퍼스')
        self.thk = Characteristic.objects.create(spec=self.spec, name='두께', lsl=Decimal('9.9'), usl=Decimal('10.1'),
                                                 unit='mm', gauge_kind='마이크로미터')
        self.width = Characteristic.objects.create(spec=self.spec, name='폭', lsl=Decimal('99'), usl=Decimal('101'),
                                                   unit='mm', plan_line=line)  # 종류가 비면 관리계획서 측정방법
        self.hole = Characteristic.objects.create(spec=self.spec, name='구멍', lsl=Decimal('5'), usl=Decimal('6'),
                                                  unit='mm', gauge_kind='핀게이지')  # 맞는 계측기 없음
        self.look = Characteristic.objects.create(spec=self.spec, name='외관', gauge_kind='마이크로미터')  # 계수형
        self.spec.approved_by, self.spec.approved_at = lead, timezone.now()
        self.spec.save()
        today = timezone.localdate()
        Gauge.objects.create(number='G-00', name='낡은 마이크로미터', last_calibrated=today - datetime.timedelta(days=400))
        Gauge.objects.create(number='G-01', name='중지 마이크로미터', last_calibrated=today, active=False)
        self.micro = Gauge.objects.create(number='G-02', name='0-25mm', kind='외측 마이크로미터', last_calibrated=today)
        self.vernier = Gauge.objects.create(number='G-03', name='버니어캘리퍼스 150mm', last_calibrated=today)
        self.lot = Lot.objects.create(number='Q-1', item=item, supplier='성일철강', qty=Decimal('50'))

    def form(self):
        c = APIClient()
        c.force_login(self.user)
        return {x['name']: x for x in c.get(f'/api/qms/inspect/form/{self.lot.pk}/{self.spec.pk}/').json()['characteristics']}

    def test_form_assigns_usable_gauge_of_matching_kind(self):
        f = self.form()
        self.assertEqual(f['두께']['gauge'], self.micro.pk)  # 종류(외측 마이크로미터)에 '마이크로미터'가 들어 있다. 기한 지남·중지는 뺀다
        self.assertEqual(f['두께']['gauge_kind'], '마이크로미터')
        self.assertEqual(f['폭']['gauge'], self.vernier.pk)  # 계측기명에 들어 있어도 맞다
        self.assertEqual(f['폭']['gauge_kind'], '버니어캘리퍼스')
        self.assertIsNone(f['구멍']['gauge'])
        self.assertIsNone(f['외관']['gauge'])

    def test_kind_is_copied_to_new_revision_and_saved_from_grid(self):
        draft = new_spec_revision(self.spec)
        self.assertEqual(draft.characteristics.get(name='두께').gauge_kind, '마이크로미터')
        c = draft.characteristics.get(name='구멍')
        lead = User.objects.create_superuser('root', password='x')
        save_spec(draft, lead, {}, [{'id': c.pk, 'gauge_kind': '핀 게이지'}], None)
        c.refresh_from_db()
        self.assertEqual(c.gauge_kind, '핀 게이지')
