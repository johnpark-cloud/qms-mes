import datetime
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (Attachment, Department, FieldDef, Item, Lot, Nonconformance, Partner, PartnerCertificate,
                     Shipment)


def staff(name, group):
    u = User.objects.create_user(name, password='pw', is_staff=True)
    u.groups.add(Group.objects.get(name=group))
    return u


class MasterTest(TestCase):
    def test_department_cycle_rejected(self):
        a = Department.objects.create(code='A', name='품질')
        b = Department.objects.create(code='B', name='품질보증', parent=a)
        a.parent = b
        with self.assertRaisesMessage(ValidationError, '상위 부서가 자기 자신이나 하위 부서일 수 없습니다.'):
            a.full_clean()
        a.parent = a
        with self.assertRaisesMessage(ValidationError, '상위 부서가 자기 자신이나 하위 부서일 수 없습니다.'):
            a.full_clean()

    def test_master_edit_team_lead_only(self):
        eng, lead = staff('eng', '품질엔지니어'), staff('lead', '품질팀장')
        self.client.force_login(eng)
        data = {'code': 'D2', 'name': '생산팀', 'sort': 0, 'active': 'on'}
        self.assertEqual(self.client.get('/admin/core/department/').status_code, 200)
        self.assertEqual(self.client.post('/admin/core/department/add/', data).status_code, 403)
        self.client.force_login(lead)
        self.assertEqual(self.client.post('/admin/core/department/add/', data).status_code, 302)
        self.assertTrue(Department.objects.filter(code='D2').exists())

    def test_created_by_set_on_admin_add(self):
        lead = staff('lead', '품질팀장')
        self.client.force_login(lead)
        self.client.post('/admin/core/department/add/', {'code': 'D3', 'name': '구매팀', 'sort': 0, 'active': 'on'})
        self.assertEqual(Department.objects.get(code='D3').created_by, lead)

    def test_nav_lists_masters(self):
        from .nav import visible_nav
        labels = [l for _, items in visible_nav(staff('eng', '품질엔지니어')) for l, _ in items]
        for name in ('부서', '거래처'):
            self.assertIn(name, labels)


class PartnerTest(TestCase):
    def test_partner_needs_a_role(self):
        p = Partner(code='P1', name='대한정밀')
        with self.assertRaisesMessage(ValidationError, '협력사·고객사·외주처·교정기관 중 하나 이상을 고르세요.'):
            p.full_clean()
        p.is_supplier = True
        p.full_clean()

    def test_engineer_can_edit_certificate_not_partner(self):
        eng = staff('eng', '품질엔지니어')
        self.assertTrue(eng.has_perm('core.add_partnercertificate'))
        self.assertTrue(eng.has_perm('core.view_partner'))
        self.assertFalse(eng.has_perm('core.change_partner'))
        self.assertTrue(staff('lead', '품질팀장').has_perm('core.change_partner'))

    def test_expiring_cert_in_due_items(self):
        from qms.due import digest, due_items
        today = timezone.localdate()
        p = Partner.objects.create(code='P1', name='대한정밀', is_supplier=True)
        off = Partner.objects.create(code='P2', name='폐업', is_supplier=True, active=False)
        near = PartnerCertificate.objects.create(partner=p, standard='IATF 16949', valid_until=today + datetime.timedelta(days=29))
        PartnerCertificate.objects.create(partner=p, standard='ISO 9001', valid_until=today + datetime.timedelta(days=31))
        PartnerCertificate.objects.create(partner=off, standard='ISO 9001', valid_until=today)
        d = due_items()
        self.assertEqual(d['partner_certs'], [near])
        self.assertIn('협력사 인증 만료', [t for t, _ in digest(d)])


