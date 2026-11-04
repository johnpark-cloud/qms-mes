import io

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from openpyxl import load_workbook
from rest_framework.test import APIClient

from core.models import BomLine, Item, Process, RoutingStep


def grant(user, *codes):
    for c in codes:
        user.user_permissions.add(Permission.objects.get(content_type__app_label='core', codename=c))


class ItemApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.boss = User.objects.create_superuser('boss', password='x')
        self.client.force_login(self.boss)
        self.raw = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.raw2 = Item.objects.create(code='R2', name='음극재', item_type=Item.RAW)
        self.fin = Item.objects.create(code='F1', name='셀', item_type=Item.FINISHED)
        self.p1 = Process.objects.create(code='P10', name='코팅')
        self.p2 = Process.objects.create(code='P20', name='조립')

    def put(self, item, **body):
        d = self.client.get(f'/api/core/items/{item.pk}/').json()
        body.setdefault('version', d['version'])
        body.setdefault('bom', [])
        body.setdefault('routing', [])
        return self.client.put(f'/api/core/items/{item.pk}/', body, format='json')

    def test_list_tabs_search_export(self):
        d = self.client.get('/api/core/items/?tab=FIN').json()
        self.assertEqual(d['count'], 1)
        self.assertEqual(d['results'][0]['code'], 'F1')
        self.assertEqual(self.client.get('/api/core/items/?tab=RAW').json()['count'], 2)
        self.assertEqual(self.client.get('/api/core/items/?q=셀').json()['count'], 1)
        r = self.client.get('/api/core/items/?export=xlsx')
        ws = load_workbook(io.BytesIO(r.content)).active
        self.assertEqual([c.value for c in ws[1]], ['품번', '품명', '구분', 'BOM 수', '라우팅 수'])

    def test_create_and_duplicate(self):
        body = {'code': 'N1', 'name': '새것', 'item_type': 'SEMI'}
        r = self.client.post('/api/core/items/', body, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['code'], 'N1')
        r = self.client.post('/api/core/items/', body, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('code', r.json()['fields'])

    def test_save_bom_routing(self):
        r = self.put(self.fin, bom=[{'component': self.raw.pk, 'qty': '0.25'}, {'component': self.raw2.pk, 'qty': '2'}],
                     routing=[{'seq': 10, 'process': self.p1.pk}, {'seq': 20, 'process': self.p2.pk}])
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual([b['qty'] for b in d['bom']], ['0.25', '2'])
        self.assertEqual(BomLine.objects.filter(parent=self.fin).count(), 2)
        self.assertEqual(RoutingStep.objects.filter(item=self.fin).count(), 2)
        gone = d['bom'][0]['id']
        r = self.put(self.fin, bom=[{'id': gone, 'delete': True}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(BomLine.objects.filter(pk=gone).exists())
        self.assertTrue(BomLine.history.filter(id=gone, history_type='-').exists())

    def test_row_error_saves_nothing(self):
        r = self.put(self.fin, name='바뀜', routing=[{'seq': 10, 'process': self.p1.pk}, {'seq': 'x', 'process': self.p2.pk}])
        self.assertEqual(r.status_code, 400)
        self.assertIn('routing.1.seq', r.json()['fields'])
        self.fin.refresh_from_db()
        self.assertEqual(self.fin.name, '셀')

    def test_routing_swap_rejected_cleanly(self):
        a = RoutingStep.objects.create(item=self.fin, seq=10, process=self.p1)
        b = RoutingStep.objects.create(item=self.fin, seq=20, process=self.p2)
        r = self.put(self.fin, name='바뀜', routing=[{'id': a.pk, 'seq': 20, 'process': self.p1.pk},
                                                    {'id': b.pk, 'seq': 10, 'process': self.p2.pk}])
        self.assertEqual(r.status_code, 400)
        self.assertIn('순서를 맞바꿀 때는 두 번에 나눠 저장하세요.', r.json()['fields']['routing'])
        a.refresh_from_db(), b.refresh_from_db(), self.fin.refresh_from_db()
        self.assertEqual((a.seq, b.seq, self.fin.name), (10, 20, '셀'))

    def test_stale_version(self):
        old = self.client.get(f'/api/core/items/{self.fin.pk}/').json()['version']
        self.assertEqual(self.put(self.fin, name='첫째').status_code, 200)
        r = self.put(self.fin, name='둘째', version=old)
        self.assertEqual(r.status_code, 409)

    def test_permissions(self):
        u = User.objects.create_user('v', password='x', is_staff=True)
        grant(u, 'view_item')
        self.client.force_login(u)
        self.assertEqual(self.put(self.fin, name='x').status_code, 403)
        grant(u, 'change_item')
        r = self.put(self.fin, bom=[{'component': self.raw.pk, 'qty': '1'}])
        self.assertEqual(r.status_code, 403)
        self.assertEqual(BomLine.objects.count(), 0)
