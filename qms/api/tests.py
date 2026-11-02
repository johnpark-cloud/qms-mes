import datetime
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import EditRequest, Hold, Item, Lot, Nonconformance, WorkOrder
from qms.models import AuditFinding, Capa, ChangeRequest, CustomerClaim, Gauge, InternalAudit, PpapSubmission, Scar
from qms.overview import sections
from qms.widgets import WIDGETS, layout_for


class OverviewApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.qe = User.objects.create_user('qe', password='x', is_staff=True)
        self.qe.groups.add(Group.objects.get(name='품질엔지니어'))
        self.insp = User.objects.create_user('insp', password='x', is_staff=True)
        self.insp.groups.add(Group.objects.get(name='검사원'))
        item = Item.objects.create(code='P1', name='부품', item_type=Item.RAW)
        lot = Lot.objects.create(number='L-1', item=item, supplier='가협력')
        WorkOrder.objects.create(number='WO-1', item=item, planned_qty=10, status=WorkOrder.RUNNING, due_date=timezone.localdate())
        Nonconformance.objects.create(lot=lot, description='찍힘')  # 보류도 함께 생긴다
        Capa.objects.create(title='재발 방지', source='OTHER', action='x', owner=self.qe, due_date=timezone.localdate())

    def test_same_numbers_as_page(self):
        self.client.force_login(self.qe)
        api = self.client.get('/api/qms/overview/').json()
        page = sections(self.qe)
        self.assertTrue(any(c['title'] == '진행 중 CAPA' for _, cards in page for c in cards))
        self.assertEqual([(s['name'], [(c['title'], c['value']) for c in s['cards']]) for s in api['sections']],
                         [(name, [(c['title'], c['value']) for c in cards]) for name, cards in page])

    def test_inspector_has_no_capa_card(self):
        self.client.force_login(self.insp)
        titles = [c['title'] for s in self.client.get('/api/qms/overview/').json()['sections'] for c in s['cards']]
        self.assertIn('열린 부적합', titles)
        self.assertNotIn('진행 중 CAPA', titles)

    def test_anonymous_forbidden(self):
        self.assertEqual(self.client.get('/api/qms/overview/').status_code, 403)


class TodoApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.qe = User.objects.create_user('qe', password='x', is_staff=True)
        self.qe.groups.add(Group.objects.get(name='품질엔지니어'))
        self.insp = User.objects.create_user('insp', password='x', is_staff=True)
        self.insp.groups.add(Group.objects.get(name='검사원'))
        self.boss = User.objects.create_superuser('boss', password='x')
        item = Item.objects.create(code='P1', name='부품', item_type=Item.RAW)
        lot = Lot.objects.create(number='L-1', item=item, supplier='가협력')
        Nonconformance.objects.create(lot=lot, description='찍힘')  # 보류도 함께 생긴다
        Capa.objects.create(title='재발 방지', source='OTHER', action='x', owner=self.qe, due_date=timezone.localdate())
        today = timezone.localdate()
        Scar.objects.create(number='S-1', supplier='가협력', lot=lot, request='x', response_due=today - datetime.timedelta(days=1))
        Gauge.objects.create(number='G-1', name='마이크로미터', last_calibrated=today - datetime.timedelta(days=400))
        audit = InternalAudit.objects.create(name='공정심사', planned_date=today, auditor='김')
        AuditFinding.objects.create(audit=audit, grade='MAJOR', description='x')

    def test_widgets_match_layout(self):
        self.client.force_login(self.qe)
        data = self.client.get('/api/qms/todo/').json()
        self.assertEqual([w['key'] for w in data['widgets']], [w['key'] for w in layout_for(self.qe)])
        held = next(w for w in data['widgets'] if w['key'] == 'held_lots')
        self.assertEqual(held['data']['value'], Hold.objects.filter(released_at__isnull=True).values('lot').distinct().count())

    def test_inspector_no_kpi_widgets(self):
        self.client.force_login(self.insp)
        keys = [w['key'] for w in self.client.get('/api/qms/todo/').json()['available']]
        self.assertNotIn('kpi_ppm', keys)

    def test_broken_widget_isolated(self):
        with (mock.patch.dict(WIDGETS, {'leave': replace(WIDGETS['leave'], context=lambda *a: 1 / 0)}),
              self.assertLogs('qms', 'ERROR') as logs):
            self.client.force_login(self.qe)
            r = self.client.get('/api/qms/todo/')
        self.assertIn('위젯 불러오기 실패: leave', logs.output[0])
        self.assertEqual(r.status_code, 200)
        leave = next(w for w in r.json()['widgets'] if w['key'] == 'leave')
        self.assertTrue(leave['error'])
        self.assertIsNone(leave['data'])

    def test_save_layout_rejects_forbidden_widget(self):
        self.client.force_login(self.insp)
        r = self.client.post('/api/qms/dashboard/', [{'key': 'kpi_ppm', 'size': 'normal'}], format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {'detail': '저장할 수 없는 위젯 배치입니다.'})

    def test_save_layout_roundtrip(self):
        self.client.force_login(self.qe)
        items = [{'key': 'gauges', 'size': 'wide', 'x': 0, 'y': 0}, {'key': 'held_lots', 'size': 'normal', 'x': 3, 'y': 0}]
        r = self.client.post('/api/qms/dashboard/', items, format='json')
        self.assertEqual((r.status_code, r.json()), (200, {'ok': True}))
        got = self.client.get('/api/qms/todo/').json()['widgets']
        self.assertEqual([(w['key'], w['size'], w['x'], w['y']) for w in got], [('gauges', 'wide', 0, 0), ('held_lots', 'normal', 3, 0)])
        self.assertEqual(self.client.post('/api/qms/dashboard/', [], format='json').status_code, 200)  # 빈 배열: 기본 배치로
        self.assertEqual([w['key'] for w in self.client.get('/api/qms/todo/').json()['widgets']], [w['key'] for w in layout_for(self.qe)])

    def test_save_layout_rejects_bad_shapes(self):
        self.client.force_login(self.qe)
        for body in ({'key': 'leave'}, [{'key': 'leave', 'size': 'huge'}], [{'key': 'leave', 'size': 'normal', 'x': 9}],
                     [{'key': 'leave', 'size': 'normal'}, {'key': 'leave', 'size': 'wide'}]):
            self.assertEqual(self.client.post('/api/qms/dashboard/', body, format='json').status_code, 400, body)

    def test_anonymous_forbidden(self):
        self.assertEqual(self.client.get('/api/qms/todo/').status_code, 403)
        self.assertEqual(self.client.post('/api/qms/dashboard/', [], format='json').status_code, 403)

    def test_every_allowed_widget_serializes(self):
        char = SimpleNamespace(pk=1, name='두께', spec=SimpleNamespace(item=SimpleNamespace(code='P-1')))
        alarm = {'char': char, 'lot': 'LOT-X', 'alarms': ['규칙1']}
        with mock.patch('qms.due.recent_spc_alarms', return_value=[alarm]):
            self._every_widget()

    def _every_widget(self):
        for user in (self.qe, self.boss):
            self.client.force_login(user)
            keys = [w['key'] for w in self.client.get('/api/qms/todo/').json()['available']]
            for size, chunks in (('normal', [keys]), ('wide', [keys[:8], keys[8:]])):  # 넓게(2x2)는 한 화면에 최대 10개
                for part in chunks:
                    r = self.client.post('/api/qms/dashboard/', [{'key': k, 'size': size} for k in part], format='json')
                    self.assertEqual(r.status_code, 200)
                    r = self.client.get('/api/qms/todo/')
                    self.assertEqual(r.status_code, 200)
                    got = r.json()['widgets']
                    self.assertEqual(sorted(w['key'] for w in got), sorted(part), (user.username, size))
                    self.assertEqual([w['key'] for w in got if w['error']], [], (user.username, size))

    def test_dedicated_widget_data(self):
        self.client.force_login(self.qe)
        self.client.post('/api/qms/dashboard/', [{'key': 'todo_lists', 'size': 'wide'}, {'key': 'audits', 'size': 'wide'}], format='json')
        data = {w['key']: w['data'] for w in self.client.get('/api/qms/todo/').json()['widgets']}
        self.assertEqual(data['todo_lists']['scars'][0]['label'], 'S-1')
        self.assertTrue(data['todo_lists']['scars'][0]['overdue'])
        self.assertEqual(data['todo_lists']['gauges'][0]['label'], 'G-1 마이크로미터')
        self.assertEqual(data['audits']['audits'][0]['label'], '공정심사')
        self.assertEqual(len(data['audits']['findings']), 1)

    def test_todo_lists_wide_rows(self):
        now, item = timezone.now(), Item.objects.get(code='P1')
        lot = Lot.objects.get(number='L-1')
        nc = Nonconformance.objects.get()
        Nonconformance.objects.filter(pk=nc.pk).update(approved_at=now, customer_notify=True)  # 승인 후 미발송 + 고객 통보 대기
        claim = CustomerClaim.objects.create(number='CL-1', customer='A사', lot=lot, description='x', received_at=now - datetime.timedelta(days=10))
        er = EditRequest.objects.create(kind='EDIT', content_type=ContentType.objects.get_for_model(Nonconformance), object_id=nc.pk,
                                        object_repr='a', reason='r', requested_by=self.qe)
        EditRequest.objects.create(kind='EDIT', content_type=er.content_type, object_id=nc.pk, object_repr='b', reason='r',
                                   requested_by=self.boss, status=EditRequest.REJECTED, decided_at=now, reject_reason='안 됨')
        cr = ChangeRequest.objects.create(number='4M-1', item=item, category='MAN', description='x', customer_notice=False)
        fa = ChangeRequest.objects.create(number='4M-2', item=item, category='MAN', description='x', customer_notice=False)
        ChangeRequest.objects.filter(pk=fa.pk).update(approved_at=now - datetime.timedelta(hours=1))  # 승인됐고 초품 합격 전
        ppap = PpapSubmission.objects.create(item=item, customer='A사', reason='신규', due_date=timezone.localdate() - datetime.timedelta(days=1))
        self.client.force_login(self.boss)
        self.client.post('/api/qms/dashboard/', [{'key': 'todo_lists', 'size': 'wide'}], format='json')
        w = self.client.get('/api/qms/todo/').json()['widgets'][0]
        self.assertFalse(w['error'])
        t = w['data']
        self.assertEqual((t['claims'][0]['label'], t['claims'][0]['lot'], t['claims'][0]['overdue'], t['claims'][0]['due_label']),
                         (str(claim), str(lot), True, '봉쇄'))
        self.assertEqual(t['claims'][0]['href'], f'/admin/qms/customerclaim/{claim.pk}/change/')
        self.assertEqual(t['nc_mail_pending'][0]['href'], f'/nc/{nc.pk}/mail/')
        self.assertEqual(t['nc_notify_pending'][0]['label'], str(nc))
        self.assertEqual((t['edit_requests'][0]['requested_by'], t['edit_requests'][0]['href']), ('qe', f'/request/{er.pk}/decide/'))
        self.assertEqual(t['my_rejected'], [{'label': str(EditRequest.objects.get(status='REJECTED')), 'reject_reason': '안 됨'}])
        self.assertEqual(t['first_articles'][0]['label'], str(fa))
        self.assertEqual((t['ppaps'][0]['label'], t['ppaps'][0]['overdue']), (str(ppap), True))
        self.assertEqual(sorted((a['kind'], a['label']) for a in t['approvals']), sorted([('4M 변경', str(cr)), ('PSW', str(ppap))]))
