from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import EditRequest, Item, Lot, Nonconformance, Process
from core.rules import Locked, approve, child_editable, delete_as, dispose_nc, nc_locked_fields, save_with_lock
from qms.models import Characteristic, ChangeRequest, InspectionSpec


class LockRulesTest(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user('boss', password='pw-boss-123', is_staff=True)
        self.boss.groups.add(Group.objects.get(name='품질팀장'))
        self.eng = User.objects.create_user('eng', password='pw-eng-123', is_staff=True)
        self.eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.root = User.objects.create_superuser('root', password='pw-root-123')
        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='RAW-1', item=item)
        self.spec = InspectionSpec.objects.create(item=item, inspection_type=InspectionSpec.INCOMING)
        Characteristic.objects.create(spec=self.spec, name='두께', lsl=Decimal('9.5'), usl=Decimal('10.5'))
        self.spec.approved_by, self.spec.approved_at = self.boss, timezone.now()
        self.spec.save()

    def test_locked_record_rejects_save(self):
        self.spec.note = '바꿈'
        with self.assertRaises(Locked):
            save_with_lock(self.spec, self.eng)

    def test_edit_request_unlocks_once(self):
        req = EditRequest.objects.create(kind=EditRequest.EDIT, target=self.spec, object_repr='x', reason='r',
                                         requested_by=self.eng, status=EditRequest.APPROVED)
        self.spec.note = '1차'
        save_with_lock(self.spec, self.eng)
        req.refresh_from_db()
        self.assertEqual(req.status, EditRequest.USED)
        self.spec.note = '2차'
        with self.assertRaises(Locked):
            save_with_lock(self.spec, self.eng)

    def test_child_failure_rolls_back_and_keeps_request(self):
        req = EditRequest.objects.create(kind=EditRequest.EDIT, target=self.spec, object_repr='x', reason='r',
                                         requested_by=self.eng, status=EditRequest.APPROVED)
        ch = self.spec.characteristics.first()
        self.spec.note = '롤백'
        with mock.patch.object(Characteristic, 'save', side_effect=ValidationError('항목 오류')):
            with self.assertRaises(ValidationError) as cm:
                save_with_lock(self.spec, self.eng, children=[ch])
        self.assertNotIsInstance(cm.exception, Locked)
        req.refresh_from_db()
        self.assertEqual(req.status, EditRequest.APPROVED)
        self.assertEqual(InspectionSpec.objects.get(pk=self.spec.pk).note, '')

    def test_superuser_edits_locked(self):
        self.spec.note = '관리자'
        save_with_lock(self.spec, self.root)
        self.spec.refresh_from_db()
        self.assertEqual(self.spec.note, '관리자')

    def test_children_follow_parent_unlock(self):
        ch = self.spec.characteristics.first()
        ch.usl = ch.usl + 1
        with self.assertRaises(Locked):
            save_with_lock(self.spec, self.eng, children=[ch])
        save_with_lock(self.spec, self.root, children=[ch])
        ch.refresh_from_db()
        self.assertEqual(ch.usl, Decimal('11.5'))

    def test_delete_only_superuser(self):
        with self.assertRaises(PermissionDenied):
            delete_as(self.spec, self.boss)
        self.assertTrue(InspectionSpec.objects.filter(pk=self.spec.pk).exists())

    def test_child_editable(self):
        self.assertFalse(child_editable(self.spec, self.eng))
        self.assertTrue(child_editable(self.spec, self.root))
        nc = Nonconformance.objects.create(lot=self.lot, description='x')
        self.assertTrue(child_editable(nc, self.eng))


