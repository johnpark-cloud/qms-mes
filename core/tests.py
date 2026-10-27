from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from .models import Item, Lot, LotLink, Nonconformance, Process, RoutingStep, Shipment, WorkOrder, WorkResult


class RoutingTest(TestCase):
    def test_work_results_follow_routing(self):
        item = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        stack, weld = Process.objects.create(code='P10', name='적층'), Process.objects.create(code='P20', name='용접')
        s10 = RoutingStep.objects.create(item=item, seq=10, process=stack)
        s20 = RoutingStep.objects.create(item=item, seq=20, process=weld)
        wo = WorkOrder.objects.create(number='WO-1', item=item, planned_qty=100)
        with self.assertRaises(ValidationError):  # 적층 없이 용접
            WorkResult.objects.create(work_order=wo, step=s20, input_qty=10, good_qty=10)
        with self.assertRaises(ValidationError):  # 양품+불량 > 투입
            WorkResult.objects.create(work_order=wo, step=s10, input_qty=10, good_qty=9, defect_qty=2)
        WorkResult.objects.create(work_order=wo, step=s10, input_qty=60, good_qty=58, defect_qty=2)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrder.RUNNING)
        WorkResult.objects.create(work_order=wo, step=s20, input_qty=58, good_qty=50, defect_qty=8)
        self.assertEqual(wo.progress, 50.0)
        held = Lot.objects.create(number='L1', item=item)
        Nonconformance.objects.create(lot=held, description='x')
        with self.assertRaises(ValidationError):
            WorkResult.objects.create(work_order=wo, step=s20, lot=held, input_qty=1, good_qty=1)
        from qms.kpi import process_yield
        self.assertEqual([round(y['yield'], 2) for y in process_yield(1)], [round(58 / 60 * 100, 2), round(50 / 58 * 100, 2)])


class InterlockTest(TestCase):
    def setUp(self):
        raw = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        cell = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        self.raw = Lot.objects.create(number='RAW-1', item=raw)
        self.cell_a = Lot.objects.create(number='CELL-A', item=cell)
        self.cell_b = Lot.objects.create(number='CELL-B', item=cell)
        self.orphan = Lot.objects.create(number='CELL-X', item=cell)
        LotLink.objects.create(parent=self.raw, child=self.cell_a)
        LotLink.objects.create(parent=self.cell_a, child=self.cell_b)
        self.mrb = User.objects.create(username='mrb')
        self.mrb.groups.add(Group.objects.get(name='품질팀장'))

    def test_nc_holds_whole_lineage_and_blocks(self):
        Nonconformance.objects.create(lot=self.raw, description='이물')
        for lot in (self.raw, self.cell_a, self.cell_b):
            self.assertTrue(lot.on_hold)
        self.assertFalse(self.orphan.on_hold)
        with self.assertRaises(ValidationError):
            Shipment.objects.create(lot=self.cell_b, customer='A사', qty=1)
        with self.assertRaises(ValidationError):
            LotLink.objects.create(parent=self.cell_a, child=self.orphan)

    def test_release_rules(self):
        nc = Nonconformance.objects.create(lot=self.raw, description='이물')
        nc.disposition, nc.approved_by = Nonconformance.CONCESSION, User.objects.create(username='engineer')
        with self.assertRaises(ValidationError):  # 승인자가 품질팀장이 아님
            nc.save()
        nc.approved_by = self.mrb
        with self.assertRaises(ValidationError):  # 고객 승인 없음
            nc.save()
        nc.customer_approval_ref = 'CA-001'
        nc.save()
        self.assertFalse(self.cell_b.on_hold)
        Shipment.objects.create(lot=self.cell_b, customer='A사', qty=1)

    def test_scrap_keeps_hold(self):
        nc = Nonconformance.objects.create(lot=self.raw, description='이물')
        nc.disposition, nc.approved_by = Nonconformance.SCRAP, self.mrb
        nc.save()
        self.assertIsNotNone(nc.closed_at)
        self.assertTrue(self.cell_a.on_hold)

    def test_trace_page(self):
        Nonconformance.objects.create(lot=self.raw, description='이물')
        self.client.force_login(User.objects.create_superuser('admin'))
        html = self.client.get('/trace/', {'lot': 'CELL-A'}).content.decode()
        self.assertIn('RAW-1', html)
        self.assertIn('CELL-B', html)
        self.assertIn('보류 중', html)

    def test_cycle_and_gap(self):
        with self.assertRaises(ValidationError):
            LotLink.objects.create(parent=self.cell_b, child=self.raw)
        self.assertTrue(self.orphan.lineage_gap)
        self.assertFalse(self.raw.lineage_gap)


