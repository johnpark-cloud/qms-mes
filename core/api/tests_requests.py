"""수정·삭제 요청을 새 화면에서(W2-1): 전용 화면 기록(검사기준 등)도 요청 API로, 처리 화면은 /app/requests/<번호>."""
from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.utils import timezone

from core.models import EditRequest, Item
from qms.models import Characteristic, InspectionSpec


class EditRequestApiTest(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root', password='pw')
        self.user = User.objects.create_user('u', password='pw', is_staff=True)
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=['view_inspectionspec', 'view_item']))
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.spec = InspectionSpec.objects.create(item=self.item, inspection_type='INCOMING')
        Characteristic.objects.create(spec=self.spec, name='두께')
        self.spec.approved_by, self.spec.approved_at = self.root, timezone.now()
        self.spec.save()
        self.client.force_login(self.user)

    def post(self, url, data):
        return self.client.post(url, data, content_type='application/json')

    def ask(self, obj, kind, label='qms.inspectionspec'):
        return self.post(f'/api/records/{label}/{obj.pk}/request/', {'kind': kind, 'reason': '오타', 'password': 'pw'})

    def test_request_on_dedicated_page_record(self):
        r = self.ask(self.spec, 'EDIT')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['status'], EditRequest.PENDING)
        self.assertNotIn('edit_request_url', self.client.get(f'/api/qms/specs/{self.spec.pk}/').json())
        self.assertEqual(self.post('/api/records/auth.user/1/request/', {'kind': 'DELETE', 'reason': 'x', 'password': 'pw'}).status_code, 404)

    def test_superuser_blocked_delete_goes_to_new_page(self):
        self.client.force_login(self.root)
        r = self.ask(self.item, 'DELETE', 'core.item')  # 검사기준이 참조 중이라 바로 삭제되지 않는다
        self.assertEqual(r.status_code, 201, r.content)
        req = EditRequest.objects.get()
        self.assertEqual(r.json()['decide_url'], f'/app/requests/{req.pk}')

    def test_detail_and_decide_superuser_only(self):
        self.ask(self.spec, 'EDIT')
        req = EditRequest.objects.get()
        url = f'/api/edit-requests/{req.pk}/'
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.post(url + 'decide/', {'approve': True}).status_code, 403)
        self.client.force_login(self.root)
        d = self.client.get(url).json()
        self.assertEqual((d['kind'], d['status'], d['reason'], d['requested_by']), ('수정', 'PENDING', '오타', 'u'))
        self.assertEqual(d['target_url'], f'/app/specs/{self.spec.pk}')
        self.assertIn('품목', [row['label'] for row in d['rows']])
        self.assertEqual(self.post(url + 'decide/', {'approve': False, 'reject_reason': ''}).status_code, 400)  # 거절은 사유 필수
        r = self.post(url + 'decide/', {'approve': True})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['status'], EditRequest.APPROVED)
        self.assertEqual(self.post(url + 'decide/', {'approve': True}).status_code, 400)  # 이미 처리됨

    def test_delete_blockers_shown_and_reject(self):
        self.user.user_permissions.add(Permission.objects.get(codename='view_item'))
        self.ask(self.item, 'DELETE', 'core.item')
        req = EditRequest.objects.get()
        self.client.force_login(self.root)
        d = self.client.get(f'/api/edit-requests/{req.pk}/').json()
        self.assertTrue(any('검사기준' in b for b in d['blockers']))
        r = self.post(f'/api/edit-requests/{req.pk}/decide/', {'approve': False, 'reject_reason': '참조 중'})
        self.assertEqual(r.json()['status'], EditRequest.REJECTED)
        self.assertTrue(Item.objects.filter(pk=self.item.pk).exists())

    def test_todo_links_to_new_page(self):
        self.ask(self.spec, 'EDIT')
        req = EditRequest.objects.get()
        self.client.force_login(self.root)
        self.client.post('/api/qms/dashboard/', [{'key': 'edit_requests', 'size': 'wide'}], content_type='application/json')
        w = self.client.get('/api/qms/todo/').json()['widgets'][0]
        self.assertEqual(w['data']['rows'][0]['href'], f'/app/requests/{req.pk}')
