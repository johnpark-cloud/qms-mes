"""경영검토(ISO 9001 9.3): 등록하면 검토 기간의 품질 성과·이전 조치 상태를 자동으로 채우고, 검토 결과가 있어야 승인된다."""
import datetime

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from core.rules import approve
from qms import tests as base  # 모듈로 가져와 QmsTest가 여기서 다시 돌지 않게
from qms.models import ManagementReview, ManagementReviewAction


class ManagementReviewTest(TestCase):
    setUp_base = base.QmsTest.setUp
    inspect = base.QmsTest.inspect
    new_lot = base.QmsTest.new_lot

    def setUp(self):
        self.setUp_base()
        self.today = timezone.localdate()
        self.start = self.today - datetime.timedelta(days=30)

    def review(self, **kw):
        return ManagementReview.objects.create(**{'period_start': self.start, 'period_end': self.today,
                                                  'chair': self.lead, 'attendees': '대표, 품질팀장'} | kw)

    def test_performance_filled_from_period(self):
        self.inspect('10.0')
        self.inspect('11.0', lot=self.new_lot())  # 불합격 → 부적합 자동 등록
        self.inspect('10.0', lot=self.new_lot(), at=timezone.now() - datetime.timedelta(days=60))  # 기간 밖
        text = self.review().performance
        self.assertIn('검사: 판정 2건, 합격 1건(50.0%)', text)
        self.assertIn('부적합: 발생 1건', text)
        self.assertIn('계측기', text)

    def test_written_performance_kept(self):
        self.assertEqual(self.review(performance='직접 작성').performance, '직접 작성')

    def test_previous_open_actions_listed(self):
        old = self.review(period_start=self.start - datetime.timedelta(days=200), period_end=self.start,
                          held_on=self.start, outputs='설비 투자')
        ManagementReviewAction.objects.create(review=old, task='검사 장비 증설', owner=self.lead, due_date=self.start)
        ManagementReviewAction.objects.create(review=old, task='교육 실시', owner=self.lead, due_date=self.start,
                                              done_on=self.start)
        text = self.review().prev_actions
        self.assertIn('조치 2건 중 완료 1건', text)
        self.assertIn('검사 장비 증설', text)
        self.assertNotIn('교육 실시', text)

    def test_period_order(self):
        with self.assertRaisesMessage(ValidationError, '검토 기간'):
            self.review(period_start=self.today, period_end=self.start).full_clean()

    def test_approve_needs_outputs_then_locks(self):
        r = self.review()
        with self.assertRaisesMessage(ValidationError, '검토 결과'):
            approve(r, self.lead, 'pw-lead-123')
        r.refresh_from_db()
        self.assertIsNone(r.approved_at)
        r.outputs = '검사 인원 1명 충원'
        r.save()
        approve(r, self.lead, 'pw-lead-123')
        r.outputs = '바꿈'
        with self.assertRaises(ValidationError):
            r.save()
        # 승인 뒤에도 조치 완료일은 기록한다
        a = ManagementReviewAction.objects.create(review=r, task='충원', owner=self.lead, due_date=self.today)
        a.done_on = self.today
        a.save()

    def test_create_through_record_api(self):
        self.client.force_login(self.lead)
        r = self.client.post('/api/records/qms.managementreview/', {'values': {
            'held_on': self.today.isoformat(), 'period_start': self.start.isoformat(), 'period_end': self.today.isoformat(),
            'chair': self.lead.pk, 'attendees': '대표'}}, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIn('검사: 판정 0건', ManagementReview.objects.get().performance)

    def test_engineer_cannot_approve(self):
        eng = User.objects.create_user('eng', password='pw-eng-123', is_staff=True)
        with self.assertRaises(PermissionDenied):
            approve(self.review(outputs='x'), eng, 'pw-eng-123')
