"""3단계 ① 들여오기 대상 일반화(docs/data-flow.md 5·7절): 대상마다 미리보기·확정, 키로 고치기, 잠금·권한·모듈·보류."""
import codecs
import csv
import io

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from rest_framework.test import APIClient

from core.api.tests_master import grant
from core.importer import headers, preview_import, problems, run_import, targets
from core.models import (CodeValue, Department, ImportProfile, Item, Lot, Nonconformance, Partner, Process, RoutingStep,
                         Shipment, WorkOrder)
from core.rules import LOCKED_MSG
from core.tests_modules import force_off
from qms.models import AuditChecklist, ChangeRequest, Gauge, InternalAudit

# 대상마다 한 행. 대상이 늘면 여기에 한 줄 더한다(test_every_target_has_sample).
SAMPLES = {
    'item': {'code': 'N1', 'name': '새 품목', 'item_type': '원자재'},
    'qms.document': {'number': 'QP-9', 'title': '품질 매뉴얼'},
    'qms.gauge': {'number': 'G-9', 'name': '캘리퍼스', 'cal_type': '사내 교정', 'interval_months': '12',
                  'last_calibrated': '2026-11-01', 'active': '예'},
    'qms.gaugecalibration': {'gauge': 'G-1', 'calibrated_on': '2026-11-02', 'cal_type': '사외 교정', 'result': '합격'},
    'qms.qualification': {'user': 'kim', 'inspection_type': '수입검사', 'valid_until': '2027-12-31', 'basis': '교육 이수'},
    'core.lot': {'number': 'L-9', 'item': 'C1', 'qty': '5', 'is_serial': '아니오'},
    'qms.capa': {'title': '재발 방지', 'source': '기타', 'owner': 'kim', 'due_date': '2026-12-31', 'action': '교육'},
    'qms.customerclaim': {'number': 'CC-9', 'customer': 'H사', 'lot': 'L-1', 'description': '긁힘', 'defect_qty': '1'},
    'qms.customerrule': {'customer': 'H사', 'containment_hours': '24', 'corrective_days': '30'},
    'qms.scar': {'number': 'SC-9', 'supplier': '공급사', 'lot': 'L-1', 'request': '원인 분석',
                 'issued_at': '2026-11-01', 'response_due': '2026-11-30'},
    'qms.changerequest': {'number': 'CR-9', 'item': 'C9', 'category': '설비(Machine)', 'description': '설비 교체',
                          'customer_notice': '아니오', 'effective_at': '2026-11-20 09:00'},
    'qms.internalaudit': {'name': 'IA-9', 'kind': '내부(1자)', 'planned_date': '2026-12-01', 'auditor': '홍길동',
                          'checklist': 'CL-A'},
    'qms.auditfinding': {'audit': 'IA-1', 'grade': '관찰', 'description': '기록 누락'},
    'qms.auditchecklist': {'name': 'CL-B'},
    'qms.audititem': {'checklist': 'CL-A', 'clause': '7.1.5', 'requirement': '계측기 관리'},
    'qms.ppapsubmission': {'item': 'C1', 'customer': 'H사', 'level': 'Level 3', 'reason': '신규 부품'},
    'work_order': {'number': 'WO-9', 'item': 'C1', 'process': 'P10', 'planned_qty': '10'},
    'core.workresult': {'work_order': 'WO-1', 'step': 'P10', 'lot': 'L-1', 'input_qty': '10', 'good_qty': '9',
                        'defect_qty': '1'},
    'core.shipment': {'lot': 'L-1', 'partner': 'P0001', 'customer': 'H사', 'qty': '5'},
    'core.partner': {'name': '새 거래처', 'is_customer': '예', 'is_supplier': '아니오', 'is_outsource': '아니오',
                     'is_calibrator': '아니오'},
    'core.department': {'code': 'PR', 'name': '생산', 'parent': 'QA', 'manager': 'kim', 'sort': '1'},
    'core.codevalue': {'group': '설계자료분류', 'code': 'ZZ', 'name': '기타 자료', 'sort': '1'},
}


