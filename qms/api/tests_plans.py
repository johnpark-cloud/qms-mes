from io import BytesIO

from django.contrib.auth.models import Group, User
from django.test import TestCase
from openpyxl import load_workbook
from rest_framework.test import APIClient

from core.export import DRAFT_MARK
from core.models import Item, Process
from qms.models import ControlPlan, ControlPlanLine, InspectionSpec
from qms.rules import compare_plans, plan_diff_text, prev_plan


class PlanApiTest(TestCase):
    def setUp(self):
        def mk(name, group, pw='x'):
            u = User.objects.create_user(name, password=pw, is_staff=True)
            u.groups.add(Group.objects.get(name=group))
            return u
        self.eng, self.lead = mk('eng', '품질엔지니어'), mk('lead', '품질팀장', 'pw-lead-123')
        self.item = Item.objects.create(code='F1', name='셀', item_type=Item.FINISHED)
        self.item2 = Item.objects.create(code='F2', name='팩', item_type=Item.FINISHED)
        self.p1 = Process.objects.create(code='P10', name='코팅')

    def c(self, user):
        c = APIClient()
        c.force_login(user)
        return c

    def mkplan(self, approved=False, item=None):
        plan = ControlPlan.objects.create(item=item or self.item)
        ControlPlanLine.objects.create(plan=plan, process=self.p1, characteristic='용량', special='CC', lsl=95, usl=105,
                                       sampling='5개', inspection_type='OUTGOING', severity=9, occurrence=4, detection=3)
        ControlPlanLine.objects.create(plan=plan, characteristic='온도', inspection_type='')
        if approved:
            self.approve(plan)
        return plan

    def approve(self, plan):
        r = self.c(self.lead).post(f'/api/qms/plans/{plan.pk}/approve/', {'password': 'pw-lead-123'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_list_create_conflict(self):
        a = self.mkplan(approved=True)
        b = self.mkplan(item=self.item2)
        ControlPlan.objects.create(item=self.item2, revision=2)
        n = lambda tab: self.c(self.eng).get(f'/api/qms/plans/?tab={tab}').json()['count']
        self.assertEqual((n('all'), n('draft'), n('approved'), n('current')), (3, 2, 1, 1))
        item3 = Item.objects.create(code='F3', name='모듈', item_type=Item.FINISHED)
        r = self.c(self.eng).post('/api/qms/plans/', {'item': item3.pk, 'stage': 'PROTO'}, format='json')
        self.assertEqual(r.status_code, 201)
        r = self.c(self.eng).post('/api/qms/plans/', {'item': self.item.pk, 'stage': 'PRODUCTION'}, format='json')
        self.assertEqual((r.status_code, r.json()['existing']), (409, a.pk))
        self.assertTrue(b.pk)

    def test_save_lines_and_errors(self):
        plan = ControlPlan.objects.create(item=self.item)
        rows = [{'id': None, 'characteristic': f'항목{i}', 'process': self.p1.pk, 'severity': '5'} for i in range(3)]
        r = self.c(self.eng).put(f'/api/qms/plans/{plan.pk}/', {'lines': rows, 'version': None}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(plan.lines.count(), 3)
        bad = [{'id': None, 'characteristic': '가', 'lsl': '5', 'usl': '1'}]
        r = self.c(self.eng).put(f'/api/qms/plans/{plan.pk}/', {'lines': bad, 'version': None}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['fields']['lines.0.usl'], ['하한이 상한보다 클 수 없습니다.'])
        self.assertEqual(plan.lines.count(), 3)

    def test_approved_plan_locked(self):
        plan = self.mkplan(approved=True)
        ln = plan.lines.first()
        r = self.c(self.eng).put(f'/api/qms/plans/{plan.pk}/', {'lines': [{'id': ln.pk, 'characteristic': '바꿈'}], 'version': None},
                                 format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(ControlPlanLine.objects.get(pk=ln.pk).characteristic, '용량')

    def test_new_revision_copies_and_reuses_draft(self):
        plan = self.mkplan(approved=True)
        r = self.c(self.eng).post(f'/api/qms/plans/{plan.pk}/new-revision/').json()
        self.assertTrue(r['created'])
        new = ControlPlan.objects.get(pk=r['id'])
        self.assertEqual(new.revision, 2)
        self.assertEqual(sorted(new.lines.values_list('characteristic', 'lsl', 'severity'), key=str),
                         sorted(plan.lines.values_list('characteristic', 'lsl', 'severity'), key=str))
        r2 = self.c(self.eng).post(f'/api/qms/plans/{plan.pk}/new-revision/').json()
        self.assertEqual((r2['id'], r2['created']), (new.pk, False))

    def test_approve_with_log_and_document(self):
        plan = self.mkplan()
        doc = self.c(self.eng).get(f'/api/qms/plans/{plan.pk}/document/?export=xlsx')
        ws = load_workbook(BytesIO(doc.content)).active
        self.assertIn(DRAFT_MARK, [c.value for row in ws.iter_rows() for c in row])
        r = self.c(self.lead).post(f'/api/qms/plans/{plan.pk}/approve/', {
            'password': 'pw-lead-123', 'log': {'changes': '최초', 'reason': '제정'}}, format='json')
        self.assertEqual(r.json()['status'], '승인됨')
        d = self.c(self.eng).get(f'/api/qms/plans/{plan.pk}/document/').json()
        self.assertEqual((len(d['revisions']), d['landscape'], d['draft']), (1, True, False))
        self.assertEqual(d['tables'][0]['rows'][0][-1], 'H')
        ws = load_workbook(BytesIO(self.c(self.eng).get(f'/api/qms/plans/{plan.pk}/document/?export=xlsx').content)).active
        self.assertEqual(ws.page_setup.orientation, 'landscape')

    def test_make_specs_same_as_admin(self):
        a, b = self.mkplan(approved=True), self.mkplan(approved=True, item=self.item2)
        self.c(self.lead).post('/admin/qms/controlplan/', {'action': 'make_specs', '_selected_action': [a.pk]})
        r = self.c(self.lead).post(f'/api/qms/plans/{b.pk}/make-specs/')
        self.assertEqual(r.status_code, 200, r.content)

        def shape(item):
            return [(s.inspection_type, s.revision, s.sampling,
                     [(c.name, c.lsl, c.usl, c.unit, c.special) for c in s.characteristics.order_by('pk')])
                    for s in InspectionSpec.objects.filter(item=item)]
        self.assertTrue(shape(self.item))
        self.assertEqual(shape(self.item), shape(self.item2))
        self.assertEqual(len(r.json()['made']), 1)
        draft = self.mkplan(item=Item.objects.create(code='F9', name='x', item_type=Item.FINISHED))
        self.assertEqual(self.c(self.lead).post(f'/api/qms/plans/{draft.pk}/make-specs/').status_code, 400)
        insp = User.objects.create_user('insp', password='x', is_staff=True)
        insp.groups.add(Group.objects.get(name='검사원'))
        self.assertEqual(self.c(insp).post(f'/api/qms/plans/{b.pk}/make-specs/').status_code, 403)

    def test_compare_plans(self):
        old = self.mkplan(approved=True)
        new = ControlPlan.objects.create(item=self.item, revision=2)
        ControlPlanLine.objects.create(plan=new, process=self.p1, characteristic='용량', special='CC', lsl=90, usl=105,
                                       sampling='5개', inspection_type='OUTGOING', severity=9, occurrence=4, detection=3)
        ControlPlanLine.objects.create(plan=new, characteristic='두께')
        self.assertEqual(prev_plan(new), old)
        diff = compare_plans(old, new)
        by = {r['name']: r for r in diff['rows']}
        self.assertEqual(by['P10 용량']['status'], 'changed')
        self.assertEqual(by['P10 용량']['cells'], ['lsl'])
        self.assertEqual(by['온도']['status'], 'removed')
        self.assertEqual(by['두께']['status'], 'added')
        self.assertIn('항목 추가:', plan_diff_text(diff))
        self.assertEqual(plan_diff_text(None), '최초 제정')
