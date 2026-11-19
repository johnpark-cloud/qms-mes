"""사이드바 묶음: 상위 메뉴만 보이고 하위 메뉴는 화면 위 탭(parent), 묶음 제목은 한눈에 보기(hub)."""
from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from core.nav import NAV, NO_HUB, SUB


def nav_of(client):
    return {g['group']: g for g in client.get('/api/auth/me/').json()['nav']}


class NavTreeTest(TestCase):
    def test_sub_menus_point_to_parents_in_same_group(self):
        for _, items in NAV:
            labels = [label for label, _, _ in items]
            for label in labels:
                if label in SUB:
                    self.assertIn(SUB[label], labels, label)
                    self.assertLess(labels.index(SUB[label]), labels.index(label), label)  # 상위 메뉴가 먼저
        self.assertTrue(set(NO_HUB) <= {name for name, _ in NAV})

    def test_me_nav_has_hub_flag_and_parent(self):
        admin = User.objects.create_superuser('root', password='pw')
        self.client.force_login(admin)
        nav = nav_of(self.client)
        self.assertFalse(nav['통합 업무 홈']['hub'])
        self.assertFalse(nav['분석 및 보고서']['hub'])
        self.assertTrue(nav['품질보증 및 개선']['hub'])
        items = {i['label']: i for g in nav.values() for i in g['items']}
        self.assertEqual(items['체크리스트·증적']['parent'], '심사 관리')
        self.assertEqual(items['심사 자료 출력']['parent'], '심사 관리')
        self.assertEqual(items['생산실적']['parent'], '작업지시')
        self.assertEqual(items['교정 이력']['href'], '/app/r/qms/gaugecalibration')
        self.assertNotIn('parent', items['심사 관리'])
        self.assertNotIn('한눈에 보기', items)
        for old in ('작업 실적', '변경 이력 조회', '모듈 켜기/끄기', '전체 메뉴', '사용자 정의 칸', '번호 규칙'):
            self.assertNotIn(old, items)

    def test_child_without_visible_parent_stands_alone(self):
        u = User.objects.create_user('viewer', password='pw', is_staff=True)
        u.user_permissions.add(Permission.objects.get(codename='view_inspection'))
        self.client.force_login(u)
        items = {i['label']: i for g in nav_of(self.client).values() for i in g['items']}
        self.assertNotIn('검사 입력', items)  # qms.add_inspection 없음
        self.assertNotIn('parent', items['검사 실적'])

    def test_role_sees_grouped_quality_menus(self):
        u = User.objects.create_user('lead', password='pw', is_staff=True)
        u.groups.add(Group.objects.get(name='품질팀장'))
        self.client.force_login(u)
        g = nav_of(self.client)['품질보증 및 개선']
        tops = [i['label'] for i in g['items'] if 'parent' not in i]
        self.assertEqual(tops[0], '부적합(NCR)')
        self.assertNotIn('보류', tops)
        self.assertIn('감사 추적', [i['label'] for x in nav_of(self.client).values() for i in x['items']])
