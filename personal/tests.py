import shutil
import tempfile
from datetime import date
from pathlib import Path
from decimal import Decimal

from django.contrib.auth.models import User
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .leave import accrued_days, balance
from .models import LeaveProfile, LeaveUse, PayLine, Payslip


class LeaveTests(TestCase):
    def test_accrued_days(self):
        h = date(2025, 1, 1)
        for on, want in [(date(2025, 1, 31), 0), (date(2025, 2, 1), 1), (date(2025, 12, 31), 11), (date(2026, 1, 1), 15),
                         (date(2028, 1, 1), 16), (date(2045, 1, 1), 24), (date(2046, 1, 1), 25), (date(2024, 12, 31), 0)]:
            self.assertEqual(accrued_days(h, on), want, on)

    def test_leap_hire(self):
        u = User.objects.create_user('a')
        LeaveProfile.objects.create(owner=u, hired_on=date(2024, 2, 29))
        self.assertEqual(balance(u, date(2025, 2, 28))['period_start'], date(2025, 2, 28))

    def test_balance_used(self):
        u = User.objects.create_user('a')
        LeaveProfile.objects.create(owner=u, hired_on=date(2025, 1, 1))
        LeaveUse.objects.create(owner=u, used_on=date(2026, 3, 2), days=Decimal('1'))
        LeaveUse.objects.create(owner=u, used_on=date(2026, 3, 3), days=Decimal('0.5'))
        LeaveUse.objects.create(owner=u, used_on=date(2025, 6, 1), days=Decimal('1'))  # 지난 기간
        b = balance(u, date(2026, 6, 1))
        self.assertEqual((b['accrued'], b['used'], b['remaining']), (15, Decimal('1.5'), Decimal('13.5')))


class PayTests(TestCase):
    def test_net_pay(self):
        u = User.objects.create_user('a')
        s = Payslip.objects.create(owner=u, month=date(2026, 1, 1), base_pay=3000000)
        PayLine.objects.create(payslip=s, kind='PLUS', name='식대', amount=200000)
        PayLine.objects.create(payslip=s, kind='MINUS', name='세금', amount=300000)
        self.assertEqual(s.net, Decimal(2900000))


class OwnerOnlyTests(TestCase):
    def tearDown(self):
        self.slip.file.delete(save=False)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def setUp(self):
        self._tmp = tempfile.mkdtemp()  # 실제 data/private를 건드리지 않는다
        field = Payslip._meta.get_field('file')  # 콜러블 저장소는 import 때 한 번만 평가되므로 인스턴스를 바꾼다
        orig = field.storage
        self.addCleanup(setattr, field, 'storage', orig)
        field.storage = FileSystemStorage(location=Path(self._tmp) / 'private')
        self.a = User.objects.create_superuser('a', password='x')
        self.b = User.objects.create_user('b', password='x', is_staff=True)
        self.slip = Payslip.objects.create(owner=self.b, month=date(2026, 1, 1), base_pay=7777777,
                                           file=SimpleUploadedFile('s.pdf', b'x'))
        self.use = LeaveUse.objects.create(owner=self.b, used_on=date(2026, 1, 2))
        self.client.force_login(self.a)

    def test_owner_only(self):
        for name, pk in (('payslip', self.slip.pk), ('leaveuse', self.use.pk)):
            for action in ('change', 'delete', 'history'):
                self.assertEqual(self.client.get(f'/admin/personal/{name}/{pk}/{action}/').status_code, 404, (name, action))
        self.assertNotContains(self.client.get('/admin/personal/payslip/'), '2026-01')
        r = self.client.get('/me/')
        self.assertNotContains(r, '7,777,777')
        self.assertNotContains(r, '7777777')

    def test_generic_urls_and_file_closed(self):
        for url in (f'/print/personal/payslip/{self.slip.pk}/', f'/request/DELETE/personal/payslip/{self.slip.pk}/',
                    f'/approve/personal/payslip/{self.slip.pk}/', f'/me/payslip/{self.slip.pk}/file/'):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        n = self.slip.file.name
        for p in (n, '/' + n, './' + n, 'x/../' + n, n.replace('personal', 'Personal', 1)):
            for u in (self.a, self.b):
                self.client.force_login(u)
                self.assertEqual(self.client.get('/media/' + p).status_code, 404, p)

    def test_files_use_temp_storage(self):
        self.assertTrue(self.slip.file.path.startswith(self._tmp))
        self.assertFalse((Path(settings.DATA_DIR) / 'private' / self.slip.file.name).exists())

    def test_owner_sees_and_downloads(self):
        self.client.force_login(self.b)
        self.assertContains(self.client.get('/me/'), '7,777,777')
        r = self.client.get(f'/me/payslip/{self.slip.pk}/file/')
        self.assertEqual(r.status_code, 200)
        r.close()

    def test_save_forces_owner(self):
        r = self.client.post('/admin/personal/leaveuse/add/', {'used_on': '2026-02-02', 'days': '1', 'reason': ''})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(LeaveUse.objects.get(used_on=date(2026, 2, 2)).owner, self.a)

    def test_duplicate_month_form_error_and_normalize(self):
        r = self.client.post('/admin/personal/payslip/add/', {'month': '2026-03-15', 'base_pay': '1', 'lines-TOTAL_FORMS': '0', 'lines-INITIAL_FORMS': '0'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Payslip.objects.get(owner=self.a).month, date(2026, 3, 1))
        r = self.client.post('/admin/personal/payslip/add/', {'month': '2026-03-20', 'base_pay': '1', 'lines-TOTAL_FORMS': '0', 'lines-INITIAL_FORMS': '0'})
        self.assertContains(r, '이미 등록된 급여월입니다.')