class ShellTest(TestCase):
    def test_logo_served_from_data_dir(self):
        import tempfile
        from pathlib import Path
        from django.test import override_settings
        self.client.force_login(User.objects.create_superuser('admin'))
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DATA_DIR=Path(tmp)):
                self.assertEqual(self.client.get('/brand/logo').status_code, 404)
                self.assertIn('QMS+MES', self.client.get('/todo/').content.decode())
                (Path(tmp) / 'brand').mkdir()
                (Path(tmp) / 'brand' / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\n')
                self.assertEqual(self.client.get('/brand/logo').status_code, 200)
                self.assertIn('src="/brand/logo"', self.client.get('/todo/').content.decode())

    def test_sidebar_filters_by_permission(self):
        def side(html):
            return html.split('id="qms-sidebar"')[1].split('</nav>')[0]
        insp = User.objects.create_user('insp', is_staff=True)
        insp.groups.add(Group.objects.get(name='검사원'))
        self.client.force_login(insp)
        html = side(self.client.get('/todo/').content.decode())
        self.assertIn('검사 입력', html)
        self.assertIn('전체 메뉴', html)
        self.assertIn('aria-current="page"', html)  # /todo/ = 내 할 일
        plain = User.objects.create_user('plain', is_staff=True)
        self.client.force_login(plain)
        html = side(self.client.get('/todo/').content.decode())
        self.assertNotIn('검사 입력', html)
        self.assertIn('LOT 이력', html)
        self.client.force_login(User.objects.create_superuser('root'))
        self.assertIn('검사 입력', side(self.client.get('/todo/').content.decode()))


class EditRequestTest(TestCase):
    def setUp(self):
        from django.utils import timezone
        from qms.models import InspectionSpec
        self.item = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        self.lot = Lot.objects.create(number='L1', item=self.item)
        self.eng = User.objects.create_user('eng', password='pw', is_staff=True)
        self.eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.root = User.objects.create_superuser('root', password='pw')
        self.spec = InspectionSpec.objects.create(item=self.item, inspection_type='PROCESS', approved_by=self.root,
                                                  approved_at=timezone.now())

    def _request(self, kind, obj, password='pw'):
        from .models import EditRequest
        self.client.force_login(self.eng)
        url = f'/request/{kind}/{obj._meta.app_label}/{obj._meta.model_name}/{obj.pk}/'
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {'reason': '잘못 등록', 'password': password})
        return EditRequest.objects.order_by('-pk').first()

    def test_wrong_password_creates_nothing(self):
        from .models import EditRequest
        nc = Nonconformance.objects.create(lot=self.lot, description='x')
        self._request('DELETE', nc, password='bad')
        self.assertEqual(EditRequest.objects.count(), 0)

    def test_delete_request_flow(self):
        from .models import EditRequest, Hold
        nc = Nonconformance.objects.create(lot=self.lot, description='x')
        req = self._request('DELETE', nc)
        self.assertEqual(req.status, EditRequest.PENDING)
        self.assertTrue(Nonconformance.objects.filter(pk=nc.pk).exists())
        with self.assertRaises(PermissionDenied):
            req.decide(self.eng, True)
        req.decide(self.root, True)
        self.assertEqual(req.status, EditRequest.APPROVED)
        self.assertFalse(Nonconformance.objects.filter(pk=nc.pk).exists())
        self.assertFalse(Hold.objects.filter(nonconformance_id=nc.pk).exists())
        self.assertTrue(Nonconformance.history.filter(id=nc.pk, history_type='-').exists())

    def test_other_nc_hold_survives(self):
        from .models import EditRequest, Hold
        a = Nonconformance.objects.create(lot=self.lot, description='a')
        b = Nonconformance.objects.create(lot=self.lot, description='b')
        EditRequest.objects.create(kind='DELETE', target=a, object_repr=str(a), reason='r',
                                   requested_by=self.eng).decide(self.root, True)
        self.assertTrue(Hold.objects.filter(nonconformance=b, released_at=None).exists())
        self.assertTrue(self.lot.on_hold)

    def test_protected_delete_stays_pending(self):
        from qms.models import Inspection
        from .models import EditRequest
        nc = Nonconformance.objects.create(lot=self.lot, description='x')
        Inspection.objects.create(lot=self.lot, spec=self.spec, nonconformance=nc)
        req = EditRequest.objects.create(kind='DELETE', target=nc, object_repr=str(nc), reason='r', requested_by=self.eng)
        self.client.force_login(self.root)
        self.assertContains(self.client.get(f'/request/{req.pk}/decide/'), '먼저 지워야 할 기록')
        with self.assertRaisesMessage(ValidationError, '먼저 지워야 할 기록'):
            req.decide(self.root, True)
        req.refresh_from_db()
        self.assertEqual(req.status, EditRequest.PENDING)
        self.assertTrue(Nonconformance.objects.filter(pk=nc.pk).exists())

    def test_edit_unlock_consumed_on_success_only(self):
        from .models import EditRequest
        req = self._request('EDIT', self.spec)
        self.assertEqual(req.status, EditRequest.PENDING)
        self.client.force_login(self.root)
        self.client.post(f'/request/{req.pk}/decide/', {'approve': '1'})
        req.refresh_from_db()
        self.assertEqual(req.status, EditRequest.APPROVED)
        self.client.force_login(self.eng)
        url = f'/admin/qms/inspectionspec/{self.spec.pk}/change/'
        data = {'item': self.item.pk, 'inspection_type': 'PROCESS', 'revision': 'x', 'sampling': '', 'note': '고침',
                'characteristics-TOTAL_FORMS': 0, 'characteristics-INITIAL_FORMS': 0,
                'characteristics-MIN_NUM_FORMS': 0, 'characteristics-MAX_NUM_FORMS': 1000}
        self.assertEqual(self.client.post(url, data).status_code, 200)  # 폼 오류
        req.refresh_from_db()
        self.assertEqual(req.status, EditRequest.APPROVED)
        self.assertEqual(self.client.post(url, {**data, 'revision': 2}).status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, EditRequest.USED)
        self.spec.refresh_from_db()
        self.assertEqual((self.spec.note, self.spec.revision), ('고침', 2))
        self.assertTrue(self.spec.is_approved)
        self.spec.note = '또'
        with self.assertRaisesMessage(ValidationError, '승인된 기록은 수정할 수 없습니다'):
            self.spec.save()

    def test_non_superuser_has_no_delete(self):
        self.client.force_login(self.eng)
        self.assertEqual(self.client.get(f'/admin/core/lot/{self.lot.pk}/delete/').status_code, 403)
        html = self.client.get('/admin/core/lot/').content.decode()
        self.assertNotIn('delete_selected', html)
        self.assertIn('삭제 요청', html)
        self.client.force_login(self.root)
        self.assertIn('delete_selected', self.client.get('/admin/core/lot/').content.decode())

    def _spec_post(self, user, name, extra=None):
        from qms.models import Characteristic
        c = Characteristic.objects.filter(spec=self.spec).first() or Characteristic.objects.bulk_create(
            [Characteristic(spec=self.spec, name='두께', lsl=1, usl=2)])[0]
        self.client.force_login(user)
        return self.client.post(f'/admin/qms/inspectionspec/{self.spec.pk}/change/', {
            'item': self.item.pk, 'inspection_type': 'PROCESS', 'revision': 1, 'sampling': '', 'note': '',
            'characteristics-TOTAL_FORMS': 1, 'characteristics-INITIAL_FORMS': 1,
            'characteristics-MIN_NUM_FORMS': 0, 'characteristics-MAX_NUM_FORMS': 1000,
            'characteristics-0-id': c.pk, 'characteristics-0-spec': self.spec.pk, 'characteristics-0-name': name,
            'characteristics-0-lsl': 1, 'characteristics-0-usl': 2, 'characteristics-0-unit': '',
            'characteristics-0-special': '', 'characteristics-0-plan_line': '', **(extra or {})}), c

    def test_unlocked_edit_reaches_inline_items(self):
        from .models import EditRequest
        resp, c = self._spec_post(self.eng, '두께2')  # 잠금 상태: 항목은 읽기 전용이라 무시되고 500이 아니다
        self.assertEqual(resp.status_code, 302)
        c.refresh_from_db()
        self.assertEqual(c.name, '두께')
        req = EditRequest.objects.create(kind='EDIT', target=self.spec, object_repr=str(self.spec), reason='r',
                                         requested_by=self.eng)
        req.decide(self.root, True)
        resp, c = self._spec_post(self.eng, '두께2')
        self.assertEqual(resp.status_code, 302)
        c.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual((c.name, req.status), ('두께2', EditRequest.USED))
        c.name = '또'
        with self.assertRaises(ValidationError):
            c.save()

    def test_superuser_edits_locked_directly(self):
        from qms.models import InspectionSpec
        from .models import EditRequest
        before = self.spec.history.count()
        resp, c = self._spec_post(self.root, '관리자 수정', {'note': '관리자'})
        self.assertEqual(resp.status_code, 302)
        self.spec.refresh_from_db()
        c.refresh_from_db()
        self.assertEqual((self.spec.note, c.name), ('관리자', '관리자 수정'))
        self.assertTrue(self.spec.is_approved)
        self.assertGreater(InspectionSpec.history.filter(id=self.spec.pk).count(), before)
        self.assertEqual(EditRequest.objects.count(), 0)
        html = self.client.get(f'/admin/qms/inspectionspec/{self.spec.pk}/change/').content.decode()
        self.assertNotIn('수정 요청', html)

    def test_superuser_admin_delete_removes_nc_holds(self):
        from .models import Hold
        nc = Nonconformance.objects.create(lot=self.lot, description='x')
        self.client.force_login(self.root)
        url = f'/admin/core/nonconformance/{nc.pk}/delete/'
        self.assertNotContains(self.client.get(url), '보류: ')
        self.assertEqual(self.client.post(url, {'post': 'yes'}).status_code, 302)
        self.assertFalse(Nonconformance.objects.filter(pk=nc.pk).exists())
        self.assertFalse(Hold.objects.filter(nonconformance_id=nc.pk).exists())

    def test_locked_save_without_unlock_says_locked(self):
        from qms.models import InspectionSpec
        before = InspectionSpec.history.filter(id=self.spec.pk).count()
        self._spec_post(self.eng, '두께2')
        html = self.client.get(f'/admin/qms/inspectionspec/{self.spec.pk}/change/').content.decode()
        self.assertIn('잠긴 기록입니다. 수정 요청 후 승인받아야 수정할 수 있습니다.', html)
        self.assertNotIn('성공적으로', html)
        self.assertEqual(InspectionSpec.history.filter(id=self.spec.pk).count(), before)

    def test_delete_selected_protected_and_holds(self):
        from unittest import mock
        from qms.models import Inspection
        from .models import Hold
        blocked = Nonconformance.objects.create(lot=self.lot, description='검사 참조')
        Inspection.objects.create(lot=self.lot, spec=self.spec, nonconformance=blocked)
        holds_only = Nonconformance.objects.create(lot=self.lot, description='보류만')
        self.client.force_login(self.root)
        url = '/admin/core/nonconformance/'
        post = {'action': 'delete_selected', 'post': 'yes'}
        # 확인 화면이 막는 경우와, 그 사이 참조가 생긴 경합(ProtectedError) 경우 모두 500이 아니다
        self.assertContains(self.client.post(url, {**post, '_selected_action': [blocked.pk]}), '검사:')
        with mock.patch('core.admin.blockers', return_value=[]):
            resp = self.client.post(url, {**post, '_selected_action': [blocked.pk]})
        self.assertEqual(resp.status_code, 302)
        html = self.client.get(url).content.decode()
        self.assertIn('먼저 지워야 할 기록', html)
        self.assertNotIn('성공적으로', html)
        self.assertTrue(Nonconformance.objects.filter(pk=blocked.pk).exists())
        self.assertEqual(self.client.post(url, {**post, '_selected_action': [holds_only.pk]}).status_code, 302)
        self.assertFalse(Nonconformance.objects.filter(pk=holds_only.pk).exists())
        self.assertFalse(Hold.objects.filter(nonconformance_id=holds_only.pk).exists())
        self.assertTrue(Hold.objects.filter(nonconformance=blocked).exists())