class FieldDefTest(TestCase):
    def setUp(self):
        self.ct = ContentType.objects.get_for_model(Partner)
        self.bank = FieldDef.objects.create(target=self.ct, key='bank', label='거래 은행', kind=FieldDef.CHOICE,
                                            choices=['국민', '신한'], required=True)

    def test_fielddef_key_locked(self):
        self.bank.key = 'bank2'
        with self.assertRaisesMessage(ValidationError, '저장된 칸의 키·대상은 바꿀 수 없습니다.'):
            self.bank.full_clean()

    def test_choice_needs_choices(self):
        d = FieldDef(target=self.ct, key='grade2', label='등급2', kind=FieldDef.CHOICE)
        with self.assertRaisesMessage(ValidationError, '종류가 "선택"이면 선택지를 입력하세요.'):
            d.full_clean()

    def test_extra_validated(self):
        p = Partner(code='P1', name='가', is_supplier=True)
        with self.assertRaisesMessage(ValidationError, '거래 은행: 값을 입력하세요.'):
            p.full_clean()
        p.extra = {'bank': '우리'}
        with self.assertRaisesMessage(ValidationError, '거래 은행: 선택지에 없는 값입니다.'):
            p.full_clean()
        FieldDef.objects.create(target=self.ct, key='limit', label='여신 한도', kind=FieldDef.NUMBER)
        FieldDef.objects.create(target=self.ct, key='since', label='거래 시작', kind=FieldDef.DATE)
        FieldDef.objects.create(target=self.ct, key='owner', label='담당', kind=FieldDef.USER)
        p.extra = {'bank': '국민', 'limit': 'abc', 'since': '2026/01/01', 'owner': 999}
        with self.assertRaises(ValidationError) as e:
            p.full_clean()
        msgs = e.exception.message_dict['extra']
        self.assertIn('여신 한도: 숫자가 아닙니다.', msgs)
        self.assertIn('거래 시작: 날짜 형식(YYYY-MM-DD)이 아닙니다.', msgs)
        self.assertIn('담당: 없는 사용자입니다.', msgs)
        p.extra = {'bank': '국민', 'limit': '1000', 'since': '2026-01-01'}
        p.full_clean()
        self.assertEqual(p.extra['limit'], 1000)

    def test_inactive_def_keeps_value(self):
        p = Partner.objects.create(code='P1', name='가', is_supplier=True, extra={'bank': '국민', 'old': 'x'})
        self.bank.active = False
        self.bank.save()
        p.extra['bank'] = '아무거나'
        p.full_clean()
        self.assertEqual(p.extra, {'bank': '아무거나', 'old': 'x'})

    def test_admin_form_shows_extra_field(self):
        self.client.force_login(staff('lead', '품질팀장'))
        self.assertContains(self.client.get('/admin/core/fielddef/add/'), '거래처')  # 대상 목록에 기준정보 모델
        self.assertContains(self.client.get('/admin/core/partner/add/'), 'extra__bank')
        data = {'code': 'P9', 'name': '나', 'is_supplier': 'on', 'status': Partner._meta.get_field('status').default,
                'extra__bank': '국민', 'active': 'on', 'certificates-TOTAL_FORMS': '0', 'certificates-INITIAL_FORMS': '0'}
        r = self.client.post('/admin/core/partner/add/', data)
        self.assertEqual(r.status_code, 302, r.content.decode()[:3000] if r.status_code != 302 else '')
        self.assertEqual(Partner.objects.get(code='P9').extra, {'bank': '국민'})
        bad = dict(data, code='P10', extra__bank='')
        r = self.client.post('/admin/core/partner/add/', bad)
        self.assertContains(r, '이 필드는 필수 항목입니다.')

    def test_admin_form_layout(self):
        # 기준정보 칸 → 사용자 정의 칸 → 관리(사용·비고) 순서, 모두 여러 열 카드
        self.client.force_login(staff('lead', '품질팀장'))
        sets = self.client.get('/admin/core/partner/add/').context['adminform'].fieldsets
        self.assertEqual([name for name, _ in sets], [None, '사용자 정의 칸', '관리'])
        self.assertTrue(all('grid' in opts['classes'] for _, opts in sets))
        self.assertEqual(sets[0][1]['fields'][:2], ['code', 'name'])
        self.assertEqual(sets[1][1]['fields'], ['extra__bank'])
        self.assertEqual(sets[2][1]['fields'], ['active', 'note'])


