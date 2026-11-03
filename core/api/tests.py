from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient, APIRequestFactory

from core.api.exceptions import CSRF_MSG, handler
from core.api.permissions import ModelPerms
from core.models import Item, Lot
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
        self.assertIn('detail', r.json())
        self.assertEqual(r.json()['detail'], CSRF_MSG)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 403)

    def test_login_non_dict_body_is_400(self):
        r = self._post('/api/auth/login/', [])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['detail'], '아이디 또는 비밀번호가 맞지 않습니다.')

    def test_post_without_csrf_rejected(self):
        self.client.force_login(self.qe)
        r = self.client.post('/api/auth/logout/')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['detail'], CSRF_MSG)

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


class ModelPermsTest(TestCase):
    class FakeView:
        queryset = Item.objects.all()

    def _allowed(self, user, method):
        request = APIRequestFactory().generic(method, '/x/')
        request.user = user
        return ModelPerms().has_permission(request, self.FakeView())

    def _user(self, name, perm=None, **kw):
        user = User.objects.create_user(name, password='pw-x-123', **kw)
        if perm:
            user.user_permissions.add(Permission.objects.get(content_type__app_label='core', codename=perm))
        return user

    def test_get_needs_view_perm(self):
        self.assertFalse(self._allowed(self._user('a', is_staff=True), 'GET'))
        self.assertTrue(self._allowed(self._user('b', 'view_item', is_staff=True), 'GET'))

    def test_non_staff_with_perm_rejected(self):
        self.assertFalse(self._allowed(self._user('c', 'view_item'), 'GET'))

    def test_delete_superuser_only(self):
        staff = self._user('d', 'delete_item', is_staff=True)
        self.assertFalse(self._allowed(staff, 'DELETE'))
        root = User.objects.create_superuser('root', password='pw-root-123')
        self.assertTrue(self._allowed(root, 'DELETE'))


class SpaTest(SimpleTestCase):
    def test_app_serves_index(self):
        r = self.client.get('/app/overview')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '<div id="root">')
        self.assertContains(r, '/static/app/assets/')


class CommonApiTest(TestCase):
    def setUp(self):
        from qms.models import InspectionSpec
        from core.rules import request_revision_log

        def mk(name, group, pw='x'):
            u = User.objects.create_user(name, password=pw, is_staff=True)
            u.groups.add(Group.objects.get(name=group))
            return u
        self.eng, self.lead = mk('eng', '품질엔지니어'), mk('lead', '품질팀장', 'pw-lead-123')
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        Lot.objects.create(number='RAW-2611-001', item=self.item, supplier='가협력')
        self.spec = InspectionSpec.objects.create(item=self.item, inspection_type='INCOMING')
        self.log = request_revision_log(self.spec, self.eng, 'Rev.1', '최초 제정', '신규')

    def c(self, user):
        c = APIClient()
        c.force_login(user)
        return c

    def test_search_partial_lot(self):
        r = self.c(self.eng).get('/api/search/?q=2611')
        self.assertTrue(any(x['label'] == 'RAW-2611-001' and '/trace/?lot=' in x['url'] for x in r.json()['results']))

    def test_items_lookup(self):
        self.assertEqual(self.c(self.eng).get('/api/items/?q=양극').json()[0]['code'], 'R1')

    def test_items_needs_view_perm(self):
        plain = User.objects.create_user('plain', password='x', is_staff=True)
        self.assertEqual(self.c(plain).get('/api/items/?q=양극').status_code, 403)

    def test_audit_log_approver_only_and_no_private(self):
        r = self.c(self.eng).get('/api/audit-log/')
        self.assertEqual((r.status_code, r.json()['detail']), (403, '품질팀장만 볼 수 있습니다.'))
        keys = {m['key'] for m in self.c(self.lead).get('/api/audit-log/').json()['models']}
        self.assertIn('qms.inspectionspec', keys)
        self.assertFalse(any(k.startswith(('personal.', 'auth.')) for k in keys))
        self.assertEqual(self.c(self.lead).get('/api/audit-log/?model=personal.leaveprofile').status_code, 404)
        self.assertEqual(self.c(self.lead).get('/api/audit-log/?model=nonsense').status_code, 404)
        self.assertEqual(self.c(self.eng).get('/api/audit-log/?model=qms.inspectionspec').status_code, 403)

    def test_audit_log_huge_page_ok(self):
        r = self.c(self.lead).get('/api/audit-log/?model=qms.inspectionspec&page=' + '9' * 30)
        self.assertEqual(r.status_code, 200)

    def test_audit_log_bad_params_400(self):
        for q in ('id=abc', 'page=x'):
            self.assertEqual(self.c(self.lead).get(f'/api/audit-log/?model=qms.inspectionspec&{q}').status_code, 400)

    def test_audit_log_rows_show_changes(self):
        self.spec.note = '바꿈'
        self.spec.save()
        r = self.c(self.lead).get(f'/api/audit-log/?model=qms.inspectionspec&id={self.spec.pk}').json()
        self.assertEqual(r['results'][0]['type'], '변경')
        self.assertEqual(r['results'][-1]['type'], '생성')
        self.assertIn({'field': '비고', 'old': '', 'new': '바꿈'}, r['results'][0]['changes'])

    def test_confirm_revision_log_endpoint(self):
        r = self.c(self.lead).post(f'/api/revision-log/{self.log.pk}/approve/', {'password': 'pw-lead-123'}, format='json')
        self.assertEqual(r.json()['status'], 'CONFIRMED')
        r = self.c(self.lead).post(f'/api/revision-log/{self.log.pk}/approve/', {'password': 'pw-lead-123'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_confirm_revision_log_denied_and_wrong_password(self):
        url = f'/api/revision-log/{self.log.pk}/approve/'
        self.assertEqual(self.c(self.eng).post(url, {'password': 'x'}, format='json').status_code, 403)
        self.assertEqual(self.c(self.lead).post(url, {'password': 'bad'}, format='json').status_code, 400)
        self.assertEqual(self.c(self.lead).post('/api/revision-log/99999/approve/', {}, format='json').status_code, 404)
