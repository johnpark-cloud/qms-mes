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
                resp = self.client.get('/brand/logo')
                self.assertEqual(resp.status_code, 200)
                resp.close()  # Windows는 열린 파일을 지울 수 없다
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


class NcReportTest(TestCase):
    def setUp(self):
        import tempfile
        from django.test import override_settings
        media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        media.enable()
        self.addCleanup(media.disable)
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='L1', item=self.item, supplier='A소재')
        self.lead = User.objects.create_user('lead', password='pw', is_staff=True)
        self.lead.groups.add(Group.objects.get(name='품질팀장'))

    def _form(self, nc, **extra):
        data = {'lot': nc.lot_id, 'description': nc.description, 'origin': 'INCOMING', 'detected_at_0': '2026-10-27',
                'detected_at_1': '09:00:00', 'defect_qty': 1, 'cost': 0, 'password': 'pw',
                'photos-TOTAL_FORMS': 0, 'photos-INITIAL_FORMS': 0, 'photos-MIN_NUM_FORMS': 0, 'photos-MAX_NUM_FORMS': 1000}
        return {**data, **extra}

    def test_number_format(self):
        a = Nonconformance.objects.create(lot=self.lot, description='a')
        b = Nonconformance.objects.create(lot=self.lot, description='b')
        self.assertRegex(a.number, r'^NC-\d{6}-\d{3}$')
        self.assertTrue(a.number.endswith('-001'))
        self.assertTrue(b.number.endswith('-002'))

    def test_photo_validation(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import validate_photo
        validate_photo(SimpleUploadedFile('x.heic', b'0' * 1024))
        with self.assertRaisesMessage(ValidationError, '사진'):
            validate_photo(SimpleUploadedFile('x.exe', b'0' * 1024))
        with self.assertRaisesMessage(ValidationError, '10MB'):
            validate_photo(SimpleUploadedFile('x.jpg', b'0' * (11 * 1024 * 1024)))

    def test_disposition_requires_completion(self):
        nc = Nonconformance.objects.create(lot=self.lot, description='이물')
        self.client.force_login(self.lead)
        url = f'/admin/core/nonconformance/{nc.pk}/change/'
        resp = self.client.post(url, self._form(nc, disposition='SCRAP'))
        self.assertContains(resp, '보완 필요')
        resp = self.client.post(url, self._form(nc, disposition='SCRAP', defect_type='이물', sorting_result='재고 전수 선별',
                                                contained_qty=10))
        self.assertEqual(resp.status_code, 302)
        nc.refresh_from_db()
        self.assertIsNotNone(nc.approved_at)
        self.assertEqual(nc.approved_by, self.lead)

    def test_after_approval_fields_editable(self):
        from django.utils import timezone
        nc = Nonconformance.objects.create(lot=self.lot, description='이물')
        Nonconformance.objects.filter(pk=nc.pk).update(disposition='SCRAP', approved_by=self.lead,
                                                         approved_at=timezone.now(), closed_at=timezone.now())
        eng = User.objects.create_user('eng', password='pw', is_staff=True)
        eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.client.force_login(eng)
        html = self.client.get(f'/admin/core/nonconformance/{nc.pk}/change/').content.decode()
        self.assertIn('name="cost"', html)
        self.assertNotIn('name="description"', html)

    def test_auto_origin(self):
        from decimal import Decimal
        from qms.models import Characteristic, CustomerClaim, Inspection, InspectionSpec, Measurement
        from qms.tests import approve
        spec = InspectionSpec.objects.create(item=self.item, inspection_type='INCOMING')
        thk = Characteristic.objects.create(spec=spec, name='두께', lsl=Decimal('9.5'), usl=Decimal('10.5'))
        approve(spec, self.lead)
        insp = Inspection.objects.create(lot=self.lot, spec=spec)
        Measurement.objects.create(inspection=insp, characteristic=thk, value=Decimal('11'))
        insp.finalize()
        self.assertEqual(insp.nonconformance.origin, 'INCOMING')
        claim = CustomerClaim.objects.create(number='CL-1', customer='B사', lot=self.lot, description='용량 부족')
        self.assertEqual(claim.nonconformance.origin, 'CLAIM')

    def test_delete_removes_photo_file(self):
        import os
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import NonconformancePhoto
        from .records import delete_record
        nc = Nonconformance.objects.create(lot=self.lot, description='x')
        photo = NonconformancePhoto.objects.create(nonconformance=nc, file=SimpleUploadedFile('a.jpg', b'0' * 10))
        path = photo.file.path
        self.assertTrue(os.path.exists(path))
        with self.captureOnCommitCallbacks(execute=True):
            delete_record(nc)
        self.assertFalse(os.path.exists(path))

    def test_print_page(self):
        nc = Nonconformance.objects.create(lot=self.lot, description='이물')
        self.client.force_login(self.lead)
        resp = self.client.get(f'/print/core/nonconformance/{nc.pk}/')
        self.assertContains(resp, '부적합 보고서')
        self.assertContains(resp, nc.number)

    def test_closed_nc_interlock_fields_locked_for_superuser(self):
        from .models import Hold
        nc = Nonconformance.objects.create(lot=self.lot, description='이물')
        nc.disposition, nc.approved_by = Nonconformance.SCRAP, self.lead
        nc.save()
        other = Lot.objects.create(number='L2', item=self.item)
        holds = list(Hold.objects.filter(nonconformance=nc).values_list('lot_id', 'released_at'))
        self.client.force_login(User.objects.create_superuser('root', password='pw'))
        resp = self.client.post(f'/admin/core/nonconformance/{nc.pk}/change/',
                                self._form(nc, lot=other.pk, disposition='REWORK', customer_approval_ref='X',
                                           detected_at_0='2020-01-01', description='관리자 수정'))
        self.assertEqual(resp.status_code, 302)
        nc.refresh_from_db()
        self.assertEqual((nc.lot_id, nc.disposition, nc.customer_approval_ref), (self.lot.pk, 'SCRAP', ''))
        self.assertNotEqual(nc.detected_at.year, 2020)
        self.assertEqual(nc.description, '관리자 수정')  # 그 밖의 칸은 관리자가 고칠 수 있다
        self.assertEqual(list(Hold.objects.filter(nonconformance=nc).values_list('lot_id', 'released_at')), holds)

    def test_photo_inline_rejects_bad_files_keeps_existing(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import NonconformancePhoto
        nc = Nonconformance.objects.create(lot=self.lot, description='이물')
        old = NonconformancePhoto.objects.create(nonconformance=nc, file=SimpleUploadedFile('old.jpg', b'0' * 10))
        self.client.force_login(self.lead)
        data = self._form(nc, **{'photos-TOTAL_FORMS': 3, 'photos-INITIAL_FORMS': 1, 'photos-0-id': old.pk,
                                 'photos-0-nonconformance': nc.pk, 'photos-0-caption': '',
                                 'photos-1-file': SimpleUploadedFile('x.exe', b'0' * 10),
                                 'photos-2-file': SimpleUploadedFile('x.jpg', b'0' * (11 * 1024 * 1024))})
        resp = self.client.post(f'/admin/core/nonconformance/{nc.pk}/change/', data)
        self.assertContains(resp, '사진 파일만 올릴 수 있습니다')
        self.assertContains(resp, '10MB 이하')
        self.assertEqual(list(nc.photos.values_list('pk', flat=True)), [old.pk])
        self.assertTrue(old.file.storage.exists(old.file.name))

    def test_stored_photo_missing_on_disk_still_valid(self):
        import os
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import NonconformancePhoto
        nc = Nonconformance.objects.create(lot=self.lot, description='이물')
        photo = NonconformancePhoto.objects.create(nonconformance=nc, file=SimpleUploadedFile('a.jpg', b'0'))
        os.remove(photo.file.path)
        photo.refresh_from_db()
        photo.full_clean()
        self.assertTrue(NonconformancePhoto.history.filter(id=photo.pk).exists())


class NcQuickTest(TestCase):
    def setUp(self):
        import tempfile
        from django.test import override_settings
        media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        media.enable()
        self.addCleanup(media.disable)
        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='L1', item=item)
        self.user = User.objects.create_user('insp', password='pw', is_staff=True)
        self.user.groups.add(Group.objects.get(name='검사원'))
        self.client.force_login(self.user)

    def _post(self, lot=' L1 \n', photos=(), **extra):
        return self.client.post('/nc/new/', {'lot': lot, 'origin': 'INCOMING', 'description': '찍힘', 'defect_qty': 2,
                                             'photos': list(photos), **extra})

    def test_quick_creates_nc_and_hold(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = self._post(photos=[SimpleUploadedFile('a.heic', b'0' * 100)])
        self.assertRedirects(r, '/trace/?lot=L1', fetch_redirect_response=False)
        nc = Nonconformance.objects.get()
        self.assertEqual(nc.detected_by, self.user)
        self.assertEqual(nc.holds.count(), 1)
        self.assertEqual(nc.photos.count(), 1)
        self.assertEqual(self._post(lot='l1').status_code, 302)  # 대소문자 차이

    def test_redirect_encodes_lot(self):
        Lot.objects.create(number='A+1&2#3', item=self.lot.item)
        r = self._post(lot='A+1&2#3')
        self.assertEqual(r['Location'], '/trace/?lot=A%2B1%262%233')

    def test_bad_photo_rolls_back(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = self._post(photos=[SimpleUploadedFile('a.jpg', b'0'), SimpleUploadedFile('x.exe', b'0')])
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '사진 파일만')
        self.assertEqual(Nonconformance.objects.count(), 0)

    def test_unknown_lot(self):
        r = self._post(lot='NOPE')
        self.assertContains(r, '등록되지 않은 LOT')
        self.assertEqual(Nonconformance.objects.count(), 0)

    def test_needs_permission(self):
        u = User.objects.create_user('nop', password='pw', is_staff=True)
        self.client.force_login(u)
        self.assertEqual(self.client.get('/nc/new/').status_code, 403)

    def test_prefill(self):
        self.assertContains(self.client.get('/nc/new/?lot=L1'), 'value="L1"')


class NcMailTest(TestCase):
    def setUp(self):
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        media.enable()
        self.addCleanup(media.disable)
        from django.utils import timezone
        from .models import NonconformancePhoto
        lot = Lot.objects.create(number='L1', item=Item.objects.create(code='R1', name='양극재', item_type=Item.RAW))
        self.nc = Nonconformance.objects.create(lot=lot, description='찍힘')
        for n in ('a.jpg', 'b.png'):
            NonconformancePhoto.objects.create(nonconformance=self.nc, file=SimpleUploadedFile(n, b'0' * 50))
        self.url = f'/nc/{self.nc.pk}/mail/'
        self.client.force_login(User.objects.create_user('u', password='pw', is_staff=True, is_superuser=True))
        self.approve = lambda: Nonconformance.objects.filter(pk=self.nc.pk).update(approved_at=timezone.now())

    def test_unapproved_404(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(f'/nc/{self.nc.pk}/photos.zip').status_code, 404)

    def test_mark_sent(self):
        self.approve()
        self.assertContains(self.client.get(self.url), '본문 복사')
        self.client.post(self.url, {'action': 'mark_sent'})
        self.nc.refresh_from_db()
        self.assertIsNotNone(self.nc.mailed_at)

    def test_send_with_attachments(self):
        from django.core import mail
        from django.test import override_settings
        self.approve()
        with override_settings(SMTP_ENABLED=True, MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}}):
            r = self.client.post(self.url, {'action': 'send', 'to': 'a@x.com, b@y.com'})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(len(mail.outbox), 1)
            self.assertEqual(len(mail.outbox[0].attachments), 2)
            self.assertEqual(mail.outbox[0].to, ['a@x.com', 'b@y.com'])
            self.assertIn(self.nc.number, mail.outbox[0].subject + mail.outbox[0].body)
            self.nc.refresh_from_db()
            self.assertIsNotNone(self.nc.mailed_at)

    def test_send_invalid_address(self):
        from django.core import mail
        from django.test import override_settings
        self.approve()
        with override_settings(SMTP_ENABLED=True):
            r = self.client.post(self.url, {'action': 'send', 'to': 'bad'})
        self.assertContains(r, '메일 주소')
        self.assertEqual(len(mail.outbox), 0)
        self.nc.refresh_from_db()
        self.assertIsNone(self.nc.mailed_at)

    def test_zip(self):
        import io, zipfile
        self.approve()
        r = self.client.get(f'/nc/{self.nc.pk}/photos.zip')
        names = zipfile.ZipFile(io.BytesIO(b''.join(r.streaming_content) if r.streaming else r.content)).namelist()
        self.assertEqual(names, [f'{self.nc.number}_1.jpg', f'{self.nc.number}_2.png'])

    def test_view_only_cannot_post(self):
        from django.contrib.auth.models import Permission
        self.approve()
        u = User.objects.create_user('v', password='pw', is_staff=True)
        u.user_permissions.add(Permission.objects.get(codename='view_nonconformance'))
        self.client.force_login(u)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.post(self.url, {'action': 'mark_sent'}).status_code, 403)
        self.nc.refresh_from_db()
        self.assertIsNone(self.nc.mailed_at)

    def test_zip_skips_missing_file(self):
        import io, os, zipfile
        self.approve()
        os.remove(self.nc.photos.first().file.path)
        r = self.client.get(f'/nc/{self.nc.pk}/photos.zip')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()), 1)

    def test_send_failure_keeps_mailed_at(self):
        from smtplib import SMTPException
        from unittest import mock
        from django.test import override_settings
        self.approve()
        with override_settings(SMTP_ENABLED=True), mock.patch('django.core.mail.EmailMessage.send', side_effect=SMTPException('x')):
            r = self.client.post(self.url, {'action': 'send', 'to': 'a@x.com'})
        self.assertContains(r, '메일을 보내지 못했습니다')
        self.nc.refresh_from_db()
        self.assertIsNone(self.nc.mailed_at)


