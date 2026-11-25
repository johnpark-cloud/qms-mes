from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import APPROVER_GROUP
from qms.models import Document, DocumentForm, FormRecord

FIELDS = [{'name': '교육명', 'kind': 'text', 'required': True},
          {'name': '인원', 'kind': 'number'},
          {'name': '실시일', 'kind': 'date'},
          {'name': '구분', 'kind': 'choice', 'choices': ['사내', '사외']}]


class FormRecordTest(TestCase):
    """양식 기록(P6b): 시스템 기록이 없는 양식을 항목 정의대로 화면에서 쓰고, 승인 뒤 잠근다."""

    def setUp(self):
        doc = Document.objects.create(number='CSE-HR-01', title='교육훈련 절차')
        self.form = DocumentForm.objects.create(document=doc, code='CSE-HR-01-01', name='교육훈련 실시 기록',
                                                direction=DocumentForm.OUT, fields=FIELDS)
        self.boss = User.objects.create_superuser('boss', password='pw')
        self.c = APIClient()
        self.c.force_login(self.boss)
        self.url = f'/api/qms/forms/{self.form.pk}/'

    def test_field_definitions_are_validated(self):
        for bad in ([{'name': '', 'kind': 'text'}], [{'name': 'a', 'kind': 'zzz'}],
                    [{'name': 'a', 'kind': 'text'}, {'name': 'a', 'kind': 'number'}],
                    [{'name': 'a', 'kind': 'choice', 'choices': []}], 'x'):
            self.form.fields = bad
            with self.assertRaises(ValidationError, msg=bad):
                self.form.full_clean()

    def test_values_follow_definition(self):
        ok = FormRecord(form=self.form, author=self.boss, values={'교육명': '신입 교육', '인원': '12', '실시일': '2026-11-20', '구분': '사내'})
        ok.full_clean()
        for bad in ({'인원': '3'}, {'교육명': 'x', '인원': '열둘'}, {'교육명': 'x', '실시일': '11/20'},
                    {'교육명': 'x', '구분': '기타'}):
            with self.assertRaises(ValidationError, msg=bad):
                FormRecord(form=self.form, author=self.boss, values=bad).full_clean()

    def test_ledger_create_edit_and_lock_after_approval(self):
        r = self.c.post(self.url + 'records/', {'values': {'교육명': '신입 교육', '인원': '12'}}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        rec = FormRecord.objects.get(pk=r.json()['id'])
        self.assertEqual((rec.author, rec.values['인원']), (self.boss, '12'))
        self.assertEqual(self.c.post(self.url + 'records/', {'values': {'인원': '1'}}, format='json').status_code, 400)
        d = self.c.get(self.url).json()
        self.assertEqual(d['form']['code'], 'CSE-HR-01-01')
        self.assertEqual([f['name'] for f in d['form']['fields']], ['교육명', '인원', '실시일', '구분'])
        self.assertEqual(d['records'][0]['values']['교육명'], '신입 교육')
        self.assertEqual(d['records'][0]['url'], f'/app/r/qms/formrecord/{rec.pk}')
        patch = f'/api/qms/formrecords/{rec.pk}/'
        self.assertEqual(self.c.patch(patch, {'values': {'교육명': '신입 교육(수정)'}}, format='json').status_code, 200)
        rec.refresh_from_db()
        self.assertEqual(rec.values['교육명'], '신입 교육(수정)')
        FormRecord.objects.filter(pk=rec.pk).update(approved_by=self.boss, approved_at=timezone.now())
        self.assertEqual(self.c.patch(patch, {'values': {'교육명': '몰래'}}, format='json').status_code, 400)
        self.assertTrue(self.c.get(self.url).json()['records'][0]['approved'])

    def test_define_fields_from_ledger(self):
        r = self.c.put(self.url + 'fields/', {'fields': [{'name': '점검 항목', 'kind': 'long'}]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.form.refresh_from_db()
        self.assertEqual(self.form.fields, [{'name': '점검 항목', 'kind': 'long'}])
        self.assertEqual(self.c.put(self.url + 'fields/', {'fields': [{'name': '', 'kind': 'text'}]}, format='json').status_code, 400)

    def test_permissions_checked_on_server(self):
        u = User.objects.create_user('viewer', password='pw', is_staff=True)
        c = APIClient()
        c.force_login(u)
        self.assertEqual(c.get(self.url).status_code, 403)
        u.user_permissions.add(*Permission.objects.filter(codename__in=['view_documentform', 'view_formrecord']))
        u = User.objects.get(pk=u.pk)
        c.force_login(u)
        d = c.get(self.url).json()
        self.assertEqual((d['can_add'], d['can_define']), (False, False))
        self.assertEqual(c.post(self.url + 'records/', {'values': {'교육명': 'x'}}, format='json').status_code, 403)
        self.assertEqual(c.put(self.url + 'fields/', {'fields': []}, format='json').status_code, 403)

    def test_approver_can_sign_via_record_page(self):
        rec = FormRecord.objects.create(form=self.form, author=self.boss, values={'교육명': 'x'})
        Group.objects.get_or_create(name=APPROVER_GROUP)
        d = self.c.get(f'/api/records/qms.formrecord/{rec.pk}/').json()
        self.assertTrue(d['can_approve'])
        self.assertIn('교육명: x', next(f['value'] for f in d['fields'] if f['key'] == 'values'))
