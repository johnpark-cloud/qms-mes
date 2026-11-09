import io
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import load_workbook
from rest_framework.test import APIClient

from core.models import BomLine, CodeValue, ImportProfile, Item, NumberRule, Process, RoutingStep


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

    # ---- 규칙 기반 품번 자동 번호 ----
    def rule(self, name):
        return NumberRule.objects.get(name=name)

    def options(self):
        return self.client.get('/api/core/numbering/item-options/').json()['rules']

    def auto(self, name, values, **extra):
        body = {'name': '자동', 'item_type': '', 'code': 'IGNORED', **extra,
                'auto': {'rule': self.rule(name).pk, 'values': values}}
        return self.client.post('/api/core/items/', body, format='json')

    def test_item_options(self):
        rules = self.options()
        self.assertEqual([r['name'] for r in rules], ['제품코드', '원자재', '도면 품번', '표준품'])
        self.assertEqual([o['code'] for o in rules[0]['fields'][0]['options']], ['1', '2'])
        self.assertEqual(rules[1]['fields'][2]['label'], '자재 대분류')
        self.assertEqual(rules[1]['fields'][2]['parent'], 1)
        self.assertIsNone(rules[0]['fields'][0]['parent'])
        CodeValue.objects.filter(group='customer', code='DC').update(active=False)
        self.assertNotIn('DC', [o['code'] for o in self.options()[0]['fields'][2]['options']])
        NumberRule.objects.filter(name='표준품').update(active=False)
        self.assertNotIn('표준품', [r['name'] for r in self.options()])

    def test_item_options_skip_broken_rule(self):
        NumberRule.objects.create(name='깨짐', target='ITEM', pattern='{품번:없는규칙}{일련3}', sort=99)
        NumberRule.objects.create(name='문법', target='ITEM', pattern='{일련', sort=98)
        self.assertEqual([r['name'] for r in self.options()], ['제품코드', '원자재', '도면 품번', '표준품'])

    def test_item_preview(self):
        url = f'/api/core/numbering/item-preview/?rule={self.rule("제품코드").pk}'
        self.assertEqual(self.client.get(url + '&v=1&v=V&v=DC').json(), {'number': '1VDC001', 'item_type': 'FIN'})
        self.assertEqual(self.client.get(url + '&v=3&v=V&v=DC').status_code, 400)
        doc = self.rule('관리표준').pk
        self.assertEqual(self.client.get(f'/api/core/numbering/item-preview/?rule={doc}&v=M&v=A').status_code, 400)
        self.assertEqual(self.client.get('/api/core/numbering/item-preview/?rule=abc').status_code, 400)

    def test_auto_code_recomputed_on_save(self):
        Item.objects.create(code='1VDC001', name='먼저', item_type='FIN')
        r = self.auto('제품코드', ['1', 'V', 'DC'])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()['code'], r.json()['item_type']), ('1VDC002', 'FIN'))

    def test_auto_raw(self):
        r = self.auto('원자재', ['3', '1', '1', '1', '1'])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()['code'], r.json()['item_type']), ('31111-00001', 'RAW'))

    def test_auto_drawing_part(self):
        Item.objects.create(code='1TRT038', name='모체', item_type='FIN')
        r = self.auto('도면 품번', ['1TRT038', 'AS'])
        self.assertEqual((r.status_code, r.json()['code'], r.json()['item_type']), (201, '1TRT038-AS001', 'SEMI'))
        r = self.auto('도면 품번', ['1TRT038', 'AS'], item_type='RAW')
        self.assertEqual((r.json()['code'], r.json()['item_type']), ('1TRT038-AS002', 'RAW'))
        self.assertEqual(self.auto('도면 품번', ['1TRT038', 'BM']).status_code, 400)
        ref = next(r for r in self.options() if r['name'] == '도면 품번')['fields'][0]
        self.assertIn('1TRT038', [o['code'] for o in ref['options']])

    def test_auto_std_part(self):
        Item.objects.create(code='1TRT038', name='모체', item_type='FIN')
        r = self.auto('표준품', ['3', '1TRT038'])
        self.assertEqual((r.status_code, r.json()['code'], r.json()['item_type']), (201, '3TRT038-0001', 'RAW'))

    def test_auto_inactive_rejected(self):
        CodeValue.objects.filter(group='industry', code='V').update(active=False)
        r = self.auto('제품코드', ['1', 'V', 'DC'])
        self.assertEqual(r.status_code, 400)
        self.assertIn('사용 중지', r.json()['detail'])

    def test_auto_missing_type(self):
        Item.objects.create(code='1TRT038', name='모체', item_type='FIN')
        CodeValue.objects.filter(group='design', code='AS').update(item_type='')
        r = self.auto('도면 품번', ['1TRT038', 'AS'])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['detail'], '구분을 고르세요.')

    def test_auto_bad_shape(self):
        rid = self.rule('제품코드').pk
        for auto in ({'rule': 'x', 'values': []}, {'rule': rid, 'values': 'abc'}, {'rule': rid, 'values': [1, 2, 3]}, 'x'):
            r = self.client.post('/api/core/items/', {'name': 'n', 'item_type': 'FIN', 'auto': auto}, format='json')
            self.assertEqual(r.status_code, 400, auto)

    def test_auto_integrity_retry_message(self):
        before = Item.objects.count()
        with mock.patch('core.api.master.next_number', return_value='R1'):
            r = self.auto('제품코드', ['1', 'V', 'DC'])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['detail'], '같은 번호가 방금 사용되었습니다. 다시 시도하세요.')
        self.assertEqual(Item.objects.count(), before)

    def test_auto_too_long_is_not_retry_message(self):
        with mock.patch('core.api.master.next_number', return_value='X' * 51):
            r = self.auto('제품코드', ['1', 'V', 'DC'])
        self.assertEqual(r.status_code, 400)
        self.assertIn('code', r.json()['fields'])
        self.assertNotIn('다시 시도', r.json()['detail'])

    def test_auto_integrity_error_on_save(self):
        before = Item.objects.count()
        with mock.patch('core.api.master.next_number', return_value='R1'), mock.patch.object(Item, 'validate_unique'):
            r = self.auto('제품코드', ['1', 'V', 'DC'])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['detail'], '같은 번호가 방금 사용되었습니다. 다시 시도하세요.')
        self.assertEqual(Item.objects.count(), before)

    def test_manual_code_unchanged(self):
        r = self.client.post('/api/core/items/', {'code': 'ABC-1', 'name': 'n', 'item_type': 'FIN'}, format='json')
        self.assertEqual(r.status_code, 201)

    def test_code_parts(self):
        a = Item.objects.create(code='1VDC001', name='가', item_type='FIN')
        b = Item.objects.create(code='ABC-1', name='나', item_type='FIN')
        rows = {r['code']: r for r in self.client.get('/api/core/items/').json()['results']}
        self.assertTrue(rows['1VDC001']['code_parts'].startswith('1 완제품 · '))
        self.assertEqual(rows['ABC-1']['code_parts'], '')
        self.assertTrue(self.client.get(f'/api/core/items/{a.pk}/').json()['code_parts'].startswith('1 완제품 · '))
        self.assertEqual(self.client.get(f'/api/core/items/{b.pk}/').json()['code_parts'], '')

    def test_numbering_requires_add_item(self):
        u = User.objects.create_user('insp', password='x', is_staff=True)
        self.client.force_login(u)
        self.assertEqual(self.client.get('/api/core/numbering/item-options/').status_code, 403)
        self.assertEqual(self.client.get('/api/core/numbering/item-preview/?rule=1').status_code, 403)



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