class AttachmentTest(TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp, True)
        field = Attachment._meta.get_field('file')  # 운영 data/attachments에 쓰지 않게 임시 폴더로
        orig = field.storage
        self.addCleanup(setattr, field, 'storage', orig)
        field.storage = FileSystemStorage(location=Path(self._tmp) / 'attachments')
        self.item = Item.objects.create(code='C1', name='셀', item_type=Item.FINISHED)
        self.item_ct = ContentType.objects.get_for_model(Item)

    def attach(self, **kw):
        return Attachment.objects.create(content_type=self.item_ct, object_id=self.item.pk,
                                         file=SimpleUploadedFile('도면.pdf', b'pdf'), **kw)

    def test_attachment_rejects_personal(self):
        from personal.models import LeaveProfile
        a = Attachment(content_type=ContentType.objects.get_for_model(LeaveProfile), object_id=1,
                       file=SimpleUploadedFile('a.pdf', b'x'))
        with self.assertRaisesMessage(ValidationError, '개인 기록에는 첨부할 수 없습니다.'):
            a.full_clean()

    def test_title_defaults_to_file_name(self):
        self.assertEqual(self.attach().title, '도면.pdf')

    def test_download_requires_target_view(self):
        a = self.attach()
        nobody = User.objects.create_user('nobody', password='pw', is_staff=True)
        self.client.force_login(nobody)
        self.assertEqual(self.client.get(f'/attachments/{a.pk}/').status_code, 403)
        self.client.force_login(staff('insp', '검사원'))
        r = self.client.get(f'/attachments/{a.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), b'pdf')
        self.client.logout()
        self.assertEqual(self.client.get(f'/attachments/{a.pk}/').status_code, 302)  # 로그인 화면으로

    def test_api_upload_and_list(self):
        self.client.force_login(staff('insp', '검사원'))
        r = self.client.post('/api/attachments/', {'ct': 'core.item', 'id': self.item.pk, 'kind': 'drawing',
                                                   'file': SimpleUploadedFile('도면.pdf', b'pdf')})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['kind_label'], '도면')
        a = Attachment.objects.get()
        self.assertEqual(a.uploaded_by.username, 'insp')
        body = self.client.get('/api/attachments/', {'ct': 'core.item', 'id': self.item.pk}).json()
        self.assertEqual([x['title'] for x in body['results']], ['도면.pdf'])
        self.assertTrue(body['can_add'])
        self.assertEqual(body['results'][0]['url'], f'/attachments/{a.pk}/')
        self.assertEqual(body['results'][0]['size'], 3)
        r = self.client.post('/api/attachments/', {'ct': 'core.item', 'id': self.item.pk})
        self.assertEqual(r.status_code, 400)

    def test_api_rejects_unknown_ct(self):
        self.client.force_login(staff('lead', '품질팀장'))
        for params in ({'ct': 'personal.leaveprofile', 'id': 1}, {'ct': 'nope', 'id': 1},
                       {'ct': 'core.item', 'id': 999999}, {'ct': 'core.item', 'id': 'x'}):
            self.assertEqual(self.client.get('/api/attachments/', params).status_code, 404, params)
        self.client.force_login(staff('insp', '검사원'))  # 검사원은 거래처 보기 권한이 없다
        p = Partner.objects.create(code='P1', name='가', is_supplier=True)
        self.assertEqual(self.client.get('/api/attachments/', {'ct': 'core.partner', 'id': p.pk}).status_code, 403)

    def test_backup_copies_attachments(self):
        self.attach()
        live, dest = Path(self._tmp), Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dest, True)
        db = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': live / 'x.sqlite3'}}
        with override_settings(DATABASES=db, DATA_DIR=live, MEDIA_ROOT=live / 'media'):
            call_command('backup', str(dest))
            backup = next(dest.iterdir())
            self.assertEqual([p.read_bytes() for p in (backup / 'attachments').rglob('*.pdf')], [b'pdf'])