class SearchTest(TestCase):
    def setUp(self):
        from .search import search
        self.search = search
        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        Lot.objects.create(number='A-2310', item=item)
        Lot.objects.create(number='A-23100', item=item)
        self.su = User.objects.create_superuser('su', password='pw')
        self.client.force_login(self.su)

    def test_exact_lot_first(self):
        self.assertEqual(self.search(self.su, ' a-2310 ')[0]['url'], '/trace/?lot=A-2310')

    def test_go_redirect(self):
        r = self.client.get('/search/?q=A-2310%0A&go=1')
        self.assertRedirects(r, '/trace/?lot=A-2310', fetch_redirect_response=False)

    def test_action_match(self):
        self.assertIn('부적합 등록', [r['label'] for r in self.search(self.su, '부적')])

    def test_permission_filter(self):
        insp = User.objects.create_user('i', is_staff=True)
        insp.groups.add(Group.objects.get(name='검사원'))
        from qms.models import Capa
        Capa.objects.create(title='시정', due_date='2026-12-01', owner=self.su)
        self.assertTrue(any(r['sub'] == 'CAPA' for r in self.search(self.su, 'CAPA-')))
        self.assertFalse(any(r['sub'] == 'CAPA' for r in self.search(insp, 'CAPA-')))

    def test_special_chars_lot_roundtrip(self):
        from urllib.parse import parse_qs, urlparse
        item = Item.objects.get(code='R1')
        Lot.objects.create(number='A+1&2#3', item=item)
        url = self.search(self.su, 'A+1&2#3')[0]['url']
        self.assertEqual(parse_qs(urlparse(url).query)['lot'], ['A+1&2#3'])
        from django.utils.http import urlencode
        r = self.client.get('/search/?' + urlencode({'q': 'A+1&2#3', 'go': 1}))
        self.assertEqual(r['Location'], url)
        self.assertContains(self.client.get(r['Location']), 'A+1&amp;2#3')

    def test_go_no_result_renders_page(self):
        r = self.client.get('/search/?q=ZZZZ&go=1')
        self.assertContains(r, '검색 결과가 없습니다')
        self.assertContains(r, 'qms-sidebar')
