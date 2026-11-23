"""3단계 ③ 측정 원자료 화면 업로드(docs/data-flow.md 5·7절): 검사 입력 화면과 같은 submit_inspection 경로로 판정한다."""
import codecs
import io
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from core.models import Item, Lot
from core.tests_modules import force_off
from qms.models import Characteristic, Gauge, Inspection, InspectionSpec, Qualification

URL = '/api/qms/inspect/upload/'
HEAD = 'lot,type,characteristic,value,gauge\n'


def csv_file(body, head=HEAD):
    return SimpleUploadedFile('측정.csv', (head + body).encode('utf-8-sig'), content_type='text/csv')


class MeasurementUploadTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('lead', password='pw', is_staff=True)
        self.user.groups.add(Group.objects.get(name='품질팀장'))
        self.client = APIClient()
        self.client.force_login(self.user)
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='RAW-1', item=self.item, qty=10)
        self.spec = InspectionSpec.objects.create(item=self.item, inspection_type=InspectionSpec.INCOMING)
        self.thk = Characteristic.objects.create(spec=self.spec, name='두께', lsl=Decimal('9'), usl=Decimal('11'),
                                                 gauge_kind='마이크로미터')
        self.look = Characteristic.objects.create(spec=self.spec, name='외관')
        self.spec.approved_by, self.spec.approved_at = self.user, timezone.now()
        self.spec.save()

    def post(self, body, commit='1', head=HEAD):
        return self.client.post(URL, {'file': csv_file(body, head), 'commit': commit}, format='multipart')

    def test_pass_preview_then_commit(self):
        body = 'RAW-1,수입검사,두께,10.0,\nRAW-1,INCOMING,외관,OK,\n'
        r = self.post(body, '0')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.data['count'], r.data['errors']), (1, []))
        self.assertEqual(r.data['rows'][0]['values']['result'], '합격')
        self.assertFalse(Inspection.objects.exists())  # 미리보기는 저장하지 않는다
        r = self.post(body)
        self.assertEqual((r.data['count'], r.data['errors']), (1, []))
        insp = Inspection.objects.get()
        self.assertEqual((insp.result, insp.inspector), (Inspection.PASS, self.user))  # 올린 사람이 검사원

    def test_fail_registers_nc_and_holds(self):
        r = self.post('RAW-1,수입검사,두께,12,\nRAW-1,수입검사,외관,NG,\n')
        self.assertEqual(r.data['errors'], [])
        insp = Inspection.objects.get()
        self.assertEqual(insp.result, Inspection.FAIL)
        self.assertEqual(insp.nonconformance.detected_by, self.user)
        self.assertTrue(self.lot.on_hold)

    def test_no_qualification_rejected(self):
        other = User.objects.create_user('kim')
        Qualification.objects.create(user=other, inspection_type=InspectionSpec.INCOMING, valid_until=date(2999, 1, 1), basis='교육')
        r = self.post('RAW-1,수입검사,두께,10,\nRAW-1,수입검사,외관,OK,\n')
        self.assertEqual(r.data['count'], 0)
        self.assertIn('판정 자격이 없습니다', r.data['errors'][0])
        self.assertFalse(Inspection.objects.exists())

    def test_expired_gauge_rejected(self):
        Gauge.objects.create(number='MC-01', name='마이크로미터', last_calibrated=timezone.localdate() - timedelta(days=400))
        r = self.post('RAW-1,수입검사,두께,10,MC-01\nRAW-1,수입검사,외관,OK,\n')
        self.assertIn('교정 기한', r.data['errors'][0])
        self.assertFalse(Inspection.objects.exists())

    def test_gauge_auto_pick_or_required(self):
        Gauge.objects.create(number='VC-01', name='버니어', kind='캘리퍼스', last_calibrated=timezone.localdate())
        r = self.post('RAW-1,수입검사,두께,10,\nRAW-1,수입검사,외관,OK,\n')
        self.assertIn('계측기를 골라야 합니다', r.data['errors'][0])  # 맞는 종류가 없으면 화면과 같이 거부
        g = Gauge.objects.create(number='MC-02', name='외측', kind='마이크로미터', last_calibrated=timezone.localdate())
        r = self.post('RAW-1,수입검사,두께,10,\nRAW-1,수입검사,외관,OK,\n')
        self.assertEqual(r.data['errors'], [])
        self.assertEqual(Inspection.objects.get().measurements.get(characteristic=self.thk).gauge, g)

    def test_unknown_characteristic_and_missing_value(self):
        r = self.post('RAW-1,수입검사,두께,10,\nRAW-1,수입검사,외관,OK,\nRAW-1,수입검사,폭,3,\n')
        self.assertIn('4행: 검사항목 "폭"', r.data['errors'][0])
        r = self.post('RAW-1,수입검사,두께,10,\n')
        self.assertIn('외관: 값을 입력하세요', r.data['errors'][0])
        r = self.post('RAW-1,수입검사,두께,10,\nRAW-1,수입검사,외관,애매,\n')
        self.assertIn('3행: 외관', r.data['errors'][0])
        self.assertFalse(Inspection.objects.exists())

    def test_bad_lot_type_gauge_and_columns(self):
        r = self.post('NONE,수입검사,두께,10,\nRAW-1,최종검사,두께,10,\nRAW-1,출하검사,두께,10,\nRAW-1,수입검사,두께,10,ZZ\n')
        e = ' '.join(r.data['errors'])
        for msg in ('LOT "NONE"', '검사 구분 "최종검사"', '승인된 검사기준', '계측기 "ZZ"'):
            self.assertIn(msg, e)
        r = self.post('RAW-1,10\n', head='lot,value\n')
        self.assertIn("열 'type' 없음", r.data['errors'][0])

    def test_one_bad_group_saves_nothing(self):
        Lot.objects.create(number='RAW-2', item=self.item)
        r = self.post('RAW-1,수입검사,두께,10,\nRAW-1,수입검사,외관,OK,\nRAW-2,수입검사,두께,10,\n')
        self.assertEqual(len(r.data['errors']), 1)
        self.assertFalse(Inspection.objects.exists())

    def test_permission_module_and_template(self):
        r = self.client.get(URL)
        self.assertEqual(list(r.data['columns']), ['lot', 'type', 'count', 'result', 'nonconformance'])
        r = self.client.get(URL + 'template/')
        self.assertEqual(codecs.decode(r.content, 'utf-8-sig').strip(), HEAD.strip())
        self.client.force_login(User.objects.create_user('kim2'))
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.post('RAW-1,수입검사,두께,10,\n').status_code, 403)
        self.client.force_login(self.user)
        force_off('qms_inspection')
        self.assertIn(self.post('RAW-1,수입검사,두께,10,\n').status_code, (403, 404))
        self.assertFalse(Inspection.objects.exists())

    def test_guide_and_xlsx_template(self):
        g = {c['key']: c for c in self.client.get(URL).data['guide']}
        self.assertEqual(list(g), ['lot', 'type', 'characteristic', 'value', 'gauge'])
        self.assertEqual((g['lot']['required'], g['gauge']['required']), (True, False))
        self.assertIn('OK', g['value']['hint'])
        Gauge.objects.create(number='MC-03', name='외측', kind='마이크로미터', last_calibrated=timezone.localdate())
        r = self.client.get(URL + 'template/', {'kind': 'xlsx'})
        wb = load_workbook(io.BytesIO(r.content))
        ws = wb.active
        self.assertEqual([c.value for c in ws[1]], ['lot', 'type', 'characteristic', 'value', 'gauge'])
        listed = {str(c.value) for col in wb['목록'].iter_cols() for c in col}
        self.assertTrue({'수입검사', 'MC-03'} <= listed)
        for i, row in enumerate((('RAW-1', '수입검사', '두께', 10, 'MC-03'), ('RAW-1', '수입검사', '외관', 'OK', None)), start=2):
            for col, v in enumerate(row, start=1):
                ws.cell(i, col, v)
        buf = io.BytesIO()
        wb.save(buf)
        r = self.client.post(URL, {'file': SimpleUploadedFile('m.xlsx', buf.getvalue()), 'commit': '1'}, format='multipart')
        self.assertEqual(r.data['errors'], [])
        self.assertEqual(Inspection.objects.get().result, Inspection.PASS)
