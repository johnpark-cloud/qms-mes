"""샘플링 수준 조정 제안(ISO 2859-1 전환 규칙 참고)과 MSA 부적합 계측기 알림 — 막지 않고 할 일·알림 메일에만 띄운다 (사용자 결정 2026-11-27)."""
import datetime

from django.test import TestCase
from django.utils import timezone

from qms.due import digest, due_items, sampling_suggestions
from qms.models import Gauge, InspectionSpec, MsaStudy
from qms import tests as base  # 모듈로 가져와 QmsTest가 여기서 다시 돌지 않게



class SamplingSuggestionTest(TestCase):
    setUp_base = base.QmsTest.setUp
    inspect = base.QmsTest.inspect
    new_lot = base.QmsTest.new_lot

    def setUp(self):
        self.setUp_base()
        self.t0 = timezone.now() - datetime.timedelta(days=30)
        self.n = 0

    def lot_result(self, ok, supplier='B소재'):
        """새 LOT 한 건을 검사한다(합격 10.0 / 불합격 11.0)."""
        self.n += 1
        lot = self.new_lot()
        lot.supplier = supplier
        lot.save()
        return self.inspect('10.0' if ok else '11.0', lot=lot, at=self.t0 + datetime.timedelta(hours=self.n))

    def test_two_of_last_five_rejected_suggests_tighten(self):
        for ok in (True, True, False, True, False):
            self.lot_result(ok)
        rows = sampling_suggestions()
        self.assertEqual([(r['spec'], r['supplier'], r['action']) for r in rows], [(self.spec, 'B소재', 'tighten')])
        self.assertIn('5건 중 2건', rows[0]['reason'])

    def test_one_reject_no_suggestion_and_suppliers_separate(self):
        for ok in (True, False, True, True):
            self.lot_result(ok)
        self.lot_result(False, supplier='C상사')  # 다른 공급사 불합격은 따로 센다
        self.assertEqual(sampling_suggestions(), [])

    def test_ten_consecutive_passes_suggests_reduce(self):
        self.lot_result(False)
        for _ in range(9):
            self.lot_result(True)
        self.assertEqual(sampling_suggestions(), [])  # 연속 9건
        self.lot_result(True)
        self.assertEqual([r['action'] for r in sampling_suggestions()], ['reduce'])

    def test_reinspection_not_counted(self):
        for ok in (True, True, True, True):
            self.lot_result(ok)
        bad = self.lot_result(False)
        self.inspect('10.0', lot=bad.lot, at=self.t0 + datetime.timedelta(days=2))  # 재작업 후 재검사 합격은 첫 판정을 바꾸지 않는다
        self.lot_result(False)
        self.assertEqual([r['action'] for r in sampling_suggestions()], ['tighten'])

    def test_spec_revision_resets_stream(self):
        """기준서를 개정(샘플링 변경)하면 옛 개정으로 한 검사는 세지 않는다 → 제안이 사라진다."""
        for ok in (False, False):
            self.lot_result(ok)
        self.assertEqual(len(sampling_suggestions()), 1)
        rev2 = InspectionSpec.objects.create(item=self.raw_item, inspection_type=InspectionSpec.INCOMING, revision=2,
                                             sampling='까다로운 검사 n=13')
        base.approve(rev2, self.lead)
        self.assertEqual(sampling_suggestions(), [])

    def test_due_items_and_digest(self):
        for ok in (False, False):
            self.lot_result(ok)
        d = due_items()
        self.assertEqual(len(d['sampling']), 1)
        titles = [t for t, _ in digest(d)]
        self.assertIn('샘플링 수준 조정 제안', titles)


class MsaRejectDueTest(TestCase):
    def setUp(self):
        self.gauge = Gauge.objects.create(number='G-1', name='마이크로미터', last_calibrated=timezone.localdate())

    def test_latest_msa_rejected_gauge_listed(self):
        day = timezone.localdate()
        self.assertEqual(due_items()['msa_rejects'], [])
        MsaStudy.objects.create(gauge=self.gauge, kind='BIAS', result=MsaStudy.REJECT, performed_on=day - datetime.timedelta(days=5))
        rows = due_items()['msa_rejects']
        self.assertEqual([r.gauge for r in rows], [self.gauge])
        self.assertIn('MSA 부적합 계측기', [t for t, _ in digest(due_items())])
        MsaStudy.objects.create(gauge=self.gauge, kind='BIAS', result=MsaStudy.ACCEPT, performed_on=day)  # 다시 분석해 적합
        self.assertEqual(due_items()['msa_rejects'], [])

    def test_inactive_gauge_not_listed(self):
        MsaStudy.objects.create(gauge=self.gauge, kind='BIAS', result=MsaStudy.REJECT, performed_on=timezone.localdate())
        self.gauge.active = False
        self.gauge.save()
        self.assertEqual(due_items()['msa_rejects'], [])


class TodoWidgetTest(TestCase):
    setUp_base, inspect, new_lot = base.QmsTest.setUp, base.QmsTest.inspect, base.QmsTest.new_lot
    setUp, lot_result = SamplingSuggestionTest.setUp, SamplingSuggestionTest.lot_result

    def test_todo_widget_lists_sampling_and_msa(self):
        import json
        for ok in (False, False):
            self.lot_result(ok)
        gauge = Gauge.objects.create(number='G-9', name='캘리퍼스', last_calibrated=timezone.localdate())
        study = MsaStudy.objects.create(gauge=gauge, kind='BIAS', result=MsaStudy.REJECT, performed_on=timezone.localdate())
        self.lead.is_superuser = True
        self.lead.save()
        self.client.force_login(self.lead)
        self.client.post('/api/qms/dashboard/', json.dumps([{'key': 'todo_lists', 'size': 'wide'}]), content_type='application/json')
        data = {w['key']: w['data'] for w in self.client.get('/api/qms/todo/').json()['widgets']}['todo_lists']
        self.assertEqual([(r['href'], r['action']) for r in data['sampling']], [(f'/app/specs/{self.spec.pk}', 'tighten')])
        self.assertEqual([r['href'] for r in data['msa_rejects']], [f'/app/r/qms/msastudy/{study.pk}'])