class DisposeRulesTest(TestCase):
    def setUp(self):
        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='RAW-1', item=item)
        self.mrb = User.objects.create_user('mrb', password='pw')
        self.mrb.groups.add(Group.objects.get(name='품질팀장'))
        self.eng = User.objects.create_user('eng', password='pw-eng-123', is_staff=True)
        self.eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.root = User.objects.create_superuser('root', password='pw-root-123')
        self.nc = Nonconformance.objects.create(lot=self.lot, description='이물', defect_type='이물',
                                                process=Process.objects.create(code='P10', name='적층'),
                                                sorting_result='전수 선별', contained_qty=Decimal('5'))

    def test_wrong_password(self):
        with self.assertRaisesMessage(ValidationError, 'MRB 승인 비밀번호가 맞지 않습니다.'):
            dispose_nc(self.nc, self.mrb, 'bad', {'disposition': Nonconformance.SCRAP})
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.disposition, '')

    def test_missing_fields_block(self):
        self.nc.sorting_result = ''
        with self.assertRaisesMessage(ValidationError, '보완 필요:'):
            dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP})

    def test_dispose_ok_keeps_hold_for_scrap(self):
        dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP})
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.approved_by, self.mrb)
        self.assertTrue(self.lot.on_hold)

    def test_other_fields_rejected(self):
        with self.assertRaises(ValidationError):
            dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP, 'lot': 99})

    def test_closed_nc_locked_fields(self):
        dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.SCRAP})
        self.nc.refresh_from_db()
        self.assertIn('lot', nc_locked_fields(self.nc, self.eng))
        self.assertNotIn('cost', nc_locked_fields(self.nc, self.eng))
        self.assertEqual(sorted(nc_locked_fields(self.nc, self.root)), sorted(Nonconformance.INTERLOCK))
        with self.assertRaises(Locked):
            dispose_nc(self.nc, self.mrb, 'pw', {'disposition': Nonconformance.REWORK})

    def test_empty_disposition_rejected_without_signature(self):
        for data in ({}, {'cost': 1}, {'disposition': ''}):
            with self.subTest(data=data):
                with self.assertRaisesMessage(ValidationError, '처분을 선택하세요.'):
                    dispose_nc(self.nc, self.mrb, 'pw', data)
                self.assertIsNone(self.nc.approved_by)
                self.nc.refresh_from_db()
                self.assertIsNone(self.nc.approved_by)
                self.assertIsNone(self.nc.approved_at)

    def test_non_approver_rejected(self):
        with self.assertRaises(ValidationError):
            dispose_nc(self.nc, self.eng, 'pw-eng-123', {'disposition': Nonconformance.SCRAP})
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.disposition, '')
        self.assertIsNone(self.nc.approved_by)
        self.assertIsNone(self.nc.closed_at)


