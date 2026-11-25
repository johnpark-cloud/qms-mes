from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from core.importer import targets
from core.models import Department
from qms.models import Document, DocumentForm

URL = '/api/qms/documents/matrix/'


class DocumentMatrixTest(TestCase):
    """문서 체계(P6a): 부서별 결재서 × 입력·출력 양식. 양식은 연결된 시스템 기록 화면으로 간다."""

    def setUp(self):
        self.qa = Department.objects.create(code='QA', name='품질보증팀', sort=1)
        self.doc = Document.objects.create(number='CSE-PQ-07', title='수입검사 절차', department=self.qa)
        self.orphan = Document.objects.create(number='CSE-X-01', title='부서 없는 문서')
        DocumentForm.objects.create(document=self.doc, code='CSE-PQ-07-01', name='수입검사 의뢰서', direction=DocumentForm.IN)
        DocumentForm.objects.create(document=self.doc, code='CSE-PQ-07-02', name='수입검사 관리대장', direction=DocumentForm.OUT,
                                    target='ledger:INCOMING')
        DocumentForm.objects.create(document=self.doc, code='CSE-PQ-07-03', name='출하 기록', direction=DocumentForm.OUT,
                                    target='core.shipment')
        self.c = APIClient()
        self.c.force_login(User.objects.create_superuser('boss', password='x'))

    def test_matrix_groups_documents_by_department_with_form_chips(self):
        d = self.c.get(URL).json()
        self.assertEqual([g['name'] for g in d['departments']], ['품질보증팀', '부서 미지정'])
        doc = d['departments'][0]['documents'][0]
        self.assertEqual((doc['number'], doc['url']), ('CSE-PQ-07', f'/app/r/qms/document/{self.doc.pk}'))
        self.assertEqual([f['code'] for f in doc['inputs']], ['CSE-PQ-07-01'])
        self.assertEqual([f['code'] for f in doc['outputs']], ['CSE-PQ-07-02', 'CSE-PQ-07-03'])
        form_in, ledger, ship = doc['inputs'][0], *doc['outputs']
        self.assertEqual(form_in['url'], f'/app/r/qms/documentform/{form_in["id"]}')  # 연결 없음 → 양식 기록 화면
        self.assertEqual(ledger['url'], '/app/ledger?type=INCOMING')
        self.assertEqual(ledger['target_display'], '수입검사 관리대장')
        self.assertEqual(ship['url'], '/app/r/core/shipment')
        self.assertEqual(d['departments'][1]['documents'][0]['number'], 'CSE-X-01')

    def test_search_filters_by_document_or_form(self):
        d = self.c.get(URL + '?q=의뢰서').json()
        self.assertEqual([doc['number'] for g in d['departments'] for doc in g['documents']], ['CSE-PQ-07'])
        self.assertEqual(self.c.get(URL + '?q=없는').json()['departments'][0]['name'], '부서 미지정')

    def test_needs_view_permission(self):
        c = APIClient()
        c.force_login(User.objects.create_user('nobody', password='x', is_staff=True))
        self.assertEqual(c.get(URL).status_code, 403)

    def test_form_code_unique_and_importable(self):
        with self.assertRaises(ValidationError):
            DocumentForm(document=self.doc, code='CSE-PQ-07-01', name='중복', direction=DocumentForm.IN).full_clean()
        t = targets()['qms.documentform']
        self.assertEqual(t.match, ('code',))
        self.assertIn('department', targets()['qms.document'].columns)
