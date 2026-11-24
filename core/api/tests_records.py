import datetime
from io import BytesIO

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook

from core import recordspec
from core.models import Item, ModuleSwitch
from core.relations import record_url


def mes_fixture():
    """Phase 10 설명서마다 기록 하나씩: 작업지시·실적·출하·기준정보."""
    from django.contrib.contenttypes.models import ContentType
    from core.models import (CodeValue, Department, FieldDef, ImportProfile, Item, Lot, NumberRule, Partner, Process,
                             Project, RoutingStep, Shipment, WorkOrder, WorkResult)
    from qms.models import ExcelTemplate
    item = Item.objects.create(code='F1', name='셀', item_type=Item.FINISHED)
    step = RoutingStep.objects.create(item=item, seq=10, process=Process.objects.create(code='P10', name='조립'))
    wo = WorkOrder.objects.create(number='WO-1', item=item, planned_qty=100)
    lot = Lot.objects.create(number='FL-1', item=item, work_order=wo)
    WorkResult.objects.create(work_order=wo, step=step, lot=lot, input_qty=10, good_qty=9, defect_qty=1)
    Shipment.objects.create(lot=lot, customer='H사', qty=5)
    pj = Project.objects.create(name='NE 배터리팩', program='NE1', customer=Partner.objects.create(code='H', name='H사', is_customer=True))
    Item.objects.filter(pk=item.pk).update(project=pj)
    Department.objects.create(code='QA', name='품질')
    CodeValue.objects.create(group=CodeValue.CATEGORY, code='CL', name='셀')
    NumberRule.objects.create(name='품번', target='ITEM', pattern='{일련3}', sort=90)
    FieldDef.objects.create(target=ContentType.objects.get_for_model(Item), key='color', label='색상')
    ExcelTemplate.objects.create(name='출하성적서', target=ContentType.objects.get_for_model(Shipment),
                                 file=SimpleUploadedFile('t.xlsx', b'x'), mapping={})
    ImportProfile.objects.create(name='품번 양식', target='item', mapping={'code': '코드'})
    from core.models import Equipment, PmRecord
    eq = Equipment.objects.create(code='EQ-1', name='프레스', process=step.process)
    PmRecord.objects.create(equipment=eq, done_on=timezone.localdate(), content='윤활')
    return wo


class RecordsApiTest(TestCase):
    def setUp(self):
        from qms.models import Document, DocumentRevision, Gauge, GaugeCalibration, MsaStudy, Qualification
        self.root = User.objects.create_superuser('root', password='pw')
        self.doc = Document.objects.create(number='QP-01', title='품질 매뉴얼', doc_type='매뉴얼')
        self.rev = DocumentRevision.objects.create(document=self.doc, file=SimpleUploadedFile('a.pdf', b'x'), change_note='제정')
        today = timezone.localdate()
        self.g1 = Gauge.objects.create(number='G-1', name='마이크로미터', last_calibrated=today)
        self.g2 = Gauge.objects.create(number='G-2', name='캘리퍼스', last_calibrated=today, active=False)
        GaugeCalibration.objects.create(gauge=self.g1, calibrated_on=today)
        MsaStudy.objects.create(gauge=self.g1, kind=MsaStudy.BIAS, performed_on=today, result=MsaStudy.ACCEPT)
        self.qual = Qualification.objects.create(user=self.root, inspection_type='INCOMING', valid_until=today - datetime.timedelta(days=1),
                                                 basis='교육 이수')
        from core.models import Item, Lot, Nonconformance
        self.lot = Lot.objects.create(number='L-1', item=Item.objects.create(code='R1', name='양극재', item_type=Item.RAW))
        Nonconformance.objects.create(lot=self.lot, description='찍힘')  # 보류 자동 생성
        from qms.models import Capa, ChangeRequest, CustomerClaim, CustomerRule, Scar
        CustomerRule.objects.create(customer='H사')
        CustomerClaim.objects.create(number='CL-1', customer='H사', lot=self.lot, description='치수')
        Scar.objects.create(number='S-1', supplier='A소재', lot=self.lot, request='원인 회신', response_due=today)
        Capa.objects.create(title='치수 대책', source='OTHER', action='지그', owner=self.root, due_date=today)
        ChangeRequest.objects.create(number='CR-1', item=self.lot.item, category='MACHINE', description='설비 교체')
        from qms.models import AuditChecklist, AuditFinding, AuditItem, InternalAudit, PpapSubmission
        cl = AuditChecklist.objects.create(name='IATF 내부심사')
        AuditItem.objects.create(checklist=cl, clause='8.5.1', requirement='공정 관리')
        audit = InternalAudit.objects.create(name='상반기 공정심사', checklist=cl, planned_date=today, auditor='홍길동')
        AuditFinding.objects.create(audit=audit, clause='8.5.1', grade='OBS', description='작업표준 미게시')
        PpapSubmission.objects.create(item=self.lot.item, customer='H사', reason='신규')  # 요소 18개 자동 생성
        from qms.models import ManagementReview, ManagementReviewAction
        mr = ManagementReview.objects.create(period_start=today, period_end=today, chair=self.root, attendees='대표')
        ManagementReviewAction.objects.create(review=mr, task='검사 인원 충원', owner=self.root, due_date=today)
        mes_fixture()
        self.client.force_login(self.root)

    def test_list_tabs_search_export(self):
        d = self.client.get('/api/records/qms.gauge/').json()
        self.assertEqual([t['key'] for t in d['tabs']], ['active', 'late', 'all', 'inactive'])
        self.assertEqual([r['cells']['number'] for r in d['results']], ['G-1'])  # 첫 탭 = 사용
        self.assertEqual(d['results'][0]['url'], f'/app/r/qms/gauge/{self.g1.pk}')
        d = self.client.get('/api/records/qms.gauge/?tab=all&q=캘리').json()
        self.assertEqual([r['cells']['number'] for r in d['results']], ['G-2'])
        self.assertEqual(d['results'][0]['cells']['active'], '아니오')
        r = self.client.get('/api/records/qms.gauge/?tab=all&export=xlsx')
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        d = self.client.get('/api/records/qms.qualification/?tab=expired').json()
        self.assertEqual(d['count'], 1)
        soon = type(self.qual).objects.create(user=self.root, inspection_type='PROCESS', basis='교육',
                                              valid_until=timezone.localdate() + datetime.timedelta(days=10))
        type(self.qual).objects.create(user=self.root, inspection_type='OUTGOING', basis='교육',
                                       valid_until=timezone.localdate() + datetime.timedelta(days=365))
        d = self.client.get('/api/records/qms.qualification/?tab=soon').json()  # 30일 안에 끝나는 유효 자격
        self.assertEqual([r['url'] for r in d['results']], [f'/app/r/qms/qualification/{soon.pk}'])

    def test_overdue_count(self):  # 한눈에 보기 「지연 N」: 설명서 overdue 탭의 건수. 지금 탭·검색과 상관없이 센다
        from qms.models import Capa, CustomerClaim, Gauge
        today, now = timezone.localdate(), timezone.now()
        past = today - datetime.timedelta(days=3)
        Capa.objects.create(title='늦은 대책', source='OTHER', action='x', owner=self.root, due_date=past)
        Capa.objects.create(title='조치 끝남', source='OTHER', action='x', owner=self.root, due_date=past, done_at=past)  # 유효성 확인 대기
        d = self.client.get('/api/records/qms.capa/?tab=closed').json()
        self.assertEqual(d['overdue'], {'tab': 'late', 'count': 1})
        self.assertEqual(self.client.get('/api/records/qms.capa/?tab=late').json()['count'], 1)
        CustomerClaim.objects.create(number='CL-2', customer='H사', lot=self.lot, description='x',
                                     received_at=now - datetime.timedelta(days=30))  # 봉쇄 기한 지남
        self.assertEqual(self.client.get('/api/records/qms.customerclaim/').json()['overdue']['count'], 1)
        Gauge.objects.create(number='G-3', name='게이지', last_calibrated=today - datetime.timedelta(days=800))
        self.assertEqual(self.client.get('/api/records/qms.gauge/').json()['overdue']['count'], 1)
        self.assertEqual(self.client.get('/api/records/qms.qualification/').json()['overdue'], {'tab': 'expired', 'count': 1})
        self.assertNotIn('overdue', self.client.get('/api/records/qms.document/').json())
        for label, spec in recordspec.SPECS.items():  # 지연 탭이 실제 탭이고 쿼리가 돈다
            if spec.overdue:
                self.assertIn(spec.overdue, [k for k, _, _ in spec.tabs], label)
                self.assertIsInstance(self.client.get(f'/api/records/{label}/').json()['overdue']['count'], int, label)

    def test_list_sort_and_filter(self):  # 열 머리 정렬, 선택지·참/거짓·외래키·날짜 필터, 엑셀도 같은 조건
        from qms.models import Gauge
        old = timezone.localdate() - datetime.timedelta(days=30)
        Gauge.objects.create(number='G-3', name='게이지', last_calibrated=old)
        d = self.client.get('/api/records/qms.gauge/?tab=all&sort=-number').json()
        self.assertEqual([r['cells']['number'] for r in d['results']], ['G-3', 'G-2', 'G-1'])
        self.assertTrue(next(c for c in d['columns'] if c['key'] == 'number')['sortable'])
        self.assertFalse(next(c for c in d['columns'] if c['key'] == 'next_due')['sortable'])  # 속성은 정렬 못 함
        f = {x['key']: x for x in d['filters']}
        self.assertEqual(f['active']['type'], 'choice')
        self.assertEqual(f['last_calibrated']['type'], 'date')
        self.assertNotIn('path', f['active'])
        d = self.client.get('/api/records/qms.gauge/?tab=all&f_active=0').json()
        self.assertEqual([r['cells']['number'] for r in d['results']], ['G-2'])
        d = self.client.get(f'/api/records/qms.gauge/?tab=all&f_last_calibrated_to={old.isoformat()}').json()
        self.assertEqual([r['cells']['number'] for r in d['results']], ['G-3'])
        d = self.client.get('/api/records/qms.gauge/?tab=all&sort=nope&f_active=xx&f_last_calibrated_from=2026-13-01').json()
        self.assertEqual(d['count'], 3)  # 잘못된 값은 무시
        r = self.client.get('/api/records/qms.gauge/?tab=all&f_active=1&sort=-number&export=xlsx')
        ws = load_workbook(BytesIO(r.content)).active
        self.assertEqual([ws.cell(i, 1).value for i in range(2, ws.max_row + 1)], ['G-3', 'G-1'])
        # 외래키: 있는 값만 선택지, 날짜+시각 칸은 날짜로 거른다
        d = self.client.get('/api/records/core.nonconformance/?tab=all').json()
        f = {x['key']: x for x in d['filters']}
        self.assertEqual([o['label'] for o in f['lot']['options']], ['L-1'])
        from core.models import Item, Lot, Nonconformance
        other = Lot.objects.create(number='L-9', item=Item.objects.get(code='R1'))
        Nonconformance.objects.create(lot=other, description='긁힘')
        n = Nonconformance.objects.count()
        self.assertEqual(self.client.get(f'/api/records/core.nonconformance/?tab=all&f_lot={other.pk}').json()['count'], 1)
        self.assertEqual(self.client.get('/api/records/core.nonconformance/?tab=all&f_lot=999999').json()['count'], n)
        today = timezone.localdate().isoformat()
        self.assertEqual(self.client.get(f'/api/records/core.nonconformance/?tab=all&f_detected_at_from={today}').json()['count'], n)
        self.assertEqual(self.client.get('/api/records/core.nonconformance/?tab=all&f_detected_at_to=2000-01-01').json()['count'], 0)

    def test_detail_fields_children_side(self):
        d = self.client.get(f'/api/records/qms.document/{self.doc.pk}/').json()
        self.assertEqual(d['title'], 'QP-01 품질 매뉴얼')
        self.assertEqual(d['fields'][0], {'key': 'number', 'label': '문서번호', 'value': 'QP-01', 'url': None})
        rows = d['children'][0]['rows']
        self.assertEqual(rows[0]['url'], f'/app/r/qms/documentrevision/{self.rev.pk}')
        self.assertIn('history', d['side'])
        d = self.client.get(f'/api/records/qms.documentrevision/{self.rev.pk}/').json()
        doc = next(f for f in d['fields'] if f['key'] == 'document')
        self.assertEqual(doc['url'], f'/app/r/qms/document/{self.doc.pk}')
        self.assertEqual(d['status'], '초안')
        d = self.client.get(f'/api/records/qms.qualification/{self.qual.pk}/').json()
        self.assertEqual(next(f for f in d['fields'] if f['key'] == 'inspection_type')['value'], '수입검사')

    def test_unregistered_model_404(self):
        self.assertEqual(self.client.get('/api/records/auth.user/').status_code, 404)
        self.assertEqual(self.client.get('/api/records/personal.payslip/1/').status_code, 404)
        self.assertEqual(self.client.get('/api/records/nope/').status_code, 404)

    def test_permission_is_server_side(self):
        u = User.objects.create_user('u', password='pw', is_staff=True)
        self.client.force_login(u)
        self.assertEqual(self.client.get('/api/records/qms.gauge/').status_code, 403)
        self.assertEqual(self.client.get(f'/api/records/qms.gauge/{self.g1.pk}/history/').status_code, 403)
        u.user_permissions.add(Permission.objects.get(codename='view_gauge'))
        u = User.objects.get(pk=u.pk)
        self.client.force_login(u)
        self.assertEqual(self.client.get('/api/records/qms.gauge/').status_code, 200)
        # 미결 #6: 변경 이력은 view_ 권한이면 본다
        h = self.client.get(f'/api/records/qms.gauge/{self.g1.pk}/history/').json()
        self.assertEqual(h['results'][0]['type'], '생성')
        self.assertEqual(self.client.get(f'/api/records/qms.document/{self.doc.pk}/').status_code, 403)

    def test_module_off_gates_records(self):
        ModuleSwitch.objects.bulk_create([ModuleSwitch(key='qms_document', enabled=False)])
        u = User.objects.create_user('u', password='pw', is_staff=True)
        u.user_permissions.add(Permission.objects.get(codename='view_document'))
        self.client.force_login(u)
        self.assertEqual(self.client.get(f'/api/records/qms.document/{self.doc.pk}/').status_code, 404)

    def test_links_follow_record_url(self):
        from qms.memo import target_url
        from qms.widgets import change
        self.assertEqual(record_url(self.g1), f'/app/r/qms/gauge/{self.g1.pk}')
        self.assertEqual(target_url(self.doc), f'/app/r/qms/document/{self.doc.pk}')
        self.assertEqual(change('qms_gauge', self.g1), f'/app/r/qms/gauge/{self.g1.pk}')
        hits = self.client.get('/api/search/?q=G-1').json()['results']  # 검색은 번호 기록만, 계측기는 없음
        self.assertIsInstance(hits, list)
        self.assertIsNone(recordspec.url_for(self.qual.user))
        self.assertEqual(record_url(self.qual.user), f'/app/users/{self.qual.user.pk}')  # 사람 칸 → 사용자·조직도

    def test_admin_change_page_links_new_screen(self):
        r = self.client.get(f'/admin/qms/gauge/{self.g1.pk}/change/')
        self.assertContains(r, f'href="/app/r/qms/gauge/{self.g1.pk}"')
        self.assertContains(r, '새 화면으로')
        r = self.client.get('/admin/qms/capa/add/')
        self.assertNotContains(r, '새 화면으로')

    def test_every_spec_field_resolves(self):
        from django.apps import apps
        for label, spec in recordspec.SPECS.items():
            model = apps.get_model(label)
            obj = model.objects.first()
            self.assertIsNotNone(obj, label)
            for name in {*spec.fields, *spec.columns}:
                recordspec.value_of(obj, name)  # 오타면 AttributeError
            for c in spec.children:
                getattr(obj, c.accessor)


