"""설비 예방보전(4단계 #10): 설비 대장·보전 이력, 예방보전 기한 지남·7일 이내를 내 할 일에 띄운다."""
import datetime
import json

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from qms.due import due_items

from .models import Equipment, PmRecord
from .tests_modules import force_off


class EquipmentPmTest(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.root = User.objects.create_superuser('root', password='pw')
        self.eq = Equipment.objects.create(code='EQ-1', name='프레스 1호기', pm_interval_days=30,
                                           last_pm_on=self.today - datetime.timedelta(days=40))

    def pm(self, kind, days_ago, eq=None):
        return PmRecord.objects.create(equipment=eq or self.eq, kind=kind, done_on=self.today - datetime.timedelta(days=days_ago),
                                       content='점검')

    def test_next_pm_from_interval(self):
        self.assertEqual(self.eq.next_pm, self.today - datetime.timedelta(days=10))
        self.assertIsNone(Equipment(code='EQ-X', name='지그').next_pm)

    def test_interval_needs_last_pm(self):
        with self.assertRaises(ValidationError):
            Equipment(code='EQ-2', name='사출기', pm_interval_days=30).full_clean()

    def test_preventive_record_moves_last_pm_forward_only(self):
        self.pm(PmRecord.PREVENTIVE, 2)
        self.eq.refresh_from_db()
        self.assertEqual(self.eq.last_pm_on, self.today - datetime.timedelta(days=2))
        self.pm(PmRecord.PREVENTIVE, 20)  # 늦게 넣은 옛 기록은 되돌리지 않는다
        self.pm(PmRecord.BREAKDOWN, 0)  # 사후보전은 예방보전 주기와 무관
        self.eq.refresh_from_db()
        self.assertEqual(self.eq.last_pm_on, self.today - datetime.timedelta(days=2))

    def test_preventive_record_sets_first_last_pm(self):
        eq = Equipment.objects.create(code='EQ-3', name='지그 A')
        self.pm(PmRecord.PREVENTIVE, 1, eq)
        eq.refresh_from_db()
        self.assertEqual(eq.last_pm_on, self.today - datetime.timedelta(days=1))

    def test_future_done_on_rejected(self):
        with self.assertRaises(ValidationError):
            PmRecord(equipment=self.eq, kind=PmRecord.PREVENTIVE, done_on=self.today + datetime.timedelta(days=1),
                     content='점검').full_clean()

    def test_due_items_overdue_and_within_7_days(self):
        soon = Equipment.objects.create(code='EQ-4', name='컨베이어', pm_interval_days=30,
                                        last_pm_on=self.today - datetime.timedelta(days=24))
        Equipment.objects.create(code='EQ-5', name='여유', pm_interval_days=30, last_pm_on=self.today - datetime.timedelta(days=20))
        Equipment.objects.create(code='EQ-6', name='폐기 설비', pm_interval_days=30, last_pm_on=self.today - datetime.timedelta(days=90),
                                 status=Equipment.SCRAPPED)
        Equipment.objects.create(code='EQ-7', name='주기 없음')
        self.assertEqual(due_items()['equipment_pm'], [self.eq, soon])  # 기한 순
        force_off('mes')
        self.assertEqual(due_items()['equipment_pm'], [])

    def test_todo_widget_lists_equipment(self):
        self.client.force_login(self.root)
        self.client.post('/api/qms/dashboard/', json.dumps([{'key': 'todo_lists', 'size': 'wide'}]), content_type='application/json')
        data = {w['key']: w['data'] for w in self.client.get('/api/qms/todo/').json()['widgets']}
        self.assertEqual([(r['label'], r['href'], r['overdue']) for r in data['todo_lists']['equipment_pm']],
                         [('EQ-1 프레스 1호기', f'/app/r/core/equipment/{self.eq.pk}', True)])

    def test_records_late_tab_and_children(self):
        self.pm(PmRecord.BREAKDOWN, 3)
        Equipment.objects.create(code='EQ-8', name='정상', pm_interval_days=30, last_pm_on=self.today)
        self.client.force_login(self.root)
        d = self.client.get('/api/records/core.equipment/?tab=late').json()
        self.assertEqual([r['cells']['code'] for r in d['results']], ['EQ-1'])
        self.assertEqual(d['overdue'], {'tab': 'late', 'count': 1})
        rec = self.client.get(f'/api/records/core.equipment/{self.eq.pk}/').json()
        pms = next(c for c in rec['children'] if c['key'] == 'pm_records')
        self.assertEqual(len(pms['rows']), 1)
