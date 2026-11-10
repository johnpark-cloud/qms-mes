from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.admin import CodeValueAdmin, NumberRuleAdmin
from core.models import CodeValue, Item, NumberRule
from core.numbering import (NumberingError, candidates, check_rule, default_item_type, describe, describe_text,
                            fields, next_number, next_revision, next_serial, parse_pattern, rulebook)
from qms.apps import ensure_roles
from qms.models import Document


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


def R(name):
    return NumberRule.objects.get(name=name)


def item(code):
    return Item.objects.create(code=code, name='x', item_type='RAW')


def doc(number):
    return Document.objects.create(number=number, title='x')


class NumberingTest(TestCase):
    def test_next_serial(self):
        self.assertEqual(next_serial([], 'X', 3), '001')
        self.assertEqual(next_serial(['X001', 'X007'], 'X', 3), '008')
        with self.assertRaisesMessage(NumberingError, '일련번호가 다 찼습니다.'):
            next_serial(['X999'], 'X', 3)

    def test_serial_ignores_other_shapes(self):
        self.assertEqual(next_serial(['KEN-PQ-01-01', 'KEN-PQ-03'], 'KEN-PQ-', 2), '04')
        self.assertEqual(next_serial(['1VDC001A', '1VDC002'], '1VDC', 3), '003')
        self.assertEqual(next_serial(['1VDC1000'], '1VDC', 3), '001')
        self.assertEqual(next_serial(['1VDC١٢٣'], '1VDC', 3), '001')  # 아랍-인도 숫자는 세지 않는다

    def test_item_code(self):
        self.assertEqual(next_number(R('제품코드'), ['1', 'V', 'DC']), '1VDC001')
        item('1VDC005')
        self.assertEqual(next_number(R('제품코드'), ['1', 'V', 'DC']), '1VDC006')
        with self.assertRaises(NumberingError):  # 허용 값 아님
            next_number(R('제품코드'), ['3', 'V', 'DC'])
        self.assertEqual(default_item_type(R('제품코드'), ['2', 'V', 'DC']), 'SEMI')

    def test_parent_chain(self):
        self.assertEqual(next_number(R('원자재'), ['3', '1', '1', '1', '1']), '31111-00001')
        self.assertEqual(next_number(R('원자재'), ['3', '1', '3', '2', '0']), '31320-00001')
        with self.assertRaises(NumberingError):  # 312 아래 중분류 2 없음
            next_number(R('원자재'), ['3', '1', '2', '2', '0'])
        self.assertEqual(default_item_type(R('원자재'), ['3', '1', '1', '1', '1']), 'RAW')

    def test_doc_numbers(self):
        doc('KEN-PQ-01')
        doc('KEN-PQ-01-01')
        self.assertEqual(next_number(R('관리표준'), ['P', 'Q']), 'KEN-PQ-02')
        self.assertEqual(next_number(R('양식'), ['KEN-PQ-01']), 'KEN-PQ-01-02')
        with self.assertRaises(NumberingError):  # 없는 문서
            next_number(R('양식'), ['KEN-PQ-09'])
        item('1TDS001')
        self.assertEqual(next_number(R('기술문서'), ['1TDS001', 'BM']), '1TDS001-BM001')
        self.assertEqual(candidates(fields(R('양식'))[0]), ['KEN-PQ-01'])

    def test_drawing_part_counts_documents(self):
        item('1TRT038')
        item('1TRT038-AS101')
        doc('1TRT038-AS105')
        self.assertEqual(next_number(R('도면 품번'), ['1TRT038', 'AS']), '1TRT038-AS106')
        self.assertEqual(next_number(R('도면 품번'), ['1TRT038', 'DT']), '1TRT038-DT001')
        with self.assertRaises(NumberingError):
            next_number(R('도면 품번'), ['1TRT038', 'BM'])
        with self.assertRaises(NumberingError):  # 없는 제품
            next_number(R('도면 품번'), ['1TRT099', 'AS'])
        self.assertEqual(default_item_type(R('도면 품번'), ['1TRT038', 'DT']), 'RAW')
        self.assertEqual(default_item_type(R('도면 품번'), ['1TRT038', 'AS']), 'SEMI')

    def test_std_part(self):
        item('1TRT038')
        self.assertEqual(next_number(R('표준품'), ['3', '1TRT038']), '3TRT038-0001')
        item('3TRT038-0014')
        self.assertEqual(next_number(R('표준품'), ['3', '1TRT038']), '3TRT038-0015')
        self.assertEqual(describe('3TRT038-0001'), [('3', '원자재'), ('T', 'Train/Tram, 철차/트램용 축전지'),
                                                    ('RT', '현대로템'), ('038', '제품코드 일련번호'), ('0001', '일련번호')])
        self.assertEqual(describe('1TRT38-DT302'), [])

    def test_describe(self):
        self.assertEqual(describe('1VZZ001')[2], ('ZZ', '미등록'))
        self.assertEqual([n for _, n in describe('31111-00001')],
                         ['원자재', 'PBA, 회로자재', 'Capacitor', 'Chip', 'size 1005', '일련번호'])
        self.assertEqual(describe('1TDS001-BM001')[-2:], [('BM', 'BOM'), ('001', '일련번호')])
        self.assertEqual(describe('KEN-PQ-01-01'),
                         [('P', '절차서'), ('Q', '품질'), ('01', '관리표준 일련번호'), ('01', '일련번호')])
        self.assertEqual(describe('ABC'), [])
        d = describe('1TRT038-AS001', target='ITEM')  # 기술문서(sort 5)보다 품번 대상 도면 품번이 먼저
        self.assertEqual(d[-1], ('001', '일련번호'))
        self.assertEqual(d[-3], ('038', '제품코드 일련번호'))
        self.assertEqual(d[-2], ('AS', '기구 조립도면'))

    def test_inactive_rule_still_describes(self):
        CodeValue.objects.filter(group='customer', code='DC').update(active=False)
        with self.assertRaises(NumberingError):
            next_number(R('제품코드'), ['1', 'V', 'DC'])
        text = '1 완제품 · V Vehicle, 전기자동차(소형자동차 이상) · DC 디피코 · 001 일련번호'
        self.assertEqual(describe_text('1VDC001'), text)
        NumberRule.objects.filter(name='제품코드').update(active=False)
        with self.assertRaisesMessage(NumberingError, '사용 중지된 규칙입니다.'):
            next_number(R('제품코드'), ['1', 'V', 'DC'])
        self.assertEqual(describe_text('1VDC001'), text)

    def test_company_prefix_change(self):
        doc('KEN-PQ-01')
        r = NumberRule(name='관리표준2', target='DOC', pattern='ABC-{관리표준 문서구분}{부서}-{일련2}', sort=8)
        r.full_clean()
        r.save()
        NumberRule.objects.filter(name='관리표준').update(active=False)
        self.assertEqual(next_number(R('관리표준2'), ['P', 'Q']), 'ABC-PQ-01')
        with self.assertRaises(NumberingError):
            next_number(R('관리표준'), ['P', 'Q'])
        want = [('P', '절차서'), ('Q', '품질'), ('01', '일련번호')]
        self.assertEqual(describe('KEN-PQ-01'), want)
        self.assertEqual(describe('ABC-PQ-01'), want)
        NumberRule(name='양식2', target='DOC', pattern='{문서:관리표준2}-{일련2}').full_clean()

    def test_next_revision(self):
        self.assertEqual(next_revision([]), '0')
        self.assertEqual(next_revision(['0', '1']), '2')
        self.assertEqual(next_revision(['Rev.3', 'A', 'rev 1']), '4')
        self.assertEqual(next_revision(['A', 'B']), '0')
