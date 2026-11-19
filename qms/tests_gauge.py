"""계측기 상세 정보·교정 이력 (IATF 7.1.5)."""
import datetime

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from qms.models import Gauge, GaugeCalibration


class GaugeIntervalMonthsTest(TestCase):
    def test_next_due_adds_months_clamped_to_month_end(self):
        g = Gauge(number='G-M', name='x', last_calibrated=datetime.date(2026, 1, 31), interval_months=1)
        self.assertEqual(g.next_due, datetime.date(2026, 2, 28))
        g.interval_months = 12
        self.assertEqual(g.next_due, datetime.date(2027, 1, 31))
        g.interval_months = 13
        self.assertEqual(g.next_due, datetime.date(2027, 2, 28))
        self.assertEqual(Gauge._meta.get_field('interval_months').default, 12)

    def test_days_to_months(self):
        from qms.models import days_to_months
        self.assertEqual([days_to_months(d) for d in (365, 180, 90, 30, 1, 730)], [12, 6, 3, 1, 1, 24])


class GaugeCalibrationTest(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.g = Gauge.objects.create(number='G-1', name='마이크로미터', interval_months=12,
                                      last_calibrated=self.today - datetime.timedelta(days=400))

    def test_pass_moves_last_calibrated_forward(self):
        GaugeCalibration.objects.create(gauge=self.g, calibrated_on=self.today, result='PASS', agency='KTL')
        self.g.refresh_from_db()
        self.assertEqual(self.g.last_calibrated, self.today)
        self.assertTrue(self.g.usable_on(self.today))

    def test_older_pass_does_not_move_back(self):
        GaugeCalibration.objects.create(gauge=self.g, calibrated_on=self.today, result='PASS')
        GaugeCalibration.objects.create(gauge=self.g, calibrated_on=self.today - datetime.timedelta(days=500), result='PASS')
        self.g.refresh_from_db()
        self.assertEqual(self.g.last_calibrated, self.today)

    def test_fail_keeps_date_and_stops_use(self):
        before = self.g.last_calibrated
        GaugeCalibration.objects.create(gauge=self.g, calibrated_on=self.today, result='FAIL')
        self.g.refresh_from_db()
        self.assertEqual(self.g.last_calibrated, before)
        self.assertFalse(self.g.active)
        self.assertFalse(self.g.usable_on(self.today))

    def test_future_date_rejected(self):
        c = GaugeCalibration(gauge=self.g, calibrated_on=self.today + datetime.timedelta(days=1), result='PASS')
        with self.assertRaises(ValidationError):
            c.full_clean()


class GaugeRecordApiTest(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root', password='pw')
        self.client.force_login(self.root)
        self.g = Gauge.objects.create(number='G-1', name='캘리퍼스', last_calibrated=timezone.localdate(),
                                      maker='미쓰토요', serial_no='S123', measuring_range='0-150mm', resolution='0.01mm')
        GaugeCalibration.objects.create(gauge=self.g, calibrated_on=timezone.localdate(), result='PASS', cert_no='C-1')

    def test_detail_shows_details_and_history_with_add(self):
        d = self.client.get(f'/api/records/qms.gauge/{self.g.pk}/').json()
        values = {f['key']: f['value'] for f in d['fields']}
        self.assertEqual(values['maker'], '미쓰토요')
        self.assertEqual(values['measuring_range'], '0-150mm')
        child = next(c for c in d['children'] if c['key'] == 'calibrations')
        self.assertEqual(child['rows'][0]['cells']['cert_no'], 'C-1')
        self.assertEqual(child['add_url'], f'/app/r/qms/gaugecalibration/new?gauge={self.g.pk}')

    def test_new_calibration_prefills_gauge_and_saves(self):
        d = self.client.get(f'/api/records/qms.gaugecalibration/new/?gauge={self.g.pk}').json()
        self.assertEqual(next(f for f in d['fields'] if f['key'] == 'gauge')['value'], str(self.g.pk))
        r = self.client.post('/api/records/qms.gaugecalibration/', {'values': {
            'gauge': self.g.pk, 'calibrated_on': timezone.localdate().isoformat(), 'result': 'FAIL', 'agency': '사내'}},
            content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.g.refresh_from_db()
        self.assertFalse(self.g.active)

    def test_no_add_when_user_cannot_add(self):
        from django.contrib.auth.models import Group
        from qms.apps import ensure_roles
        ensure_roles(None)
        u = User.objects.create_user('insp', password='pw', is_staff=True)
        u.groups.add(Group.objects.get(name='검사원'))
        self.client.force_login(u)
        d = self.client.get(f'/api/records/qms.gauge/{self.g.pk}/').json()
        child = next(c for c in d['children'] if c['key'] == 'calibrations')
        self.assertIsNone(child['add_url'])
        self.assertEqual(len(child['rows']), 1)
