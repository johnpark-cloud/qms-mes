from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Item, Lot, RevisionLog
from core.rules import Locked, request_revision_log
from qms.models import Characteristic, ControlPlan, ControlPlanLine, Gauge, Inspection, InspectionSpec, Qualification
from qms.rules import (RECEIVE_MSG, Stale, compare_specs, diff_text, measurement, new_spec_revision, open_or_new_revision,
                       receive_lot, save_spec, spec_logs, spec_version, submit_inspection)


class InspectionRulesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('lead', password='pw-lead-123', is_staff=True)
        self.user.groups.add(Group.objects.get(name='품질팀장'))
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='RAW-1', item=self.item)
        self.spec = InspectionSpec.objects.create(item=self.item, inspection_type=InspectionSpec.INCOMING)
        self.char = Characteristic.objects.create(spec=self.spec, name='두께', lsl=Decimal('9'), usl=Decimal('11'))
        self.spec.approved_by, self.spec.approved_at = self.user, timezone.now()
        self.spec.save()
        Qualification.objects.create(user=self.user, inspection_type=InspectionSpec.INCOMING,
                                     valid_until=date(2999, 1, 1), basis='테스트')

    def test_pass(self):
        insp = submit_inspection(self.lot, self.spec, self.user, None, {self.char.pk: '10'})
        self.assertEqual(insp.result, Inspection.PASS)

    def test_fail_creates_nc_with_defect(self):
        insp = submit_inspection(self.lot, self.spec, self.user, None, {self.char.pk: '12'}, '치수', '-3')
        self.assertEqual(insp.result, Inspection.FAIL)
        self.assertEqual(insp.nonconformance.defect_type, '치수')
        self.assertEqual(insp.nonconformance.defect_qty, 0)
        self.assertTrue(self.lot.on_hold)

    def test_gauge_required_once_registered(self):
        g = Gauge.objects.create(number='G-1', name='마이크로미터', last_calibrated=timezone.localdate())
        with self.assertRaisesMessage(ValidationError, '계측기를 골라야 합니다'):
            submit_inspection(self.lot, self.spec, self.user, None, {self.char.pk: '10'})
        self.assertFalse(Inspection.objects.exists())
        self.assertEqual(submit_inspection(self.lot, self.spec, self.user, g, {self.char.pk: '10'}).result, Inspection.PASS)

    def test_missing_value_rolls_back(self):
        with self.assertRaisesMessage(ValidationError, '값을 입력하세요'):
            submit_inspection(self.lot, self.spec, self.user, None, {})
        self.assertFalse(Inspection.objects.exists())

    def test_nan_rejected(self):
        self.assertIsNone(measurement(self.char, 'nan'))

    def test_receive(self):
        lot, created = receive_lot('NEW-1', self.item, '5', '협력사A')
        self.assertTrue(created)
        with self.assertRaisesMessage(ValidationError, RECEIVE_MSG):
            receive_lot('NEW-2', self.item, '0', '')


