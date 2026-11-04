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



class ProcessApiTest(TestCase):
    URL = '/api/core/processes/'

    def setUp(self):
        self.client = APIClient()
        self.boss = User.objects.create_superuser('boss', password='x')
        self.user = User.objects.create_user('u', password='x', is_staff=True)
        grant(self.user, 'view_process', 'add_process', 'change_process', 'delete_process')

    def put(self, rows, version=None):
        if version is None:
            version = self.client.get(self.URL).json()['version']
        return self.client.put(self.URL, {'rows': rows, 'version': version}, format='json')

    def test_add_edit(self):
        self.client.force_login(self.user)
        r = self.put([{'code': 'P1', 'name': '코팅'}, {'code': 'P2', 'name': '조립'}])
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual([x['code'] for x in d['rows']], ['P1', 'P2'])
        self.assertTrue(d['editable'])
        self.assertFalse(d['can_delete'])
        old = d['version']
        self.put([{'id': d['rows'][0]['id'], 'code': 'P1', 'name': '도포'}], old)
        self.assertEqual(Process.objects.get(code='P1').name, '도포')
        self.assertEqual(self.put([{'code': 'P3', 'name': 'x'}], old).status_code, 409)
        self.assertFalse(Process.objects.filter(code='P3').exists())

    def test_delete_superuser_only(self):
        p = Process.objects.create(code='P1', name='코팅')
        self.client.force_login(self.user)
        r = self.put([{'id': p.pk, 'delete': True}, {'code': 'P9', 'name': 'x'}])
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Process.objects.filter(pk=p.pk).exists())
        self.assertFalse(Process.objects.filter(code='P9').exists())
        self.client.force_login(self.boss)
        self.assertEqual(self.put([{'id': p.pk, 'delete': True}]).status_code, 200)
        self.assertFalse(Process.objects.filter(pk=p.pk).exists())

    def test_delete_used_process(self):
        p = Process.objects.create(code='P1', name='코팅')
        item = Item.objects.create(code='F', name='셀', item_type=Item.FINISHED)
        RoutingStep.objects.create(item=item, seq=1, process=p)
        self.client.force_login(self.boss)
        self.assertEqual(self.put([{'id': p.pk, 'delete': True}]).status_code, 409)
        self.assertTrue(Process.objects.filter(pk=p.pk).exists())

    def test_permissions_and_export(self):
        Process.objects.create(code='P1', name='코팅')
        nobody = User.objects.create_user('n', password='x', is_staff=True)
        self.client.force_login(nobody)
        self.assertEqual(self.client.get(self.URL).status_code, 403)
        self.assertEqual(self.client.put(self.URL, {'rows': []}, format='json').status_code, 403)
        self.client.force_login(self.boss)
        r = self.client.get(self.URL + '?export=xlsx')
        ws = load_workbook(io.BytesIO(r.content)).active
        self.assertEqual([c.value for c in ws[1]], ['공정 코드', '공정명'])
