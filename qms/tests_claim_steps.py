"""8D 단계별 기한과 지연 표시(4단계 개선 2): D1~D3은 봉쇄(D3), D4는 원인(D4), D5는 대책(D5), D6~D8은 종결(D8) 기한을 따른다."""
import datetime

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import Item, Lot

from .due import due_items
from .models import CustomerClaim, CustomerRule

H, D = datetime.timedelta(hours=1), datetime.timedelta(days=1)


class ClaimStepTest(TestCase):
    def setUp(self):
        self.lot = Lot.objects.create(number='L1', item=Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED))
        CustomerRule.objects.create(customer='A사', containment_hours=24, root_cause_days=5, corrective_days=10, closure_days=30)

    def claim(self, ago, **steps):
        return CustomerClaim.objects.create(number=f'CL-{CustomerClaim.objects.count()}', customer='A사', lot=self.lot,
                                            description='x', received_at=timezone.now() - ago, **steps)

    def test_each_step_follows_its_milestone(self):
        c = self.claim(datetime.timedelta(0))
        got = [c.step_due(f) - c.received_at for f, _ in CustomerClaim.STEPS]
        self.assertEqual(got, [24 * H, 24 * H, 24 * H, 5 * D, 10 * D, 30 * D, 30 * D, 30 * D])
        self.assertEqual(c.current_due, ('봉쇄', c.received_at + 24 * H))
        for f, label, after in (('d1_team', '봉쇄', 24 * H), ('d2_problem', '봉쇄', 24 * H), ('d3_containment', '원인', 5 * D),
                                ('d4_root_cause', '대책', 10 * D), ('d5_corrective', '종결', 30 * D)):
            setattr(c, f, '완료')
            self.assertEqual(c.current_due, (label, c.received_at + after), f)
        for f in ('d6_verification', 'd7_prevention', 'd8_closure'):
            setattr(c, f, '완료')
        self.assertIsNone(c.current_due)
        self.assertEqual(c.delay, '')

    def test_default_rule_for_unknown_customer(self):
        c = CustomerClaim.objects.create(number='CL-X', customer='없는 고객', lot=self.lot, description='x')
        self.assertEqual([c.step_due(f) - c.received_at for f in ('d3_containment', 'd4_root_cause', 'd5_corrective', 'd8_closure')],
                         [24 * H, 5 * D, 10 * D, 60 * D])

    def test_rule_order_is_checked(self):
        for bad in ({'root_cause_days': 11}, {'closure_days': 9}, {'containment_hours': 5 * 24 + 1}):
            rule = CustomerRule(customer='B사', **{'containment_hours': 24, 'root_cause_days': 5, 'corrective_days': 10,
                                                   'closure_days': 30, **bad})
            with self.assertRaises(ValidationError, msg=bad):
                rule.full_clean()

    def test_delay_and_step_status(self):
        c = self.claim(8 * D, d1_team='팀', d2_problem='문제', d3_containment='봉쇄')  # 접수 8일 뒤에 D1~D3 기록 → 7일 늦음
        self.assertEqual(c.delay, 'D4 근본 원인 3일 지연')  # D4 기한 5일 → 3일 지남
        lines = c.step_status.splitlines()
        self.assertEqual(len(lines), 8)
        self.assertIn('D3 봉쇄 조치', lines[2])
        self.assertIn('완료(7일 늦음)', lines[2])
        self.assertIn('3일 지연 중', lines[3])
        self.assertNotIn('지연', lines[4])  # D5 기한은 아직 남음
        fresh = self.claim(2 * H)
        self.assertEqual(fresh.delay, '')
        self.assertIn('D1 팀 구성', fresh.step_status.splitlines()[0])
        self.assertNotIn('지연', fresh.step_status)
        late = self.claim(30 * H)
        self.assertEqual(late.delay, 'D1 팀 구성 6시간 지연')

    def test_todo_uses_current_step_due(self):
        c = self.claim(4 * D + 12 * H, d1_team='팀', d2_problem='문제', d3_containment='봉쇄')  # D4 기한까지 12시간
        claims = due_items()['claims']
        self.assertEqual([(x.pk, x.due_label, x.overdue) for x in claims], [(c.pk, '원인', False)])
        self.assertEqual(claims[0].due, c.received_at + 5 * D)
        self.claim(datetime.timedelta(0), d1_team='팀', d2_problem='문제', d3_containment='봉쇄')  # D4 기한 5일 → 목록 밖
        self.assertEqual(len(due_items()['claims']), 1)

    def test_record_screen_shows_steps_and_list_delay(self):
        c = self.claim(8 * D, d1_team='팀', d2_problem='문제', d3_containment='봉쇄')
        self.client.force_login(User.objects.create_superuser('su', password='pw'))
        d = self.client.get(f'/api/records/qms.customerclaim/{c.pk}/').json()
        props = {p['label']: p['value'] for p in d['fields']}
        self.assertIn('3일 지연 중', props['단계별 기한'])
        self.assertIn('원인(D4) 기한', props)
        rows = self.client.get('/api/records/qms.customerclaim/').json()
        self.assertIn('지연', [col['label'] for col in rows['columns']])
        self.assertIn('D4 근본 원인 3일 지연', str(rows['results'][0]))