class RecordsWriteApiTest(TestCase):
    """Phase 6(B2): 기록 화면에서 수정·승인·수정/삭제 요청 (REC-05·06)."""

    def setUp(self):
        from qms.models import Document, DocumentRevision, Gauge
        self.root = User.objects.create_superuser('root', password='pw')
        self.doc = Document.objects.create(number='QP-01', title='품질 매뉴얼', doc_type='매뉴얼')
        self.rev = DocumentRevision.objects.create(document=self.doc, file=SimpleUploadedFile('a.pdf', b'x'), change_note='제정')
        self.g = Gauge.objects.create(number='G-1', name='마이크로미터', last_calibrated=timezone.localdate())
        self.user = User.objects.create_user('u', password='pw', is_staff=True)
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=[
            'view_gauge', 'change_gauge', 'view_documentrevision', 'change_documentrevision']))
        self.client.force_login(self.user)

    def detail(self, label, pk):
        return self.client.get(f'/api/records/{label}/{pk}/').json()

    def patch(self, label, pk, values, version=None):
        if version is None:
            version = self.detail(label, pk)['version']
        return self.client.patch(f'/api/records/{label}/{pk}/', {'values': values, 'version': version},
                                 content_type='application/json')

    def post(self, url, data):
        return self.client.post(url, data, content_type='application/json')

    def test_detail_describes_edit(self):
        d = self.detail('qms.gauge', self.g.pk)
        self.assertTrue(d['can_change'])
        self.assertFalse(d['locked'])
        self.assertFalse(d['can_approve'])  # 계측기는 승인 대상이 아니다
        edit = {e['key']: e for e in d['edit']}
        self.assertEqual(edit['interval_months']['type'], 'int')
        self.assertNotIn('interval_days', edit)
        self.assertEqual((edit['active']['type'], edit['active']['value']), ('bool', True))
        self.assertEqual(edit['last_calibrated']['type'], 'date')
        self.assertEqual(d['requests'], {'edit': False, 'delete': True})

    def test_patch_saves_with_history(self):
        r = self.patch('qms.gauge', self.g.pk, {'name': '캘리퍼스', 'interval_months': 6, 'active': False})
        self.assertEqual(r.status_code, 200, r.content)
        self.g.refresh_from_db()
        self.assertEqual((self.g.name, self.g.interval_months, self.g.active), ('캘리퍼스', 6, False))
        self.assertEqual(self.g.history.first().history_user, self.user)
        self.assertEqual(r.json()['fields'][1]['value'], '캘리퍼스')

    def test_patch_field_errors(self):
        from qms.models import Gauge
        Gauge.objects.create(number='G-2', name='x', last_calibrated=timezone.localdate())
        r = self.patch('qms.gauge', self.g.pk, {'number': 'G-2', 'interval_months': 'abc', 'name': ''})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.json()['fields']), {'number', 'interval_months', 'name'})
        self.g.refresh_from_db()
        self.assertEqual(self.g.number, 'G-1')

    def test_patch_rejects_unlisted_and_sign_fields(self):
        r = self.patch('qms.documentrevision', self.rev.pk, {'approved_at': '2026-01-01T00:00', 'approved_by': self.root.pk})
        self.assertEqual(r.status_code, 400)
        self.assertIn('승인 서명', r.json()['fields']['approved_at'][0])
        r = self.patch('qms.documentrevision', self.rev.pk, {'document': 999})
        self.assertEqual(r.status_code, 400)
        self.assertIn('document', r.json()['fields'])
        self.rev.refresh_from_db()
        self.assertIsNone(self.rev.approved_at)
        from qms.models import DocumentRevision
        DocumentRevision.objects.create(document=self.doc, revision='9', file=SimpleUploadedFile('b.pdf', b'x'), change_note='n')
        r = self.patch('qms.documentrevision', self.rev.pk, {'revision': '9'})  # 문서·개정 고유 조건
        self.assertEqual(r.status_code, 400, r.content)

    def test_edit_fk_datetime_and_admin_link_superuser_only(self):
        from core.models import Item, Lot, Nonconformance, Partner
        from qms.models import CustomerClaim
        p = Partner.objects.create(code='P1', name='H사', is_customer=True)
        lot = Lot.objects.create(number='L-1', item=Item.objects.create(code='R1', name='x', item_type=Item.RAW))
        claim = CustomerClaim.objects.create(number='CL-1', customer='H사', lot=lot, description='치수')
        self.assertIsNone(self.detail('qms.gauge', self.g.pk)['admin_url'])  # 관리 화면 링크는 시스템 관리자만
        self.client.force_login(self.root)
        d = self.detail('qms.customerclaim', claim.pk)
        self.assertEqual(d['admin_url'], f'/admin/qms/customerclaim/{claim.pk}/change/')
        e = {x['key']: x for x in d['edit']}
        self.assertEqual(e['partner']['type'], 'choice')
        self.assertIn(str(p.pk), [c['value'] for c in e['partner']['choices']])
        self.assertEqual((e['lot']['type'], e['lot']['value']), ('choice', str(lot.pk)))
        self.assertEqual(e['received_at']['type'], 'datetime')
        self.assertFalse({'number', 'nonconformance'} & set(e))  # 자동 번호·자동 연결은 그대로
        r = self.patch('qms.customerclaim', claim.pk, {'partner': str(p.pk), 'received_at': '2026-11-01T09:30'})
        self.assertEqual(r.status_code, 200, r.content)
        claim.refresh_from_db()
        self.assertEqual(claim.partner, p)
        self.assertEqual(timezone.localtime(claim.received_at).strftime('%Y-%m-%d %H:%M'), '2026-11-01 09:30')
        nc = Nonconformance.objects.create(lot=lot, description='찍힘')
        e = {x['key'] for x in self.detail('core.nonconformance', nc.pk)['edit']}
        self.assertTrue({'process', 'detected_by', 'capa_required'} <= e)
        self.assertFalse({'number', 'lot', 'detected_at', 'disposition', 'customer_approval_ref', 'cost'} & e)  # 인터록·처분 칸

    def test_spec_edit_never_includes_sign_fields(self):
        from core import rules
        from core.models import Nonconformance
        self.assertFalse(set(recordspec.SPECS['core.nonconformance'].edit) & {*rules.DISPOSE_FIELDS, *Nonconformance.INTERLOCK})
        for label, spec in recordspec.SPECS.items():
            self.assertFalse(set(spec.edit) & recordspec.sign_fields(spec), label)
            self.assertTrue(set(spec.edit) <= set(spec.fields), label)

    def test_patch_needs_change_permission(self):
        u = User.objects.create_user('v', password='pw', is_staff=True)
        u.user_permissions.add(Permission.objects.get(codename='view_gauge'))
        self.client.force_login(u)
        self.assertFalse(self.detail('qms.gauge', self.g.pk)['can_change'])
        self.assertEqual(self.patch('qms.gauge', self.g.pk, {'name': 'x'}).status_code, 403)

    def test_patch_stale_version_409(self):
        v = self.detail('qms.gauge', self.g.pk)['version']
        self.g.name = '다른 사람'
        self.g.save()
        self.assertEqual(self.patch('qms.gauge', self.g.pk, {'name': 'x'}, version=v).status_code, 409)

    def test_document_body_compare_and_sheet(self):
        """W7: 본문 편집 → 승인 잠금 → 새 개정이 본문 복사 → 이전 개정과 비교 → 양식지 본문·개정 이력."""
        from core.rules import approve
        from qms.models import DocumentRevision
        self.assertEqual(self.patch('qms.documentrevision', self.rev.pk, {'body': '1. 목적\n2. 범위'}).status_code, 200)
        d = self.detail('qms.documentrevision', self.rev.pk)
        self.assertEqual((d['body']['label'], d['body']['value'], d['body']['prev']), ('본문', '1. 목적\n2. 범위', None))
        self.assertIn('body', {e['key'] for e in d['edit']})
        self.assertNotIn('body', {f['key'] for f in d['fields']})  # 본문은 칸 표가 아니라 아래 구역
        self.rev.refresh_from_db()
        approve(self.rev, self.root, 'pw')
        self.assertEqual(self.patch('qms.documentrevision', self.rev.pk, {'body': '몰래'}).status_code, 409)
        rev2 = DocumentRevision.objects.create(document=self.doc, change_note='범위에 협력사 추가')
        self.assertEqual(rev2.body, '1. 목적\n2. 범위')
        r = self.patch('qms.documentrevision', rev2.pk, {'body': '1. 목적\n2. 범위(협력사 포함)\n3. 용어'})
        self.assertEqual(r.status_code, 200, r.content)
        b = self.detail('qms.documentrevision', rev2.pk)['body']
        self.assertEqual(b['prev'], str(self.rev))
        self.assertEqual(b['diff'], [[' ', '1. 목적'], ['-', '2. 범위'], ['+', '2. 범위(협력사 포함)'], ['+', '3. 용어']])
        doc = self.client.get(f'/api/records/qms.documentrevision/{rev2.pk}/document/').json()
        self.assertEqual(doc['body'], '1. 목적\n2. 범위(협력사 포함)\n3. 용어')
        self.assertEqual([(x['label'], x['changes'], x['approved_by']) for x in doc['revisions']],
                         [(f'Rev.{self.rev.revision}', '제정', 'root'), (f'Rev.{rev2.revision}', '범위에 협력사 추가', '')])
        self.assertTrue(doc['draft'])

    def test_approve_then_locked(self):
        url = f'/api/records/qms.documentrevision/{self.rev.pk}/approve/'
        self.assertEqual(self.post(url, {'password': 'pw'}).status_code, 403)  # 품질팀장만
        self.client.force_login(self.root)
        self.assertTrue(self.detail('qms.documentrevision', self.rev.pk)['can_approve'])
        self.assertEqual(self.post(url, {'password': 'no'}).status_code, 400)
        self.assertEqual(self.post(url, {'password': 'pw'}).status_code, 200)
        self.rev.refresh_from_db()
        self.assertEqual(self.rev.approved_by, self.root)
        self.assertEqual(self.post(url, {'password': 'pw'}).status_code, 400)  # 이미 승인
        self.assertEqual(self.post(f'/api/records/qms.gauge/{self.g.pk}/approve/', {'password': 'pw'}).status_code, 404)
        # 승인 후 잠금: 일반 사용자는 화면에서도 서버에서도 못 고친다
        self.client.force_login(self.user)
        d = self.detail('qms.documentrevision', self.rev.pk)
        self.assertTrue(d['locked'])
        self.assertFalse(d['can_change'])
        self.assertTrue(d['requests']['edit'])
        self.assertEqual(self.patch('qms.documentrevision', self.rev.pk, {'change_note': '몰래'}).status_code, 409)
        self.rev.refresh_from_db()
        self.assertEqual(self.rev.change_note, '제정')

    def test_edit_request_then_unlock(self):
        from core.models import EditRequest
        from core.rules import approve
        approve(self.rev, self.root, 'pw')
        url = f'/api/records/qms.documentrevision/{self.rev.pk}/request/'
        self.assertEqual(self.post(url, {'kind': 'EDIT', 'reason': '', 'password': 'pw'}).status_code, 400)
        self.assertEqual(self.post(url, {'kind': 'EDIT', 'reason': '오타', 'password': 'no'}).status_code, 400)
        r = self.post(url, {'kind': 'EDIT', 'reason': '오타', 'password': 'pw'})
        self.assertEqual(r.status_code, 201, r.content)
        req = EditRequest.objects.get()
        self.assertEqual((req.status, req.requested_by), (EditRequest.PENDING, self.user))
        req.decide(self.root, True)
        self.assertTrue(self.detail('qms.documentrevision', self.rev.pk)['can_change'])
        self.assertEqual(self.patch('qms.documentrevision', self.rev.pk, {'change_note': '제정(오타 수정)'}).status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, EditRequest.USED)
        self.assertEqual(self.patch('qms.documentrevision', self.rev.pk, {'change_note': '또'}).status_code, 409)

    def test_delete_request(self):
        from core.models import EditRequest
        from qms.models import Gauge
        url = f'/api/records/qms.gauge/{self.g.pk}/request/'
        self.assertEqual(self.post(url, {'kind': 'EDIT', 'reason': 'x', 'password': 'pw'}).status_code, 404)  # 수정 요청은 잠긴 기록만
        r = self.post(url, {'kind': 'DELETE', 'reason': '중복 등록', 'password': 'pw'})
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.json()['deleted'])
        self.assertEqual(EditRequest.objects.get().kind, EditRequest.DELETE)
        # 시스템 관리자는 요청과 동시에 실행된다
        g2 = Gauge.objects.create(number='G-9', name='y', last_calibrated=timezone.localdate())
        self.client.force_login(self.root)
        r = self.post(f'/api/records/qms.gauge/{g2.pk}/request/', {'kind': 'DELETE', 'reason': '중복', 'password': 'pw'})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()['deleted'])
        self.assertFalse(Gauge.objects.filter(pk=g2.pk).exists())