def csv_file(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    return SimpleUploadedFile('a.csv', buf.getvalue().encode())


def xlsx_file(wb):
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile('a.xlsx', buf.getvalue())


class ImportTargetsTest(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root', password='pw')
        self.kim = User.objects.create_user('kim', password='pw', is_staff=True)
        Department.objects.create(code='QA', name='품질')
        self.c1 = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        Item.objects.create(code='C9', name='모듈', item_type=Item.FINISHED)  # 4M 변경은 C9에만: C1 출하를 막지 않게
        RoutingStep.objects.create(item=self.c1, seq=10, process=Process.objects.create(code='P10', name='조립'))
        self.wo = WorkOrder.objects.create(number='WO-1', item=self.c1, planned_qty=100)
        self.lot = Lot.objects.create(number='L-1', item=self.c1, work_order=self.wo)
        Partner.objects.create(name='H사', is_customer=True, is_supplier=True)
        Gauge.objects.create(number='G-1', name='마이크로미터', last_calibrated=timezone.localdate())
        self.cl = AuditChecklist.objects.create(name='CL-A')
        InternalAudit.objects.create(name='IA-1', planned_date=timezone.localdate(), auditor='홍길동')

    def profile(self, key, fields):
        cols = headers(targets()[key])
        return ImportProfile.objects.create(name=f'{key} 양식', target=key, mapping={f: cols[f] for f in fields})

    def file(self, profile, *rows):
        cols = list(profile.mapping)
        return csv_file([[profile.mapping[f] for f in cols]] + [[r.get(f, '') for f in cols] for r in rows])

    def test_every_target_has_sample(self):
        self.assertEqual(set(SAMPLES), set(targets()))
        self.assertEqual(problems(), [])

    def test_preview_and_commit_every_target(self):
        for key, row in SAMPLES.items():
            with self.subTest(key), transaction.atomic():
                model = targets()[key].model
                profile = self.profile(key, row)
                before = model.objects.count()
                r = preview_import(profile, self.file(profile, row), self.root)
                self.assertEqual((r['count'], r['errors']), (1, []))
                self.assertEqual(r['rows'][0]['values'], row)
                self.assertEqual(model.objects.count(), before)  # 미리보기는 저장하지 않는다
                self.assertEqual(run_import(profile, self.file(profile, row), self.root), (1, []))
                self.assertEqual(model.objects.count(), before + 1)
                transaction.set_rollback(True)  # 대상끼리 섞이지 않게(클레임이 LOT을 보류하는 등)

    def test_converts_bool_choice_and_owner(self):
        p = self.profile('core.lot', SAMPLES['core.lot'])
        run_import(p, self.file(p, SAMPLES['core.lot']), self.root)
        lot = Lot.objects.get(number='L-9')
        self.assertEqual((lot.is_serial, lot.item, lot.qty), (False, self.c1, 5))
        p = self.profile('qms.changerequest', SAMPLES['qms.changerequest'])
        self.assertEqual(run_import(p, self.file(p, SAMPLES['qms.changerequest']), self.root), (1, []))
        self.assertEqual(ChangeRequest.objects.get(number='CR-9').category, 'MACHINE')  # 선택지 이름 → 코드

    def test_key_match_updates_edit_fields_only(self):
        p = self.profile('work_order', ('number', 'item', 'planned_qty'))
        self.assertEqual(run_import(p, self.file(p, {'number': 'WO-1', 'item': 'C1', 'planned_qty': '200'}), self.root),
                         (1, []))
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.planned_qty, 200)
        self.assertEqual(WorkOrder.objects.count(), 1)
        count, errors = run_import(p, self.file(p, {'number': 'WO-1', 'item': 'C9', 'planned_qty': '300'}), self.root)
        self.assertEqual(count, 0)
        self.assertIn('바꿀 수 없습니다', errors[0])
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.planned_qty, 200)

    def test_locked_record_is_refused(self):
        cr = ChangeRequest.objects.create(number='CR-1', item=Item.objects.get(code='C9'), category='MACHINE',
                                          description='처음', effective_at=timezone.now())
        ChangeRequest.objects.filter(pk=cr.pk).update(approved_at=timezone.now(), approved_by=self.root)
        p = self.profile('qms.changerequest', ('number', 'description'))
        count, errors = run_import(p, self.file(p, {'number': 'CR-1', 'description': '바꿈'}), self.kim)
        self.assertEqual(count, 0)
        self.assertIn(LOCKED_MSG, errors[0])
        cr.refresh_from_db()
        self.assertEqual(cr.description, '처음')

    def test_held_lot_shipment_is_refused(self):
        Nonconformance.objects.create(lot=self.lot, description='이물')
        row = SAMPLES['core.shipment']
        p = self.profile('core.shipment', row)
        count, errors = run_import(p, self.file(p, {**row, 'qty': '1'}, row), self.root)
        self.assertEqual(count, 0)
        self.assertIn('보류', errors[0])
        self.assertFalse(Shipment.objects.exists())

    def test_module_off_is_refused(self):
        force_off('mes')
        p = self.profile('work_order', SAMPLES['work_order'])
        r = preview_import(p, self.file(p, SAMPLES['work_order']), self.root)
        self.assertIn('꺼져', r['errors'][0])

    def test_lookup_errors(self):
        p = self.profile('work_order', ('number', 'item', 'planned_qty'))
        count, errors = run_import(p, self.file(p, {'number': 'WO-9', 'item': '없는품번', 'planned_qty': '1'}), self.root)
        self.assertIn("품목: '없는품번'이(가) 없습니다.", errors[0])
        AuditChecklist.objects.create(name='CL-A')
        p = self.profile('qms.audititem', SAMPLES['qms.audititem'])
        count, errors = run_import(p, self.file(p, SAMPLES['qms.audititem']), self.root)
        self.assertIn('두 건', errors[0])
        p = self.profile('core.workresult', SAMPLES['core.workresult'])
        count, errors = run_import(p, self.file(p, {**SAMPLES['core.workresult'], 'step': 'P99'}), self.root)
        self.assertIn("공정 코드 'P99'", errors[0])

    def test_code_parent_path(self):
        for top in ('8', '9'):  # 0~6은 기본 자료(0011)
            m = CodeValue.objects.create(group=CodeValue.MATERIAL, code=top, name=f'자재{top}')
            CodeValue.objects.create(group=CodeValue.MAT_L, code='5', name='대', parent=m)
        p = self.profile('core.codevalue', ('group', 'parent', 'code', 'name'))
        row = {'group': '자재 중분류', 'parent': '5', 'code': '7', 'name': '중'}
        self.assertIn("'1/5'", run_import(p, self.file(p, row), self.root)[1][0])  # 대분류 5가 두 곳이라 위까지 적게 한다
        self.assertEqual(run_import(p, self.file(p, {**row, 'parent': '9/5'}), self.root), (1, []))
        got = CodeValue.objects.get(group=CodeValue.MAT_M, code='7')
        self.assertEqual(got.parent.parent.code, '9')
        self.assertEqual(run_import(p, self.file(p, {**row, 'parent': '9/5', 'name': '중2'}), self.root), (1, []))
        got.refresh_from_db()
        self.assertEqual(got.name, '중2')  # 묶음+상위+코드가 같으면 고친다

    def test_profile_rejects_unknown_column(self):
        p = ImportProfile(name='x', target='work_order', mapping={'bogus': 'A'})
        with self.assertRaisesMessage(ValidationError, 'bogus'):
            p.full_clean()
        self.assertIn(('qms.gauge', '계측기'), ImportProfile._meta.get_field('target').choices)

    def test_api_needs_add_and_change(self):
        client = APIClient()
        u = User.objects.create_user('u', password='pw', is_staff=True)
        grant(u, 'add_workorder')
        client.force_login(u)
        p = self.profile('work_order', SAMPLES['work_order'])
        post = lambda: client.post('/api/core/import/', {'profile': p.pk, 'file': self.file(p, SAMPLES['work_order']),
                                                         'commit': '1'}, format='multipart')
        self.assertEqual(post().status_code, 403)
        grant(u, 'change_workorder')
        u = User.objects.get(pk=u.pk)  # 권한 캐시 비우기
        client.force_login(u)
        self.assertEqual(post().json(), {'count': 1, 'errors': []})

    def test_template_round_trip_every_target(self):
        """3단계 ②: 빈 양식을 받아 채워 올리면 설정 없이 그대로 들어간다."""
        client = APIClient()
        client.force_login(self.root)
        listed = {t['key']: t for t in client.get('/api/core/import/targets/').json()}
        self.assertEqual(set(listed), set(targets()))
        for key, row in SAMPLES.items():
            with self.subTest(key), transaction.atomic():
                r = client.get('/api/core/import/template/', {'target': key})
                self.assertEqual(r.status_code, 200)
                self.assertIn('text/csv', r['Content-Type'])
                self.assertTrue(r.content.startswith(codecs.BOM_UTF8))  # 한국어 엑셀이 글자를 깨지 않게
                header = next(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))))
                titles = listed[key]['headers']
                self.assertEqual(header, list(titles.values()))
                self.assertEqual(len(set(header)), len(header))  # 같은 제목이 둘이면 칸을 구분하지 못한다
                model = targets()[key].model
                before = model.objects.count()
                r = client.post('/api/core/import/', {'target': key, 'file': csv_file([header, [row.get(f, '') for f in titles]]),
                                                      'commit': '1'}, format='multipart')
                self.assertEqual(r.json(), {'count': 1, 'errors': []})
                self.assertEqual(model.objects.count(), before + 1)
                transaction.set_rollback(True)

    def test_template_needs_add_and_change(self):
        client = APIClient()
        client.force_login(self.kim)
        self.assertEqual(client.get('/api/core/import/targets/').json(), [])
        self.assertEqual(client.get('/api/core/import/template/', {'target': 'work_order'}).status_code, 403)
        grant(self.kim, 'add_workorder', 'change_workorder')
        client.force_login(User.objects.get(pk=self.kim.pk))
        self.assertEqual([t['key'] for t in client.get('/api/core/import/targets/').json()], ['work_order'])
        self.assertEqual(client.get('/api/core/import/template/', {'target': 'work_order'}).status_code, 200)
        self.assertEqual(client.get('/api/core/import/template/', {'target': 'nope'}).status_code, 400)
        r = client.post('/api/core/import/', {'target': 'nope', 'file': csv_file([['a']]), 'commit': '0'}, format='multipart')
        self.assertEqual(r.status_code, 400)
        force_off('mes')
        self.assertEqual(client.get('/api/core/import/targets/').json(), [])  # 꺼진 모듈 대상은 목록에서 뺀다

    def test_guide_says_what_to_write(self):
        """신입이 칸마다 무엇을 적을지: 필수 여부·적는 값·예를 대상 목록에 싣는다."""
        client = APIClient()
        client.force_login(self.root)
        listed = {t['key']: t for t in client.get('/api/core/import/targets/').json()}
        for key, t in listed.items():
            with self.subTest(key):
                self.assertEqual([g['key'] for g in t['guide']], list(t['headers']))
                self.assertTrue(all(g['hint'] for g in t['guide']))
        lot = {g['key']: g for g in listed['core.lot']['guide']}
        self.assertTrue(lot['number']['required'])
        self.assertIn('품목의 품번', lot['item']['hint'])
        self.assertIn('같은 값', lot['number']['hint'])  # 키 열: 있으면 고친다
        self.assertEqual((lot['is_serial']['required'], lot['is_serial']['example']), (False, '아니오'))
        item = {g['key']: g for g in listed['item']['guide']}
        self.assertIn('원자재', item['item_type']['hint'])
        self.assertIn('2026-', {g['key']: g for g in listed['qms.gauge']['guide']}['last_calibrated']['example'])

    def test_xlsx_template_round_trip_every_target(self):
        """엑셀 빈 양식: 입력 시트(1행 표준 열 제목·드롭다운) + 작성 안내 시트. 채워 올리면 그대로 들어간다."""
        client = APIClient()
        client.force_login(self.root)
        listed = {t['key']: t for t in client.get('/api/core/import/targets/').json()}
        for key, row in SAMPLES.items():
            with self.subTest(key), transaction.atomic():
                r = client.get('/api/core/import/template/', {'target': key, 'kind': 'xlsx'})
                self.assertEqual(r.status_code, 200)
                self.assertIn('spreadsheetml', r['Content-Type'])
                wb = load_workbook(io.BytesIO(r.content))
                ws = wb.active
                self.assertEqual(ws.title, '입력')
                titles = listed[key]['headers']
                self.assertEqual([c.value for c in ws[1]], list(titles.values()))
                self.assertIn('작성 안내', wb.sheetnames)
                for col, f in enumerate(titles, start=1):
                    ws.cell(2, col, row.get(f) or None)
                model = targets()[key].model
                before = model.objects.count()
                r = client.post('/api/core/import/', {'target': key, 'file': xlsx_file(wb), 'commit': '1'}, format='multipart')
                self.assertEqual(r.json(), {'count': 1, 'errors': []})
                self.assertEqual(model.objects.count(), before + 1)
                transaction.set_rollback(True)

    def test_xlsx_template_dropdowns(self):
        client = APIClient()
        client.force_login(self.root)
        wb = load_workbook(io.BytesIO(client.get('/api/core/import/template/', {'target': 'core.lot', 'kind': 'xlsx'}).content))
        ws, lists = wb['입력'], wb['목록']
        self.assertEqual(lists.sheet_state, 'hidden')
        listed = {str(c.value) for col in lists.iter_cols() for c in col}
        self.assertTrue({'C1', 'C9', '예', '아니오'} <= listed)  # 품목 품번·예/아니오를 골라 넣는다
        styles = sorted(dv.errorStyle for dv in ws.data_validations.dataValidation)
        self.assertEqual(styles, ['stop', 'warning', 'warning', 'warning'])  # 예/아니오는 목록만, 품목·거래처·작업지시는 경고만
        self.assertTrue(ws['A1'].comment)  # 열 제목에 마우스를 올리면 적을 값이 보인다
        self.assertEqual(client.get('/api/core/import/template/', {'target': 'core.lot', 'kind': 'pdf'}).status_code, 400)
