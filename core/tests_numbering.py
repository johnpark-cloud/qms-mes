from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.admin import CodeValueAdmin, NumberRuleAdmin
from core.models import CodeValue, NumberRule
from core.numbering import NumberingError, check_rule, parse_pattern, rulebook
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


class NumberRuleTest(TestCase):
    def test_parse_pattern(self):
        t = parse_pattern('{품목분류:1,2}{산업분류}{고객사}{일련3}')
        self.assertEqual([x.kind for x in t], ['code', 'code', 'code', 'serial'])
        self.assertEqual((t[0].group, t[0].allowed, t[3].width), ('category', ('1', '2'), 3))
        t = parse_pattern('{품목분류:3}{품번:제품코드:뒤6}-{일련4}')
        self.assertEqual((t[1].kind, t[1].target, t[1].rule, t[1].tail), ('ref', 'ITEM', '제품코드', 6))
        self.assertEqual((t[2].kind, t[2].text), ('text', '-'))

    def test_seed_rules_valid(self):
        rows = list(NumberRule.objects.values_list('sort', 'name', 'target', 'pattern'))
        self.assertEqual(rows, [
            (1, '관리표준', 'DOC', 'KEN-{관리표준 문서구분}{부서}-{일련2}'),
            (2, '양식', 'DOC', '{문서:관리표준}-{일련2}'),
            (3, '제품코드', 'ITEM', '{품목분류:1,2}{산업분류}{고객사}{일련3}'),
            (4, '원자재', 'ITEM', '{품목분류:3}{자재분류}{자재 대분류}{자재 중분류}{자재 소분류}-{일련5}'),
            (5, '기술문서', 'DOC', '{품번:제품코드}-{설계자료분류}{일련3}'),
            (6, '도면 품번', 'ITEM', '{품번:제품코드}-{설계자료분류:AS,SU,DT,PA,BA}{일련3}'),
            (7, '표준품', 'ITEM', '{품목분류:3}{품번:제품코드:뒤6}-{일련4}')])
        for r in NumberRule.objects.all():
            r.full_clean()

    def test_rule_validation(self):
        bad = [('X', 'ITEM', 'X{일련3}-A'), ('X', 'ITEM', '{일련2}{일련2}'), ('X', 'DOC', 'KEN-{부서}'),
               ('X', 'ITEM', '{공장}{일련2}'), ('X', 'ITEM', '{품목분류:9}{일련2}'),
               ('X', 'ITEM', '{품번:없음}-{일련2}'), ('X', 'DOC', '{문서:제품코드}-{일련2}'),
               ('자기', 'ITEM', '{품번:자기}-{일련2}'), ('X', 'ITEM', '{품번:제품코드:뒤4}-{일련2}'),
               ('X', 'ITEM', '{자재 중분류}{일련2}'), ('X', 'ITEM', '{자재분류}{자재 중분류}{일련2}')]
        for args in bad:
            with self.subTest(args), self.assertRaises(NumberingError):
                check_rule(*args)
        rules = {**rulebook(), 'B': NumberRule(name='B', target='ITEM', pattern='{품번:A}-{일련2}')}
        with self.assertRaises(NumberingError):
            check_rule('A', 'ITEM', '{품번:B}-{일련2}', rules)
        check_rule('X', 'ITEM', '{품번:제품코드:뒤5}-{일련2}')
        check_rule('X', 'ITEM', '{품번:제품코드:뒤6}-{일련2}')
        check_rule('X', 'ITEM', '{자재분류}-{자재 대분류}{일련2}')  # 바로 앞 코드 토큰 기준(고정 글자는 건너뜀)
        rules = {**rulebook(), 'M': NumberRule(name='M', target='ITEM', pattern='{품번:없음}-{일련2}')}
        with self.assertRaises(NumberingError):  # 참조 규칙이 가리키는 규칙이 없어도 KeyError가 아니라 오류
            check_rule('X', 'ITEM', '{품번:M:뒤2}-{일련2}', rules)

    def test_pattern_locked(self):
        msg = '저장된 규칙의 이름·대상·틀은 바꿀 수 없습니다. 새 규칙을 만드세요.'
        r = NumberRule.objects.get(name='제품코드')
        r.pattern = '{품목분류:1}{일련3}'
        with self.assertRaises(ValidationError) as cm:
            r.full_clean()
        self.assertEqual(cm.exception.message_dict['pattern'], [msg])
        r = NumberRule.objects.get(name='제품코드')
        r.name = '제품코드2'
        with self.assertRaises(ValidationError) as cm:
            r.full_clean()
        self.assertEqual(cm.exception.message_dict['name'], [msg])
        r = NumberRule.objects.get(name='제품코드')
        r.active = False
        r.full_clean()

    def test_rule_admin(self):
        ensure_roles(None)
        eng = User.objects.create_user('eng', password='x', is_staff=True)
        eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.assertTrue(eng.has_perm('core.add_numberrule') and eng.has_perm('core.change_numberrule'))
        ma = NumberRuleAdmin(NumberRule, None)
        req = type('R', (), {'user': eng})()
        self.assertFalse(ma.has_delete_permission(req))
        obj = NumberRule.objects.get(name='제품코드')
        self.assertEqual(set(ma.get_readonly_fields(req, obj)), {'name', 'target', 'pattern'})
        self.assertFalse({'name', 'target', 'pattern'} & set(ma.get_readonly_fields(req)))
        self.client.force_login(eng)
        r = self.client.get(f'/admin/core/numberrule/{obj.pk}/change/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('name="pattern"', r.content.decode())
        r = self.client.get('/admin/core/numberrule/add/')
        self.assertEqual(r.status_code, 200)
        for f in ('name', 'target', 'pattern'):
            self.assertIn(f'name="{f}"', r.content.decode())
