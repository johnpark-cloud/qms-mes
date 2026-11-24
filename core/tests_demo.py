"""예시 데이터 명령(demo_data): 모든 주요 모델에 행이 생기고, 다시 실행해도 행이 늘지 않는다."""
from io import StringIO

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

COVERED = [
    'core.Item', 'core.Process', 'core.BomLine', 'core.RoutingStep', 'core.WorkOrder', 'core.WorkResult', 'core.Lot', 'core.LotLink',
    'core.Shipment', 'core.Nonconformance', 'core.Hold', 'core.Partner', 'core.Department', 'core.FieldDef', 'core.NumberRule',
    'core.CodeValue', 'core.ImportProfile',
    'qms.Inspection', 'qms.Measurement', 'qms.Gauge', 'qms.GaugeCalibration', 'qms.Qualification', 'qms.Capa', 'qms.ChangeRequest',
    'qms.Document', 'qms.DocumentRevision', 'qms.InternalAudit', 'qms.AuditFinding', 'qms.AuditChecklist', 'qms.AuditItem', 'qms.Evidence',
    'qms.CustomerClaim', 'qms.CustomerRule', 'qms.Scar', 'qms.PpapSubmission', 'qms.PpapElement', 'qms.InspectionSpec',
    'qms.Characteristic', 'qms.ControlPlan', 'qms.ControlPlanLine', 'qms.Memo',
    'personal.LeaveProfile', 'personal.LeaveUse', 'personal.Payslip',
]


def counts():
    return {m._meta.label: m.objects.count() for app in ('core', 'qms', 'personal') for m in apps.get_app_config(app).get_models()}


class DemoDataTest(TestCase):
    def test_run_twice(self):
        get_user_model().objects.create_superuser('root', 'r@example.com', 'x')
        call_command('demo_data', stdout=StringIO())
        first = counts()
        for label in COVERED:
            self.assertGreaterEqual(first[label], 1, label)
        self.assertGreaterEqual(first['core.Hold'], 3)
        self.assertTrue(get_user_model().objects.get(username='ex_lead').has_usable_password() is False)
        call_command('demo_data', stdout=StringIO())
        self.assertEqual(counts(), first)
        from qms.models import Characteristic, InspectionSpec
        self.assertTrue(Characteristic.objects.filter(spec__item__code='EX-R100', gauge_kind='외측 마이크로미터').exists())
        self.assertTrue(InspectionSpec.objects.filter(item__code='EX-F300', revision=2, approved_at__isnull=True).exists())

    def test_real_personal_records_untouched(self):
        import datetime
        from personal.models import LeaveProfile, LeaveUse, Payslip
        root = get_user_model().objects.create_superuser('root', 'r@example.com', 'x')
        LeaveProfile.objects.create(owner=root, hired_on=datetime.date(2020, 1, 2))
        call_command('demo_data', stdout=StringIO())
        self.assertFalse(LeaveUse.objects.filter(owner=root).exists())
        self.assertFalse(Payslip.objects.filter(owner=root).exists())
