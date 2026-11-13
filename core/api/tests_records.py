import datetime

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from core import recordspec
from core.models import ModuleSwitch
from core.relations import record_url


class RecordsApiTest(TestCase):
    def setUp(self):
        from qms.models import Document, DocumentRevision, Gauge, Qualification
        self.root = User.objects.create_superuser('root', password='pw')
        self.doc = Document.objects.create(number='QP-01', title='품질 매뉴얼', doc_type='매뉴얼')
        self.rev = DocumentRevision.objects.create(document=self.doc, file=SimpleUploadedFile('a.pdf', b'x'), change_note='제정')
        today = timezone.localdate()
        self.g1 = Gauge.objects.create(number='G-1', name='마이크로미터', last_calibrated=today)
        self.g2 = Gauge.objects.create(number='G-2', name='캘리퍼스', last_calibrated=today, active=False)
        self.qual = Qualification.objects.create(user=self.root, inspection_type='INCOMING', valid_until=today - datetime.timedelta(days=1),
                                                 basis='교육 이수')
        self.client.force_login(self.root)

    def test_list_tabs_search_export(self):
        d = self.client.get('/api/records/qms.gauge/').json()
        self.assertEqual([t['key'] for t in d['tabs']], ['active', 'all', 'inactive'])
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
        self.assertEqual(self.client.get('/api/records/qms.capa/').status_code, 404)
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