class ApproveRulesTest(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user('boss', password='pw')
        self.boss.groups.add(Group.objects.get(name='품질팀장'))
        self.eng = User.objects.create_user('eng', password='pw-eng-123', is_staff=True)
        self.eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.spec = InspectionSpec.objects.create(item=self.item, inspection_type=InspectionSpec.INCOMING)
        Characteristic.objects.create(spec=self.spec, name='두께', lsl=Decimal('9.5'), usl=Decimal('10.5'))

    def test_non_approver(self):
        with self.assertRaisesMessage(PermissionDenied, '품질팀장만 승인할 수 있습니다.'):
            approve(self.spec, self.eng, 'pw')

    def test_wrong_password(self):
        with self.assertRaisesMessage(ValidationError, '비밀번호가 맞지 않습니다.'):
            approve(self.spec, self.boss, 'bad')
        self.assertIsNone(self.spec.approved_at)

    def test_model_rule_restores_fields(self):
        cr = ChangeRequest.objects.create(number='CR-1', item=self.item, category='MATERIAL',
                                          description='x', customer_notice=True)
        with self.assertRaises(ValidationError):
            approve(cr, self.boss, 'pw')
        self.assertIsNone(cr.approved_at)
        self.assertIsNone(cr.approved_by)

    def test_ok_then_already(self):
        approve(self.spec, self.boss, 'pw')
        self.spec.refresh_from_db()
        self.assertEqual(self.spec.approved_by, self.boss)
        with self.assertRaisesMessage(ValidationError, '이미 승인된 기록입니다.'):
            approve(self.spec, self.boss, 'pw')


class NcModelLockTest(TestCase):
    """종결된 부적합은 모델 save가 막는다. 인터록 칸은 누구도, 나머지는 수정 승인·관리자만 바꾼다(AFTER_APPROVAL 칸 제외)."""

    def setUp(self):
        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='RAW-1', item=item)
        self.other = Lot.objects.create(number='RAW-2', item=item)
        mrb = User.objects.create_user('mrb', password='pw')
        mrb.groups.add(Group.objects.get(name='품질팀장'))
        self.eng = User.objects.create_user('eng', password='pw-eng-123', is_staff=True)
        self.root = User.objects.create_superuser('root', password='pw-root-123')
        self.nc = Nonconformance.objects.create(lot=self.lot, description='이물', origin='INCOMING', defect_type='이물',
                                                sorting_result='전수 선별', contained_qty=Decimal('5'))
        dispose_nc(self.nc, mrb, 'pw', {'disposition': Nonconformance.SCRAP})
        self.nc.refresh_from_db()

    def test_open_nc_is_editable(self):
        nc = Nonconformance.objects.create(lot=self.other, description='긁힘')
        nc.description = '긁힘 2'
        nc.save()

    def test_plain_save_of_closed_nc_is_blocked(self):
        self.nc.description = '바꿈'
        with self.assertRaisesMessage(ValidationError, '종결된 부적합은 수정할 수 없습니다.'):
            self.nc.save()

    def test_save_with_lock_without_unlock_is_locked(self):
        self.nc.description = '바꿈'
        with self.assertRaises(Locked):
            save_with_lock(self.nc, self.eng)
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.description, '이물')

    def test_after_approval_fields_stay_open(self):
        self.nc.cost, self.nc.capa_required = Decimal('1000'), True
        save_with_lock(self.nc, self.eng)
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.cost, Decimal('1000'))

    def test_superuser_edits_non_interlock_fields(self):
        self.nc.description = '관리자 수정'
        save_with_lock(self.nc, self.root)
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.description, '관리자 수정')

    def test_interlock_fields_blocked_even_for_superuser_and_edit_request(self):
        EditRequest.objects.create(kind=EditRequest.EDIT, status=EditRequest.APPROVED, requested_by=self.eng,
                                   target=self.nc, reason='오기')
        for user in (self.root, self.eng):
            for name, value in [('lot', self.other), ('disposition', Nonconformance.CONCESSION),
                                ('customer_approval_ref', 'C-1'), ('detected_at', timezone.now())]:
                with self.subTest(user=user.username, field=name):
                    nc = Nonconformance.objects.get(pk=self.nc.pk)
                    setattr(nc, name, value)
                    with self.assertRaisesMessage(ValidationError, '보류 인터록 칸'):
                        save_with_lock(nc, user)
        self.assertEqual(Nonconformance.objects.get(pk=self.nc.pk).lot, self.lot)


class NcLockedFieldsAdminTest(TestCase):
    """종결 뒤 읽기 전용 칸은 nc_locked_fields가 정하고 admin이 그대로 쓴다. 모델 save 가드와 같은 칸이다."""

    def test_locked_fields_match_admin_readonly_fields(self):
        from django.contrib import admin
        from django.test import RequestFactory

        item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        lot = Lot.objects.create(number='RAW-1', item=item)
        mrb = User.objects.create_user('mrb', password='pw')
        mrb.groups.add(Group.objects.get(name='품질팀장'))
        eng = User.objects.create_user('eng', password='pw-eng-123', is_staff=True)
        eng.groups.add(Group.objects.get(name='품질엔지니어'))
        root = User.objects.create_superuser('root', password='pw-root-123')
        nc = Nonconformance.objects.create(lot=lot, description='이물', origin='INCOMING', defect_type='이물',
                                           sorting_result='전수 선별', contained_qty=Decimal('5'))
        dispose_nc(nc, mrb, 'pw', {'disposition': Nonconformance.SCRAP})
        nc.refresh_from_db()
        ma = admin.site._registry[Nonconformance]
        for user in (eng, root):
            with self.subTest(user=user.username):
                request = RequestFactory().get('/')
                request.user = user
                locked = nc_locked_fields(nc, user)
                self.assertTrue(locked)
                self.assertEqual(ma.get_readonly_fields(request, nc), ma.AUTO + [f for f in locked if f not in ma.AUTO])
        self.assertEqual(nc_locked_fields(nc, root), list(Nonconformance.INTERLOCK))


