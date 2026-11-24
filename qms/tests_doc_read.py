"""문서 열람 확인(4단계 #9): 승인된 개정을 읽었다고 남기고, 최근 30일에 승인된 최신본 중 안 읽은 것을 내 할 일에 띄운다."""
import datetime

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .due import due_items
from .models import Document, DocumentRead, DocumentRevision
from .tests import approve


class DocumentReadTest(TestCase):
    def setUp(self):
        self.lead = User.objects.create_user('lead', password='pw-lead-123', is_staff=True)
        self.lead.groups.add(Group.objects.get(name='품질팀장'))
        self.eng = User.objects.create_user('eng', password='pw-eng-123', is_staff=True)
        self.eng.groups.add(Group.objects.get(name='품질엔지니어'))
        self.doc = Document.objects.create(number='KEN-WI-01', title='작업표준')
        self.rev = DocumentRevision.objects.create(document=self.doc, change_note='제정', body='본문')

    def url(self, rev, tail=''):
        return f'/api/records/qms.documentrevision/{rev.pk}/{tail}'

    def test_draft_cannot_be_acknowledged(self):
        with self.assertRaises(ValidationError):
            DocumentRead.objects.create(revision=self.rev, user=self.eng)
        self.client.force_login(self.eng)
        self.assertFalse(self.client.get(self.url(self.rev)).json()['can_ack'])
        self.assertEqual(self.client.post(self.url(self.rev, 'ack/'), {}, content_type='application/json').status_code, 400)

    def test_ack_records_reader_once(self):
        approve(self.rev, self.lead)
        self.client.force_login(self.eng)
        self.assertTrue(self.client.get(self.url(self.rev)).json()['can_ack'])
        for _ in range(2):  # 두 번 눌러도 한 줄
            d = self.client.post(self.url(self.rev, 'ack/'), {}, content_type='application/json').json()
        self.assertFalse(d['can_ack'])
        self.assertEqual(DocumentRead.objects.filter(revision=self.rev, user=self.eng).count(), 1)
        reads = next(c for c in d['children'] if c['key'] == 'reads')
        self.assertEqual([r['cells']['user'] for r in reads['rows']], ['eng'])

    def test_ack_needs_view_permission(self):
        approve(self.rev, self.lead)
        self.client.force_login(User.objects.create_user('nobody', password='pw-x-12345', is_staff=True))
        self.assertEqual(self.client.post(self.url(self.rev, 'ack/'), {}, content_type='application/json').status_code, 403)
        self.assertFalse(DocumentRead.objects.exists())

    def test_unread_current_revisions_in_due_items(self):
        approve(self.rev, self.lead)
        old_doc = Document.objects.create(number='KEN-WI-02', title='옛 표준')
        old = DocumentRevision.objects.create(document=old_doc, change_note='제정', body='본문')
        approve(old, self.lead)
        DocumentRevision.objects.filter(pk=old.pk).update(approved_at=timezone.now() - datetime.timedelta(days=31))
        self.assertEqual(due_items(user=self.eng)['unread_docs'], [self.rev])
        self.assertEqual(due_items()['unread_docs'], [])  # 알림 메일(사용자 없음)에는 없다
        newer = DocumentRevision.objects.create(document=self.doc, change_note='개정', body='본문2')
        approve(newer, self.lead)
        self.assertEqual(due_items(user=self.eng)['unread_docs'], [newer])  # 옛 개정은 최신본이 아니다
        DocumentRead.objects.create(revision=newer, user=self.eng)
        self.assertEqual(due_items(user=self.eng)['unread_docs'], [])

    def test_todo_widget_lists_unread(self):
        import json
        approve(self.rev, self.lead)
        self.client.force_login(self.eng)
        self.client.post('/api/qms/dashboard/', json.dumps([{'key': 'todo_lists', 'size': 'wide'}]), content_type='application/json')
        data = {w['key']: w['data'] for w in self.client.get('/api/qms/todo/').json()['widgets']}
        self.assertEqual([(r['label'], r['href']) for r in data['todo_lists']['unread_docs']],
                         [('KEN-WI-01 작업표준 Rev.0', f'/app/r/qms/documentrevision/{self.rev.pk}')])
