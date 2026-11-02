from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Item, Lot, Nonconformance, WorkOrder
from qms.models import Capa
from qms.overview import sections


class OverviewApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.qe = User.objects.create_user('qe', password='x', is_staff=True)
        self.qe.groups.add(Group.objects.get(name='품질엔지니어'))
        self.insp = User.objects.create_user('insp', password='x', is_staff=True)
        self.insp.groups.add(Group.objects.get(name='검사원'))
        item = Item.objects.create(code='P1', name='부품', item_type=Item.RAW)
        lot = Lot.objects.create(number='L-1', item=item, supplier='가협력')
        WorkOrder.objects.create(number='WO-1', item=item, planned_qty=10, status=WorkOrder.RUNNING, due_date=timezone.localdate())
        Nonconformance.objects.create(lot=lot, description='찍힘')  # 보류도 함께 생긴다
        Capa.objects.create(title='재발 방지', source='OTHER', action='x', owner=self.qe, due_date=timezone.localdate())

    def test_same_numbers_as_page(self):
        self.client.force_login(self.qe)
        api = self.client.get('/api/qms/overview/').json()
        page = sections(self.qe)
        self.assertTrue(any(c['title'] == '진행 중 CAPA' for _, cards in page for c in cards))
        self.assertEqual([(s['name'], [(c['title'], c['value']) for c in s['cards']]) for s in api['sections']],
                         [(name, [(c['title'], c['value']) for c in cards]) for name, cards in page])

    def test_inspector_has_no_capa_card(self):
        self.client.force_login(self.insp)
        titles = [c['title'] for s in self.client.get('/api/qms/overview/').json()['sections'] for c in s['cards']]
        self.assertIn('열린 부적합', titles)
        self.assertNotIn('진행 중 CAPA', titles)

    def test_anonymous_forbidden(self):
        self.assertEqual(self.client.get('/api/qms/overview/').status_code, 403)
