from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from core.api.exceptions import handler
from core.models import Item
from core.rules import LOCKED_MSG, Locked


class AuthApiTest(TestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.qe = User.objects.create_user('qe', password='pw-qe-123', is_staff=True)
        self.qe.groups.add(Group.objects.get(name='품질팀장'))

    def _post(self, url, data=None):
        self.client.get('/api/auth/csrf/')
        return self.client.post(url, data, format='json', HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)

    def test_anonymous_forbidden(self):
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 403)

    def test_csrf_endpoint_is_open(self):
        r = self.client.get('/api/auth/csrf/')
        self.assertEqual((r.status_code, r.json()), (200, {}))
        self.assertIn('csrftoken', r.cookies)

    def test_login_wrong_password(self):
        r = self._post('/api/auth/login/', {'username': 'qe', 'password': 'bad'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['detail'], '아이디 또는 비밀번호가 맞지 않습니다.')

    def test_login_then_me(self):
        r = self._post('/api/auth/login/', {'username': 'qe', 'password': 'pw-qe-123'})
        self.assertEqual(r.status_code, 200)
        me = self.client.get('/api/auth/me/')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json(), r.json())
        body = me.json()
        self.assertEqual(body['username'], 'qe')
        self.assertTrue(body['is_approver'])
        self.assertEqual(body['groups'], ['품질팀장'])
        self.assertIn('core.view_lot', body['perms'])
        self.assertEqual(body['perms'], sorted(body['perms']))
        self.assertEqual(body['nav'][0]['group'], '통합 업무 홈')
        self.assertIn({'label': '내 할 일', 'href': '/todo/'}, body['nav'][0]['items'])

    def test_nav_filtered_by_permission(self):
        plain = User.objects.create_user('plain', password='pw-plain-123', is_staff=True)
        self.client.force_login(plain)
        body = self.client.get('/api/auth/me/').json()
        labels = [i['label'] for g in body['nav'] for i in g['items']]
        self.assertIn('내 할 일', labels)
        self.assertNotIn('LOT 이력 조회', labels)  # core.view_lot이 없다
        self.assertFalse(body['is_approver'])

    def test_login_without_csrf_rejected(self):
        r = self.client.post('/api/auth/login/', {'username': 'qe', 'password': 'pw-qe-123'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 403)

    def test_post_without_csrf_rejected(self):
        self.client.force_login(self.qe)
        r = self.client.post('/api/auth/logout/')
        self.assertEqual(r.status_code, 403)
        self.assertIn('detail', r.json())

    def test_logout(self):
        self._post('/api/auth/login/', {'username': 'qe', 'password': 'pw-qe-123'})
        self.assertEqual(self._post('/api/auth/logout/').status_code, 204)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 403)

    def test_non_staff_login_rejected(self):
        User.objects.create_user('office', password='pw-office-123', is_staff=False)
        r = self._post('/api/auth/login/', {'username': 'office', 'password': 'pw-office-123'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['detail'], '아이디 또는 비밀번호가 맞지 않습니다.')

    def test_schema_staff_only(self):
        self.assertEqual(self.client.get('/api/schema/').status_code, 403)
        self.client.force_login(self.qe)
        self.assertEqual(self.client.get('/api/schema/').status_code, 200)


class ExceptionHandlerTest(SimpleTestCase):
    def test_validation_error_with_fields(self):
        r = handler(ValidationError({'qty': ['수량 오류']}), {})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['fields'], {'qty': ['수량 오류']})
        self.assertEqual(r.data['detail'], '수량 오류')

    def test_validation_error_without_fields(self):
        r = handler(ValidationError('비밀번호가 맞지 않습니다.'), {})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data, {'detail': '비밀번호가 맞지 않습니다.', 'fields': {}})

    def test_locked_is_409(self):
        r = handler(Locked('아무 문구'), {})
        self.assertEqual((r.status_code, r.data), (409, {'detail': LOCKED_MSG}))

    def test_permission_denied_keeps_message(self):
        r = handler(PermissionDenied('품질팀장만 승인할 수 있습니다.'), {})
        self.assertEqual((r.status_code, r.data), (403, {'detail': '품질팀장만 승인할 수 있습니다.'}))

    def test_permission_denied_default_message(self):
        r = handler(PermissionDenied(), {})
        self.assertEqual((r.status_code, r.data), (403, {'detail': '권한이 없습니다.'}))

    def test_other_exceptions_use_drf_default(self):
        from rest_framework.exceptions import NotFound
        self.assertEqual(handler(NotFound(), {}).status_code, 404)
        self.assertIsNone(handler(RuntimeError('x'), {}))


class ProtectedErrorHandlerTest(TestCase):
    def test_protected_error_is_409_with_blockers(self):
        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        r = handler(ProtectedError('막힘', {item}), {})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['blockers'], [f'{Item._meta.verbose_name}: {item}'])
        self.assertTrue(r.data['detail'].startswith('먼저 지워야 할 기록: '))