class RecordsNcApiTest(TestCase):
    """Phase 7(B3): LOT·부적합·보류 기록 화면. 처분은 MRB 서명 API로만, 보류는 읽기 전용 (REC-08)."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from core.models import Item, Lot, LotLink, Nonconformance
        self.root = User.objects.create_superuser('root', password='pw')
        raw = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        fg = Item.objects.create(code='F1', name='셀', item_type=Item.FINISHED)
        self.raw = Lot.objects.create(number='RAW-1', item=raw, qty=5)
        self.fg = Lot.objects.create(number='FG-1', item=fg)
        LotLink.objects.create(parent=self.raw, child=self.fg)
        self.nc = Nonconformance.objects.create(lot=self.raw, origin='INCOMING', description='찍힘', defect_type='외관',
                                                sorting_result='전수 선별', contained_qty=5)
        self.hold = self.nc.holds.get(lot=self.raw)
        perms = Permission.objects.filter(codename__in=['view_lot', 'view_hold', 'view_nonconformance', 'change_nonconformance',
                                                        'change_hold'])
        self.boss = User.objects.create_user('boss', password='pw', is_staff=True)
        self.boss.groups.add(Group.objects.get(name='품질팀장'))
        self.boss.user_permissions.add(*perms)
        self.eng = User.objects.create_user('eng', password='pw', is_staff=True)
        self.eng.user_permissions.add(*perms)
        self.client.force_login(self.boss)

    def get(self, label, pk):
        return self.client.get(f'/api/records/{label}/{pk}/')

    def dispose(self, data, nc=None):
        return self.client.post(f'/api/records/core.nonconformance/{(nc or self.nc).pk}/dispose/', data,
                                content_type='application/json')

    def test_links_open_new_record_screen(self):
        self.assertEqual(record_url(self.raw), f'/app/r/core/lot/{self.raw.pk}')
        self.assertEqual(record_url(self.nc), f'/app/r/core/nonconformance/{self.nc.pk}')
        self.assertEqual(record_url(self.hold), f'/app/r/core/hold/{self.hold.pk}')
        d = self.get('core.lot', self.raw.pk).json()
        kids = {c['key']: c for c in d['children']}
        self.assertEqual(kids['nonconformances']['rows'][0]['url'], f'/app/r/core/nonconformance/{self.nc.pk}')
        self.assertEqual(len(kids['holds']['rows']), 1)
        d = self.client.get('/api/records/core.lot/?tab=hold').json()
        self.assertEqual(sorted(r['cells']['number'] for r in d['results']), ['FG-1', 'RAW-1'])  # 하위 계보도 보류

    def test_hold_is_read_only(self):
        for user in (self.boss, self.root):
            self.client.force_login(user)
            d = self.get('core.hold', self.hold.pk).json()
            self.assertFalse(d['can_change'])
            self.assertEqual(d['requests'], {'edit': False, 'delete': False})
            for values in ({}, {'released_at': '2026-01-01T00:00'}):
                r = self.client.patch(f'/api/records/core.hold/{self.hold.pk}/', {'values': values, 'version': d['version']},
                                      content_type='application/json')
                self.assertEqual(r.status_code, 403, r.content)
            r = self.client.post(f'/api/records/core.hold/{self.hold.pk}/request/',
                                 {'kind': 'DELETE', 'reason': 'x', 'password': 'pw'}, content_type='application/json')
            self.assertEqual(r.status_code, 404)
        self.hold.refresh_from_db()
        self.assertIsNone(self.hold.released_at)

    def test_patch_cannot_dispose(self):
        d = self.get('core.nonconformance', self.nc.pk).json()
        self.assertTrue(d['can_change'])
        self.assertTrue(d['can_dispose'])
        self.assertEqual([e['key'] for e in d['dispose']], ['disposition', 'customer_approval_ref', 'cost'])
        for key, value in (('disposition', 'SCRAP'), ('customer_approval_ref', 'A-1'), ('approved_by', self.boss.pk),
                           ('closed_at', '2026-01-01T00:00')):
            r = self.client.patch(f'/api/records/core.nonconformance/{self.nc.pk}/', {'values': {key: value}, 'version': d['version']},
                                  content_type='application/json')
            self.assertEqual(r.status_code, 400, key)
            self.assertEqual(r.json()['fields'][key], ['승인 서명으로만 바꿀 수 있습니다.'])
        r = self.client.patch(f'/api/records/core.nonconformance/{self.nc.pk}/', {'values': {'description': '찍힘 2곳'},
                              'version': d['version']}, content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.nc.refresh_from_db()
        self.assertEqual((self.nc.description, self.nc.disposition), ('찍힘 2곳', ''))

    def test_dispose_rules_same_messages(self):
        def detail_of(r):
            self.assertEqual(r.status_code, 400, r.content)
            return r.json()['detail']
        self.assertEqual(detail_of(self.dispose({'disposition': 'SCRAP', 'password': 'bad'})), 'MRB 승인 비밀번호가 맞지 않습니다.')
        self.assertEqual(detail_of(self.dispose({'disposition': '', 'password': 'pw'})), '처분을 선택하세요.')
        self.assertEqual(detail_of(self.dispose({'disposition': 'CONCESSION', 'password': 'pw'})), '특채는 고객 승인 문서번호가 필요합니다.')
        self.assertEqual(detail_of(self.dispose({'disposition': 'REWORK', 'password': 'pw'})),
                         '재작업·수리는 부적합 발견 이후 재검사 합격 기록이 있어야 보류를 해제합니다.')
        self.assertIn('바꿀 수 없는 칸', detail_of(self.dispose({'disposition': 'SCRAP', 'lot': self.fg.pk, 'password': 'pw'})))
        self.client.force_login(self.eng)  # 품질팀장이 아니면 처분 불가 (모델 clean 문구)
        self.assertFalse(self.get('core.nonconformance', self.nc.pk).json()['can_dispose'])
        self.assertEqual(detail_of(self.dispose({'disposition': 'SCRAP', 'password': 'pw'})), '처분에는 품질팀장(MRB 승인자)이 필요합니다.')
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.disposition, '')

    def test_dispose_scrap_keeps_hold_concession_releases(self):
        from core.models import Nonconformance
        r = self.dispose({'disposition': 'SCRAP', 'cost': '1000', 'password': 'pw'})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((d['status'], d['can_dispose'], d['can_change'], d['locked']), ('종결', False, False, True))
        self.assertTrue(self.raw.on_hold and self.fg.on_hold)  # 폐기는 보류 유지
        self.assertEqual(self.dispose({'disposition': 'SCRAP', 'password': 'pw'}).status_code, 409)  # 종결 뒤 재처분 불가
        nc2 = Nonconformance.objects.create(lot=self.fg, origin='INCOMING', description='x', defect_type='외관',
                                            sorting_result='선별', contained_qty=1)
        r = self.dispose({'disposition': 'CONCESSION', 'customer_approval_ref': 'CUS-7', 'password': 'pw'}, nc2)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(nc2.holds.filter(released_at__isnull=True).exists())
        self.nc.refresh_from_db()
        self.assertEqual((self.nc.approved_by, self.nc.cost), (self.boss, 1000))

    def test_dispose_missing_fields(self):
        from core.models import Nonconformance
        nc = Nonconformance.objects.create(lot=self.fg, description='x')  # 공정 내부: 부적합 유형·선별·격리·공정 비어 있음
        r = self.dispose({'disposition': 'SCRAP', 'password': 'pw'}, nc)
        self.assertEqual(r.status_code, 400)
        self.assertIn('보완 필요:', r.json()['detail'])

    def test_dispose_needs_change_permission_and_nc(self):
        u = User.objects.create_user('v', password='pw', is_staff=True)
        u.user_permissions.add(Permission.objects.get(codename='view_nonconformance'))
        self.client.force_login(u)
        self.assertFalse(self.get('core.nonconformance', self.nc.pk).json()['can_dispose'])
        self.assertEqual(self.dispose({'disposition': 'SCRAP', 'password': 'pw'}).status_code, 403)
        self.client.force_login(self.root)
        r = self.client.post(f'/api/records/core.lot/{self.raw.pk}/dispose/', {'disposition': 'SCRAP', 'password': 'pw'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 404)


class RecordsCapaClaimApiTest(TestCase):
    """Phase 8(B4): CAPA·클레임·SCAR·4M 변경 기록 화면. 종결은 「종결」 API로 모델 규칙 그대로 (REC-09)."""

    def setUp(self):
        from django.contrib.contenttypes.models import ContentType
        from core.models import Item, Lot
        from qms.models import Capa, ChangeRequest, CustomerClaim, CustomerRule, Scar
        self.root = User.objects.create_superuser('root', password='pw')
        self.today = timezone.localdate()
        self.item = Item.objects.create(code='F1', name='셀', item_type=Item.FINISHED)
        self.lot = Lot.objects.create(number='FG-1', item=self.item)
        self.rule = CustomerRule.objects.create(customer='H사', containment_hours=12)
        self.claim = CustomerClaim.objects.create(number='CL-1', customer='H사', lot=self.lot, description='치수')
        self.scar = Scar.objects.create(number='S-1', supplier='A소재', lot=self.lot, request='원인 회신', response_due=self.today)
        self.capa = Capa.objects.create(title='치수 대책', source='8D', action='지그', owner=self.root, due_date=self.today,
                                        source_type=ContentType.objects.get_for_model(CustomerClaim), source_id=self.claim.pk)
        self.cr = ChangeRequest.objects.create(number='CR-1', item=self.item, category='MACHINE', description='설비 교체')
        self.client.force_login(self.root)

    def detail(self, label, pk):
        r = self.client.get(f'/api/records/{label}/{pk}/')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def patch(self, label, pk, values):
        v = self.detail(label, pk)['version']
        return self.client.patch(f'/api/records/{label}/{pk}/', {'values': values, 'version': v}, content_type='application/json')

    def close(self, label, pk):
        return self.client.post(f'/api/records/{label}/{pk}/close/', {}, content_type='application/json')

    def test_links_open_new_record_screen(self):
        for obj in (self.claim, self.scar, self.capa, self.cr, self.rule):
            meta = obj._meta
            self.assertEqual(record_url(obj), f'/app/r/{meta.app_label}/{meta.model_name}/{obj.pk}')
            self.detail(meta.label_lower, obj.pk)

    def test_capa_shows_source_and_claim_links(self):
        d = self.detail('qms.capa', self.capa.pk)
        src = next(f for f in d['fields'] if f['key'] == 'source_record')
        self.assertEqual((src['label'], src['url']), ('출처 기록', record_url(self.claim)))
        links = {x['label']: x['url'] for x in self.detail('qms.customerclaim', self.claim.pk)['links']}
        self.assertIn('/app/r/qms/capa/new?source=8D', links['CAPA 만들기'])
        self.assertEqual(links['LOT 이력 (추적)'], '/app/trace?lot=FG-1')

    def test_claim_8d_steps_and_close(self):
        d = self.detail('qms.customerclaim', self.claim.pk)
        f = {x['key']: x for x in d['fields']}
        self.assertEqual(f['current_step']['value'], 'D1 팀 구성')
        self.assertEqual([k for k in f if k.startswith('d') and k[1].isdigit()],
                         ['d1_team', 'd2_problem', 'd3_containment', 'd4_root_cause', 'd5_corrective', 'd6_verification',
                          'd7_prevention', 'd8_closure'])
        self.assertTrue(d['can_close'])
        r = self.close('qms.customerclaim', self.claim.pk)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['detail'], 'D1 팀 구성이(가) 비어 있어 종결할 수 없습니다.')
        r = self.patch('qms.customerclaim', self.claim.pk, {'closed_at': '2026-01-01T00:00'})
        self.assertEqual(r.json()['fields']['closed_at'], ['승인 서명으로만 바꿀 수 있습니다.'])
        from qms.models import CustomerClaim
        r = self.patch('qms.customerclaim', self.claim.pk, {k: f'{k} 내용' for k, _ in CustomerClaim.STEPS})
        self.assertEqual(r.status_code, 200, r.content)
        d = self.close('qms.customerclaim', self.claim.pk).json()
        self.assertEqual((d['status'], d['can_close']), ('종결', False))
        self.assertEqual(self.close('qms.customerclaim', self.claim.pk).json()['detail'], '이미 종결된 기록입니다.')

    def test_change_request_stage_review_and_revisions(self):
        """W6: 4M 진행 단계 드롭다운(승인 완료 제외)·검토자·검토 의견, 양식지 개정 이력."""
        d = self.detail('qms.changerequest', self.cr.pk)
        ed = {e['key']: e for e in d['edit']}
        self.assertEqual([c['value'] for c in ed['stage']['choices']], ['DRAFT', 'REVIEW', 'HOLD', 'REJECTED'])
        self.assertEqual([c['value'] for c in ed['customer_status']['choices']], ['NA', 'PENDING', 'REQUESTED', 'APPROVED', 'REJECTED'])
        for k in ('reviewer', 'reviewed_at', 'review_comment'):
            self.assertIn(k, ed)
        r = self.patch('qms.changerequest', self.cr.pk, {'stage': 'APPROVED'})
        self.assertEqual(r.status_code, 400, r.content)
        r = self.patch('qms.changerequest', self.cr.pk, {'stage': 'REVIEW', 'reviewer': str(self.root.pk),
                                                          'review_comment': '금형 치수 확인 필요', 'description': '설비 교체(2호기)'})
        self.assertEqual(r.status_code, 200, r.content)
        f = {x['key']: x['value'] for x in self.detail('qms.changerequest', self.cr.pk)['fields']}
        self.assertEqual((f['stage'], f['review_comment']), ('검토 중', '금형 치수 확인 필요'))
        doc = self.client.get(f'/api/records/qms.changerequest/{self.cr.pk}/document/').json()
        rev = next(t for t in doc['tables'] if t['title'] == '개정 이력')
        self.assertEqual(rev['columns'], ['차수', '일시', '변경자', '변경 내용'])
        self.assertEqual([r[0] for r in rev['rows']], ['신규', 'Rev.1'])
        self.assertIn('변경 내용: 설비 교체 → 설비 교체(2호기)', rev['rows'][1][3])
        self.assertEqual(rev['rows'][1][2], 'root')

    def test_scar_and_capa_close_rules(self):
        r = self.close('qms.scar', self.scar.pk)
        self.assertEqual(r.json()['detail'], '공급자 회신 없이 종결할 수 없습니다.')
        self.assertEqual(self.patch('qms.scar', self.scar.pk, {'response': '열처리 조건 변경'}).status_code, 200)
        self.assertEqual(self.close('qms.scar', self.scar.pk).status_code, 200)
        self.scar.refresh_from_db()
        self.assertEqual(self.scar.closed_at, self.today)
        r = self.close('qms.capa', self.capa.pk)
        self.assertEqual(r.json()['detail'], '유효성 확인 결과가 "유효"여야 종결할 수 있습니다. 무효면 새 CAPA를 만드세요.')
        self.assertFalse(self.detail('qms.customerrule', self.rule.pk)['can_close'])
        self.assertEqual(self.close('qms.customerrule', self.rule.pk).status_code, 404)
        self.assertEqual(self.close('qms.changerequest', self.cr.pk).status_code, 404)

    def test_close_needs_change_permission(self):
        u = User.objects.create_user('v', password='pw', is_staff=True)
        u.user_permissions.add(Permission.objects.get(codename='view_scar'))
        self.client.force_login(u)
        self.assertFalse(self.detail('qms.scar', self.scar.pk)['can_close'])
        self.assertEqual(self.close('qms.scar', self.scar.pk).status_code, 403)

    def test_change_request_ref_editable_and_first_article_state(self):
        f = lambda: {x['key']: x['value'] for x in self.detail('qms.changerequest', self.cr.pk)['fields']}
        self.assertEqual(f()['first_article_state'], '')
        url = f'/api/records/qms.changerequest/{self.cr.pk}/approve/'
        r = self.client.post(url, {'password': 'pw'}, content_type='application/json')
        self.assertEqual(r.json()['detail'], '고객 통보 대상 변경은 고객 승인 문서번호가 있어야 승인할 수 있습니다.')
        self.assertEqual(self.patch('qms.changerequest', self.cr.pk, {'customer_approval_ref': 'H-77'}).status_code, 200)
        self.assertEqual(self.client.post(url, {'password': 'pw'}, content_type='application/json').status_code, 200)
        self.assertEqual(f()['first_article_state'], '미확인 (출하 차단)')

    def test_closing_allowed_when_module_off(self):
        ModuleSwitch.objects.bulk_create([ModuleSwitch(key='qms_supplier', enabled=False)])  # 열린 SCAR 검사 우회: 이미 꺼진 상태
        self.assertEqual(self.patch('qms.scar', self.scar.pk, {'response': '회신'}).status_code, 200)
        self.assertEqual(self.close('qms.scar', self.scar.pk).status_code, 200)
        r = self.client.post(f'/api/records/qms.scar/{self.scar.pk}/request/', {'kind': 'DELETE', 'reason': 'x', 'password': 'pw'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 403)
        u = User.objects.create_user('v', password='pw', is_staff=True)
        u.user_permissions.add(*Permission.objects.filter(codename__in=['view_scar', 'change_scar']))
        self.client.force_login(u)
        self.assertEqual(self.close('qms.scar', self.scar.pk).status_code, 404)


class RecordsAuditPpapApiTest(TestCase):
    """Phase 9(B5): 내부심사·체크리스트·심사 항목·PPAP 기록 화면. 지적 → CAPA, PPAP 요소는 승인 후 잠김 (REC-10)."""

    def setUp(self):
        from core.models import Item
        from qms.models import AuditChecklist, AuditFinding, AuditItem, Document, InternalAudit, PpapSubmission
        self.root = User.objects.create_superuser('root', password='pw')
        self.today = timezone.localdate()
        self.cl = AuditChecklist.objects.create(name='IATF 내부심사', standard='IATF 16949')
        self.ai = AuditItem.objects.create(checklist=self.cl, clause='8.5.1', requirement='공정 관리')
        self.audit = InternalAudit.objects.create(name='상반기 공정심사', checklist=self.cl, planned_date=self.today, auditor='홍길동')
        self.finding = AuditFinding.objects.create(audit=self.audit, clause='8.5.1', grade='MINOR', description='작업표준 미게시')
        self.item = Item.objects.create(code='F1', name='셀', item_type=Item.FINISHED)
        self.ppap = PpapSubmission.objects.create(item=self.item, customer='H사', reason='신규', level=1)
        self.doc = Document.objects.create(number='AAR-1', title='외관 승인', doc_type='보고서')
        self.client.force_login(self.root)

    def detail(self, label, pk):
        r = self.client.get(f'/api/records/{label}/{pk}/')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def patch(self, label, pk, values):
        v = self.detail(label, pk)['version']
        return self.client.patch(f'/api/records/{label}/{pk}/', {'values': values, 'version': v}, content_type='application/json')

    def close(self, label, pk):
        return self.client.post(f'/api/records/{label}/{pk}/close/', {}, content_type='application/json')

    def test_links_open_new_record_screen(self):
        for obj in (self.cl, self.ai, self.audit, self.finding, self.ppap, self.ppap.elements.first()):
            meta = obj._meta
            self.assertEqual(record_url(obj), f'/app/r/{meta.app_label}/{meta.model_name}/{obj.pk}')
            self.detail(meta.label_lower, obj.pk)
        d = self.detail('qms.auditchecklist', self.cl.pk)
        self.assertEqual(d['children'][0]['rows'][0]['url'], record_url(self.ai))

    def test_finding_capa_button_and_link(self):
        d = self.detail('qms.internalaudit', self.audit.pk)
        rows = next(c for c in d['children'] if c['key'] == 'findings')['rows']
        self.assertEqual(rows[0]['url'], record_url(self.finding))
        links = {x['label']: x['url'] for x in self.detail('qms.auditfinding', self.finding.pk)['links']}
        self.assertIn('/app/r/qms/capa/new?source=AUDIT', links['CAPA 만들기'])
        from django.contrib.contenttypes.models import ContentType
        from qms.models import AuditFinding, Capa
        capa = Capa.objects.create(title='표준 게시', source='AUDIT', action='게시', owner=self.root, due_date=self.today,
                                   source_type=ContentType.objects.get_for_model(AuditFinding), source_id=self.finding.pk)
        f = {x['key']: x for x in self.detail('qms.auditfinding', self.finding.pk)['fields']}
        self.assertEqual((f['capa']['value'], f['capa']['url']), (str(capa), record_url(capa)))

    def test_audit_close_rules(self):
        self.assertTrue(self.detail('qms.internalaudit', self.audit.pk)['can_close'])
        self.assertEqual(self.close('qms.internalaudit', self.audit.pk).json()['detail'], '실시일 없이 종결할 수 없습니다.')
        self.assertEqual(self.patch('qms.internalaudit', self.audit.pk, {'performed_at': self.today.isoformat()}).status_code, 200)
        self.assertEqual(self.close('qms.internalaudit', self.audit.pk).json()['detail'],
                         'CAPA가 연결되지 않은 중·경부적합 발견사항이 있어 종결할 수 없습니다.')
        self.assertEqual(self.patch('qms.auditfinding', self.finding.pk, {'grade': 'OBS'}).status_code, 200)
        d = self.close('qms.internalaudit', self.audit.pk).json()
        self.assertEqual((d['status'], d['can_close']), ('종결', False))

    def test_ppap_elements_table_and_lock_after_approval(self):
        d = self.detail('qms.ppapsubmission', self.ppap.pk)
        table = next(c for c in d['children'] if c['key'] == 'elements')
        self.assertEqual(len(table['rows']), 18)
        self.assertIn('증적 기록', [c['label'] for c in table['columns']])
        el = self.ppap.elements.get(number=13)  # Level 1에서 제출(S) 요소
        self.assertEqual(self.patch('qms.ppapelement', el.pk, {'note': '고객 지정 양식'}).status_code, 200)
        url = f'/api/records/qms.ppapsubmission/{self.ppap.pk}/approve/'
        r = self.client.post(url, {'password': 'pw'}, content_type='application/json')
        self.assertIn('제출(S) 요소에 증적이 없습니다', r.json()['detail'])
        type(el).objects.filter(pk=el.pk).update(document=self.doc)
        self.assertEqual(self.client.post(url, {'password': 'pw'}, content_type='application/json').status_code, 200)
        d = self.detail('qms.ppapelement', el.pk)
        self.assertEqual((d['locked'], d['can_change']), (True, False))
        r = self.patch('qms.ppapelement', el.pk, {'note': '바꿈'})
        self.assertEqual(r.status_code, 409, r.content)
        el.refresh_from_db()
        self.assertEqual(el.note, '고객 지정 양식')

    def test_ppap_element_links_record_and_opens_sheets(self):
        """W4: 요소에 문서·증적 기록을 새 화면에서 잇고, 요소 표·「⋯」에서 양식지로 연다."""
        from qms.models import ControlPlan
        plan = ControlPlan.objects.create(item=self.item)
        other = ControlPlan.objects.create(item=Item.objects.create(code='X9', name='남의 품목', item_type=Item.FINISHED))
        el = self.ppap.elements.get(number=7)
        edit = {e['key']: e for e in self.detail('qms.ppapelement', el.pk)['edit']}
        values = [c['value'] for c in edit['record']['choices']]
        self.assertIn(f'qms.controlplan:{plan.pk}', values)
        self.assertNotIn(f'qms.controlplan:{other.pk}', values)  # 이 제출 품목의 기록만
        r = self.patch('qms.ppapelement', el.pk, {'record': f'qms.controlplan:{plan.pk}', 'document': str(self.doc.pk)})
        self.assertEqual(r.status_code, 200, r.content)
        el.refresh_from_db()
        self.assertEqual((el.record, el.document), (plan, self.doc))
        sheets = [{'label': '문서 양식지', 'url': f'/app/r/qms/document/{self.doc.pk}/print'},
                  {'label': '기록 양식지', 'url': f'/app/plans/{plan.pk}/print'}]
        rows = next(c for c in self.detail('qms.ppapsubmission', self.ppap.pk)['children'] if c['key'] == 'elements')['rows']
        self.assertEqual(next(x for x in rows if x['id'] == el.pk)['sheets'], sheets)
        links = self.detail('qms.ppapelement', el.pk)['links']
        self.assertEqual([x for x in links if x in sheets], sheets)
        for bad in (f'auth.user:{self.root.pk}', 'qms.controlplan:99999', 'x'):  # 개인·인증 기록, 없는 기록, 틀린 값
            self.assertEqual(self.patch('qms.ppapelement', el.pk, {'record': bad}).status_code, 400, bad)
        self.assertEqual(self.patch('qms.ppapelement', el.pk, {'record': ''}).status_code, 200)
        el.refresh_from_db()
        self.assertIsNone(el.record)

    def test_audit_evidence_rows_open_sheets(self):
        from qms.models import Evidence
        Evidence.objects.create(item=self.ai, document=self.doc)
        row = self.detail('qms.audititem', self.ai.pk)['children'][0]['rows'][0]
        self.assertEqual(row['sheets'], [{'label': '문서 양식지', 'url': f'/app/r/qms/document/{self.doc.pk}/print'}])

    def test_audit_closing_allowed_when_module_off(self):
        self.finding.grade = 'OBS'
        self.finding.save()
        ModuleSwitch.objects.bulk_create([ModuleSwitch(key='qms_audit', enabled=False)])
        self.assertEqual(self.patch('qms.internalaudit', self.audit.pk, {'performed_at': self.today.isoformat()}).status_code, 200)
        self.assertEqual(self.close('qms.internalaudit', self.audit.pk).status_code, 200)
        self.assertEqual(self.client.get(f'/api/records/qms.ppapsubmission/{self.ppap.pk}/').status_code, 200)
        u = User.objects.create_user('v', password='pw', is_staff=True)
        u.user_permissions.add(*Permission.objects.filter(codename__in=['view_auditchecklist', 'change_auditchecklist']))
        self.client.force_login(u)
        self.assertEqual(self.client.get(f'/api/records/qms.auditchecklist/{self.cl.pk}/').status_code, 404)


class RecordsMesMasterApiTest(TestCase):
    """Phase 10(B6): 작업지시·실적·출하·기준정보 기록 화면, 보류 인터록 유지, /admin/ 없는 메뉴 (REC-11)."""

    def setUp(self):
        self.root = User.objects.create_superuser('root', password='pw')
        self.wo = mes_fixture()
        self.result = self.wo.results.get()
        self.lot = self.wo.lots.get()
        self.ship = self.lot.shipments.get()
        self.client.force_login(self.root)

    def detail(self, label, pk):
        r = self.client.get(f'/api/records/{label}/{pk}/')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def patch(self, label, pk, values):
        v = self.detail(label, pk)['version']
        return self.client.patch(f'/api/records/{label}/{pk}/', {'values': values, 'version': v}, content_type='application/json')

    def test_links_open_new_record_screen(self):
        from django.apps import apps
        for label in ('core.workorder', 'core.workresult', 'core.shipment', 'core.partner', 'core.department',
                      'core.codevalue', 'core.numberrule', 'core.fielddef', 'qms.exceltemplate', 'core.importprofile',
                      'core.project'):
            obj = apps.get_model(label).objects.first()
            self.assertEqual(record_url(obj), f'/app/r/{label.replace(".", "/")}/{obj.pk}')
            self.detail(label, obj.pk)
            self.assertEqual(self.client.get(f'/api/records/{label}/').status_code, 200)
        d = self.detail('core.workorder', self.wo.pk)
        kids = {c['key']: c for c in d['children']}
        self.assertEqual(kids['results']['rows'][0]['url'], record_url(self.result))
        self.assertEqual(kids['lots']['rows'][0]['url'], record_url(self.lot))

    def test_project_screen(self):
        from core.models import Partner, Project
        pj = Project.objects.get()
        kids = {c['key']: c for c in self.detail('core.project', pj.pk)['children']}
        self.assertEqual(kids['items']['rows'][0]['url'], f'/app/items/{self.wo.item_id}')
        kids = {c['key']: c for c in self.detail('core.partner', pj.customer_id)['children']}
        self.assertEqual(kids['projects']['rows'][0]['url'], record_url(pj))
        self.assertEqual(self.client.get('/api/records/core.project/?tab=open').json()['count'], 1)
        self.assertEqual(self.client.get('/api/records/core.project/?tab=closed').json()['count'], 0)
        r = self.client.post('/api/records/core.project/', {'values': {'name': 'MX', 'customer': pj.customer_id}},
                             content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Project.objects.get(name='MX').code, 'PJ0002')
        sup = Partner.objects.create(name='소재', is_supplier=True)
        r = self.client.post('/api/records/core.project/', {'values': {'name': 'Y', 'customer': sup.pk}},
                             content_type='application/json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_quantity_fix_keeps_model_rules(self):
        r = self.patch('core.workresult', self.result.pk, {'good_qty': '20'})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('양품+불량 수량이 투입 수량보다 많습니다.', r.content.decode())
        self.assertEqual(self.patch('core.workresult', self.result.pk, {'good_qty': '8'}).status_code, 200)
        r = self.patch('core.shipment', self.ship.pk, {'lot': self.lot.pk})  # LOT(인터록 칸)은 기록 화면에서 못 바꾼다
        self.assertEqual(r.status_code, 400, r.content)

    def test_held_lot_still_blocked(self):
        from django.core.exceptions import ValidationError
        from core.models import Nonconformance, Shipment, WorkResult
        nc = Nonconformance.objects.create(lot=self.lot, description='찍힘')
        msg = f'[부적합] {nc.number}: {self.lot.number}은(는) 보류 중이라 출하할 수 없습니다.'
        with self.assertRaisesMessage(ValidationError, msg):
            Shipment.objects.create(lot=self.lot, customer='H사', qty=1)
        with self.assertRaisesMessage(ValidationError, '보류 중이라 실적 등록할 수 없습니다.'):
            WorkResult.objects.create(work_order=self.wo, step=self.result.step, lot=self.lot, input_qty=1, good_qty=1)
        self.assertEqual(self.patch('core.shipment', self.ship.pk, {'qty': '4'}).status_code, 200)  # 지난 출하 정정은 그대로

    def test_menu_has_no_admin_links_for_users(self):
        from django.contrib.auth.models import Group
        hrefs = lambda: {i['label']: i['href'] for g in self.client.get('/api/auth/me/').json()['nav'] for i in g['items']}
        root = hrefs()
        self.assertEqual(root['작업지시'], '/app/r/core/workorder')
        self.assertEqual(root['출하'], '/app/r/core/shipment')
        self.assertEqual(root['검사 실적'], '/app/inspections')
        self.assertEqual(root['품목·BOM·라우팅'], '/app/items')
        self.assertEqual(root['고객사별 8D 기한'], '/app/customer-rules')
        self.assertEqual({k for k, v in root.items() if v.startswith('/admin/')}, {'관리자 화면'})
        lead = User.objects.create_user('lead', password='pw', is_staff=True)
        lead.groups.add(Group.objects.get(name='품질팀장'))
        self.client.force_login(lead)
        links = hrefs()
        self.assertIn('부적합(NCR)', links)
        self.assertEqual([k for k, v in links.items() if v.startswith('/admin/')], [])
        side = self.client.get('/todo/').content.decode().partition('id="qms-sidebar"')[2].partition('</nav>')[0]
        self.assertIn('href="/app/r/core/nonconformance"', side)
        self.assertNotIn('href="/admin/', side)

    def test_admin_stays_for_system_admin(self):
        for url in ('/admin/', '/admin/core/workorder/', f'/admin/core/workorder/{self.wo.pk}/change/', '/admin/core/shipment/',
                    '/admin/core/partner/', '/admin/auth/user/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_mes_off_closes_record_screen(self):
        ModuleSwitch.objects.bulk_create([ModuleSwitch(key='mes', enabled=False)])
        u = User.objects.create_user('v', password='pw', is_staff=True)
        u.user_permissions.add(*Permission.objects.filter(codename__in=['view_workorder', 'view_partner']))
        self.client.force_login(u)
        self.assertEqual(self.client.get(f'/api/records/core.workorder/{self.wo.pk}/').status_code, 404)
        self.assertEqual(self.client.get('/api/records/core.partner/').status_code, 200)  # 기준정보는 끌 수 없다
        labels = [i['label'] for g in self.client.get('/api/auth/me/').json()['nav'] for i in g['items']]
        self.assertNotIn('작업지시', labels)


class RecordsCreateApiTest(TestCase):
    """기록 화면 새로 만들기: 설명서 create 칸만, add_ 권한, 모델 규칙(보류 인터록) 유지."""

    def setUp(self):
        self.root = User.objects.create_superuser('root', password='pw')
        self.wo = mes_fixture()
        self.lot = self.wo.lots.get()
        self.step = self.wo.results.get().step
        self.client.force_login(self.root)

    def post(self, label, values):
        return self.client.post(f'/api/records/{label}/', {'values': values}, content_type='application/json')

    def test_new_form_lists_create_fields_with_fk_choices(self):
        r = self.client.get('/api/records/core.workresult/new/')
        self.assertEqual(r.status_code, 200, r.content)
        f = {e['key']: e for e in r.json()['fields']}
        self.assertEqual(list(f), ['work_order', 'step', 'lot', 'input_qty', 'good_qty', 'defect_qty'])
        self.assertEqual(f['work_order']['type'], 'choice')
        self.assertIn({'value': str(self.wo.pk), 'label': 'WO-1'}, f['work_order']['choices'])
        self.assertFalse(f['lot']['required'])
        self.assertEqual(self.client.get('/api/records/core.hold/new/').status_code, 404)  # create 없는 설명서
        self.assertEqual(self.client.get('/api/records/core.workorder/').json()['new_url'], '/app/r/core/workorder/new')
        # 옛 관리 화면 추가 폼으로 보내지 않는다: 파일·JSON 칸 양식도 새 화면에서 만든다
        self.assertEqual(self.client.get('/api/records/qms.exceltemplate/').json()['new_url'], '/app/r/qms/exceltemplate/new')
        self.assertEqual(self.client.get('/api/records/core.importprofile/').json()['new_url'], '/app/r/core/importprofile/new')
        self.assertEqual(self.client.get('/api/records/qms.documentrevision/').json()['new_url'], '/app/r/qms/documentrevision/new')
        self.assertIsNone(self.client.get('/api/records/core.hold/').json()['new_url'])

    def test_create_with_file_and_json(self):
        import json

        from django.contrib.contenttypes.models import ContentType

        from qms.models import ExcelTemplate
        f = {e['key']: e for e in self.client.get('/api/records/qms.exceltemplate/new/').json()['fields']}
        self.assertEqual((f['file']['type'], f['mapping']['type']), ('file', 'json'))
        self.assertIn('B3', f['mapping']['help'])
        ct = str(ContentType.objects.get(app_label='core', model='nonconformance').pk)
        values = {'name': '고객 양식', 'target': ct, 'mapping': '{"B3": "number"}'}
        r = self.client.post('/api/records/qms.exceltemplate/', {'values': json.dumps(values),
                                                                 'file': SimpleUploadedFile('양식.xlsx', b'x')})
        self.assertEqual(r.status_code, 201, r.content)
        t = ExcelTemplate.objects.get(pk=r.json()['id'])
        self.assertEqual(t.mapping, {'B3': 'number'})
        self.assertTrue(t.file.name.endswith('.xlsx'))
        # 파일이 없고 JSON이 깨지면 칸별 오류
        r = self.client.post('/api/records/qms.exceltemplate/', {'values': json.dumps({**values, 'mapping': '{'})})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(set(r.json()['fields']), {'file', 'mapping'})
        # 설명서 밖 파일 칸은 거부
        r = self.client.post('/api/records/core.importprofile/', {'values': json.dumps({'name': 'x'}),
                                                                  'photo': SimpleUploadedFile('a.png', b'x')})
        self.assertEqual(r.status_code, 400)
        self.assertIn('photo', r.json()['fields'])

    def test_create_import_profile_json_mapping(self):
        from core.models import ImportProfile
        r = self.post('core.importprofile', {'name': '고객 A', 'target': 'work_order', 'header_row': '2',
                                             'mapping': '{"number": "지시번호"}'})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(ImportProfile.objects.get(pk=r.json()['id']).mapping, {'number': '지시번호'})
        r = self.post('core.importprofile', {'name': '고객 B', 'target': 'work_order', 'mapping': '{"nope": "x"}'})
        self.assertEqual(r.status_code, 400)  # 모델 clean: 대상에 없는 칸
        self.assertIn('mapping', r.json()['fields'])

    def test_create_work_order_and_result(self):
        from core.models import WorkOrder, WorkResult
        r = self.post('core.workorder', {'number': 'WO-2', 'item': str(self.wo.item_id), 'planned_qty': '50'})
        self.assertEqual(r.status_code, 201, r.content)
        wo = WorkOrder.objects.get(number='WO-2')
        self.assertEqual(r.json(), {'id': wo.pk, 'url': record_url(wo)})
        self.assertEqual(wo.history.count(), 1)
        r = self.post('core.workresult', {'work_order': str(wo.pk), 'step': str(self.step.pk), 'input_qty': '5', 'good_qty': '5'})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(WorkResult.objects.get(pk=r.json()['id']).operator, self.root)

    def test_model_rules_still_apply(self):
        from core.models import Nonconformance, Shipment
        r = self.post('core.workresult', {'work_order': str(self.wo.pk), 'step': str(self.step.pk), 'input_qty': '1', 'good_qty': '2'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('양품+불량 수량이 투입 수량보다 많습니다.', r.content.decode())
        r = self.post('core.shipment', {'lot': str(self.lot.pk), 'customer': 'H사', 'qty': '1', 'shipped_at': '2020-01-01'})
        self.assertEqual(r.status_code, 400)  # create에 없는 칸
        Nonconformance.objects.create(lot=self.lot, description='찍힘')
        n = Shipment.objects.count()
        r = self.post('core.shipment', {'lot': str(self.lot.pk), 'customer': 'H사', 'qty': '1'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('보류 중이라 출하할 수 없습니다.', r.content.decode())
        self.assertEqual(Shipment.objects.count(), n)

    def test_master_data_sets_created_by(self):
        from core.models import Partner
        r = self.post('core.partner', {'name': '공급사', 'is_supplier': True})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Partner.objects.get(name='공급사').created_by, self.root)

    def test_partner_new_form_numbers_code_and_takes_contacts(self):
        from core.models import Partner
        d = self.client.get('/api/records/core.partner/new/').json()
        f = {e['key']: e for e in d['fields']}
        self.assertNotIn('code', f)  # 코드는 모델이 매긴다
        self.assertEqual(f['contacts']['type'], 'rows')
        self.assertEqual([c['key'] for c in f['contacts']['columns']], ['role', 'name', 'phone', 'email'])
        self.assertEqual(d['groups'], [{'label': '구분', 'keys': ['is_customer', 'is_supplier', 'is_outsource', 'is_calibrator']}])
        rows = [{'role': '품질', 'name': ' 김품질 ', 'phone': '010', 'email': 'q@x.kr'}, {'role': '', 'name': '', 'phone': '', 'email': ''}]
        r = self.post('core.partner', {'name': '가', 'is_customer': True, 'contacts': rows})
        self.assertEqual(r.status_code, 201, r.content)
        p = Partner.objects.get(name='가')
        self.assertEqual(p.code, 'P0001')
        self.assertEqual(p.contacts, [{'role': '품질', 'name': '김품질', 'phone': '010', 'email': 'q@x.kr'}])  # 빈 줄은 버린다
        self.assertEqual(self.post('core.partner', {'name': '나', 'is_supplier': True, 'contacts': []}).status_code, 201)
        self.assertEqual(Partner.objects.get(name='나').code, 'P0002')
        r = self.post('core.partner', {'name': '다', 'is_supplier': True, 'contacts': [{'role': '영업', 'name': '', 'phone': '1', 'email': ''}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn('1번째 담당자의 이름을 입력하세요.', r.content.decode())
        r = self.post('core.partner', {'name': '다', 'is_supplier': True, 'contacts': [{'name': '이', 'email': 'nope'}]})
        self.assertIn('1번째 담당자의 이메일 형식이 올바르지 않습니다.', r.content.decode())
        detail = self.client.get(f'/api/records/core.partner/{p.pk}/').json()
        self.assertEqual(detail['groups'][0]['label'], '구분')
        self.assertIn('품질 김품질 · 010 · q@x.kr', [x['value'] for x in detail['fields']])

    def test_fielddef_new_and_edit_choices_as_tags(self):
        from django.contrib.contenttypes.models import ContentType
        from core.models import Department, FieldDef
        ct = ContentType.objects.get_for_model(Department)
        self.assertEqual(self.client.get('/api/records/core.fielddef/').json()['new_url'], '/app/r/core/fielddef/new')
        f = {e['key']: e for e in self.client.get('/api/records/core.fielddef/new/').json()['fields']}
        self.assertEqual(list(f), ['target', 'key', 'label', 'kind', 'choices', 'required', 'sort'])
        self.assertEqual((f['choices']['type'], f['choices']['value']), ('tags', []))
        self.assertIn(str(ct.pk), [c['value'] for c in f['target']['choices']])
        r = self.post('core.fielddef', {'target': str(ct.pk), 'key': 'cost_center', 'label': '원가 센터', 'kind': 'text', 'choices': []})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(FieldDef.objects.get(key='cost_center').choices, [])
        r = self.post('core.fielddef', {'target': str(ct.pk), 'key': 'bank', 'label': '은행', 'kind': 'choice', 'choices': [' ', '']})
        self.assertEqual(r.json()['fields']['choices'], ['종류가 "선택"이면 선택지를 입력하세요.'])
        r = self.post('core.fielddef', {'target': str(ct.pk), 'key': 'bank', 'label': '은행', 'kind': 'choice',
                                        'choices': ['국민', ' 신한 ', '', '국민']})
        self.assertEqual(r.status_code, 201, r.content)
        fd = FieldDef.objects.get(key='bank')
        self.assertEqual(fd.choices, ['국민', '신한'])  # 앞뒤 빈칸·빈 값·중복을 버린다
        d = self.client.get(f'/api/records/core.fielddef/{fd.pk}/').json()
        self.assertIn('국민, 신한', [x['value'] for x in d['fields']])
        self.assertIn('choices', [e['key'] for e in d['edit']])
        r = self.client.patch(f'/api/records/core.fielddef/{fd.pk}/', {'values': {'choices': ['국민', '신한', '우리']}, 'version': d['version']},
                              content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        fd.refresh_from_db()
        self.assertEqual(fd.choices, ['국민', '신한', '우리'])
        self.assertEqual(fd.history.count(), 2)

    def test_needs_add_permission(self):
        u = User.objects.create_user('v', password='pw', is_staff=True)
        u.user_permissions.add(*Permission.objects.filter(codename__in=['view_workorder', 'change_workorder']))
        self.client.force_login(u)
        self.assertEqual(self.client.get('/api/records/core.workorder/new/').status_code, 403)
        r = self.post('core.workorder', {'number': 'WO-3', 'item': str(self.wo.item_id), 'planned_qty': '1'})
        self.assertEqual(r.status_code, 403)


class NewScreenCreateTest(TestCase):
    """옛 관리 화면 추가 폼 대신 새 화면 「새로 만들기」. 파일·JSON 칸이 필수인 양식만 관리 화면에 남는다."""

    def setUp(self):
        self.root = User.objects.create_superuser('root', password='pw')
        self.wo = mes_fixture()
        self.client.force_login(self.root)

    def test_new_url_opens_new_screen(self):
        for label in ('core.lot', 'qms.capa', 'qms.changerequest', 'qms.customerclaim', 'qms.document', 'qms.gauge',
                      'qms.internalaudit', 'qms.auditchecklist', 'qms.audititem', 'qms.auditfinding', 'qms.ppapsubmission',
                      'qms.qualification', 'qms.scar', 'qms.customerrule'):
            app, model = label.split('.')
            self.assertEqual(self.client.get(f'/api/records/{label}/').json()['new_url'], f'/app/r/{app}/{model}/new', label)
            self.assertEqual(self.client.get(f'/api/records/{label}/new/').status_code, 200, label)
        self.assertEqual(self.client.get('/api/records/core.nonconformance/').json()['new_url'], '/app/nc-new')
        self.assertIsNone(self.client.get('/api/records/core.hold/').json()['new_url'])  # 부적합 등록으로만 생긴다
        self.assertIsNone(self.client.get('/api/records/qms.ppapelement/').json()['new_url'])  # 제출마다 자동으로 생긴다

    def test_capa_new_prefills_from_query_and_links_source(self):
        from django.contrib.contenttypes.models import ContentType
        from core.models import Lot, Nonconformance
        from qms.models import Capa
        nc = Nonconformance.objects.create(lot=Lot.objects.get(number='FL-1'), description='찍힘')
        ct = ContentType.objects.get_for_model(Nonconformance)
        d = self.client.get(f'/api/records/qms.capa/new/?source=NC&title=찍힘&source_type={ct.pk}&source_id={nc.pk}&bogus=1').json()
        f = {e['key']: e for e in d['fields']}
        self.assertEqual((f['source']['value'], f['title']['value'], f['owner']['value']), ('NC', '찍힘', str(self.root.pk)))
        self.assertTrue(f['source_type']['hidden'])
        self.assertEqual(f['source_id']['value'], str(nc.pk))
        self.assertNotIn('bogus', f)
        r = self.client.post('/api/records/qms.capa/', {'values': {
            'title': '찍힘', 'source': 'NC', 'owner': str(self.root.pk), 'due_date': '2026-12-31', 'action': '지그 교체',
            'source_type': str(ct.pk), 'source_id': str(nc.pk)}}, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Capa.objects.get(pk=r.json()['id']).source_record, nc)

    def test_create_lot_and_gauge(self):
        from core.models import Lot
        from qms.models import Gauge
        r = self.client.post('/api/records/core.lot/', {'values': {'number': 'R-9', 'item': str(self.wo.item_id), 'qty': '5'}},
                             content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Lot.objects.get(number='R-9').qty, 5)
        r = self.client.post('/api/records/qms.gauge/', {'values': {'number': 'G-9', 'name': '캘리퍼스', 'last_calibrated': '2026-11-01'}},
                             content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(Gauge.objects.filter(number='G-9').exists())


class RecordDocumentApiTest(TestCase):
    """양식지(W3): 기록 화면 「양식지」 → A4 한 장 문서. 옛 인쇄 주소(/print/…)는 새 양식지로 넘긴다."""

    def setUp(self):
        from core.models import Item, Lot, Nonconformance, NonconformancePhoto
        from qms.models import Capa, Gauge
        self.root = User.objects.create_superuser('root', password='pw')
        self.lot = Lot.objects.create(number='L-1', item=Item.objects.create(code='R1', name='양극재', item_type=Item.RAW))
        self.nc = Nonconformance.objects.create(lot=self.lot, description='찍힘', defect_type='외관', detected_by=self.root)
        NonconformancePhoto.objects.create(nonconformance=self.nc, file=SimpleUploadedFile('a.jpg', b'0' * 10), caption='찍힘 부위')
        self.capa = Capa.objects.create(title='치수 대책', source='OTHER', action='지그', owner=self.root,
                                        due_date=timezone.localdate())
        self.gauge = Gauge.objects.create(number='G-1', name='마이크로미터', last_calibrated=timezone.localdate())
        self.client.force_login(self.root)

    def doc(self, label, pk):
        r = self.client.get(f'/api/records/{label}/{pk}/document/')
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_nc_report_sections_photos_signoff(self):
        d = self.doc('core.nonconformance', self.nc.pk)
        self.assertEqual(d['title'], '부적합 보고서')
        self.assertTrue(d['draft'])  # MRB 승인 전
        self.assertEqual([t['title'][:1] for t in d['tables']], list('①②③④⑤⑥⑦'))
        self.assertIn(['LOT', 'L-1'], d['tables'][1]['rows'])
        self.assertIn(['부적합 유형', '외관'], d['tables'][2]['rows'])
        self.assertEqual(d['head'], [])  # 구역 표가 머리말을 대신한다
        self.assertEqual([p['caption'] for p in d['photos']], ['찍힘 부위'])
        self.assertEqual(d['signoff']['written_by'], 'root')
        self.assertEqual(d['signoff']['approved_by'], '')

    def test_capa_sections_and_generic_head(self):
        d = self.doc('qms.capa', self.capa.pk)
        self.assertEqual(d['title'], '시정조치 보고서(CAPA)')
        self.assertEqual([t['title'] for t in d['tables']], ['개요', '원인·대책', '유효성 확인'])
        self.assertIn(['조치 내용', '지그'], d['tables'][1]['rows'])
        self.assertFalse(d['draft'])
        g = self.doc('qms.gauge', self.gauge.pk)  # 구역이 없는 기록: 상세 칸 전부를 머리말로
        self.assertEqual(g['title'], '계측기')
        self.assertIn(['관리번호', 'G-1'], g['head'])

    def test_xlsx(self):
        r = self.client.get(f'/api/records/core.nonconformance/{self.nc.pk}/document/?export=xlsx')
        self.assertEqual(r.status_code, 200)
        ws = load_workbook(BytesIO(r.content)).active
        self.assertEqual(ws['A1'].value, '부적합 보고서')

    def test_view_permission_required(self):
        u = User.objects.create_user('nobody', password='pw', is_staff=True)
        self.client.force_login(u)
        self.assertEqual(self.client.get(f'/api/records/core.nonconformance/{self.nc.pk}/document/').status_code, 403)
        self.assertEqual(self.client.get('/api/records/auth.user/1/document/').status_code, 404)

    def test_old_print_url_moves_to_new_sheet(self):
        r = self.client.get(f'/print/core/nonconformance/{self.nc.pk}/')
        self.assertRedirects(r, f'/app/r/core/nonconformance/{self.nc.pk}/print', fetch_redirect_response=False)
        r = self.client.get('/print/qms/inspection/7/')
        self.assertEqual(r.status_code, 404)  # 없는 검사는 넘기기 전에 404


class RecordScreenPolishTest(TestCase):
    """W9 전수 검토: 붙일 수 없는 설정 표는 연결·메모·첨부 칸을 내지 않고, 만들 수 없는 종류는 이유를 말한다."""

    def setUp(self):
        self.root = User.objects.create_superuser('root', password='pw')
        self.client.force_login(self.root)

    def test_setting_record_has_no_relation_side(self):
        from core.models import ImportProfile
        p = ImportProfile.objects.create(name='A', target='work_order', mapping={'number': '지시번호'})
        side = self.client.get(f'/api/records/core.importprofile/{p.pk}/').json()['side']
        self.assertEqual(side, ['history'])  # 관련 기록·메모·첨부 API가 404인 표

    def test_no_create_says_where_records_come_from(self):
        r = self.client.get('/api/records/core.hold/new/')
        self.assertEqual(r.status_code, 404)
        self.assertIn('부적합', r.json()['detail'])
        self.assertEqual(r.json()['list_url'], '/app/r/core/hold')

    def test_numbers_and_mappings_read_like_a_form(self):
        from decimal import Decimal

        from core.models import Hold, ImportProfile, Lot, Nonconformance, WorkOrder
        from qms.models import Characteristic, Measurement
        wo = WorkOrder(number='WO-9', planned_qty=Decimal('2000.000'))
        self.assertEqual(recordspec.value_of(wo, 'planned_qty')[0], '2,000')  # 0 꼬리·자리 구분
        wo.planned_qty = Decimal('0.500')
        self.assertEqual(recordspec.value_of(wo, 'planned_qty')[0], '0.5')
        p = ImportProfile(name='A', target='item', mapping={'code': '코드', 'name': '품명'})
        self.assertEqual(recordspec.value_of(p, 'mapping')[0], 'code: 코드\nname: 품명')
        c = Characteristic(name='폭')
        self.assertEqual(str(Measurement(characteristic=c, value=Decimal('100.00000'))), '폭 = 100')
        self.assertEqual(str(Measurement(characteristic=c, ok=True)), '폭 = 합격')
        lot = Lot(number='L-1')
        self.assertEqual(str(Hold(lot=lot, nonconformance=Nonconformance(number='NC-1', lot=lot))), 'L-1 보류 (NC-1)')

    def test_people_show_by_name(self):
        from core.models import Department
        u = User.objects.create_user('ex_lead', first_name='팀장', last_name='예시')
        d = Department.objects.create(code='QA', name='품질', manager=u)
        self.assertEqual(recordspec.value_of(d, 'manager')[0], '팀장 예시')  # 아이디(ex_lead)가 아니라 이름
        form = self.client.get('/api/records/core.department/new/').json()
        manager = next(f for f in form['fields'] if f['key'] == 'manager')
        self.assertIn({'value': str(u.pk), 'label': '팀장 예시'}, manager['choices'])
