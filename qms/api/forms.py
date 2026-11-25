"""양식 기록(P6b): 시스템 기록이 없는 양식을 항목 정의(DocumentForm.fields)대로 대장에서 쓰고 고친다.
규칙(항목 검사·승인 뒤 잠금)은 모델 clean/save가 막고, 여기서는 권한만 본다. 승인은 기록 화면(/app/r/qms/formrecord/<id>)."""
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import require_perm
from core.relations import record_url
from qms.models import DocumentForm, FormRecord

from .documents import target_url


def _record(r):
    return {'id': r.pk, 'written_on': r.written_on.isoformat(), 'author': r.author.get_full_name() or r.author.username,
            'values': r.values, 'approved': r.is_approved, 'url': record_url(r)}


def _save(rec, data):
    if 'values' in data:
        rec.values = data['values'] if isinstance(data['values'], dict) else {}
    if data.get('written_on'):
        rec.written_on = parse_date(str(data['written_on'])) or rec.written_on
    rec.full_clean()
    rec.save()


class FormLedgerView(APIView):
    schema = None

    def get(self, request, pk):
        u = request.user
        require_perm(u, 'qms.view_documentform')
        require_perm(u, 'qms.view_formrecord')
        f = get_object_or_404(DocumentForm.objects.select_related('document'), pk=pk)
        return Response({
            'form': {'id': f.pk, 'code': f.code, 'name': f.name, 'revision': f.revision,
                     'direction': f.get_direction_display(), 'fields': f.fields, 'url': record_url(f),
                     'document': {'number': f.document.number, 'title': f.document.title, 'url': record_url(f.document)},
                     'target_url': target_url(f) if f.target else None, 'target_display': f.get_target_display()},
            'records': [_record(r) for r in f.records.select_related('author')],
            'kinds': DocumentForm.KINDS,
            'can_add': u.has_perm('qms.add_formrecord'), 'can_edit': u.has_perm('qms.change_formrecord'),
            'can_define': u.has_perm('qms.change_documentform')})


class FormFieldsView(APIView):
    schema = None

    def put(self, request, pk):
        require_perm(request.user, 'qms.change_documentform')
        f = get_object_or_404(DocumentForm, pk=pk)
        f.fields = request.data.get('fields')
        f.full_clean()
        f.save()
        return Response({'fields': f.fields})


class FormRecordCreateView(APIView):
    schema = None

    def post(self, request, pk):
        require_perm(request.user, 'qms.add_formrecord')
        rec = FormRecord(form=get_object_or_404(DocumentForm, pk=pk), author=request.user)
        _save(rec, request.data)
        return Response(_record(rec), status=201)


class FormRecordView(APIView):
    schema = None

    def patch(self, request, pk):
        require_perm(request.user, 'qms.change_formrecord')
        rec = get_object_or_404(FormRecord, pk=pk)
        _save(rec, request.data)
        return Response(_record(rec))
