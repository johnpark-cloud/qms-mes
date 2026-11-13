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
        from core.models import Item, Lot, Nonconformance
        self.lot = Lot.objects.create(number='L-1', item=Item.objects.create(code='R1', name='양극재', item_type=Item.RAW))
        Nonconformance.objects.create(lot=self.lot, description='찍힘')  # 보류 자동 생성
        from qms.models import Capa, ChangeRequest, CustomerClaim, CustomerRule, Scar
        CustomerRule.objects.create(customer='H사')
        CustomerClaim.objects.create(number='CL-1', customer='H사', lot=self.lot, description='치수')
        Scar.objects.create(number='S-1', supplier='A소재', lot=self.lot, request='원인 회신', response_due=today)
        Capa.objects.create(title='치수 대책', source='OTHER', action='지그', owner=self.root, due_date=today)
        ChangeRequest.objects.create(number='CR-1', item=self.lot.item, category='MACHINE', description='설비 교체')
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
        self.assertEqual(edit['interval_days']['type'], 'int')
        self.assertEqual((edit['active']['type'], edit['active']['value']), ('bool', True))
        self.assertEqual(edit['last_calibrated']['type'], 'date')
        self.assertEqual(d['requests'], {'edit': False, 'delete': True})

    def test_patch_saves_with_history(self):
        r = self.patch('qms.gauge', self.g.pk, {'name': '캘리퍼스', 'interval_days': 180, 'active': False})
        self.assertEqual(r.status_code, 200, r.content)
        self.g.refresh_from_db()
        self.assertEqual((self.g.name, self.g.interval_days, self.g.active), ('캘리퍼스', 180, False))
        self.assertEqual(self.g.history.first().history_user, self.user)
        self.assertEqual(r.json()['fields'][1]['value'], '캘리퍼스')

    def test_patch_field_errors(self):
        from qms.models import Gauge
        Gauge.objects.create(number='G-2', name='x', last_calibrated=timezone.localdate())
        r = self.patch('qms.gauge', self.g.pk, {'number': 'G-2', 'interval_days': 'abc', 'name': ''})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.json()['fields']), {'number', 'interval_days', 'name'})
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

    def test_spec_edit_never_includes_sign_fields(self):
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
        nc = Nonconformance.objects.create(lot=self.fg, description='x')  # 공정 내부: 불량유형·선별·격리·공정 비어 있음
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
        self.assertIn('/admin/qms/capa/add/?source=8D', links['CAPA 만들기'])
        self.assertEqual(links['LOT 이력 (추적)'], '/trace/?lot=FG-1')

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

    def test_scar_and_capa_close_rules(self):
        r = self.close('qms.scar', self.scar.pk)
        self.assertEqual(r.json()['detail'], '협력사 회신 없이 종결할 수 없습니다.')
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