class LinkMastersTest(TestCase):
    def setUp(self):
        self.item = Item.objects.create(code='R1', name='원자재', item_type=Item.RAW)
        self.lot = Lot.objects.create(number='L1', item=self.item, supplier=' 대한정밀 ')
        self.p = Partner.objects.create(code='P1', name='대한정밀', is_supplier=True)

    def run_cmd(self, **kw):
        out = StringIO()
        # 테스트 DB에서 실제 backup(SQLite 파일 복사)은 하지 않고 호출 여부만 본다
        with mock.patch('core.management.commands.link_masters.call_command') as backup:
            call_command('link_masters', stdout=out, **kw)
        return out.getvalue(), backup

    def test_dry_run_writes_nothing(self):
        out, backup = self.run_cmd()
        self.lot.refresh_from_db()
        self.assertIsNone(self.lot.partner)
        self.assertIn('연결 가능 1', out)
        backup.assert_not_called()

    def test_apply_needs_backup_dir(self):
        with mock.patch.dict('os.environ', {'QMS_BACKUP_DIR': ''}):
            with self.assertRaisesMessage(CommandError, '백업 폴더를 --backup-dir이나 QMS_BACKUP_DIR로 지정하세요.'):
                self.run_cmd(apply=True)
        self.lot.refresh_from_db()
        self.assertIsNone(self.lot.partner)

    def test_apply_links_and_backs_up(self):
        out, backup = self.run_cmd(apply=True, backup_dir='X:/bk')
        backup.assert_called_once()
        self.assertEqual(backup.call_args.args[:2], ('backup', 'X:/bk'))
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.partner, self.p)
        self.assertEqual(self.lot.supplier, ' 대한정밀 ')  # 글자 칸은 그대로
        self.assertEqual(self.lot.history.first().history_change_reason, '기준정보 연결(link_masters)')
        self.assertIn('연결함 1건', out)

    def test_ambiguous_name_not_linked(self):
        Partner.objects.create(code='P2', name='대한 정밀', is_supplier=True)  # 공백만 다른 같은 이름
        out, _ = self.run_cmd(apply=True, backup_dir='X:/bk')
        self.lot.refresh_from_db()
        self.assertIsNone(self.lot.partner)
        self.assertIn('여러 후보: 대한정밀 → P1, P2', out)

    def test_role_mismatch_not_linked(self):
        ship = Shipment.objects.create(lot=self.lot, customer='대한정밀', qty=1)
        out, _ = self.run_cmd(apply=True, backup_dir='X:/bk')
        ship.refresh_from_db()
        self.assertIsNone(ship.partner)
        self.assertIn('구분 불일치: 대한정밀 → P1(고객사 아님)', out)

    def test_not_found_reported(self):
        Shipment.objects.create(lot=self.lot, customer='없는회사', qty=1)
        out, _ = self.run_cmd()
        self.assertIn('못 찾음: 없는회사(1)', out)

    def test_existing_fk_not_overwritten(self):
        other = Partner.objects.create(code='P9', name='다른곳', is_supplier=True)
        Lot.objects.filter(pk=self.lot.pk).update(partner=other)
        out, _ = self.run_cmd(apply=True, backup_dir='X:/bk')
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.partner, other)
        self.assertIn('연결 가능 0, 이미 연결 1', out)

    def test_link_approved_ppap_keeps_history(self):
        from qms.models import PpapSubmission
        cust = Partner.objects.create(code='C1', name='A사', is_customer=True)
        ppap = PpapSubmission.objects.create(item=self.item, customer='A사', level=3, reason='신규')
        PpapSubmission.objects.filter(pk=ppap.pk).update(approved_at=timezone.now())
        ship = Shipment.objects.create(lot=self.lot, customer='a사', qty=1)
        Nonconformance.objects.create(lot=self.lot, description='치수 불량')  # 이제 LOT 보류 → 출하 인터록 대상
        self.lot.refresh_from_db()
        self.assertTrue(self.lot.on_hold)
        before = ppap.history.count()
        self.run_cmd(apply=True, backup_dir='X:/bk')
        ppap.refresh_from_db()
        ship.refresh_from_db()
        self.assertEqual((ppap.partner, ship.partner), (cust, cust))
        self.assertEqual(ppap.history.count(), before + 1)
        self.assertEqual(ppap.customer, 'A사')
        self.assertIsNotNone(ppap.approved_at)

    def test_auditor_matched_by_full_name(self):
        from qms.models import InternalAudit
        u = User.objects.create_user('hgd', first_name='길동', last_name='홍')
        dept = Department.objects.create(code='QA', name='품질팀')
        audit = InternalAudit.objects.create(name='공정심사', planned_date=timezone.localdate(), auditor='홍 길동',
                                             auditee='qa')
        self.run_cmd(apply=True, backup_dir='X:/bk')
        audit.refresh_from_db()
        self.assertEqual((audit.auditor_user, audit.auditee_dept), (u, dept))
