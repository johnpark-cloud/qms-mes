import datetime
import json
import re
import shutil
import sqlite3
import tempfile
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from core.importer import run_import
from core.models import APPROVER_GROUP, ImportProfile, Item, Lot, LotLink, Nonconformance, Shipment, WorkOrder

from . import kpi, spc
from .management.commands.collect import ingest
from .models import (AuditChecklist, AuditFinding, AuditItem, Capa, ChangeRequest, Characteristic, ControlPlan, ControlPlanLine, CustomerClaim,
                     DashboardLayout,
                     Document, ExcelTemplate, Gauge, Inspection, InspectionSpec, InternalAudit, Measurement, PpapSubmission,
                     Qualification, Scar)
from .similar import similar

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

    def inspect(self, thk, look=True, lot=None, at=None):
        insp = Inspection.objects.create(lot=lot or self.raw, spec=self.spec, **({'inspected_at': at} if at else {}))
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
        nc = self.inspect('11.0', at=timezone.now() - datetime.timedelta(seconds=1)).nonconformance  # 재검사는 반드시 이후(시계 해상도 무관)
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
        res = spc.control_chart(groups, lsl=9, usl=11)
        self.assertEqual(res['n'], 3)
        self.assertIn('관리한계 이탈', res['points'][-1]['alarms'])
        self.assertIsNotNone(res['cpk'])
        with self.assertRaises(ValueError):
            spc.control_chart([(0, [1, 2]), (1, [2])])  # 부분군 크기가 섞이면 안 된다

    def test_nine_points_one_side(self):
        groups = [(i, [9, 9.2]) for i in range(5)] + [(i, [10, 10.1]) for i in range(5, 14)]
        res = spc.control_chart(groups)
        self.assertIn('중심선 한쪽 연속 9점', res['points'][-1]['alarms'])

    def test_i_mr(self):
        res = spc.control_chart([(i, [v]) for i, v in enumerate([10, 10.2, 9.8, 10.1, 9.9, 13])])
        self.assertEqual(res['kind'], 'I-MR')
        self.assertIsNone(res['points'][0]['r'])
        self.assertAlmostEqual(res['points'][1]['r'], 0.2)
        mrbar = (0.2 + 0.4 + 0.3 + 0.2 + 3.1) / 5
        self.assertAlmostEqual(res['limits']['ucl'], (10 + 10.2 + 9.8 + 10.1 + 9.9 + 13) / 6 + 2.66 * mrbar)
        self.assertIn('범위(R) 이탈', res['points'][-1]['alarms'])

    def test_special_characteristic_alarm_creates_nc(self):
        spec = InspectionSpec.objects.create(item=self.raw_item, inspection_type=InspectionSpec.PROCESS)
        cc = Characteristic.objects.create(spec=spec, name='용량', lsl=0, usl=100, special='CC')
        approve(spec, self.lead)

        def run(v):
            insp = Inspection.objects.create(lot=self.raw, spec=spec)
            Measurement.objects.create(inspection=insp, characteristic=cc, value=Decimal(v))
            insp.finalize()
            return insp
        for v in ('50', '50.5', '49.5', '50.2', '49.8', '50'):
            self.assertIsNone(run(v).nonconformance)
        insp = run('70')  # 규격 안이지만 관리한계 밖
        self.assertEqual(insp.result, Inspection.PASS)
        self.assertIn('SPC 경보', insp.nonconformance.description)
        self.assertTrue(self.cell.on_hold)

    # 계측기 · 자격
    def test_expired_gauge_rejected(self):
        g = Gauge.objects.create(number='MC-01', name='마이크로미터', interval_days=365,
                                 last_calibrated=timezone.localdate() - datetime.timedelta(days=400))
        insp = Inspection.objects.create(lot=self.raw, spec=self.spec)
        with self.assertRaises(ValidationError):
            Measurement.objects.create(inspection=insp, characteristic=self.thk, value=10, gauge=g)
        g.last_calibrated = timezone.localdate()
        g.save()
        Measurement.objects.create(inspection=insp, characteristic=self.thk, value=10, gauge=g)

    def test_qualification_enforced_once_registered(self):
        self.inspect('10.0')  # 자격 기록이 없으면 누구나 판정
        Qualification.objects.create(user=self.lead, inspection_type=InspectionSpec.INCOMING,
                                     valid_until=timezone.localdate() + datetime.timedelta(days=30), basis='교육')
        insp = Inspection.objects.create(lot=self.raw, spec=self.spec)
        Measurement.objects.create(inspection=insp, characteristic=self.thk, value=10)
        Measurement.objects.create(inspection=insp, characteristic=self.look, ok=True)
        with self.assertRaises(ValidationError):
            insp.finalize()  # 검사자 미지정
        insp.inspector = self.lead
        insp.save()
        insp.finalize()
        self.assertEqual(insp.result, Inspection.PASS)

    # 관리계획서 · 4M
    def test_control_plan_makes_specs(self):
        plan = ControlPlan.objects.create(item=self.cell_item)
        ControlPlanLine.objects.create(plan=plan, characteristic='용량', special='CC', lsl=95, usl=105,
                                       inspection_type=InspectionSpec.OUTGOING, severity=9, occurrence=4, detection=3)
        ControlPlanLine.objects.create(plan=plan, characteristic='온도', inspection_type='')
        self.client.force_login(self.lead)
        url = '/admin/qms/controlplan/'
        self.client.post(url, {'action': 'make_specs', '_selected_action': [plan.pk]})
        self.assertFalse(InspectionSpec.objects.filter(item=self.cell_item).exists())  # 미승인은 거부
        approve(plan, self.lead)
        self.assertEqual(plan.lines.first().action_priority, 'H')
        self.client.post(url, {'action': 'make_specs', '_selected_action': [plan.pk]})
        spec = InspectionSpec.objects.get(item=self.cell_item)
        self.assertEqual(spec.inspection_type, InspectionSpec.OUTGOING)
        self.assertEqual([(c.name, c.special) for c in spec.characteristics.all()], [('용량', 'CC')])
        self.assertFalse(spec.is_approved)

    def test_4m_change_blocks_shipment_until_first_article(self):
        cr = ChangeRequest.objects.create(number='4M-1', item=self.raw_item, category='MATERIAL', description='원료 협력사 변경',
                                          effective_at=timezone.now() - datetime.timedelta(hours=1))
        self.client.force_login(self.lead)
        self.client.post(f'/approve/qms/changerequest/{cr.pk}/', {'password': 'pw-lead-123'})
        cr.refresh_from_db()
        self.assertFalse(cr.is_approved)  # 고객 승인번호 없음
        cr.customer_approval_ref = 'CA-9'
        cr.save()
        self.client.post(f'/approve/qms/changerequest/{cr.pk}/', {'password': 'pw-lead-123'})
        cr.refresh_from_db()
        self.assertTrue(cr.is_approved)
        with self.assertRaises(ValidationError):
            Shipment.objects.create(lot=self.raw, customer='A사', qty=1)
        self.inspect('10.0')  # 초품 합격
        Shipment.objects.create(lot=self.raw, customer='A사', qty=1)

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

    def test_excel_fill_hides_user_secrets(self):
        wb = Workbook()
        buf = BytesIO()
        wb.save(buf)
        self.lead.first_name = '길동'
        self.lead.save()
        capa = Capa.objects.create(title='시정', due_date='2026-12-01', owner=self.lead)
        tpl = ExcelTemplate.objects.create(name='CAPA', target=ContentType.objects.get_for_model(Capa),
                                           file=SimpleUploadedFile('c.xlsx', buf.getvalue()),
                                           mapping={'A1': 'owner.password', 'A2': 'owner.username', 'A3': 'owner.email',
                                                    'A4': 'owner.payslip_set.first.base_pay', 'A5': 'owner.first_name',
                                                    'A6': 'owner.get_full_name', 'A7': 'title'})
        ws = load_workbook(BytesIO(tpl.fill(capa))).active
        self.assertEqual([ws[f'A{i}'].value for i in range(1, 8)], [None, 'lead', None, None, '길동', '길동', '시정'])

    def test_excel_fill_calls_only_read_methods(self):
        from .models import Memo, MemoPhoto
        wb = Workbook()
        buf = BytesIO()
        wb.save(buf)
        xlsx = buf.getvalue()
        claim = CustomerClaim.objects.create(number='CL-7', customer='A사', lot=self.cell, description='x')
        history = claim.history.count()
        claim.description = '저장 안 함'
        tpl = ExcelTemplate.objects.create(name='악성', target=ContentType.objects.get_for_model(CustomerClaim),
                                           file=SimpleUploadedFile('x.xlsx', xlsx),
                                           mapping={'A1': 'save', 'A2': 'refresh_from_db', 'A3': '_meta', 'A4': 'lot.delete',
                                                    'A5': 'delete', 'A6': 'number'})
        ws = load_workbook(BytesIO(tpl.fill(claim))).active
        self.assertEqual([ws[f'A{i}'].value for i in range(1, 7)], [None, None, None, None, None, 'CL-7'])
        self.assertEqual(claim.description, '저장 안 함')
        self.assertEqual(claim.history.count(), history)
        self.assertTrue(CustomerClaim.objects.filter(pk=claim.pk, description='x').exists())
        self.assertTrue(Lot.objects.filter(pk=self.cell.pk).exists())

        memo = Memo.objects.create(body='메모', speaker_kind='CUSTOMER', author=self.lead)
        MemoPhoto.objects.create(memo=memo, file='memo/a.jpg')
        tpl = ExcelTemplate.objects.create(name='메모', target=ContentType.objects.get_for_model(Memo),
                                           file=SimpleUploadedFile('m.xlsx', xlsx),
                                           mapping={'A1': 'photos.update', 'A2': 'photos.count', 'A3': 'photos.first.memo.body',
                                                    'A4': 'get_speaker_kind_display', 'A5': 'photos.all.delete',
                                                    'A6': 'photos.exists'})
        ws = load_workbook(BytesIO(tpl.fill(memo))).active
        self.assertEqual([ws[f'A{i}'].value for i in range(1, 7)], [None, 1, '메모', '고객', None, True])
        self.assertEqual(memo.photos.count(), 1)

    def test_coa(self):
        out_spec = InspectionSpec.objects.create(item=self.raw_item, inspection_type=InspectionSpec.OUTGOING)
        cap = Characteristic.objects.create(spec=out_spec, name='수분', usl=Decimal('200'), unit='ppm', special='SC')
        approve(out_spec, self.lead)
        self.inspect('10.0')  # 수입검사 합격 (출하검사가 있으면 그것을 쓴다)
        insp = Inspection.objects.create(lot=self.raw, spec=out_spec)
        Measurement.objects.create(inspection=insp, characteristic=cap, value=Decimal('150'))
        insp.finalize()
        ship = Shipment.objects.create(lot=self.raw, customer='A사', qty=1)
        self.assertEqual(ship.coa_rows(), [['수분', 'SC', None, Decimal('200'), 'ppm', Decimal('150'), '합격']])
        wb = Workbook()
        buf = BytesIO()
        wb.save(buf)
        tpl = ExcelTemplate.objects.create(name='A사 COA', target=ContentType.objects.get_for_model(Shipment),
                                           file=SimpleUploadedFile('coa.xlsx', buf.getvalue()),
                                           mapping={'B1': 'lot.number', 'A3': 'coa_rows'})
        ws = load_workbook(BytesIO(tpl.fill(ship))).active
        self.assertEqual([ws['B1'].value, ws['A3'].value, ws['F3'].value, ws['G3'].value], ['RAW-1', '수분', 150, '합격'])
        self.client.force_login(self.lead)
        self.assertContains(self.client.get(f'/print/core/shipment/{ship.pk}/'), '출하성적서')

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
        (live / 'private' / 'personal').mkdir(parents=True)
        (live / 'private' / 'personal' / 's.pdf').write_bytes(b'pay')
        db = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': live / 'db.sqlite3'}}
        with override_settings(DATABASES=db, DATA_DIR=live, MEDIA_ROOT=live / 'media'):
            call_command('backup', str(dest))
            backup = next(dest.iterdir())
            out = StringIO()
            call_command('restore', str(backup), stdout=out)
            self.assertIn('리허설 통과', out.getvalue())
            self.assertIn('core_lot: 2건', out.getvalue())
            self.assertEqual((backup / 'private' / 'personal' / 's.pdf').read_bytes(), b'pay')
            (live / 'private' / 'personal' / 's.pdf').unlink()  # 운영 쪽 파일이 사라진 상황
            call_command('restore', str(backup), '--apply', stdout=StringIO())
            self.assertEqual((live / 'private' / 'personal' / 's.pdf').read_bytes(), b'pay')
        self.assertTrue(any(p.name.startswith('pre-restore-') for p in live.iterdir()))
        for p in live.glob('pre-restore-*'):  # 같은 초에 만든 보관 폴더와 겹치지 않게
            shutil.rmtree(p)
        shutil.rmtree(backup / 'private')  # 옛 백업: private 없음 -> 현재 파일 유지
        with override_settings(DATABASES=db, DATA_DIR=live, MEDIA_ROOT=live / 'media'):
            call_command('restore', str(backup), '--apply', stdout=StringIO())
        self.assertEqual((live / 'private' / 'personal' / 's.pdf').read_bytes(), b'pay')
        (backup / 'db.sqlite3').write_bytes(b'not a db')
        with self.assertRaises(CommandError):
            call_command('restore', str(backup), stdout=StringIO())

    def test_secret_key_not_in_code(self):
        from django.conf import settings
        self.assertNotIn('django-insecure', settings.SECRET_KEY)
        self.assertNotIn('django-insecure', (Path(settings.BASE_DIR) / 'config' / 'settings.py').read_text('utf-8'))

    # KPI · 협력사 · 재발 방지
    def test_kpi_and_suppliers(self):
        self.raw.supplier = 'B소재'
        self.raw.qty = 1000
        self.raw.save()
        Shipment.objects.create(lot=self.cell, customer='A사', qty=2000)
        claim = CustomerClaim.objects.create(number='CL-1', customer='A사', lot=self.cell, description='x', defect_qty=4)
        Nonconformance.objects.filter(pk=claim.nonconformance_id).update(defect_type='용량', defect_qty=4, cost=30000)
        self.inspect('11.0').nonconformance  # 수입검사 불합격 → 부적합
        Nonconformance.objects.filter(lot=self.raw).update(defect_type='치수', defect_qty=10, cost=5000)
        self.inspect('10.0')  # 같은 LOT 재검사 합격은 직행률에 들어가지 않는다
        Scar.objects.create(number='S-1', supplier='B소재', lot=self.raw, request='개선', response_due=timezone.localdate() - datetime.timedelta(days=1))

        this_month = kpi.monthly(1)[0]
        self.assertEqual(this_month['ppm'], 4 / 2000 * 1e6)
        self.assertEqual(this_month['fpy'], 0.0)  # (RAW-1, 수입검사)의 첫 판정이 불합격
        self.assertEqual(this_month['copq'], 35000)
        self.assertEqual([p['defect_type'] for p in kpi.pareto(1)], ['치수', '용량'])
        b = next(r for r in kpi.suppliers(1) if r['name'] == 'B소재')
        self.assertEqual((b['inspections'], b['fail_rate'], b['ppm'], b['scars'], b['scar_on_time']),
                         (2, 50.0, 10 / 1000 * 1e6, 1, 0.0))
        self.client.force_login(self.lead)
        self.assertContains(self.client.get('/kpi/?months=3'), '치수')
        self.assertContains(self.client.get('/suppliers/'), 'B소재')

    def test_similar_past_cases(self):
        old = CustomerClaim.objects.create(number='CL-OLD', customer='A사', lot=self.cell, description='셀 용량 미달 불량',
                                           **{f: '완료' for f, _ in CustomerClaim.STEPS})
        old.d4_root_cause = '전해액 주입량 부족'
        old.closed_at = timezone.now()
        old.save()
        nc = old.nonconformance
        nc.disposition, nc.approved_by, nc.customer_approval_ref = Nonconformance.CONCESSION, self.lead, 'CA-1'
        nc.save()
        unrelated = Nonconformance.objects.create(lot=Lot.objects.create(number='X', item=Item.objects.create(
            code='Z', name='z', item_type=Item.RAW)), description='포장 파손')
        unrelated.disposition, unrelated.approved_by, unrelated.customer_approval_ref = Nonconformance.CONCESSION, self.lead, 'C'
        unrelated.save()
        new = Nonconformance.objects.create(lot=self.cell, description='용량 미달 발생')
        found = similar(new)
        self.assertEqual([p for _, p, _ in found], [nc])
        self.client.force_login(self.lead)
        self.assertContains(self.client.get(f'/admin/core/nonconformance/{new.pk}/change/'), '전해액 주입량 부족')

    # CAPA · 내부심사 · PPAP · 알림
    def test_capa_lifecycle_and_link_from_source(self):
        scar = Scar.objects.create(number='S-1', supplier='B소재', lot=self.raw, request='치수 불량 개선',
                                   response_due=timezone.localdate())
        self.client.force_login(self.lead)
        page = self.client.get(f'/admin/qms/scar/{scar.pk}/change/').content.decode()
        self.assertIn('CAPA 만들기', page)
        add_url = re.search(r'href="(/admin/qms/capa/add/\?[^"]+)"', page).group(1).replace('&amp;', '&')
        self.assertContains(self.client.get(add_url), 'S-1 B소재')  # 제목이 미리 채워짐
        capa = Capa.objects.create(title='치수', source='SCAR', source_type=ContentType.objects.get_for_model(Scar),
                                   source_id=scar.pk, action='금형 보정', owner=self.lead,
                                   due_date=timezone.localdate() - datetime.timedelta(days=1))
        self.assertEqual(capa.status, '기한 초과')
        second = Capa.objects.create(title='둘째', source='OTHER', action='x', owner=self.lead, due_date=timezone.localdate())
        self.assertEqual((capa.number[-3:], second.number[-3:]), ('001', '002'))  # 같은 순간에 만들어도 번호가 겹치지 않음
        self.assertIn(capa.number, self.client.get(f'/admin/qms/scar/{scar.pk}/change/').content.decode())
        capa.closed_at = timezone.localdate()
        with self.assertRaises(ValidationError):  # 유효성 확인 없이 종결
            capa.save()
        capa.closed_at, capa.done_at = None, timezone.localdate()
        capa.save()
        self.assertEqual(capa.status, '유효성 확인 대기')
        capa.effective, capa.verified_at, capa.verified_by = True, timezone.localdate(), self.lead
        capa.closed_at = timezone.localdate()
        capa.save()
        self.assertEqual(capa.status, '종결')

    def test_internal_audit_needs_capa_for_major_minor(self):
        audit = InternalAudit.objects.create(name='공정심사', planned_date=timezone.localdate(), auditor='김심사',
                                             performed_at=timezone.localdate())
        finding = AuditFinding.objects.create(audit=audit, clause='8.5.1', grade='MINOR', description='작업표준 미게시')
        AuditFinding.objects.create(audit=audit, clause='7.5', grade='OBS', description='관찰')
        audit.closed_at = timezone.localdate()
        with self.assertRaises(ValidationError):
            audit.save()
        Capa.objects.create(title='표준 게시', source='AUDIT', source_type=ContentType.objects.get_for_model(AuditFinding),
                            source_id=finding.pk, action='게시', owner=self.lead, due_date=timezone.localdate())
        finding.refresh_from_db()
        self.assertIsNotNone(finding.capa)  # 지적에서 만든 CAPA가 자동 연결
        audit.save()

    def test_ppap_elements_and_psw_signature(self):
        plan = ControlPlan.objects.create(item=self.raw_item)
        approve(plan, self.lead)
        ppap = PpapSubmission.objects.create(item=self.raw_item, customer='A사', level=3, reason='신규')
        self.assertEqual(ppap.elements.count(), 18)
        self.assertEqual(ppap.elements.get(number=7).record, plan)  # 관리계획서 자동 연결
        self.assertEqual(ppap.elements.get(number=15).requirement, 'R')
        self.client.force_login(self.lead)
        url = f'/approve/qms/ppapsubmission/{ppap.pk}/'
        self.assertContains(self.client.post(url, {'password': 'pw-lead-123'}), '증적이 없습니다')
        doc = Document.objects.create(number='D-1', title='PPAP 묶음')
        for e in ppap.missing_elements():
            e.document = doc
            e.save()
        self.client.post(url, {'password': 'pw-lead-123'})
        ppap.refresh_from_db()
        self.assertTrue(ppap.is_approved)
        ppap.submitted_at = timezone.localdate()
        ppap.save()  # 승인 후에도 제출일은 기록
        ppap.level = 2
        with self.assertRaises(ValidationError):
            ppap.save()
        self.assertContains(self.client.get(f'/print/qms/ppapsubmission/{ppap.pk}/'), '부품 제출 보증서')

    def test_due_items_nc_and_requests(self):
        from core.models import EditRequest
        from .due import digest, due_items
        su = User.objects.create_superuser('su11', password='pw-su-123')
        nc = Nonconformance.objects.create(lot=self.cell, description='x')  # 보완 필요 항목 있음
        nc2 = Nonconformance.objects.create(lot=self.cell, description='y', approved_at=timezone.now(), customer_notify=True)
        ct = ContentType.objects.get_for_model(Nonconformance)
        EditRequest.objects.create(kind='EDIT', content_type=ct, object_id=nc.pk, object_repr='a', reason='r', requested_by=self.lead)
        EditRequest.objects.create(kind='EDIT', content_type=ct, object_id=nc.pk, object_repr='b', reason='r', requested_by=self.lead,
                                   status='REJECTED', decided_at=timezone.now(), reject_reason='no')
        EditRequest.objects.create(kind='EDIT', content_type=ct, object_id=nc.pk, object_repr='c', reason='r', requested_by=self.lead,
                                   status='REJECTED', decided_at=timezone.now() - datetime.timedelta(days=8))
        from .models import Memo
        Memo.objects.create(body='m', author=self.lead)
        d = due_items(user=su)
        self.assertIn(nc, d['nc_incomplete'])
        self.assertEqual(d['nc_mail_pending'], [nc2])
        self.assertEqual(d['nc_notify_pending'], [nc2])
        self.assertEqual(len(d['edit_requests']), 1)
        self.assertEqual(d['my_rejected'], [])
        self.assertEqual(d['memos_unsorted'], 1)
        self.assertEqual([r.object_repr for r in due_items(user=self.lead)['my_rejected']], ['b'])
        self.assertEqual(due_items(user=self.lead)['edit_requests'], [])
        titles = [t for t, _ in digest(due_items(approver=True))]
        for t in ('부적합 보완 필요', '메일 발송 대기', '고객 통보 미처리', '삭제·수정 요청 대기'):
            self.assertIn(t, titles)

    @override_settings(MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}})
    def test_notify(self):
        from django.core import mail
        out = StringIO()
        with mock.patch.dict('os.environ', {'QMS_NOTIFY_EMAILS': 'qa@example.com', 'QMS_TEAMS_WEBHOOK': ''}):
            call_command('notify', stdout=out)
        self.assertIn('보낼 항목이 없습니다', out.getvalue())
        self.assertEqual(len(mail.outbox), 0)
        Gauge.objects.create(number='MC-01', name='마이크로미터', last_calibrated=timezone.localdate() - datetime.timedelta(days=400))
        with mock.patch.dict('os.environ', {'QMS_NOTIFY_EMAILS': 'qa@example.com', 'QMS_TEAMS_WEBHOOK': 'https://hook'}), \
                mock.patch('urllib.request.urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.status = 202
            call_command('notify', stdout=StringIO())
        self.assertEqual(mail.outbox[0].to, ['qa@example.com'])
        self.assertIn('MC-01', mail.outbox[0].body)
        payload = json.loads(urlopen.call_args[0][0].data)
        self.assertIn('MC-01', json.dumps(payload, ensure_ascii=False))

    # 검사원 입력 화면
    def test_inspector_screen_flow(self):
        clerk = User.objects.create_user('clerk', password='pw-clerk-123', is_staff=True)
        clerk.groups.add(Group.objects.get(name='검사원'))
        self.client.force_login(clerk)
        self.assertContains(self.client.get('/inspect/lot/?lot=RAW-1'), f'/inspect/{self.raw.pk}/{self.spec.pk}/')
        self.assertContains(self.client.get('/inspect/lot/?lot=NOPE'), '찾을 수 없습니다')
        self.assertContains(self.client.post(f'/inspect/check/{self.thk.pk}/', {f'c{self.thk.pk}': '11'}), '규격 이탈')
        url = f'/inspect/{self.raw.pk}/{self.spec.pk}/submit/'
        r = self.client.post(url, {f'c{self.thk.pk}': '10.0'})  # 외관 누락 → 아무것도 저장 안 됨
        self.assertContains(r, '값을 입력하세요')
        self.assertFalse(Inspection.objects.exists())
        r = self.client.post(url, {f'c{self.thk.pk}': '11.0', f'c{self.look.pk}': 'OK'})
        self.assertContains(r, '하위 계보 보류')
        insp = Inspection.objects.get()
        self.assertEqual((insp.result, insp.inspector), (Inspection.FAIL, clerk))
        self.assertTrue(self.cell.on_hold)
        outsider = User.objects.create_user('viewer', password='x', is_staff=True)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get('/inspect/').status_code, 403)

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

    def test_capa_source_choices(self):
        from django.contrib import admin
        self.client.force_login(User.objects.create_superuser('admin', password='x'))
        req = self.client.get('/admin/qms/capa/add/').wsgi_request
        qs = admin.site._registry[Capa].get_form(req)().fields['source_type'].queryset
        self.assertEqual(sorted(qs.values_list('model', flat=True)), ['auditfinding', 'customerclaim', 'nonconformance', 'scar'])

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
        # 빨간 상태 배지가 그려지는 화면들 (format_html 인자 누락 회귀 방지)
        ppap = PpapSubmission.objects.create(item=self.cell_item, customer='A사', reason='신규')
        AuditItem.objects.create(checklist=AuditChecklist.objects.create(name='QSA'), clause='1', requirement='x')
        cr = ChangeRequest.objects.create(number='4M-9', item=self.cell_item, category='MAN', description='x',
                                          customer_notice=False, effective_at=timezone.now() + datetime.timedelta(days=1))
        approve(cr, self.lead)
        audit = InternalAudit.objects.create(name='심사', planned_date=timezone.localdate(), auditor='김')
        AuditFinding.objects.create(audit=audit, grade='MAJOR', description='x')
        for url in (f'/admin/qms/ppapsubmission/{ppap.pk}/change/', '/admin/qms/audititem/', '/admin/qms/changerequest/',
                    '/admin/qms/internalaudit/', f'/admin/qms/internalaudit/{audit.pk}/change/', '/admin/qms/capa/add/',
                    '/admin/core/workorder/add/', '/kpi/', '/suppliers/', '/inspect/', '/trace/?lot=CELL-1'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        scar = Scar.objects.create(number='S-1', supplier='B사', lot=self.raw, request='x', response_due=timezone.localdate())
        gauge = Gauge.objects.create(number='G-1', name='캘리퍼스', last_calibrated=timezone.localdate())
        wo = WorkOrder.objects.create(number='WO-9', item=self.cell_item, planned_qty=1)
        for url in ('/admin/qms/ppapsubmission/add/', '/admin/qms/scar/add/', f'/admin/qms/scar/{scar.pk}/change/',
                    '/admin/qms/internalaudit/add/', '/admin/qms/gauge/add/', f'/admin/qms/gauge/{gauge.pk}/change/',
                    '/admin/qms/customerclaim/add/', f'/admin/core/workorder/{wo.pk}/change/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        for url in ('/admin/qms/inspection/add/', f'/admin/qms/customerclaim/{claim.pk}/change/',
                    f'/admin/qms/inspectionspec/{self.spec.pk}/change/', '/admin/core/nonconformance/add/',
                    '/admin/qms/auditchecklist/add/', '/admin/qms/document/add/', '/import/', '/admin/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class TimelineTest(TestCase):
    inspect = QmsTest.inspect  # 같은 픽스처를 쓰되 QmsTest의 테스트는 다시 돌리지 않는다

    def setUp(self):
        QmsTest.setUp(self)
        self.admin = User.objects.create_superuser('tl-admin')

    def test_order(self):
        from core.timeline import lot_timeline
        now = timezone.now()  # 시계 해상도와 무관하게: LOT 생성 < 불합격 < 재검사 합격 < 처분·출하
        Lot.objects.filter(pk=self.raw.pk).update(created_at=now - datetime.timedelta(seconds=10))
        self.raw.refresh_from_db()
        nc = self.inspect('11.0', at=now - datetime.timedelta(seconds=5)).nonconformance
        self.inspect('10.0')
        nc.disposition, nc.approved_by = Nonconformance.REWORK, self.lead
        nc.save()
        Shipment.objects.create(lot=self.raw, customer='A사', qty=1)
        self.assertEqual([e['kind'] for e in lot_timeline(self.raw)],
                         ['created', 'inspection', 'nc', 'inspection', 'disposition', 'shipment'])

    def test_actions_held(self):
        from core.timeline import lot_actions
        self.inspect('11.0')
        names = [n for n, _ in lot_actions(self.raw, self.admin)]
        self.assertEqual(names[0], '처분 입력')
        self.assertNotIn('출하 등록', names)

    def test_actions_fresh_and_perms(self):
        from core.timeline import lot_actions
        self.assertEqual([n for n, _ in lot_actions(self.raw, self.admin)], ['검사 입력', '부적합 등록'])
        self.assertEqual(lot_actions(self.raw, User.objects.create_user('nobody', is_staff=True)), [])

    def test_trace_page(self):
        self.client.force_login(self.admin)
        r = self.client.get('/trace/', {'lot': 'RAW-1'})
        self.assertContains(r, 'class="timeline"')

    def test_summary_badges_and_inherited_hold_action(self):
        from core.timeline import lot_actions
        self.client.force_login(self.admin)
        self.raw.supplier = '협력A'
        self.raw.qty = Decimal('7')
        self.raw.save()
        self.inspect('10.0')
        r = self.client.get('/trace/', {'lot': 'RAW-1'})
        self.assertContains(r, '협력A')
        self.assertContains(r, '수량 7')
        self.assertNotContains(r, '출하완료')
        Shipment.objects.create(lot=self.raw, customer='A사', qty=1)
        self.assertContains(self.client.get('/trace/', {'lot': 'RAW-1'}), '출하완료')
        nc = Nonconformance.objects.create(lot=self.raw, description='x')  # 하위 CELL-1도 보류
        self.assertContains(self.client.get('/trace/', {'lot': 'CELL-1'}), '보류 중')
        acts = lot_actions(self.cell, self.admin)
        self.assertEqual(acts[0][0], '처분 입력')
        self.assertIn(f'/{nc.pk}/change/', acts[0][1])
        self.assertNotIn('출하 등록', [n for n, _ in acts])

    def test_scrapped_lot_has_no_disposition_or_ship_action(self):
        from core.timeline import lot_actions
        nc = Nonconformance.objects.create(lot=self.raw, description='x')
        nc.disposition, nc.approved_by = Nonconformance.SCRAP, self.lead
        nc.save()
        names = [n for n, _ in lot_actions(self.raw, self.admin)]
        self.assertNotIn('처분 입력', names)
        self.assertNotIn('출하 등록', names)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class MemoTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('memo-admin')
        self.item = Item.objects.create(code='M1', name='셀', item_type=Item.FINISHED)
        self.lot = Lot.objects.create(number='L1', item=self.item)
        self.nc = Nonconformance.objects.create(lot=self.lot, description='찍힘')
        self.client.force_login(self.admin)

    def test_attached_to_record(self):
        from .models import Memo
        r = self.client.get(f'/memo/new/?ct=core.nonconformance&id={self.nc.pk}', HTTP_HX_REQUEST='true')
        self.assertContains(r, 'hx-post=')
        self.assertNotContains(r, '<html')
        photo = SimpleUploadedFile('a.jpg', b'x', content_type='image/jpeg')
        r = self.client.post(f'/memo/new/?ct=core.nonconformance&id={self.nc.pk}',
                             {'body': '포장 라벨 확인 요청', 'speaker_kind': 'AUDITOR', 'photos': [photo]},
                             HTTP_HX_REQUEST='true')
        self.assertContains(r, '포장 라벨 확인 요청')
        memo = Memo.objects.get()
        self.assertEqual(memo.target, self.nc)
        self.assertEqual(memo.author, self.admin)
        self.assertEqual(memo.photos.count(), 1)
        self.assertContains(self.client.get(f'/admin/core/nonconformance/{self.nc.pk}/change/'), '포장 라벨 확인 요청')
        self.assertContains(self.client.get('/trace/', {'lot': 'L1'}), 'id="memo-box"')

    def test_auto_audit(self):
        from .memo import todays_audit
        today = timezone.localdate()
        self.assertIsNone(self.client.get('/memo/new/').context['form']['audit'].value())
        planned = InternalAudit.objects.create(name='계획', planned_date=today, auditor='김')
        done = InternalAudit.objects.create(name='실시', planned_date=today - datetime.timedelta(days=3),
                                            performed_at=today, auditor='이', kind='CUSTOMER')
        self.assertEqual(todays_audit(today), done)
        self.assertEqual(self.client.get('/memo/new/').context['form']['audit'].value(), done.pk)
        done.performed_at = today - datetime.timedelta(days=1)
        done.save()
        self.assertEqual(todays_audit(today), planned)
        self.assertIsNone(todays_audit(today + datetime.timedelta(days=1)))

    def test_inbox_assign(self):
        from .models import Memo
        r = self.client.post('/memo/new/', {'body': '창고 온도', 'speaker_kind': 'INSPECTOR'})
        self.assertRedirects(r, '/memo/inbox/')
        memo = Memo.objects.get()
        self.assertIsNone(memo.target)
        self.assertContains(self.client.get('/memo/inbox/'), '창고 온도')
        r = self.client.post('/memo/inbox/', {'memo': memo.pk, 'kind': 'LOT', 'number': 'NOPE'}, follow=True)
        self.assertContains(r, '찾을 수 없습니다')
        memo.refresh_from_db()
        self.assertIsNone(memo.target)
        self.client.post('/memo/inbox/', {'memo': memo.pk, 'kind': 'LOT', 'number': ' L1 \n'})
        memo.refresh_from_db()
        self.assertEqual(memo.target, self.lot)

    def test_audit_memo_list(self):
        from .models import Memo
        audit = InternalAudit.objects.create(name='고객 심사', planned_date=timezone.localdate(), auditor='김')
        Memo.objects.create(body='라벨 위치 지적', target=self.nc, audit=audit, author=self.admin)
        r = self.client.get(f'/admin/qms/internalaudit/{audit.pk}/change/')
        self.assertContains(r, '이번 심사 메모')
        self.assertContains(r, '라벨 위치 지적')
        self.assertContains(r, 'CAPA 만들기')

    def test_only_author_edits(self):
        from .models import Memo
        memo = Memo.objects.create(body='원문', author=self.admin)
        other = User.objects.create_user('other', is_staff=True)
        other.groups.add(Group.objects.get(name='품질엔지니어'))
        self.client.force_login(other)
        self.assertEqual(self.client.post(f'/memo/{memo.pk}/edit/', {'body': '바꿈', 'speaker_kind': 'OTHER'}).status_code, 403)
        self.assertEqual(self.client.post(f'/admin/qms/memo/{memo.pk}/change/', {'body': '바꿈', 'speaker_kind': 'OTHER'}).status_code, 403)
        memo.refresh_from_db()
        self.assertEqual(memo.body, '원문')
        self.client.force_login(self.admin)
        self.client.post(f'/memo/{memo.pk}/edit/', {'body': '바꿈', 'speaker_kind': 'OTHER'})
        memo.refresh_from_db()
        self.assertEqual(memo.body, '바꿈')

    def test_audit_memo_capa_links(self):
        from .models import Memo
        audit = InternalAudit.objects.create(name='심사A', planned_date=timezone.localdate(), auditor='김')
        Memo.objects.create(body='부적합 건', target=self.nc, audit=audit, author=self.admin)
        Memo.objects.create(body='LOT 건', target=self.lot, audit=audit, author=self.admin)
        html = self.client.get(f'/admin/qms/internalaudit/{audit.pk}/change/').content.decode()
        nc_ct = ContentType.objects.get_for_model(Nonconformance).pk
        self.assertIn(f'source_type={nc_ct}', html)
        self.assertEqual(html.count('source_type='), 1)  # LOT 메모는 출처 기록 없이
        self.assertIn('source=AUDIT&amp;title=%EC%8B%AC%EC%82%ACA%3A+LOT', html)

    def test_inbox_bad_id_and_permissions(self):
        from .models import Memo
        self.assertEqual(self.client.post('/memo/inbox/', {'memo': 'abc', 'kind': 'LOT', 'number': 'L1'}).status_code, 404)
        capa = Capa.objects.create(title='t', source='OTHER', action='a', owner=self.admin, due_date=timezone.localdate())
        inspector = User.objects.create_user('insp', is_staff=True)
        inspector.groups.add(Group.objects.get(name='검사원'))
        own = Memo.objects.create(body='검사원 메모', author=inspector)
        self.client.force_login(inspector)
        r = self.client.post('/memo/inbox/', {'memo': own.pk, 'kind': 'CAPA', 'number': capa.number}, follow=True)
        self.assertContains(r, '찾을 수 없습니다')
        own.refresh_from_db()
        self.assertIsNone(own.target)
        others = Memo.objects.create(body='남의 메모', author=self.admin)
        self.assertEqual(self.client.post('/memo/inbox/', {'memo': others.pk, 'kind': 'LOT', 'number': 'L1'}).status_code, 403)
        eng = User.objects.create_user('eng', is_staff=True)
        eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.client.force_login(eng)
        self.client.post('/memo/inbox/', {'memo': others.pk, 'kind': 'LOT', 'number': 'L1'})
        others.refresh_from_db()
        self.assertEqual(others.target, self.lot)

    def test_ct_allow_list_and_no_js_redirect(self):
        self.assertEqual(self.client.get(f'/memo/new/?ct=core.hold&id={self.lot.holds.get().pk}').status_code, 404)
        self.assertEqual(self.client.get(f'/memo/new/?ct=auth.user&id={self.admin.pk}').status_code, 404)
        data = {'body': 'x', 'speaker_kind': 'OTHER'}
        r = self.client.post(f'/memo/new/?ct=core.nonconformance&id={self.nc.pk}', data)
        self.assertRedirects(r, f'/admin/core/nonconformance/{self.nc.pk}/change/')
        r = self.client.post(f'/memo/new/?ct=core.lot&id={self.lot.pk}', data)
        self.assertRedirects(r, '/trace/?lot=L1')


class AuditPackTest(TestCase):
    def setUp(self):
        from core.models import NonconformancePhoto
        self.media = tempfile.mkdtemp()
        ov = override_settings(MEDIA_ROOT=self.media)
        ov.enable()
        self.addCleanup(ov.disable)
        self.admin = User.objects.create_superuser('pack-admin')
        self.client.force_login(self.admin)
        self.i1 = Item.objects.create(code='I1', name='셀', item_type=Item.FINISHED)
        i2 = Item.objects.create(code='I2', name='팩', item_type=Item.FINISHED)
        now = timezone.now()
        self.ncs = {}
        for key, item, days in (('in', self.i1, 5), ('out', self.i1, 200), ('other', i2, 5)):
            lot = Lot.objects.create(number=f'L-{key}', item=item)
            nc = Nonconformance.objects.create(lot=lot, description=key, detected_at=now - datetime.timedelta(days=days))
            NonconformancePhoto.objects.create(nonconformance=nc, file=SimpleUploadedFile(f'{key}.jpg', b'0' * 10))
            self.ncs[key] = nc
        self.url = f'?item={self.i1.pk}'

    def test_pack_contents(self):
        r = self.client.get('/audit-pack/' + self.url)
        self.assertContains(r, self.ncs['in'].number)
        self.assertNotContains(r, self.ncs['out'].number)
        self.assertNotContains(r, self.ncs['other'].number)
        r = self.client.get('/audit-pack/' + self.url + '&from=2026-13-40&to=x')
        self.assertContains(r, '날짜 형식이 올바르지 않습니다')
        r = self.client.get('/audit-pack/' + self.url + '&from=2026-10-27&to=2026-10-01')
        self.assertContains(r, '시작일이 종료일보다 늦습니다')

    def test_pack_zip(self):
        import zipfile
        r = self.client.get('/audit-pack/zip/' + self.url)
        with zipfile.ZipFile(BytesIO(r.content)) as z:
            names = z.namelist()
        self.assertEqual(names, [f"부적합/{self.ncs['in'].number}_1.jpg"])

    def test_pack_needs_permission(self):
        self.client.force_login(User.objects.create_user('nobody', is_staff=True))
        self.assertEqual(self.client.get('/audit-pack/' + self.url).status_code, 403)


class DashboardTest(TestCase):
    def setUp(self):
        self.inspector = User.objects.create_user('insp', password='x', is_staff=True)
        self.admin = User.objects.create_superuser('boss', password='x')
        self.client.force_login(self.inspector)

    def save(self, items):
        return self.client.post('/dashboard/save/', json.dumps(items), content_type='application/json')

    def keys(self, user):
        from .widgets import layout_for
        return [w['key'] for w in layout_for(user)]

    def test_default_by_role(self):
        self.assertNotIn('edit_requests', self.keys(self.inspector))
        self.assertIn('edit_requests', self.keys(self.admin))
        self.assertNotIn('approvals', self.keys(self.inspector))
        self.assertIn('approvals', self.keys(self.admin))
        lead = User.objects.create_user('lead', is_staff=True)
        lead.groups.add(Group.objects.get_or_create(name=APPROVER_GROUP)[0])
        self.assertIn('approvals', self.keys(lead))

    def test_spc_card_once(self):
        from types import SimpleNamespace
        char = SimpleNamespace(pk=1, name='두께', spec=SimpleNamespace(item=SimpleNamespace(code='P-1')))
        alarm = {'char': char, 'lot': 'LOT-X', 'alarms': ['규칙1-UNIQUE']}
        with mock.patch('qms.due.recent_spc_alarms', return_value=[alarm]):
            html = self.client.get('/todo/').content.decode()
        self.assertEqual(html.count('규칙1-UNIQUE'), 1)

    def test_every_widget_renders(self):
        from .widgets import WIDGETS
        self.client.force_login(self.admin)
        self.assertEqual(self.save([{'key': k, 'size': 'normal'} for k in WIDGETS]).status_code, 200)
        r = self.client.get('/todo/')
        self.assertNotContains(r, '불러오기 실패')
        for w in WIDGETS.values():
            self.assertContains(r, w.title)

    def test_save_and_load(self):
        from .widgets import layout_for
        items = [{'key': 'gauges', 'size': 'wide'}, {'key': 'held_lots', 'size': 'normal'}]
        self.assertEqual(self.save(items).status_code, 200)
        self.assertEqual(layout_for(self.inspector), items)

    def test_rejects_bad_payload(self):
        for items in ([{'key': 'nope', 'size': 'normal'}], [{'key': 'edit_requests', 'size': 'normal'}],
                      [{'key': 'approvals', 'size': 'normal'}],
                      [{'key': 'gauges', 'size': 'huge'}],
                      [{'key': 'gauges', 'size': 'normal'}, {'key': 'gauges', 'size': 'wide'}]):
            self.assertEqual(self.save(items).status_code, 400, items)
        r = self.client.post('/dashboard/save/', 'not json', content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(DashboardLayout.objects.exists())

    def test_stale_layout(self):
        from .widgets import DEFAULT_LAYOUTS, layout_for
        row = DashboardLayout.objects.create(user=self.inspector, widgets=[{'key': 'gone'}, {'key': 'held_lots'}])
        self.assertEqual(self.keys(self.inspector), ['held_lots'])
        row.widgets = 'not a list'
        row.save()
        self.assertEqual(layout_for(self.inspector), DEFAULT_LAYOUTS['inspector'])

    def test_failing_widget_isolated(self):
        from .widgets import WIDGETS
        self.save([{'key': 'gauges', 'size': 'normal'}, {'key': 'held_lots', 'size': 'normal'}])

        def boom(request, d):
            raise RuntimeError('x')
        with mock.patch.object(WIDGETS['gauges'], 'context', boom), self.assertLogs('qms', 'ERROR'):
            r = self.client.get('/todo/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '불러오기 실패')
        self.assertContains(r, '보류 LOT')

    def test_reset(self):
        self.save([{'key': 'gauges', 'size': 'normal'}])
        self.assertEqual(self.save([]).status_code, 200)
        self.assertFalse(DashboardLayout.objects.exists())

    def test_leave_owner_only(self):
        from personal.models import LeaveProfile
        LeaveProfile.objects.create(owner=self.admin, hired_on=datetime.date(2020, 1, 1))
        self.save([{'key': 'leave', 'size': 'normal'}])
        self.assertContains(self.client.get('/todo/'), '연차 정보 없음')
