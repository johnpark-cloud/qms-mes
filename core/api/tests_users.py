"""조직도·사용자 새 화면(W5): 시스템 관리자만, 권한·비밀번호 변경은 관리자 비밀번호 재입력, 삭제 대신 비활성."""
from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.models import Department, Member
from core.nav import visible_nav

URL = '/api/core/org/'


class OrgApiTest(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root', password='pw')
        self.lead = User.objects.create_user('lead', password='pw', is_staff=True)
        self.lead.groups.add(Group.objects.get(name='품질팀장'))
        self.qa = Department.objects.create(code='QA', name='품질팀')
        self.qc = Department.objects.create(code='QC', name='검사파트', parent=self.qa)

    def post(self, data):
        return self.client.post(URL, data, content_type='application/json')

    def test_superuser_only(self):
        self.client.force_login(self.lead)  # 품질팀장도 못 연다
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.post({'action': 'move_user', 'id': self.lead.pk, 'dept': self.qa.pk}).status_code, 403)
        self.assertFalse(Member.objects.exists())

    def test_tree_payload(self):
        Member.objects.create(user=self.lead, department=self.qc, position='과장')
        self.client.force_login(self.root)
        d = self.client.get(URL).json()
        self.assertEqual({x['code'] for x in d['depts']}, {'QA', 'QC'})
        self.assertEqual(next(x for x in d['depts'] if x['code'] == 'QC')['parent'], self.qa.pk)
        lead = next(u for u in d['users'] if u['username'] == 'lead')
        self.assertEqual((lead['dept'], lead['position'], lead['groups']), (self.qc.pk, '과장', ['품질팀장']))
        self.assertIn('검사원', d['groups'])
        self.assertNotIn('password', lead)

    def test_move_user_and_dept(self):
        self.client.force_login(self.root)
        r = self.post({'action': 'move_user', 'id': self.lead.pk, 'dept': self.qc.pk})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Member.objects.get(user=self.lead).department, self.qc)
        self.assertEqual(self.post({'action': 'move_user', 'id': self.lead.pk, 'dept': None}).status_code, 200)
        self.assertIsNone(Member.objects.get(user=self.lead).department)
        # 부서를 자기 하위로 옮기면 순환 오류
        r = self.post({'action': 'move_dept', 'id': self.qa.pk, 'parent': self.qc.pk})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(Department.objects.get(pk=self.qa.pk).parent)
        qc2 = Department.objects.create(code='PD', name='생산팀')
        self.assertEqual(self.post({'action': 'move_dept', 'id': self.qc.pk, 'parent': qc2.pk}).status_code, 200)
        self.assertEqual(Department.objects.get(pk=self.qc.pk).parent, qc2)

    def test_create_user_needs_admin_password(self):
        self.client.force_login(self.root)
        new = {'action': 'save_user', 'username': 'kim', 'last_name': '김', 'first_name': '검사', 'email': '',
               'dept': self.qc.pk, 'position': '사원', 'groups': ['검사원'], 'password': 'Qms!2026long', 'active': True}
        r = self.post(new)
        self.assertEqual(r.status_code, 400)
        self.assertIn('admin_password', r.json()['fields'])
        r = self.post({**new, 'admin_password': 'wrong'})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.filter(username='kim').exists())
        r = self.post({**new, 'admin_password': 'pw'})
        self.assertEqual(r.status_code, 200, r.content)
        kim = User.objects.get(username='kim')
        self.assertTrue(kim.is_staff and kim.is_active and kim.check_password('Qms!2026long'))
        self.assertFalse(kim.is_superuser)
        self.assertEqual(list(kim.groups.values_list('name', flat=True)), ['검사원'])
        self.assertEqual((kim.member.department, kim.member.position), (self.qc, '사원'))

    def test_weak_password_and_duplicate_username(self):
        self.client.force_login(self.root)
        base = {'action': 'save_user', 'last_name': '', 'first_name': '', 'groups': [], 'active': True, 'admin_password': 'pw'}
        r = self.post({**base, 'username': 'kim', 'password': '1234'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('password', r.json()['fields'])
        r = self.post({**base, 'username': 'lead', 'password': 'Qms!2026long'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('username', r.json()['fields'])

    def test_edit_info_without_password_but_roles_need_it(self):
        self.client.force_login(self.root)
        info = {'action': 'save_user', 'id': self.lead.pk, 'username': 'lead', 'last_name': '이', 'first_name': '팀장',
                'email': 'lead@example.com', 'dept': self.qa.pk, 'position': '부장', 'title': '팀장', 'phone': '201',
                'employee_no': 'E001', 'groups': ['품질팀장'], 'active': True}
        r = self.post(info)  # 역할이 그대로면 재입력 없이 저장
        self.assertEqual(r.status_code, 200, r.content)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.last_name, self.lead.email, self.lead.member.title), ('이', 'lead@example.com', '팀장'))
        r = self.post({**info, 'groups': ['품질팀장', '검사원']})  # 역할 변경은 재입력
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.lead.groups.count(), 1)
        r = self.post({**info, 'admin': True})  # 관리자 권한도
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.post({**info, 'admin': True, 'admin_password': 'pw'}).status_code, 200)
        self.lead.refresh_from_db()
        self.assertTrue(self.lead.is_superuser)

    def test_deactivate_not_delete_and_no_self_lockout(self):
        self.client.force_login(self.root)
        info = {'action': 'save_user', 'id': self.lead.pk, 'username': 'lead', 'groups': ['품질팀장'], 'active': False}
        self.assertEqual(self.post(info).status_code, 200)
        self.lead.refresh_from_db()
        self.assertFalse(self.lead.is_active)
        self.assertTrue(User.objects.filter(pk=self.lead.pk).exists())
        me = {'action': 'save_user', 'id': self.root.pk, 'username': 'root', 'groups': [], 'admin_password': 'pw'}
        self.assertEqual(self.post({**me, 'active': False, 'admin': True}).status_code, 400)  # 자기 계정 비활성 금지
        self.assertEqual(self.post({**me, 'active': True, 'admin': False}).status_code, 400)  # 자기 관리자 권한 해제 금지
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active and self.root.is_superuser)

    def test_reset_password(self):
        self.client.force_login(self.root)
        r = self.post({'action': 'reset_password', 'id': self.lead.pk, 'password': 'New!Pass2026'})
        self.assertEqual(r.status_code, 400)
        r = self.post({'action': 'reset_password', 'id': self.lead.pk, 'password': 'New!Pass2026', 'admin_password': 'pw'})
        self.assertEqual(r.status_code, 200, r.content)
        self.lead.refresh_from_db()
        self.assertTrue(self.lead.check_password('New!Pass2026'))

    def test_member_history_kept(self):
        self.client.force_login(self.root)
        self.post({'action': 'move_user', 'id': self.lead.pk, 'dept': self.qa.pk})
        self.post({'action': 'move_user', 'id': self.lead.pk, 'dept': self.qc.pk})
        self.assertEqual(Member.objects.get(user=self.lead).history.count(), 2)

    def test_menu_points_to_new_screen(self):
        links = dict(link for _, items in visible_nav(self.root) for link in items)
        self.assertEqual(links['사용자·조직도'], '/admin/auth/user/')
        from core.nav import app_href
        self.assertEqual(app_href('/admin/auth/user/'), '/app/users')
        self.assertEqual(app_href(f'/admin/auth/user/{self.lead.pk}/change/'), f'/app/users/{self.lead.pk}')
