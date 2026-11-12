from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core import relations
from core.models import Attachment, Item, Lot, Nonconformance, Partner


class RelationsApiTest(TestCase):
    def setUp(self):
        from qms.models import Inspection, InspectionSpec
        self.root = User.objects.create_superuser('root', password='pw')
        self.partner = Partner.objects.create(code='P1', name='한빛소재', is_supplier=True)
        self.item = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        self.lot = Lot.objects.create(number='L1', item=self.item, partner=self.partner)
        self.spec = InspectionSpec.objects.create(item=self.item, inspection_type='PROCESS', approved_by=self.root,
                                                  approved_at=timezone.now())
        self.nc = Nonconformance.objects.create(lot=self.lot, description='찍힘')
        self.insps = [Inspection.objects.create(lot=self.lot, spec=self.spec) for _ in range(2)]
        self.client.force_login(self.root)

    def _get(self, url, status=200):
        r = self.client.get(url)
        self.assertEqual(r.status_code, status, getattr(r, 'data', r.content))
        return r.json() if status == 200 else r

    def test_lot_incoming_groups(self):
        data = self._get(f'/api/relations/core.lot/{self.lot.pk}/')
        self.assertEqual(data['record']['text'], str(self.lot))
        self.assertEqual(data['incoming'][0]['model'], 'core.nonconformance')
        insp = next(g for g in data['incoming'] if g['model'] == 'qms.inspection')
        self.assertEqual(insp['count'], 2)
        self.assertEqual(insp['items'][0]['url'], f'/app/inspections/{self.insps[1].pk}')  # 최근 것 먼저

    def test_group_hidden_without_permission(self):
        from qms.models import Capa
        Capa.objects.create(title='재발 방지', source='NC', action='지그 교체', owner=self.root,
                            due_date=timezone.localdate(), source_type=ContentType.objects.get_for_model(Nonconformance),
                            source_id=self.nc.pk)
        data = self._get(f'/api/relations/core.nonconformance/{self.nc.pk}/')
        self.assertIn('qms.capa', [g['model'] for g in data['incoming']])
        inspector = User.objects.create_user('ins', password='pw', is_staff=True)
        inspector.groups.add(Group.objects.get(name='검사원'))
        self.client.force_login(inspector)
        data = self._get(f'/api/relations/core.nonconformance/{self.nc.pk}/')
        self.assertNotIn('qms.capa', [g['model'] for g in data['incoming']])
        key = 'qms.capa:source_type'
        self._get(f'/api/relations/core.nonconformance/{self.nc.pk}/?key={key}', status=403)

    def test_record_without_admin_page(self):
        # 측정값은 관리 화면이 없다. 링크 없이(url None) 글자만 돌려줘야 하고 500이 나면 안 된다.
        from qms.models import Characteristic, Measurement
        ch, = Characteristic.objects.bulk_create([Characteristic(spec=self.spec, name='두께', lsl=1, usl=2)])  # 승인된 기준 잠금 우회(시험용)
        Measurement.objects.create(inspection=self.insps[0], characteristic=ch, value=1.5)
        data = self._get(f'/api/relations/qms.inspection/{self.insps[0].pk}/')
        group = next(g for g in data['incoming'] if g['model'] == 'qms.measurement')
        self.assertIsNone(group['items'][0]['url'])

    def test_record_permission_required(self):
        nobody = User.objects.create_user('nobody', password='pw', is_staff=True)
        self.client.force_login(nobody)
        self._get(f'/api/relations/core.lot/{self.lot.pk}/', status=403)

    def test_outgoing_partner(self):
        data = self._get(f'/api/relations/core.lot/{self.lot.pk}/')
        partner = next(g for g in data['outgoing'] if g['model'] == 'core.partner')
        self.assertEqual(partner['label'], '거래처')
        self.assertEqual(partner['items'][0]['text'], str(self.partner))

    def test_registry_excludes_personal(self):
        self._get('/api/relations/personal.leaveprofile/1/', status=404)
        self._get('/api/relations/core.nosuch/1/', status=404)
        self._get('/api/relations/auth.user/1/', status=404)
        self.assertFalse([r for r in relations.relations_for(User) if r.model._meta.app_label == 'personal'])

    def test_excluded_models(self):
        names = [r.model.__name__ for r in relations.relations_for(Item)]
        self.assertFalse([n for n in names if n.startswith('Historical')])
        self.assertNotIn('DashboardLayout', names)
        self.assertNotIn('ImportProfile', names)

    def test_paging(self):
        from qms.models import Inspection
        for _ in range(23):
            Inspection.objects.create(lot=self.lot, spec=self.spec)
        data = self._get(f'/api/relations/core.lot/{self.lot.pk}/?key=qms.inspection:lot&page=2')
        self.assertEqual((data['count'], data['page'], data['pages'], len(data['items'])), (25, 2, 2, 5))
        self._get(f'/api/relations/core.lot/{self.lot.pk}/?key=qms.nosuch:lot', status=404)

    def test_attachments_group(self):
        Attachment.objects.create(content_type=ContentType.objects.get_for_model(Lot), object_id=self.lot.pk,
                                  file='2026/11/a.pdf', title='성적서')
        Attachment.objects.create(content_type=ContentType.objects.get_for_model(Item), object_id=self.lot.pk,
                                  file='2026/11/b.pdf', title='다른 기록')  # 같은 번호, 다른 종류
        data = self._get(f'/api/relations/core.lot/{self.lot.pk}/')
        att = next(g for g in data['incoming'] if g['model'] == 'core.attachment')
        self.assertEqual(att['count'], 1)

    def test_query_count(self):
        url = f'/api/relations/core.lot/{self.lot.pk}/'
        self._get(url)  # 캐시·ContentType 데우기
        groups = len(relations.relations_for(Lot))
        with CaptureQueriesContext(connection) as ctx:
            self._get(url)
        self.assertLessEqual(len(ctx), groups * 2 + 8)
