"""공급자 등급 연동: 성적(수입검사 불합격률·PPM·SCAR 회신)으로 제안 등급, 거래처 등급 반영, 강화 검사 대상 경고."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Partner
from qms import kpi
from qms import tests as base  # 모듈로 가져와 QmsTest가 여기서 다시 돌지 않게


class SuggestGradeTest(TestCase):
    def test_grade_bands(self):
        row = {'inspections': 10, 'fail_rate': 0.0, 'ppm': 50.0, 'scar_on_time': None}
        self.assertEqual(kpi.suggest_grade(row), 'A')
        self.assertEqual(kpi.suggest_grade({**row, 'fail_rate': 2.0}), 'B')
        self.assertEqual(kpi.suggest_grade({**row, 'scar_on_time': 70.0}), 'C')  # 회신이 늦으면 B가 될 수 없다
        self.assertEqual(kpi.suggest_grade({**row, 'fail_rate': 8.0}), 'C')
        self.assertEqual(kpi.suggest_grade({**row, 'fail_rate': 20.0}), 'D')
        self.assertEqual(kpi.suggest_grade({**row, 'ppm': 5000.0}), 'D')

    def test_no_data_no_grade(self):
        self.assertIsNone(kpi.suggest_grade({'inspections': 0, 'fail_rate': None, 'ppm': None, 'scar_on_time': None}))


class SupplierGradeApiTest(TestCase):
    setUp_base = base.QmsTest.setUp
    inspect = base.QmsTest.inspect

    def setUp(self):
        self.setUp_base()
        self.partner = Partner.objects.create(name='B소재', is_supplier=True, status=Partner.APPROVED, grade='A')
        self.raw.supplier = 'B소재'
        self.raw.save()
        self.client.force_login(self.lead)

    def test_rows_show_current_and_suggested_grade(self):
        self.inspect('11.0')  # 불합격 1건 / 1건 = 100%
        row = next(r for r in self.client.get('/api/qms/suppliers/').json()['rows'] if r['name'] == 'B소재')
        self.assertEqual((row['partner'], row['grade'], row['status'], row['suggested']),
                         (self.partner.pk, 'A', '승인', 'D'))
        self.assertTrue(self.client.get('/api/qms/suppliers/').json()['can_grade'])

    def test_supplier_without_partner_record(self):
        self.raw.supplier = '미등록상사'
        self.raw.save()
        self.inspect('10.0')
        row = next(r for r in self.client.get('/api/qms/suppliers/').json()['rows'] if r['name'] == '미등록상사')
        self.assertEqual((row['partner'], row['grade'], row['suggested']), (None, '', 'A'))

    def test_apply_grade_keeps_history(self):
        before = self.partner.history.count()
        r = self.client.post('/api/qms/suppliers/grade/', {'partner': self.partner.pk, 'grade': 'C'}, content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.partner.refresh_from_db()
        self.assertEqual((self.partner.grade, self.partner.evaluated_on), ('C', timezone.localdate()))
        self.assertEqual(self.partner.history.count(), before + 1)

    def test_apply_grade_rejects_bad_input_and_no_permission(self):
        post = lambda body: self.client.post('/api/qms/suppliers/grade/', body, content_type='application/json')
        self.assertEqual(post({'partner': self.partner.pk, 'grade': 'Z'}).status_code, 400)
        customer = Partner.objects.create(name='고객', is_customer=True)
        self.assertEqual(post({'partner': customer.pk, 'grade': 'B'}).status_code, 400)
        self.client.force_login(User.objects.create_user('plain', is_staff=True))
        self.assertEqual(post({'partner': self.partner.pk, 'grade': 'B'}).status_code, 403)
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.grade, 'A')

    def test_watch_warning_for_low_grade_or_conditional(self):
        form = f'/api/qms/inspect/form/{self.raw.pk}/{self.spec.pk}/'
        detail = f'/api/records/core.lot/{self.raw.pk}/'
        self.assertEqual(self.client.get(form).json()['watch'], '')
        self.assertEqual(self.client.get(detail).json()['notices'], [])
        self.partner.grade = 'C'
        self.partner.save()
        watch = self.client.get(form).json()['watch']
        self.assertIn('강화 검사 대상', watch)
        self.assertIn('등급 C', watch)
        self.assertIn('강화 검사 대상', self.client.get(detail).json()['notices'][0]['message'])
        self.partner.grade, self.partner.status = 'B', Partner.CONDITIONAL
        self.partner.save()
        self.assertIn('조건부 승인', self.client.get(form).json()['watch'])

    def test_watch_uses_lot_partner_link_first(self):
        other = Partner.objects.create(name='다른 이름', is_supplier=True, grade='D')
        self.raw.partner = other
        self.raw.save()
        self.assertIn('등급 D', self.client.get(f'/api/qms/inspect/form/{self.raw.pk}/{self.spec.pk}/').json()['watch'])
