from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.admin import CodeValueAdmin
from core.models import CodeValue
from qms.apps import ensure_roles


def cv(**kw):
    return CodeValue(**{'name': 'x', **kw})


class CodeValueTest(TestCase):
    def assertFieldError(self, obj, field):
        with self.assertRaises(ValidationError) as cm:
            obj.full_clean()
        self.assertIn(field, cm.exception.message_dict)

    def test_format_checked(self):
        self.assertFieldError(cv(group='customer', code='D'), 'code')
        self.assertFieldError(cv(group='industry', code='VV'), 'code')
        self.assertFieldError(cv(group='category', code='A', item_type='FIN'), 'code')

    def test_parent_rules(self):
        mat = CodeValue.objects.get(group='material', code='1')
        self.assertFieldError(cv(group='mat_m', code='9', parent=mat), 'parent')
        self.assertFieldError(cv(group='mat_l', code='9'), 'parent')
        self.assertFieldError(cv(group='industry', code='Z', parent=mat), 'parent')

    def test_item_type_rules(self):
        self.assertFieldError(cv(group='category', code='9', item_type=''), 'item_type')
        self.assertFieldError(cv(group='industry', code='Z', item_type='FIN'), 'item_type')
        cv(group='design', code='ZZ', item_type='').full_clean()
        cv(group='design', code='ZY', item_type='RAW').full_clean()

    def test_unique_within_parent(self):
        m1 = CodeValue.objects.get(group='material', code='1')
        m2 = CodeValue.objects.get(group='material', code='2')
        CodeValue.objects.create(group='mat_l', code='9', name='a', parent=m1)
        self.assertRaises(ValidationError, cv(group='mat_l', code='9', parent=m1).full_clean)
        cv(group='mat_l', code='9', parent=m2).full_clean()

    def test_seed_rows_valid(self):
        counts = {'category': 3, 'industry': 13, 'customer': 32, 'material': 7, 'doc_kind': 4, 'dept': 7, 'design': 34}
        for g, n in counts.items():
            self.assertEqual(CodeValue.objects.filter(group=g).count(), n, g)
        for row in CodeValue.objects.all():
            row.full_clean()
        types = dict(CodeValue.objects.filter(group='category').values_list('code', 'item_type'))
        self.assertEqual(types, {'1': 'FIN', '2': 'SEMI', '3': 'RAW'})
        d = dict(CodeValue.objects.filter(group='design').values_list('code', 'item_type'))
        self.assertEqual([d[c] for c in ('AS', 'SU', 'BA', 'DT', 'PA', 'BM')], ['SEMI'] * 3 + ['RAW'] * 2 + [''])
        a = CodeValue.objects.get(group='material', code='1')
        b = CodeValue.objects.get(group='mat_l', parent=a, code='1')
        c = CodeValue.objects.get(group='mat_m', parent=b, code='1')
        self.assertEqual(CodeValue.objects.get(group='mat_s', parent=c, code='1').name, 'size 1005')

    def test_admin_delete_superuser_only(self):
        ensure_roles(None)
        eng = User.objects.create_user('eng', password='x', is_staff=True)
        eng.groups.add(Group.objects.get(name='품질엔지니어'))
        insp = User.objects.create_user('insp', password='x', is_staff=True)
        insp.groups.add(Group.objects.get(name='검사원'))
        self.assertTrue(eng.has_perm('core.add_codevalue') and eng.has_perm('core.change_codevalue'))
        self.assertFalse(insp.has_perm('core.view_codevalue'))
        self.client.force_login(eng)
        self.assertEqual(self.client.get('/admin/core/codevalue/').status_code, 200)
        req = type('R', (), {'user': eng})()
        self.assertFalse(CodeValueAdmin(CodeValue, None).has_delete_permission(req))
