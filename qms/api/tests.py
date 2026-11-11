import datetime
from decimal import Decimal
from io import BytesIO
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from core.export import XLSX
from core.models import EditRequest, Hold, Item, Lot, Nonconformance, WorkOrder
from qms.models import (AuditFinding, Capa, ChangeRequest, Characteristic, CustomerClaim, Gauge, Inspection, InspectionSpec,
                        InternalAudit, Measurement, PpapSubmission, Scar)
from qms.overview import sections
from qms.rules import RECEIVE_MSG, new_spec_revision, submit_inspection
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


class SpecApiTest(TestCase):
    def setUp(self):
        def mk(name, group, pw='x'):
            u = User.objects.create_user(name, password=pw, is_staff=True)
            u.groups.add(Group.objects.get(name=group))
            return u
        self.eng, self.lead, self.insp = mk('eng', '품질엔지니어'), mk('lead', '품질팀장', 'pw-lead-123'), mk('insp', '검사원')
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.spec = InspectionSpec.objects.create(item=self.item, inspection_type='INCOMING')
        for n in ('두께', '폭'):
            Characteristic.objects.create(spec=self.spec, name=n)
        self.spec.approved_by, self.spec.approved_at = self.lead, timezone.now()
        self.spec.save()
        item2 = Item.objects.create(code='R2', name='음극재', item_type=Item.RAW)
        InspectionSpec.objects.create(item=item2, inspection_type='INCOMING')

    def c(self, user):
        c = APIClient()
        c.force_login(user)
        return c

    def new_draft(self):
        return new_spec_revision(self.spec)

    def test_list_tabs_and_current(self):
        r = self.c(self.eng).get('/api/qms/specs/?tab=current')
        self.assertEqual([x['id'] for x in r.json()['results']], [self.spec.pk])
        self.assertEqual(self.c(self.eng).get('/api/qms/specs/?tab=draft').json()['count'], 1)

    def test_list_export_xlsx(self):
        r = self.c(self.eng).get('/api/qms/specs/?tab=all&export=xlsx')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], XLSX)
        ws = load_workbook(BytesIO(r.content)).active
        self.assertEqual(ws['A1'].value, '품번')
        self.assertEqual(ws.max_row, 3)

    def test_create_conflict_points_to_existing(self):
        r = self.c(self.eng).post('/api/qms/specs/', {'item': self.item.pk, 'inspection_type': 'INCOMING'}, format='json')
        self.assertEqual((r.status_code, r.json()['existing']), (409, self.spec.pk))

    def test_put_on_approved_rejected(self):  # 스펙 9장
        c = self.spec.characteristics.first()
        body = {'characteristics': [{'id': c.pk, 'name': '바꿈', 'lsl': '1', 'usl': '2'}], 'version': None}
        r = self.c(self.eng).put(f'/api/qms/specs/{self.spec.pk}/', body, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Characteristic.objects.get(pk=c.pk).name, c.name)

    def test_put_field_errors_by_row(self):
        draft = self.new_draft()
        body = {'characteristics': [{'id': None, 'name': '가', 'lsl': 'abc'}], 'version': None}
        r = self.c(self.eng).put(f'/api/qms/specs/{draft.pk}/', body, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('characteristics.0.lsl', r.json()['fields'])

    def test_put_stale_409(self):
        draft = self.new_draft()
        old = self.c(self.eng).get(f'/api/qms/specs/{draft.pk}/').json()['version']
        self.c(self.lead).put(f'/api/qms/specs/{draft.pk}/', {'note': 'a', 'characteristics': [], 'version': old}, format='json')
        r = self.c(self.eng).put(f'/api/qms/specs/{draft.pk}/', {'note': 'b', 'characteristics': [], 'version': old}, format='json')
        self.assertEqual((r.status_code, r.json()['detail']), (409, '다른 사람이 먼저 고쳤습니다. 다시 불러오세요.'))

    def test_inspector_cannot_edit(self):
        draft = self.new_draft()
        r = self.c(self.insp).put(f'/api/qms/specs/{draft.pk}/', {'characteristics': [], 'version': None}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_new_revision_then_approve_with_log(self):
        r = self.c(self.eng).post(f'/api/qms/specs/{self.spec.pk}/new-revision/')
        new_id = r.json()['id']
        self.assertEqual(InspectionSpec.objects.get(pk=new_id).revision, 2)
        self.assertEqual(self.c(self.eng).post(f'/api/qms/specs/{new_id}/approve/', {'password': 'x'}, format='json').status_code, 403)
        r = self.c(self.lead).post(f'/api/qms/specs/{new_id}/approve/',
                                   {'password': 'pw-lead-123', 'log': {'changes': '두께 상한 변경', 'reason': '고객 요청'}}, format='json')
        self.assertEqual(r.json()['status'], '승인됨')
        logs = self.c(self.eng).get(f'/api/qms/specs/{new_id}/revision-log/').json()['results']
        self.assertEqual([(l['label'], l['status']) for l in logs][-1], ('Rev.2', 'CONFIRMED'))

    def test_approve_stale_version_409(self):
        draft = self.new_draft()
        v = self.c(self.eng).get(f'/api/qms/specs/{draft.pk}/').json()['version']
        Characteristic.objects.create(spec=draft, name='새').save()
        r = self.c(self.lead).post(f'/api/qms/specs/{draft.pk}/approve/', {'password': 'pw-lead-123', 'version': v}, format='json')
        self.assertEqual((r.status_code, r.json()['detail']), (409, '다른 사람이 먼저 고쳤습니다. 다시 불러오세요.'))
        draft.refresh_from_db()
        self.assertIsNone(draft.approved_at)

    def test_crafted_bodies_400_not_500(self):
        draft = self.new_draft()
        for url in (f'/api/qms/specs/{draft.pk}/approve/', f'/api/qms/specs/{draft.pk}/revision-log/'):
            r = self.c(self.lead).post(url, [1], format='json')
            self.assertEqual((r.status_code, r.json()['detail']), (400, '요청 형식이 잘못되었습니다.'), url)
        r = self.c(self.eng).post(f'/api/qms/specs/{draft.pk}/revision-log/', {'changes': 1, 'reason': {}}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_huge_page_is_ok(self):
        self.assertEqual(self.c(self.eng).get('/api/qms/specs/?page=' + '9' * 30).status_code, 200)

    def test_spec_404_is_korean(self):
        r = self.c(self.eng).get('/api/qms/specs/99999/')
        self.assertEqual((r.status_code, r.json()['detail']), (404, '찾을 수 없습니다.'))

    def test_create_race_returns_409(self):
        # 확인 단계는 "없다"고 보고, 만들 때 uniq_spec_rev에 걸리는 경쟁 상황
        calls = []
        real = InspectionSpec.objects.filter

        def racing(*a, **kw):
            calls.append(1)
            return real(*a, **kw) if len(calls) > 1 else InspectionSpec.objects.none()
        with mock.patch.object(InspectionSpec.objects, 'filter', side_effect=racing):
            r = self.c(self.eng).post('/api/qms/specs/', {'item': self.item.pk, 'inspection_type': 'INCOMING'}, format='json')
        self.assertEqual((r.status_code, r.json()['existing']), (409, self.spec.pk))

    def test_document_xlsx_endpoint(self):
        r = self.c(self.insp).get(f'/api/qms/specs/{self.spec.pk}/document/?export=xlsx')
        self.assertEqual((r.status_code, r['Content-Type']), (200, XLSX))

    def test_detail_fields_and_revision_log_post(self):
        d = self.c(self.eng).get(f'/api/qms/specs/{self.spec.pk}/').json()
        self.assertEqual((d['status'], d['editable'], d['can_approve'], d['can_delete_rows']), ('승인됨', False, False, False))
        draft = self.new_draft()
        r = self.c(self.eng).post(f'/api/qms/specs/{draft.pk}/revision-log/', {'label': 'X', 'changes': '가', 'reason': '나'}, format='json')
        self.assertEqual((r.status_code, r.json()['label'], r.json()['status']), (201, 'Rev.2', 'PENDING'))
        r = self.c(self.insp).post(f'/api/qms/specs/{draft.pk}/revision-log/', {'changes': '가', 'reason': '나'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_malformed_bodies_are_400(self):
        draft = self.new_draft()
        url = f'/api/qms/specs/{draft.pk}/'
        for body in ('x', [1], {'characteristics': 'x'}, {'characteristics': {'a': 1}}, {'characteristics': [1]}):
            r = self.c(self.eng).put(url, body, format='json')
            self.assertEqual(r.status_code, 400, body)
        self.assertIn('characteristics', self.c(self.eng).put(url, {'characteristics': 'x'}, format='json').json()['fields'])
        for body in ('x', [1], {'item': self.item.pk, 'inspection_type': ['a']}, {'item': self.item.pk, 'inspection_type': {'a': 1}}):
            self.assertEqual(self.c(self.eng).post('/api/qms/specs/', body, format='json').status_code, 400, body)
        new_id = self.c(self.eng).post(f'/api/qms/specs/{self.spec.pk}/new-revision/').json()['id']
        ap = f'/api/qms/specs/{new_id}/approve/'
        for log in ('x', ['a'], {'changes': '가'}, {'reason': '나'}):
            r = self.c(self.lead).post(ap, {'password': 'pw-lead-123', 'log': log}, format='json')
            self.assertEqual(r.status_code, 400, log)
        self.assertIsNone(InspectionSpec.objects.get(pk=new_id).approved_at)

    def test_no_perm_staff_and_anonymous(self):
        nobody = User.objects.create_user('nobody', password='x', is_staff=True)
        c, pk = self.c(nobody), self.spec.pk
        for path in ('/api/qms/specs/', f'/api/qms/specs/{pk}/', f'/api/qms/specs/{pk}/revision-log/', f'/api/qms/specs/{pk}/document/'):
            self.assertEqual(c.get(path).status_code, 403, path)
        self.assertEqual(APIClient().get('/api/qms/specs/').status_code, 403)

    def test_new_revision_from_old_revision_uses_latest_approved(self):
        r2 = self.new_draft()
        r2.characteristics.filter(name='두께').update(name='두께B')
        r2.approved_by, r2.approved_at = self.lead, timezone.now()
        r2.save()
        new_id = self.c(self.eng).post(f'/api/qms/specs/{self.spec.pk}/new-revision/').json()['id']
        new = InspectionSpec.objects.get(pk=new_id)
        self.assertEqual(new.revision, 3)
        self.assertEqual(sorted(new.characteristics.values_list('name', flat=True)), ['두께B', '폭'])

    def test_special_options_shape(self):
        d = self.c(self.eng).get(f'/api/qms/specs/{self.spec.pk}/').json()
        self.assertEqual(d['special_options'][0], {'value': '', 'label': '없음'})


class InspectApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('insp', password='x', is_staff=True)
        self.user.groups.add(Group.objects.get(name='검사원'))
        self.lead = User.objects.create_user('lead', password='x', is_staff=True)
        self.item = Item.objects.create(code='D-1', name='강판', item_type=Item.RAW)
        self.spec = InspectionSpec.objects.create(item=self.item, inspection_type=InspectionSpec.INCOMING, sampling='n=5')
        self.thk = Characteristic.objects.create(spec=self.spec, name='두께', lsl=Decimal('9.9'), usl=Decimal('10.1'), unit='mm')
        self.look = Characteristic.objects.create(spec=self.spec, name='외관')
        self.spec.approved_by, self.spec.approved_at = self.lead, timezone.now()
        self.spec.save()
        self.gauge = Gauge.objects.create(number='G-01', name='마이크로미터', last_calibrated=timezone.localdate())
        self.q1 = Lot.objects.create(number='Q-1', item=self.item, supplier='성일철강', qty=Decimal('50'))
        self.q2 = Lot.objects.create(number='Q-2', item=self.item, supplier='성일철강', qty=Decimal('20'))
        submit_inspection(self.q2, self.spec, self.user, self.gauge, {self.thk.pk: '10.0', self.look.pk: 'OK'})
        self.only_inspect = User.objects.create_user('only', password='x', is_staff=True)
        self.only_inspect.user_permissions.add(Permission.objects.get(codename='add_inspection', content_type__app_label='qms'))

    def c(self, user=None):
        c = APIClient()
        c.force_login(user or self.user)
        return c

    def submit(self, lot=None, values=None, **kw):
        body = {'lot': getattr(lot, 'pk', lot) if lot is not None else self.q1.pk, 'spec': self.spec.pk, 'gauge': self.gauge.pk,
                'values': values if values is not None else {str(self.thk.pk): '10.0', str(self.look.pk): 'OK'},
                'defect_type': '', 'defect_qty': None, **kw}
        return self.c().post('/api/qms/inspect/submit/', body, format='json')

    def counts(self):
        return Inspection.objects.count(), Measurement.objects.count()

    def test_queue_lists_uninspected_oldest_first(self):
        q0 = Lot.objects.create(number='Q-0', item=self.item, qty=1, created_at=timezone.now() - datetime.timedelta(days=3))
        r = self.c().get('/api/qms/inspect/queue/?tab=INCOMING').json()
        self.assertEqual([x['number'] for x in r['results']], ['Q-0', 'Q-1'])
        row = r['results'][1]
        self.assertEqual((row['item_code'], row['qty'], row['spec_id'], row['on_hold']), ('D-1', '50', self.spec.pk, False))
        q0.delete()
        Nonconformance.objects.create(lot=self.q1, description='찍힘')
        r = self.c().get('/api/qms/inspect/queue/?tab=bad').json()
        self.assertEqual([x['number'] for x in r['results']], ['Q-1'])
        self.assertTrue(r['results'][0]['on_hold'])
        self.assertEqual(self.c().get('/api/qms/inspect/queue/?tab=PROCESS').json()['count'], 0)
        self.assertEqual(self.c().get('/api/qms/inspect/queue/?q=nope').json()['count'], 0)
        self.assertEqual(self.c().get('/api/qms/inspect/queue/?q=성일').json()['count'], 1)
        r = self.c().get('/api/qms/inspect/queue/?export=xlsx')
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        ws = load_workbook(BytesIO(r.content)).active
        self.assertEqual([c.value for c in ws[1]][:7], ['LOT', '품번', '품명', '협력사', '수량', '생성일', '보류'])

    def test_lot_lookup(self):
        d = self.c().get('/api/qms/inspect/lot/?number=Q-2').json()
        self.assertEqual(d['lot']['number'], 'Q-2')
        self.assertEqual([(s['id'], s['inspection_type'], s['done']) for s in d['specs']], [(self.spec.pk, 'INCOMING', True)])
        self.assertFalse(self.c().get('/api/qms/inspect/lot/?number=Q-1').json()['specs'][0]['done'])
        self.assertEqual(self.c().get('/api/qms/inspect/lot/?number=+').status_code, 400)
        r = self.c().get('/api/qms/inspect/lot/?number=NEW')
        self.assertEqual(r.status_code, 404)
        self.assertEqual((r.json()['detail'], r.json()['can_receive']), ('등록되지 않은 LOT입니다.', True))
        self.assertEqual(r.json()['items'], [{'value': self.item.pk, 'label': 'D-1 강판'}])
        self.assertEqual(r.json()['suppliers'], ['성일철강'])

    def test_unknown_lot_without_add_lot(self):
        r = self.c(self.only_inspect).get('/api/qms/inspect/lot/?number=NEW')
        self.assertEqual(r.status_code, 404)
        self.assertFalse(r.json()['can_receive'])
        self.assertNotIn('items', r.json())
        r = self.c(self.only_inspect).post('/api/qms/inspect/receive/', {'number': 'NEW', 'item': self.item.pk, 'qty': '5'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Lot.objects.filter(number='NEW').exists())

    def test_receive_creates_or_reuses(self):
        url, body = '/api/qms/inspect/receive/', {'number': 'NEW-1', 'item': self.item.pk, 'qty': '50', 'supplier': '대한'}
        r = self.c().post(url, body, format='json')
        self.assertEqual((r.status_code, r.json()['created'], r.json()['lot']['supplier']), (201, True, '대한'))
        self.assertEqual(r.json()['specs'][0]['id'], self.spec.pk)
        r = self.c().post(url, body, format='json')
        self.assertEqual((r.status_code, r.json()['created']), (200, False))
        r = self.c().post(url, {**body, 'number': 'NEW-2', 'qty': '0'}, format='json')
        self.assertEqual((r.status_code, r.json()['detail']), (400, RECEIVE_MSG))
        for bad in ([], {**body, 'number': 'NEW-3', 'item': 'x'}, {**body, 'number': ['a']}, {**body, 'number': 'NEW-4', 'qty': [1]}):
            self.assertEqual(self.c().post(url, bad, format='json').status_code, 400, bad)
        self.assertFalse(Lot.objects.filter(number__in=['NEW-2', 'NEW-3', 'NEW-4']).exists())

    def test_form_only_usable_gauges(self):
        Gauge.objects.create(number='G-OLD', name='낡은', last_calibrated=timezone.localdate() - datetime.timedelta(days=400))
        Gauge.objects.create(number='G-OFF', name='중지', last_calibrated=timezone.localdate(), active=False)
        d = self.c().get(f'/api/qms/inspect/form/{self.q1.pk}/{self.spec.pk}/').json()
        self.assertEqual(d['gauges'], [{'value': self.gauge.pk, 'label': 'G-01 마이크로미터'}])
        self.assertEqual(d['spec'], {'id': self.spec.pk, 'title': str(self.spec), 'sampling': 'n=5'})
        self.assertEqual(d['lot']['number'], 'Q-1')
        self.assertEqual(d['characteristics'][0], {'id': self.thk.pk, 'name': '두께', 'spec_text': '9.9 ~ 10.1 mm', 'unit': 'mm',
                                                   'is_variable': True, 'special': ''})
        self.assertEqual(d['characteristics'][1]['spec_text'], 'OK/NG')
        self.assertIn('치수', d['defect_types'])
        self.assertFalse(d['done'])
        r = self.c().get(f'/api/qms/inspect/form/{self.q2.pk}/{self.spec.pk}/')  # 합격한 LOT은 재검사 화면을 열지 않는다
        self.assertEqual(r.status_code, 400)
        self.assertIn('재검사는 처분 전인 부적합이 있을 때', r.json()['detail'])
        submit_inspection(self.q1, self.spec, self.user, self.gauge, {self.thk.pk: '12', self.look.pk: 'OK'}, '치수', '1')
        self.assertTrue(self.c().get(f'/api/qms/inspect/form/{self.q1.pk}/{self.spec.pk}/').json()['done'])
        draft = new_spec_revision(self.spec)
        self.assertEqual(self.c().get(f'/api/qms/inspect/form/{self.q1.pk}/{draft.pk}/').status_code, 404)

    def test_form_rejects_old_revision_and_other_item(self):
        rev2 = new_spec_revision(self.spec)
        InspectionSpec.objects.filter(pk=rev2.pk).update(approved_by=self.lead, approved_at=timezone.now())
        r = self.c().get(f'/api/qms/inspect/form/{self.q1.pk}/{self.spec.pk}/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('유효본이 아닙니다', r.json()['detail'])
        self.assertEqual(self.c().get(f'/api/qms/inspect/form/{self.q1.pk}/{rev2.pk}/').status_code, 200)
        other = Lot.objects.create(number='Q-X', item=Item.objects.create(code='X-1', name='다른', item_type=Item.RAW))
        r = self.c().get(f'/api/qms/inspect/form/{other.pk}/{rev2.pk}/')
        self.assertEqual((r.status_code, r.json()['detail']), (400, '검사기준의 품번과 LOT의 품번이 다릅니다.'))

    def test_check_and_submit_value_forms(self):
        url = '/api/qms/inspect/check/'
        for char, cases in ((self.thk, {' 10.0 ': True, '10,0': None, 'abc': None, 'NaN': None, '11': False}),
                            (self.look, {'OK': True, 'NG': False, 'ok': None})):
            for raw, want in cases.items():
                r = self.c().post(url, {'spec': self.spec.pk, 'values': {str(char.pk): raw}}, format='json')
                self.assertEqual(r.json()['results'], {str(char.pk): want}, raw)
        other = InspectionSpec.objects.create(item=Item.objects.create(code='X', name='x', item_type=Item.RAW), inspection_type='INCOMING')
        oc = Characteristic.objects.create(spec=other, name='남의 항목')
        r = self.c().post(url, {'spec': self.spec.pk, 'values': {str(oc.pk): 'OK', str(self.look.pk): 5}}, format='json')
        self.assertEqual(r.json()['results'], {str(self.look.pk): None})
        for bad in ([], {'spec': self.spec.pk, 'values': []}, {'spec': 'a', 'values': {}}, {'spec': '²', 'values': {}},
                    {'spec': 10**30, 'values': {}}):
            self.assertEqual(self.c().post(url, bad, format='json').status_code, 400, bad)
        before = self.counts()
        r = self.submit(values={str(self.thk.pk): '10,0', str(self.look.pk): 'OK'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('값을 입력하세요', r.json()['detail'])
        self.assertEqual(self.counts(), before)

    def test_submit_pass_and_fail(self):
        r = self.submit()
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.json()['result'], r.json()['result_display'], r.json()['nonconformance']), ('PASS', '합격', None))
        q3 = Lot.objects.create(number='Q-3', item=self.item, qty=10)
        r = self.submit(q3, {str(self.thk.pk): '11', str(self.look.pk): 'OK'}, defect_type='치수', defect_qty=3)
        self.assertEqual(r.status_code, 201)
        nc = Nonconformance.objects.get(pk=r.json()['nonconformance']['id'])
        self.assertEqual(r.json()['nonconformance']['number'], nc.number)
        self.assertEqual((nc.defect_type, nc.defect_qty, nc.detected_by), ('치수', 3, self.user))
        self.assertTrue(self.c().get('/api/qms/inspect/lot/?number=Q-3').json()['lot']['on_hold'])

    def test_submit_rejects_stale_spec_and_expired_gauge(self):
        self.assertEqual(self.c().get(f'/api/qms/inspect/form/{self.q1.pk}/{self.spec.pk}/').status_code, 200)
        r2 = new_spec_revision(self.spec)
        r2.approved_by, r2.approved_at = self.lead, timezone.now()
        r2.save()
        before = self.counts()
        r = self.submit()
        self.assertEqual(r.status_code, 400)
        self.assertIn('유효본이 아닙니다', r.json()['detail'])
        self.assertEqual(self.counts(), before)
        self.gauge.last_calibrated = timezone.localdate() - datetime.timedelta(days=self.gauge.interval_days + 1)
        self.gauge.save()
        chars = {c.name: c.pk for c in r2.characteristics.all()}
        r = self.submit(spec=r2.pk, values={str(chars['두께']): '10.0', str(chars['외관']): 'OK'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('교정 기한', r.json()['detail'])
        self.assertEqual(self.counts(), before)

    def test_submit_bad_body_400(self):
        before = self.counts()
        self.assertEqual(self.c().post('/api/qms/inspect/submit/', [], format='json').status_code, 400)
        for kw in ({'values': []}, {'values': {'x': '1'}}, {'values': {str(self.thk.pk): 10.0, str(self.look.pk): 'OK'}},
                   {'lot': 'a'}, {'spec': None}, {'gauge': 'a'}, {'gauge': True},
                   {'lot': '²'}, {'values': {'²': '1'}}, {'gauge': '²'}, {'lot': 10**30}, {'spec': '1' + '0' * 30},
                   {'gauge': 10**30}, {'values': {'1' + '0' * 30: '1'}}):
            self.assertEqual(self.submit(**kw).status_code, 400, kw)
        r = self.submit(gauge=99999)
        self.assertEqual((r.status_code, r.json()['detail']), (400, '계측기를 찾을 수 없습니다.'))
        self.assertIn('값을 입력하세요', self.submit(values={'x': '1'}).json()['detail'])
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.submit(lot=99999).status_code, 404)
        self.assertEqual(self.submit(spec=99999).status_code, 404)
        self.assertEqual(self.submit(defect_type=['x'], defect_qty=[1]).status_code, 201)  # 형식이 틀린 불량 정보는 빈 값으로

    def test_permission(self):
        nobody = self.c(User.objects.create_user('nobody', password='x', is_staff=True))
        base = '/api/qms/inspect/'
        for path in ('queue/', 'lot/?number=Q-1', f'form/{self.q1.pk}/{self.spec.pk}/'):
            self.assertEqual(nobody.get(base + path).status_code, 403, path)
        for path in ('check/', 'submit/', 'receive/'):
            self.assertEqual(nobody.post(base + path, {}, format='json').status_code, 403, path)
        self.assertEqual(APIClient().get(base + 'queue/').status_code, 403)

    def test_api_matches_old_view(self):
        q3 = Lot.objects.create(number='Q-3', item=self.item, supplier='성일철강', qty=50)
        self.c().post(f'/inspect/{self.q1.pk}/{self.spec.pk}/submit/', {
            f'c{self.thk.pk}': '11.0', f'c{self.look.pk}': 'OK', 'gauge': self.gauge.pk, 'defect_type': '치수', 'defect_qty': '3'})
        self.assertEqual(self.submit(q3, {str(self.thk.pk): '11.0', str(self.look.pk): 'OK'},
                                     defect_type='치수', defect_qty='3').status_code, 201)

        def snap(lot):
            i = Inspection.objects.get(lot=lot)
            nc = i.nonconformance
            return (i.result, list(i.measurements.order_by('characteristic_id')
                                   .values_list('characteristic_id', 'value', 'ok', 'gauge_id')),
                    (nc.defect_type, nc.defect_qty, nc.inspected_qty, nc.detected_by_id, nc.origin))
        self.assertEqual(snap(self.q1), snap(q3))
        self.assertEqual(snap(q3)[0], Inspection.FAIL)


class InspectionApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('insp', password='x', is_staff=True)
        self.user.groups.add(Group.objects.get(name='검사원'))
        self.lead = User.objects.create_user('lead', password='x', is_staff=True)
        self.item = Item.objects.create(code='D-1', name='강판', item_type=Item.RAW)
        self.specs = {}
        for t in (InspectionSpec.INCOMING, InspectionSpec.OUTGOING):
            s = InspectionSpec.objects.create(item=self.item, inspection_type=t)
            Characteristic.objects.create(spec=s, name='두께', lsl=Decimal('9.9'), usl=Decimal('10.1'), unit='mm')
            s.approved_by, s.approved_at = self.lead, timezone.now()
            s.save()
            self.specs[t] = s
        self.gauge = Gauge.objects.create(number='G-01', name='마이크로미터', last_calibrated=timezone.localdate())
        self.lots = [Lot.objects.create(number=f'L-{i}', item=self.item, supplier='성일철강' if i < 3 else '한빛', qty=10) for i in (1, 2, 3, 4)]

    def make(self, lot, t, value):
        c = self.specs[t].characteristics.get()
        return submit_inspection(lot, self.specs[t], self.user, self.gauge, {c.pk: value})

    def c(self, user=None):
        c = APIClient()
        c.force_login(user or self.user)
        return c

    def test_list_tabs_and_search(self):
        self.make(self.lots[0], 'INCOMING', '10.0')
        self.make(self.lots[3], 'INCOMING', '10.0')
        self.make(self.lots[1], 'OUTGOING', '10.0')
        r = self.c().get('/api/qms/inspections/?tab=INCOMING').json()
        self.assertEqual([x['lot_number'] for x in r['results']], ['L-4', 'L-1'])
        self.assertEqual(r['results'][0]['result_display'], '합격')
        self.assertEqual(self.c().get('/api/qms/inspections/?tab=OUTGOING').json()['count'], 1)
        self.assertEqual(self.c().get('/api/qms/inspections/?tab=PROCESS').json()['count'], 0)
        self.assertEqual(self.c().get('/api/qms/inspections/?tab=INCOMING&q=성일').json()['count'], 1)
        r = self.c().get('/api/qms/inspections/?tab=INCOMING&export=xlsx')
        self.assertEqual(r.status_code, 200)
        ws = load_workbook(BytesIO(r.content)).active
        self.assertEqual([c.value for c in ws[1]], ['검사 일시', 'LOT', '품번', '품명', '협력사', '검사기준', '검사자', '판정', '부적합'])

    def test_list_summary_follows_tab_and_search(self):
        self.make(self.lots[0], 'INCOMING', '10.0')
        self.make(self.lots[1], 'INCOMING', '11.0')
        Inspection.objects.create(lot=self.lots[2], spec=self.specs['INCOMING'])  # 미판정
        self.make(self.lots[3], 'OUTGOING', '11.0')
        r = self.c().get('/api/qms/inspections/?tab=INCOMING').json()
        self.assertEqual(r['summary'], {'total': 3, 'passed': 1, 'failed': 1, 'pending': 1})
        self.assertEqual(r['count'], 3)
        r = self.c().get('/api/qms/inspections/?tab=INCOMING&q=L-1').json()
        self.assertEqual(r['summary'], {'total': 1, 'passed': 1, 'failed': 0, 'pending': 0})
        r = self.c().get('/api/qms/inspections/?tab=OUTGOING').json()
        self.assertEqual(r['summary'], {'total': 1, 'passed': 0, 'failed': 1, 'pending': 0})

    def test_list_paging(self):
        for lot in self.lots[:3]:
            self.make(lot, 'INCOMING', '10.0')
        with mock.patch('qms.api.inspections.PAGE_SIZE', 2):
            a = self.c().get('/api/qms/inspections/?tab=INCOMING&page=1').json()
            b = self.c().get('/api/qms/inspections/?tab=INCOMING&page=2').json()
            z = self.c().get('/api/qms/inspections/?tab=INCOMING&page=x').json()
        self.assertEqual(([x['lot_number'] for x in a['results']], a['has_more']), (['L-3', 'L-2'], True))
        self.assertEqual(([x['lot_number'] for x in b['results']], b['has_more'], b['summary']['total']), (['L-1'], False, 3))
        self.assertEqual(z['page'], 1)

    def test_detail_and_document(self):
        ok = self.make(self.lots[0], 'INCOMING', '10.0')
        bad = self.make(self.lots[1], 'INCOMING', '11.0')
        d = self.c().get(f'/api/qms/inspections/{ok.pk}/').json()
        self.assertEqual((d['status'], d['nonconformance'], d['lot']['trace_url']), ('합격', None, '/trace/?lot=L-1'))
        d = self.c().get(f'/api/qms/inspections/{bad.pk}/').json()
        self.assertEqual(d['status'], '불합격')
        self.assertEqual(d['nonconformance']['number'], bad.nonconformance.number)
        self.assertEqual(d['measurements'][0]['passed'], False)
        self.assertEqual(d['measurements'][0]['spec_text'], '9.9 ~ 10.1 mm')
        r = self.c().get(f'/api/qms/inspections/{bad.pk}/document/')
        self.assertEqual(r.json()['title'], '수입검사 성적서')
        r = self.c().get(f'/api/qms/inspections/{bad.pk}/document/?export=xlsx')
        self.assertEqual(r.status_code, 200)
        self.assertIn('.xlsx', r['Content-Disposition'])

    def test_permission(self):
        i = self.make(self.lots[0], 'INCOMING', '10.0')
        nobody = User.objects.create_user('nobody', password='x', is_staff=True)
        for url in ('/api/qms/inspections/', f'/api/qms/inspections/{i.pk}/', f'/api/qms/inspections/{i.pk}/document/'):
            self.assertEqual(self.c(nobody).get(url).status_code, 403, url)
        r = self.c().get('/api/qms/inspections/999999/')
        self.assertEqual((r.status_code, r.json()['detail']), (404, '찾을 수 없습니다.'))
        self.assertEqual(self.c().get('/api/qms/inspections/999999/document/').status_code, 404)



    def test_trace_timeline_links_new_inspection_page(self):
        insp = self.make(self.lots[0], InspectionSpec.INCOMING, '10.0')
        d = self.c().get('/api/core/trace/?lot=L-1').json()
        self.assertIn(f'/app/inspections/{insp.pk}', [e['url'] for e in d['timeline']])

class CustomerRuleApiTest(TestCase):
    URL = '/api/qms/customer-rules/'

    def test_save_and_export(self):
        c = APIClient()
        c.force_login(User.objects.create_superuser('boss', password='x'))
        v = c.get(self.URL).json()['version']
        r = c.put(self.URL, {'version': v, 'rows': [{'customer': 'A사', 'containment_hours': '하루', 'corrective_days': 10}]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('rows.0.containment_hours', r.json()['fields'])
        r = c.put(self.URL, {'version': v, 'rows': [{'customer': 'A사', 'containment_hours': 12, 'corrective_days': 7}]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['rows'][0]['containment_hours'], 12)
        ws = load_workbook(BytesIO(c.get(self.URL + '?export=xlsx').content)).active
        self.assertEqual([x.value for x in ws[1]], ['고객사', '봉쇄(D3) 기한(시간)', '대책(D5) 기한(일)'])


class MemoApiTest(TestCase):
    URL = '/api/qms/memos/'

    def setUp(self):
        self.insp = User.objects.create_user('insp', password='x', is_staff=True)
        self.insp.groups.add(Group.objects.get(name='검사원'))
        self.other = User.objects.create_user('other', password='x', is_staff=True)
        self.other.groups.add(Group.objects.get(name='검사원'))
        self.eng = User.objects.create_user('eng', password='x', is_staff=True)
        self.eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.item = Item.objects.create(code='P1', name='부품', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='L-1', item=self.item, supplier='가협력')

    def c(self, user):
        c = APIClient()
        c.force_login(user)
        return c

    def test_add_to_record_and_list(self):
        c = self.c(self.insp)
        r = c.post(self.URL + f'?ct=core.lot&id={self.lot.pk}', {'body': '포장 찢김', 'speaker_kind': 'CUSTOMER'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.json()['speaker'], r.json()['can_edit']), ('고객', True))
        d = c.get(self.URL + f'?ct=core.lot&id={self.lot.pk}').json()
        self.assertEqual([m['body'] for m in d['results']], ['포장 찢김'])
        self.assertTrue(d['can_add'])
        self.assertEqual(c.get(self.URL).json()['results'], [])  # 미분류 아님

    def test_empty_body_400(self):
        r = self.c(self.insp).post(self.URL, {'body': '', 'speaker_kind': 'AUDITOR'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('body', r.json()['fields'])

    def test_photo_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        with self.settings(MEDIA_ROOT=self._tmp()):
            r = self.c(self.insp).post(self.URL, {'body': '사진', 'speaker_kind': 'AUDITOR',
                                                  'photos': SimpleUploadedFile('a.png', b'0' * 50, 'image/png')})
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual(len(r.json()['photos']), 1)

    def _tmp(self):
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_edit_author_only(self):
        mid = self.c(self.insp).post(self.URL, {'body': 'a', 'speaker_kind': 'AUDITOR'}).json()['id']
        self.assertEqual(self.c(self.other).post(f'{self.URL}{mid}/', {'body': 'b', 'speaker_kind': 'AUDITOR'}).status_code, 403)
        r = self.c(self.insp).post(f'{self.URL}{mid}/', {'body': 'b', 'speaker_kind': 'AUDITOR'})
        self.assertEqual((r.status_code, r.json()['body']), (200, 'b'))

    def test_link_unsorted(self):
        mid = self.c(self.insp).post(self.URL, {'body': 'a', 'speaker_kind': 'AUDITOR'}).json()['id']
        url = f'{self.URL}{mid}/link/'
        self.assertEqual(self.c(self.other).post(url, {'kind': 'LOT', 'number': 'L-1'}, format='json').status_code, 403)
        r = self.c(self.insp).post(url, {'kind': 'LOT', 'number': 'NOPE'}, format='json')
        self.assertEqual((r.status_code, list(r.json()['fields'])), (400, ['number']))
        self.assertEqual(self.c(self.eng).post(url, {'kind': 'LOT', 'number': ' L-1 '}, format='json').status_code, 200)
        from qms.models import Memo
        self.assertEqual(Memo.objects.get(pk=mid).target, self.lot)
        self.assertEqual(self.c(self.insp).get(self.URL).json()['results'], [])

    def test_target_rules(self):
        c = self.c(self.insp)
        self.assertEqual(c.get(self.URL + '?ct=auth.user&id=1').status_code, 404)
        self.assertEqual(c.get(self.URL + '?ct=qms.capa&id=1').status_code, 403)  # 검사원은 CAPA를 못 본다
        plain = User.objects.create_user('plain', password='x', is_staff=True)
        self.assertEqual(self.c(plain).get(self.URL).status_code, 403)
        self.assertEqual(self.c(plain).post(self.URL, {'body': 'a', 'speaker_kind': 'AUDITOR'}).status_code, 403)
