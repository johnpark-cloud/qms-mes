"""분석 화면 API(품질 KPI·공급자 평가·SPC 관리도)와 옛 주소 → 새 화면 연결."""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.nav import app_href
from qms.models import Inspection, Measurement
from qms import tests as base  # 모듈로 가져와 QmsTest가 여기서 다시 돌지 않게


class AnalysisApiTest(TestCase):
    setUp = base.QmsTest.setUp
    new_lot = base.QmsTest.new_lot
    inspect = base.QmsTest.inspect

    def test_permissions_match_old_screens(self):
        plain = User.objects.create_user('plain', is_staff=True)
        clerk = User.objects.create_user('clerk2', is_staff=True)
        clerk.groups.add(Group.objects.get(name='검사원'))
        eng = User.objects.create_user('eng', is_staff=True)
        eng.groups.add(Group.objects.get(name='품질엔지니어'))
        urls = ('/api/qms/kpi/', '/api/qms/suppliers/', f'/api/qms/spc/{self.thk.pk}/')
        for user, codes in ((plain, (403, 403, 403)), (clerk, (403, 403, 200)), (eng, (200, 200, 200))):
            self.client.force_login(user)
            self.assertEqual(tuple(self.client.get(u).status_code for u in urls), codes, user)

    def test_kpi_and_suppliers_rows(self):
        self.raw.supplier = 'B소재'
        self.raw.save()
        self.inspect('11.0')  # 불합격 → 부적합
        self.client.force_login(self.lead)
        d = self.client.get('/api/qms/kpi/?months=3').json()
        self.assertEqual(d['months'], 3)
        self.assertEqual(len(d['rows']), 3)
        self.assertTrue(d['show']['quality'])
        s = self.client.get('/api/qms/suppliers/?months=99').json()
        self.assertEqual(s['months'], 36)
        self.assertIn('B소재', [r['name'] for r in s['rows']])

    def test_spc_points_and_alarm_nc_link(self):
        for i in range(14):
            self.inspect('10.02' if i % 2 else '10.0', lot=self.new_lot())
        insp = Inspection.objects.create(lot=self.new_lot(), spec=self.spec)
        Measurement.objects.create(inspection=insp, characteristic=self.thk, value=Decimal('10.45'))
        Measurement.objects.create(inspection=insp, characteristic=self.look, ok=True)
        insp.finalize()
        self.client.force_login(self.lead)
        d = self.client.get(f'/api/qms/spc/{self.thk.pk}/').json()
        self.assertEqual(d['kind'], 'I-MR')
        self.assertEqual(len(d['points']), 15)
        last = d['points'][-1]
        self.assertTrue(last['alarms'])
        self.assertTrue(last['nc_url'].startswith(f'/app/nc-new?lot={insp.lot.number}'))
        self.assertIsNone(d['points'][0]['nc_url'])

    def test_spc_too_few_points_reports_error(self):
        self.client.force_login(self.lead)
        d = self.client.get(f'/api/qms/spc/{self.thk.pk}/').json()
        self.assertIn('error', d)

    def test_old_paths_map_to_new_screens(self):
        self.assertEqual(app_href('/kpi/'), '/app/kpi')
        self.assertEqual(app_href('/suppliers/?months=3'), '/app/suppliers?months=3')
        self.assertEqual(app_href('/spc/12/'), '/app/spc/12')
