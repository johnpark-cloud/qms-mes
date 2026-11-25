"""문서 체계(P6a): 부서별 결재서 × 입력·출력 양식. 양식 칩은 연결 기록의 화면·대장으로, 연결이 없으면 양식 기록으로 간다."""
from django.db.models import Prefetch, Q
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import require_perm
from core.models import Department
from core.nav import app_href
from core.relations import record_url
from qms.models import Document, DocumentForm


def target_url(form):
    if not form.target:
        return f'/app/documents/forms/{form.pk}'  # 양식 기록 대장(P6b)
    if form.target.startswith('ledger:'):
        return f'/app/ledger?type={form.target.partition(":")[2]}'
    app, _, model = form.target.partition('.')
    return app_href(f'/admin/{app}/{model}/')


def _form(f):
    return {'id': f.pk, 'code': f.code, 'name': f.name, 'revision': f.revision,
            'target_display': f.get_target_display(), 'url': target_url(f)}


class DocMatrixView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'qms.view_document')
        docs = Document.objects.prefetch_related(Prefetch('forms', DocumentForm.objects.order_by('sort', 'code'))).order_by('number')
        q = request.query_params.get('q', '').strip()
        if q:
            docs = docs.filter(Q(number__icontains=q) | Q(title__icontains=q) | Q(forms__code__icontains=q)
                               | Q(forms__name__icontains=q)).distinct()
        by_dept = {}
        for d in docs:
            forms = list(d.forms.all())
            by_dept.setdefault(d.department_id, []).append({
                'id': d.pk, 'number': d.number, 'title': d.title, 'doc_type': d.doc_type, 'url': record_url(d),
                'inputs': [_form(f) for f in forms if f.direction == DocumentForm.IN],
                'outputs': [_form(f) for f in forms if f.direction == DocumentForm.OUT]})
        groups = [{'id': dep.pk, 'name': dep.name, 'documents': by_dept[dep.pk]}
                  for dep in Department.objects.filter(pk__in=[k for k in by_dept if k])]  # Meta.ordering = 정렬·코드
        if None in by_dept:
            groups.append({'id': None, 'name': '부서 미지정', 'documents': by_dept[None]})
        return Response({'departments': groups})
