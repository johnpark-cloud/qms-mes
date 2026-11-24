"""측정시스템 분석(MSA): GR&R 원자료(평균·범위법)로 %GRR·ndc·판정을 계산하고, 부적합이면 계측기에 안내를 띄운다."""
import datetime
import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from qms import msa
from qms.models import Characteristic, Gauge, InspectionSpec, MsaStudy
from core.models import Item

# 부품 2 × 측정자 2 × 반복 2. 범위 모두 0.2 → EV = 0.2 × 0.8862, AV는 음수라 0, PV = 1.0 × 0.7071
ROWS = [('P1', 'A', 1, 1.0), ('P1', 'A', 2, 1.2), ('P1', 'B', 1, 1.1), ('P1', 'B', 2, 1.3),
        ('P2', 'A', 1, 2.0), ('P2', 'A', 2, 2.2), ('P2', 'B', 1, 2.1), ('P2', 'B', 2, 2.3)]


def csv_bytes(rows=ROWS, header='부품,측정자,반복,측정값'):
    return ('\n'.join([header] + [','.join(str(v) for v in r) for r in rows]) + '\n').encode()


class GrrCalcTest(TestCase):
    def test_average_range_method(self):
        r = msa.grr([{'부품': p, '측정자': o, '반복': t, '측정값': v} for p, o, t, v in ROWS])
        self.assertAlmostEqual(r['ev'], 0.17724, places=5)
        self.assertEqual(r['av'], 0)
        self.assertAlmostEqual(r['pv'], 0.7071, places=4)
        self.assertAlmostEqual(r['grr_percent'], 24.31, places=2)
        self.assertEqual(r['ndc'], 5)
        self.assertEqual((r['parts'], r['operators'], r['trials']), (2, 2, 2))

    def test_judge(self):
        self.assertEqual(msa.judge(Decimal('9.9'), 6), MsaStudy.ACCEPT)
        self.assertEqual(msa.judge(Decimal('24'), 5), MsaStudy.CONDITIONAL)
        self.assertEqual(msa.judge(Decimal('31'), 5), MsaStudy.REJECT)
        self.assertEqual(msa.judge(Decimal('8'), 4), MsaStudy.REJECT)  # 구별 범주 5 미만

    def test_bad_layout(self):
        rows = [{'부품': p, '측정자': o, '반복': t, '측정값': v} for p, o, t, v in ROWS]
        for bad, word in ((rows[:-1], '반복'), ([r for r in rows if r['측정자'] == 'A'], '측정자'),
                          ([{**rows[0], '측정값': '가'}] + rows[1:], '숫자'), ([{'부품': 'P1'}], '열')):
            with self.assertRaises(ValidationError) as e:
                msa.grr(bad)
            self.assertIn(word, str(e.exception))


class MsaStudyTest(TestCase):  # 파일은 QMS_DATA_DIR(테스트는 임시 폴더) 아래 media에 저장된다
    def setUp(self):
        self.gauge = Gauge.objects.create(number='G-1', name='마이크로미터', last_calibrated=timezone.localdate())
        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        spec = InspectionSpec.objects.create(item=item, inspection_type=InspectionSpec.INCOMING)
        self.char = Characteristic.objects.create(spec=spec, name='두께', lsl=Decimal('0'), usl=Decimal('5'))
        self.lead = User.objects.create_user('lead', is_staff=True)
        self.lead.groups.add(Group.objects.get(name='품질팀장'))
        self.client.force_login(self.lead)
        self.today = timezone.localdate().isoformat()

    def post(self, values, data=None):
        body = {'values': json.dumps({'gauge': self.gauge.pk, 'performed_on': self.today, **values})}
        if data is not None:
            body['data'] = SimpleUploadedFile('grr.csv', data, content_type='text/csv')
        return self.client.post('/api/records/qms.msastudy/', body)

    def test_grr_from_uploaded_data(self):
        r = self.post({'kind': 'GRR', 'characteristic': self.char.pk}, csv_bytes())
        self.assertEqual(r.status_code, 201, r.content)
        s = MsaStudy.objects.get()
        self.assertEqual((s.grr_percent, s.ndc, s.result), (Decimal('24.31'), 5, MsaStudy.CONDITIONAL))
        self.assertIn('EV', s.summary)
        self.assertIn('공차 대비', s.summary)  # 특성에 공차가 있으면 %공차도
        self.assertTrue(s.data.read().startswith('부품'.encode()))  # 원자료 파일 전체가 남는다

    def test_bad_data_file_is_field_error(self):
        r = self.post({'kind': 'GRR'}, csv_bytes(ROWS[:-1]))
        self.assertEqual(r.status_code, 400)
        self.assertIn('data', r.json()['fields'])
        self.assertFalse(MsaStudy.objects.exists())

    def test_grr_needs_data_or_numbers(self):
        r = self.post({'kind': 'GRR'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('grr_percent', r.json()['fields'])
        r = self.post({'kind': 'GRR', 'grr_percent': '8.5', 'ndc': 7, 'result': 'REJECT'})  # 판정은 숫자로 정한다
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(MsaStudy.objects.get().result, MsaStudy.ACCEPT)

    def test_other_kinds_need_result(self):
        self.assertIn('result', self.post({'kind': 'BIAS'}).json()['fields'])
        self.assertEqual(self.post({'kind': 'BIAS', 'result': 'ACCEPT'}).status_code, 201)

    def test_future_date_rejected(self):
        with self.assertRaises(ValidationError):
            MsaStudy(gauge=self.gauge, kind='BIAS', result='ACCEPT',
                     performed_on=timezone.localdate() + datetime.timedelta(days=1)).full_clean()

    def test_gauge_notice_when_latest_study_rejected(self):
        url = f'/api/records/qms.gauge/{self.gauge.pk}/'
        self.assertEqual(self.client.get(url).json()['notices'], [])
        day = timezone.localdate()
        MsaStudy.objects.create(gauge=self.gauge, kind='BIAS', result=MsaStudy.REJECT, performed_on=day - datetime.timedelta(days=5))
        self.assertIn('측정시스템 분석', self.client.get(url).json()['notices'][0]['message'])
        MsaStudy.objects.create(gauge=self.gauge, kind='BIAS', result=MsaStudy.ACCEPT, performed_on=day)
        self.assertEqual(self.client.get(url).json()['notices'], [])