class SpecRulesTest(TestCase):
    def setUp(self):
        self.eng = User.objects.create_user('eng', password='pw-eng-123', is_staff=True)
        self.eng.groups.add(Group.objects.get(name='품질엔지니어'))
        # 품질엔지니어 그룹에는 delete_ 권한이 없다. 삭제 줄 저장 테스트용으로 항목 삭제 권한만 더한다
        self.eng.user_permissions.add(Permission.objects.get(codename='delete_characteristic', content_type__app_label='qms'))
        self.lead = User.objects.create_user('lead2', password='pw-lead-123', is_staff=True)
        self.lead.groups.add(Group.objects.get(name='품질팀장'))
        self.superuser = User.objects.create_superuser('root', password='pw-root-123')
        self.item = Item.objects.create(code='R1', name='양극재', item_type=Item.RAW)
        self.item2 = Item.objects.create(code='R2', name='양극재2', item_type=Item.RAW)
        self.item3 = Item.objects.create(code='R3', name='양극재3', item_type=Item.RAW)
        self.spec = self._approved(self.item)
        self.spec2 = self._approved(self.item2)
        self.other_draft = InspectionSpec.objects.create(item=self.item3, inspection_type=InspectionSpec.INCOMING)

    def _approved(self, item):
        line = ControlPlanLine.objects.create(plan=ControlPlan.objects.create(item=item), characteristic='폭')
        spec = InspectionSpec.objects.create(item=item, inspection_type=InspectionSpec.INCOMING, sampling='n=5', note='비고')
        Characteristic.objects.create(spec=spec, name='두께', lsl=Decimal('9'), usl=Decimal('11'), unit='mm', special='SC')
        Characteristic.objects.create(spec=spec, name='폭', lsl=Decimal('4'), usl=Decimal('6'), unit='mm', plan_line=line)
        spec.approved_by, spec.approved_at = self.lead, timezone.now()
        spec.save()
        return spec

    def test_new_revision_matches_admin(self):
        # 같은 원본을 두 번 만들어 하나는 admin 동작, 하나는 공용 함수로 개정한다
        via_func = new_spec_revision(self.spec)
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:qms_inspectionspec_changelist'),
                         {'action': 'new_revision', '_selected_action': [self.spec2.pk]})
        via_admin = InspectionSpec.objects.get(item=self.item2, revision=2)
        snap = lambda s: (s.revision, s.sampling, s.note, sorted(
            (c.name, c.lsl, c.usl, c.unit, c.special, c.plan_line_id is not None) for c in s.characteristics.all()))
        self.assertEqual(snap(via_func), snap(via_admin))
        self.assertEqual(via_func.revision, 2)
        self.assertFalse(via_func.is_approved)

    def test_open_or_new_reuses_draft(self):
        draft, created = open_or_new_revision(self.spec)
        again, created2 = open_or_new_revision(self.spec)
        self.assertEqual((created, created2, again.pk), (True, False, draft.pk))

    def test_save_bad_row_id_and_properties(self):
        draft, _ = open_or_new_revision(self.spec)
        for bad in ([1], {}, 'x', True):
            with self.assertRaises(ValidationError) as cm:
                save_spec(draft, self.eng, {}, [{'id': bad, 'name': 'a'}], None)
            self.assertIn('characteristics.0.id', cm.exception.message_dict, bad)
        for data, key in (({'sampling': 'x' * 300}, 'sampling'), ({'sampling': {}}, 'sampling'), ({'note': 5}, 'note')):
            with self.assertRaises(ValidationError) as cm:
                save_spec(draft, self.eng, data, [], None)
            self.assertIn(key, cm.exception.message_dict)

    def test_diff_text_shows_plan_line_as_text(self):
        draft, _ = open_or_new_revision(self.spec)
        c = draft.characteristics.get(name='폭')
        c.plan_line = None
        c._edit_unlocked = True
        c.save()
        self.assertIn(f'{c.name}', diff_text(compare_specs(self.spec, draft)))
        text = diff_text(compare_specs(self.spec, draft))
        old = str(self.spec.characteristics.get(name='폭').plan_line)
        self.assertIn(f"{old} → ", text)
        self.assertNotRegex(text, r'\d+ → ')

    def test_save_adds_changes_deletes_in_one_go(self):
        draft, _ = open_or_new_revision(self.spec)
        keep, drop = draft.characteristics.order_by('name')   # 두께, 폭
        rows = [{'id': keep.pk, 'name': '두께', 'lsl': '9.5', 'usl': '11', 'unit': 'mm', 'special': 'SC', 'plan_line': None},
                {'id': drop.pk, 'delete': True},
                {'id': None, 'name': '길이', 'lsl': '', 'usl': '', 'unit': '', 'special': '', 'plan_line': None},
                {'id': None, 'name': '', 'lsl': '', 'usl': '', 'unit': '', 'special': '', 'plan_line': None}]  # 빈 줄은 무시
        save_spec(draft, self.eng, {'sampling': 'n=8', 'note': ''}, rows, spec_version(draft))
        self.assertEqual(sorted(draft.characteristics.values_list('name', flat=True)), ['길이', '두께'])
        self.assertEqual(draft.characteristics.get(name='두께').lsl, Decimal('9.5'))
        self.assertEqual(InspectionSpec.objects.get(pk=draft.pk).sampling, 'n=8')

    def test_save_normalizes_numbers(self):          # Review Focus 2
        draft, _ = open_or_new_revision(self.spec)
        save_spec(draft, self.eng, {}, [{'id': None, 'name': '무게', 'lsl': ' 1,234.5 ', 'usl': '', 'unit': 'g'}], None)
        c = draft.characteristics.get(name='무게')
        self.assertEqual((c.lsl, c.usl), (Decimal('1234.5'), None))

    def test_save_bad_row_saves_nothing_and_points_to_cell(self):
        draft, _ = open_or_new_revision(self.spec)
        before = draft.characteristics.count()
        rows = [{'id': None, 'name': '가', 'lsl': '1'}, {'id': None, 'name': '나', 'lsl': 'abc'}]
        with self.assertRaises(ValidationError) as cm:
            save_spec(draft, self.eng, {}, rows, None)
        self.assertIn('characteristics.1.lsl', cm.exception.message_dict)
        self.assertEqual(draft.characteristics.count(), before)

    def test_save_rejects_lsl_above_usl(self):
        draft, _ = open_or_new_revision(self.spec)
        before = draft.characteristics.count()
        with self.assertRaises(ValidationError) as cm:
            save_spec(draft, self.eng, {}, [{'id': None, 'name': '뒤바뀜', 'lsl': '11', 'usl': '9'}], None)
        self.assertEqual(cm.exception.message_dict['characteristics.0.usl'], ['하한이 상한보다 클 수 없습니다.'])
        self.assertEqual(draft.characteristics.count(), before)
        save_spec(draft, self.eng, {}, [{'id': None, 'name': '같음', 'lsl': '10', 'usl': '10'}], None)  # 같으면 허용

    def test_plan_line_rejects_lsl_above_usl(self):
        line = ControlPlanLine(characteristic='x', lsl=5, usl=1)
        with self.assertRaises(ValidationError) as cm:
            line.clean()
        self.assertIn('usl', cm.exception.message_dict)

    def test_save_rejects_foreign_row(self):         # Review Focus 1
        other = Characteristic.objects.create(spec=self.other_draft, name='남의 항목')
        draft, _ = open_or_new_revision(self.spec)
        with self.assertRaises(ValidationError) as cm:
            save_spec(draft, self.eng, {}, [{'id': other.pk, 'name': '바꿈'}], None)
        self.assertIn('characteristics.0.id', cm.exception.message_dict)
        self.assertEqual(Characteristic.objects.get(pk=other.pk).name, '남의 항목')

    def test_save_on_approved_is_locked(self):
        c = self.spec.characteristics.first()
        with self.assertRaises(Locked):
            save_spec(self.spec, self.eng, {}, [{'id': c.pk, 'name': '바꿈', 'lsl': '9', 'usl': '11'}], None)

    def test_save_delete_on_approved_rejected(self):  # Review Focus 3
        c = self.spec.characteristics.first()
        with self.assertRaises((Locked, PermissionDenied)):
            save_spec(self.spec, self.eng, {}, [{'id': c.pk, 'delete': True}], None)
        self.assertTrue(Characteristic.objects.filter(pk=c.pk).exists())

    def test_spec_version_sees_spec_only_change(self):
        draft, _ = open_or_new_revision(self.spec)
        for n in range(3):  # 항목 이력 번호가 기준서 이력 번호보다 앞서게 한다
            Characteristic.objects.create(spec=draft, name=f'x{n}')
        self.assertGreater(Characteristic.history.filter(spec_id=draft.pk).latest('history_id').history_id,
                           draft.history.latest('history_id').history_id)
        v = spec_version(draft)
        draft.sampling = 'n=99'
        draft.save()
        self.assertNotEqual(spec_version(draft), v)

    def test_stale_version_rejected(self):
        draft, _ = open_or_new_revision(self.spec)
        v = spec_version(draft)
        save_spec(draft, self.lead, {'note': '먼저'}, [], v)
        with self.assertRaises(Stale):
            save_spec(InspectionSpec.objects.get(pk=draft.pk), self.eng, {'note': '나중'}, [], v)

    def test_compare_and_text(self):
        draft, _ = open_or_new_revision(self.spec)
        rows = [{'id': c.pk, 'delete': True} for c in draft.characteristics.filter(name='폭')]
        rows += [{'id': draft.characteristics.get(name='두께').pk, 'name': '두께', 'lsl': '9', 'usl': '10.5', 'unit': 'mm', 'special': 'SC'},
                 {'id': None, 'name': '길이'}]
        save_spec(draft, self.eng, {'sampling': 'n=8'}, rows, None)
        diff = compare_specs(self.spec, draft)
        self.assertEqual(diff['fields']['sampling'][1], 'n=8')
        self.assertEqual({r['name']: r['status'] for r in diff['rows']}, {'두께': 'changed', '폭': 'removed', '길이': 'added'})
        self.assertEqual(next(r for r in diff['rows'] if r['name'] == '두께')['cells'], ['usl'])
        text = diff_text(diff)
        for part in ('샘플링', '항목 추가: 길이', '항목 삭제: 폭', '두께'):
            self.assertIn(part, text)
        self.assertEqual(diff_text(compare_specs(None, self.spec)), '최초 제정')

    def test_spec_logs_across_revisions(self):
        # Rev.1 확정 1건 + Rev.2 대기 1건 → Rev.2 문서용은 1건, 탭용은 2건
        old = request_revision_log(self.spec, self.eng, 'Rev.1', '최초 제정', '신규')
        RevisionLog.objects.filter(pk=old.pk).update(status=RevisionLog.CONFIRMED, approved_by=self.lead)
        draft, _ = open_or_new_revision(self.spec)
        request_revision_log(draft, self.eng, 'Rev.2', '폭 변경', '고객 요청')
        self.assertEqual(spec_logs(draft, confirmed_only=True).count(), 1)
        self.assertEqual(spec_logs(draft, confirmed_only=False).count(), 2)
        self.assertEqual(spec_logs(self.spec, confirmed_only=False).count(), 1)   # Rev.1에서는 Rev.2 이력이 안 보인다
