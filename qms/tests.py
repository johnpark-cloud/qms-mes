import datetime
import sqlite3
import tempfile
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from core.importer import run_import
from core.models import ImportProfile, Item, Lot, LotLink, Nonconformance, WorkOrder

from . import spc
from .management.commands.collect import ingest
from .models import Characteristic, CustomerClaim, ExcelTemplate, Inspection, InspectionSpec, Measurement

TMP_MEDIA = tempfile.mkdtemp()


def approve(obj, user):
    obj.approved_by, obj.approved_at = user, timezone.now()
    obj.save()


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class QmsTest(TestCase):
    def setUp(self):
        self.lead = User.objects.create_user('lead', password='pw-lead-123', is_staff=True)
        self.lead.groups.add(Group.objects.get(name='품질팀장'))
        self.raw_item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.cell_item = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        self.raw = Lot.objects.create(number='RAW-1', item=self.raw_item)
        self.cell = Lot.objects.create(number='CELL-1', item=self.cell_item)
        LotLink.objects.create(parent=self.raw, child=self.cell)
        self.spec = InspectionSpec.objects.create(item=self.raw_item, inspection_type=InspectionSpec.INCOMING)
        self.thk = Characteristic.objects.create(spec=self.spec, name='두께', lsl=Decimal('9.5'), usl=Decimal('10.5'))
        self.look = Characteristic.objects.create(spec=self.spec, name='외관')
        approve(self.spec, self.lead)

    def inspect(self, thk, look=True, lot=None):
        insp = Inspection.objects.create(lot=lot or self.raw, spec=self.spec)
        Measurement.objects.create(inspection=insp, characteristic=self.thk, value=Decimal(thk))
        Measurement.objects.create(inspection=insp, characteristic=self.look, ok=look)
        insp.finalize()
        return insp

    # 검사
    def test_unapproved_spec_rejected(self):
        draft = InspectionSpec.objects.create(item=self.raw_item, inspection_type=InspectionSpec.INCOMING, revision=2)
        with self.assertRaises(ValidationError):
            Inspection.objects.create(lot=self.raw, spec=draft)
        self.assertEqual(InspectionSpec.current(self.raw_item, InspectionSpec.INCOMING), self.spec)

    def test_approved_spec_locked(self):
        self.spec.sampling = '바꿈'
        with self.assertRaises(ValidationError):
            self.spec.save()
        with self.assertRaises(ValidationError):
            Characteristic.objects.create(spec=self.spec, name='추가')

    def test_fail_creates_nc_and_holds_lineage(self):
        insp = self.inspect('11.0')
        self.assertEqual(insp.result, Inspection.FAIL)
        self.assertIn('두께', insp.nonconformance.description)
        self.assertTrue(self.cell.on_hold)
        with self.assertRaises(ValidationError):  # 판정 후 잠금
            Measurement.objects.create(inspection=insp, characteristic=self.thk, value=10)

    def test_missing_measurement(self):
        insp = Inspection.objects.create(lot=self.raw, spec=self.spec)
        Measurement.objects.create(inspection=insp, characteristic=self.thk, value=10)
        with self.assertRaises(ValidationError):
            insp.finalize()

    def test_rework_needs_pass_after_nc(self):
        nc = self.inspect('11.0').nonconformance
        nc.disposition, nc.approved_by = Nonconformance.REWORK, self.lead
        with self.assertRaises(ValidationError):
            nc.save()
        nc.refresh_from_db()
        self.inspect('10.0')  # 재작업 후 재검사 합격
        nc.disposition, nc.approved_by = Nonconformance.REWORK, self.lead
        nc.save()
        self.assertFalse(self.cell.on_hold)

    # 8D
    def test_claim_holds_and_closing_needs_all_steps(self):
        claim = CustomerClaim.objects.create(number='CL-1', customer='A사', lot=self.cell, description='용량 미달')
        self.assertTrue(self.cell.on_hold)
        self.assertEqual(claim.containment_due - claim.received_at, datetime.timedelta(hours=24))
        self.assertEqual(claim.current_step, 'D1 팀 구성')
        claim.closed_at = timezone.now()
        with self.assertRaises(ValidationError):
            claim.save()

    # SPC
    def test_xbar_r(self):
        groups = [(i, [10, 10.2, 9.8]) for i in range(8)] + [(8, [12, 12, 12])]
        res = spc.xbar_r(groups, lsl=9, usl=11)
        self.assertEqual(res['n'], 3)
        self.assertIn('관리한계 이탈', res['points'][-1]['alarms'])
        self.assertIsNotNone(res['cpk'])
        with self.assertRaises(ValueError):
            spc.xbar_r([(0, [1]), (1, [2])])

    def test_nine_points_one_side(self):
        groups = [(i, [9, 9.2]) for i in range(5)] + [(i, [10, 10.1]) for i in range(5, 14)]
        res = spc.xbar_r(groups)
        self.assertIn('중심선 한쪽 연속 9점', res['points'][-1]['alarms'])

    # 엑셀 가져오기
    def test_import_work_orders_and_rollback(self):
        profile = ImportProfile.objects.create(name='A사 계획', target='work_order', mapping={
            'number': '지시번호', 'item': '품번', 'planned_qty': '수량', 'due_date': '납기'})
        ok = '지시번호,품번,수량,납기\nWO-1,C1,100,2026-11-01\nWO-2,C1,50,\n'.encode('cp949')
        self.assertEqual(run_import(profile, SimpleUploadedFile('plan.csv', ok)), (2, []))
        self.assertEqual(WorkOrder.objects.get(number='WO-1').due_date, datetime.date(2026, 11, 1))
        bad = '지시번호,품번,수량,납기\nWO-3,C1,1,\nWO-4,없는품번,1,\n'.encode('utf-8')
        count, errors = run_import(profile, SimpleUploadedFile('plan.csv', bad))
        self.assertEqual(len(errors), 1)
        self.assertFalse(WorkOrder.objects.filter(number='WO-3').exists())  # 전체 롤백

    def test_import_items_xlsx(self):
        wb = Workbook()
        wb.active.append(['코드', '이름', '구분'])
        wb.active.append(['S1', '전극', '반제품'])
        buf = BytesIO()
        wb.save(buf)
        profile = ImportProfile.objects.create(name='품번', target='item',
                                               mapping={'code': '코드', 'name': '이름', 'item_type': '구분'})
        self.assertEqual(run_import(profile, SimpleUploadedFile('items.xlsx', buf.getvalue())), (1, []))
        self.assertEqual(Item.objects.get(code='S1').item_type, Item.SEMI)

    # 보고서
    def test_excel_template_fill(self):
        wb = Workbook()
        wb.active['A1'] = '클레임 번호'
        buf = BytesIO()
        wb.save(buf)
        claim = CustomerClaim.objects.create(number='CL-9', customer='A사', lot=self.cell, description='x')
        tpl = ExcelTemplate.objects.create(name='A사 8D', target=ContentType.objects.get_for_model(CustomerClaim),
                                           file=SimpleUploadedFile('8d.xlsx', buf.getvalue()),
                                           mapping={'B1': 'number', 'B2': 'lot.number', 'B3': 'received_at'})
        out = load_workbook(BytesIO(tpl.fill(claim))).active
        self.assertEqual((out['B1'].value, out['B2'].value), ('CL-9', 'CELL-1'))
        self.assertIsInstance(out['B3'].value, datetime.datetime)

    # 자동수집
    def test_collect_csv(self):
        path = Path(tempfile.mkdtemp()) / 'm.csv'
        path.write_text('lot,type,characteristic,value\nRAW-1,수입검사,두께,10.1\nRAW-1,수입검사,외관,OK\n', encoding='utf-8')
        self.assertEqual(ingest(path), ['RAW-1 합격'])
        path.write_text('lot,type,characteristic,value\nRAW-1,수입검사,없는항목,1\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            ingest(path)

    def test_backup_command(self):
        dest = tempfile.mkdtemp()
        old = Path(dest) / 'qms-20000101-000000'
        old.mkdir()
        with override_settings(DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3',
                                                      'NAME': Path(tempfile.mkdtemp()) / 'x.sqlite3'}}):
            call_command('backup', dest)
        made = [p.name for p in Path(dest).iterdir()]
        self.assertEqual(len(made), 1)  # 30일 지난 백업은 지워진다
        self.assertTrue((Path(dest) / made[0] / 'db.sqlite3').exists())

    def test_restore_rehearsal_and_apply(self):
        dest, live = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        from core.management.commands.restore import TABLES
        with sqlite3.connect(live / 'db.sqlite3') as con:  # 점검 대상 테이블만 있는 작은 '운영 DB'
            for t in TABLES:
                con.execute(f'CREATE TABLE {t} (id INTEGER)')
            con.execute('INSERT INTO core_lot VALUES (1), (2)')
        con.close()
        db = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': live / 'db.sqlite3'}}
        with override_settings(DATABASES=db, DATA_DIR=live, MEDIA_ROOT=live / 'media'):
            call_command('backup', str(dest))
            backup = next(dest.iterdir())
            out = StringIO()
            call_command('restore', str(backup), stdout=out)
            self.assertIn('리허설 통과', out.getvalue())
            self.assertIn('core_lot: 2건', out.getvalue())
            call_command('restore', str(backup), '--apply', stdout=StringIO())
        self.assertTrue(any(p.name.startswith('pre-restore-') for p in live.iterdir()))
        (backup / 'db.sqlite3').write_bytes(b'not a db')
        with self.assertRaises(CommandError):
            call_command('restore', str(backup), stdout=StringIO())

    def test_secret_key_not_in_code(self):
        from django.conf import settings
        self.assertNotIn('django-insecure', settings.SECRET_KEY)
        self.assertNotIn('django-insecure', (Path(settings.BASE_DIR) / 'config' / 'settings.py').read_text('utf-8'))

    # 화면 · 승인 서명
    def test_approve_requires_password(self):
        draft = InspectionSpec.objects.create(item=self.cell_item, inspection_type=InspectionSpec.OUTGOING)
        self.client.force_login(self.lead)
        url = f'/approve/qms/inspectionspec/{draft.pk}/'
        self.client.post(url, {'password': 'wrong'})
        draft.refresh_from_db()
        self.assertFalse(draft.is_approved)
        self.client.post(url, {'password': 'pw-lead-123'})
        draft.refresh_from_db()
        self.assertEqual(draft.approved_by, self.lead)

    def test_pages_render(self):
        for v in ('9.9', '10.0', '10.1'):
            self.inspect(v)
        claim = CustomerClaim.objects.create(number='CL-2', customer='A사', lot=self.cell, description='x',
                                             received_at=timezone.now() - datetime.timedelta(days=3))
        self.client.force_login(User.objects.create_superuser('admin', password='x'))
        html = self.client.get('/todo/').content.decode()
        self.assertIn('CL-2', html)
        self.assertIn('초과', html)
        self.assertEqual(self.client.get(f'/spc/{self.thk.pk}/').status_code, 200)
        self.assertIn('CL-2', self.client.get(f'/print/qms/customerclaim/{claim.pk}/').content.decode())
        for url in ('/admin/qms/inspection/add/', f'/admin/qms/customerclaim/{claim.pk}/change/',
                    f'/admin/qms/inspectionspec/{self.spec.pk}/change/', '/admin/core/nonconformance/add/',
                    '/admin/qms/auditchecklist/add/', '/admin/qms/document/add/', '/import/', '/admin/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
