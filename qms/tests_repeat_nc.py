"""반복 부적합 → CAPA 제안(4단계 개선 1): 같은 품번·같은 부적합 유형이 90일 안에 CAPA 없이 3건이면 시정조치를 제안한다."""
import datetime
import json
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from core.models import Item, Lot, Nonconformance
from core.tests_modules import force_off

from .due import digest, due_items
from .models import Capa


class RepeatNcTest(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser('su', password='pw')
        self.item = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        self.other = Item.objects.create(code='C2', name='팩', item_type=Item.FINISHED)
        self.n = 0

    def nc(self, defect_type='치수', item=None, days_ago=0):
        self.n += 1
        lot = Lot.objects.create(number=f'L-{self.n}', item=item or self.item)
        return Nonconformance.objects.create(lot=lot, description='x', defect_type=defect_type,
                                             detected_at=timezone.now() - datetime.timedelta(days=days_ago, minutes=100 - self.n))

    def capa_from(self, nc):
        return Capa.objects.create(title='t', source='NC', source_type=ContentType.objects.get_for_model(Nonconformance),
                                   source_id=nc.pk, action='a', owner=self.su, due_date=timezone.localdate())

    def groups(self):
        return [(g['item'].code, g['defect_type'], len(g['ncs'])) for g in due_items()['repeat_ncs']]

    def test_three_same_item_and_type_suggest_capa(self):
        self.nc(), self.nc()
        self.nc(defect_type='이물'), self.nc(item=self.other), self.nc(defect_type=''), self.nc(days_ago=91)
        self.assertEqual(self.groups(), [])
        self.nc(defect_type=' 치수 ')  # 앞뒤 공백은 같은 유형
        self.assertEqual(self.groups(), [('C1', '치수', 3)])
        self.assertIn('반복 부적합 (CAPA 제안)', [t for t, _ in digest(due_items())])

    def test_capa_from_group_resets_count(self):
        a, b, c = self.nc(), self.nc(), self.nc()
        self.capa_from(b)
        self.assertEqual(self.groups(), [])  # CAPA를 만든 부적합까지는 그 CAPA가 다룬다
        self.nc()
        self.assertEqual(self.groups(), [])
        self.nc()
        self.assertEqual(self.groups(), [('C1', '치수', 3)])  # b 뒤의 c + 새 2건 = 3건이면 다시 제안
        self.assertEqual(due_items()['repeat_ncs'][0]['ncs'][0], c)

    def test_off_module_hides(self):
        self.nc(), self.nc(), self.nc()
        force_off('qms_capa')
        self.assertEqual(due_items()['repeat_ncs'], [])

    def test_record_detail_notice_and_todo_link(self):
        first, _, last = self.nc(), self.nc(), self.nc()
        lone = self.nc(defect_type='이물')
        self.client.force_login(self.su)
        d = self.client.get(f'/api/records/core.nonconformance/{first.pk}/').json()
        self.assertEqual(len(d['notices']), 1)
        notice = d['notices'][0]
        self.assertIn('3건', notice['message'])
        q = parse_qs(urlparse(notice['url']).query)
        self.assertEqual((q['source'], q['source_id']), (['NC'], [str(last.pk)]))  # 가장 최근 부적합을 출처로
        self.assertIn('반복 부적합', q['title'][0])
        self.assertEqual(self.client.get(f'/api/records/core.nonconformance/{lone.pk}/').json()['notices'], [])
        self.client.post('/api/qms/dashboard/', json.dumps([{'key': 'todo_lists', 'size': 'wide'}]), content_type='application/json')
        data = {w['key']: w['data'] for w in self.client.get('/api/qms/todo/').json()['widgets']}
        rows = data['todo_lists']['repeat_ncs']
        self.assertEqual([(r['label'], r['href']) for r in rows], [('C1 셀 · 치수', notice['url'])])
        self.assertEqual(rows[0]['count'], 3)