class AdminRulesEquivalenceTest(TestCase):
    """같은 입력을 admin 경로(화면 POST)와 공용 함수에 넣으면 저장 여부·오류 문구·이력 행 수가 같다
    (docs/architecture-migration-plan.md 3.2·9장). 두 경로는 같은 조건으로 만든 서로 다른 기록에 실행한다."""

    def setUp(self):
        import tempfile
        from django.test import override_settings
        media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        media.enable()
        self.addCleanup(media.disable)
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.boss = User.objects.create_user('boss', password='pw-boss-123', is_staff=True)
        self.boss.groups.add(Group.objects.get(name='품질팀장'))
        self.client.force_login(self.boss)
        self.seq = 0

    def _nc(self, sorting):
        self.seq += 1
        lot = Lot.objects.create(number=f'RAW-{self.seq}', item=self.item)
        return Nonconformance.objects.create(lot=lot, description='이물', origin='INCOMING', defect_type='이물',
                                             sorting_result=sorting, contained_qty=Decimal('5'))

    def _dispose_both(self, password='pw-boss-123', sorting='전수 선별', **data):
        """(admin 결과, 공용 함수 결과). 결과는 (저장 여부, 이력 증가량, 오류 문구, 해제된 보류 수)."""
        a, b = self._nc(sorting), self._nc(sorting)
        before = a.history.count(), b.history.count()
        form = {'lot': a.lot_id, 'description': a.description, 'origin': 'INCOMING', 'detected_at_0': '2026-10-27',
                'detected_at_1': '09:00:00', 'defect_qty': 1, 'cost': 0, 'password': password, 'defect_type': '이물',
                'sorting_result': sorting, 'contained_qty': 5, 'photos-TOTAL_FORMS': 0, 'photos-INITIAL_FORMS': 0,
                'photos-MIN_NUM_FORMS': 0, 'photos-MAX_NUM_FORMS': 1000, **data}
        resp = self.client.post(f'/admin/core/nonconformance/{a.pk}/change/', form)
        admin_text = resp.content.decode() if resp.status_code == 200 else ''
        try:
            dispose_nc(b, self.boss, password, data)
            rules_text = ''
        except ValidationError as e:
            rules_text = ' '.join(e.messages)
        out = []
        for nc, n, text in ((a, before[0], admin_text), (b, before[1], rules_text)):
            nc = Nonconformance.objects.get(pk=nc.pk)
            released = nc.holds.filter(released_at__isnull=False).count()
            out.append((nc.approved_by_id is not None and nc.closed_at is not None, nc.history.count() - n, text, released))
        return out

    def _same(self, result, *, saved, phrases=()):
        (a_saved, a_hist, a_text, a_rel), (r_saved, r_hist, r_text, r_rel) = result
        self.assertEqual((a_saved, r_saved), (saved, saved))
        self.assertEqual(a_hist, r_hist)
        self.assertEqual(a_rel, r_rel)
        for phrase in phrases:
            self.assertIn(phrase, a_text)
            self.assertIn(phrase, r_text)
        return a_hist, a_rel

    def test_dispose_ok(self):
        hist, released = self._same(self._dispose_both(disposition='SCRAP'), saved=True)
        self.assertGreater(hist, 0)
        self.assertEqual(released, 0)  # 폐기는 보류 유지

    def test_dispose_wrong_password(self):
        hist, _ = self._same(self._dispose_both(password='bad', disposition='SCRAP'), saved=False,
                             phrases=['MRB 승인 비밀번호가 맞지 않습니다.'])
        self.assertEqual(hist, 0)

    def test_dispose_missing_fields(self):
        hist, _ = self._same(self._dispose_both(sorting='', disposition='SCRAP'), saved=False, phrases=['보완 필요'])
        self.assertEqual(hist, 0)

    def test_dispose_wrong_password_and_missing_fields_show_both_in_order(self):
        result = self._dispose_both(password='bad', sorting='', disposition='SCRAP')
        self._same(result, saved=False, phrases=['MRB 승인 비밀번호가 맞지 않습니다.', '보완 필요'])
        for text in (result[0][2], result[1][2]):  # 순서도 admin과 같다: 비밀번호, 보완 필요
            self.assertLess(text.index('MRB 승인 비밀번호'), text.index('보완 필요'))

    def test_concession_needs_customer_approval_ref(self):
        hist, released = self._same(self._dispose_both(disposition='CONCESSION'), saved=False,
                                    phrases=['특채는 고객 승인 문서번호가 필요합니다.'])
        self.assertEqual((hist, released), (0, 0))

    def test_concession_with_ref_releases_hold_like_admin(self):
        hist, released = self._same(self._dispose_both(disposition='CONCESSION', customer_approval_ref='CA-1'), saved=True)
        self.assertGreater(hist, 0)
        self.assertEqual(released, 1)  # 특채는 보류를 푼다

    def test_rework_needs_retest_pass(self):
        hist, released = self._same(self._dispose_both(disposition='REWORK'), saved=False,
                                    phrases=['재작업·수리는 부적합 발견 이후 재검사 합격 기록이 있어야 보류를 해제합니다.'])
        self.assertEqual((hist, released), (0, 0))

    def _approve_both(self, password):
        specs = []
        for code in ('S1', 'S2'):
            item = Item.objects.create(code=code, name=code, item_type=Item.RAW)
            spec = InspectionSpec.objects.create(item=item, inspection_type=InspectionSpec.INCOMING)
            Characteristic.objects.create(spec=spec, name='두께', lsl=Decimal('9.5'), usl=Decimal('10.5'))
            specs.append(spec)
        view_spec, rules_spec = specs
        before = view_spec.history.count(), rules_spec.history.count()
        resp = self.client.post(f'/approve/qms/inspectionspec/{view_spec.pk}/', {'password': password})
        view_text = resp.content.decode() if resp.status_code == 200 else ''
        try:
            approve(rules_spec, self.boss, password)
            rules_text = ''
        except ValidationError as e:
            rules_text = ' '.join(e.messages)
        res = []
        for spec, n, text in ((view_spec, before[0], view_text), (rules_spec, before[1], rules_text)):
            spec = InspectionSpec.objects.get(pk=spec.pk)
            res.append((spec.approved_by_id is not None, spec.history.count() - n, text))
        return res

    def test_approve_ok(self):
        (v_saved, v_hist, _), (r_saved, r_hist, _) = self._approve_both('pw-boss-123')
        self.assertEqual((v_saved, r_saved), (True, True))
        self.assertEqual(v_hist, r_hist)
        self.assertGreater(v_hist, 0)

    def test_approve_wrong_password(self):
        (v_saved, v_hist, v_text), (r_saved, r_hist, r_text) = self._approve_both('bad')
        self.assertEqual((v_saved, r_saved), (False, False))
        self.assertEqual((v_hist, r_hist), (0, 0))
        self.assertIn('비밀번호가 맞지 않습니다.', v_text)
        self.assertIn('비밀번호가 맞지 않습니다.', r_text)