class ImportApiTest(TestCase):
    CSV = '코드,이름,구분\nA1,가,원자재\nA2,나,완제품\n'

    def setUp(self):
        self.client = APIClient()
        self.boss = User.objects.create_superuser('boss', password='x')
        self.client.force_login(self.boss)
        self.profile = ImportProfile.objects.create(
            name='품번', target='item', mapping={'code': '코드', 'name': '이름', 'item_type': '구분'})

    def file(self, text=None):
        return SimpleUploadedFile('i.csv', (self.CSV if text is None else text).encode())

    def post(self, commit, text=None):
        return self.client.post('/api/core/import/', {'profile': self.profile.pk, 'file': self.file(text), 'commit': commit},
                                format='multipart')

    def test_non_ascii_digit_profile_is_400(self):
        r = self.client.post('/api/core/import/', {'profile': '²', 'file': self.file(), 'commit': '0'}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_preview_writes_nothing(self):
        r = self.post('0')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual((d['count'], d['errors'], len(d['rows'])), (2, [], 2))
        self.assertEqual(d['rows'][0], {'line': 2, 'values': {'code': 'A1', 'name': '가', 'item_type': '원자재'}})
        self.assertEqual(Item.objects.count(), 0)

    def test_commit_same_as_old_view(self):
        got = lambda: sorted(Item.objects.values_list('code', 'name', 'item_type'))
        self.client.post('/import/', {'profile': self.profile.pk, 'file': self.file()})
        old = got()
        Item.objects.all().delete()
        self.assertEqual(self.post('1').json(), {'count': 2, 'errors': []})
        self.assertEqual(got(), old)
        self.assertEqual(len(old), 2)

    def test_error_rolls_back(self):
        d = self.post('1', '코드,이름,구분\nA1,가,원자재\nA2,나,없는구분\n').json()
        self.assertTrue(d['errors'][0].startswith('3행:'))
        self.assertEqual(Item.objects.count(), 0)

    def test_permission(self):
        u = User.objects.create_user('u', password='x', is_staff=True)
        grant(u, 'add_item')
        self.client.force_login(u)
        self.assertEqual(self.post('1').status_code, 403)

    def test_bad_input(self):
        self.assertEqual(self.post('2').status_code, 400)
        r = self.client.post('/api/core/import/', {'commit': '0'}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_profiles(self):
        d = self.client.get('/api/core/import/profiles/').json()
        self.assertEqual(d[0]['target'], 'item')
