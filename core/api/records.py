"""records API: 기록 설명서(core/recordspec.py)로 목록·상세·변경 이력을 준다(REC-02).

권한은 그 모델의 view_ 권한. 변경 이력도 view_ 권한이면 본다(미결 #6, 2026-11-13 사용자 결정).
꺼진 모듈은 미들웨어가 주소의 label 인자로 막는다.
"""
from django.apps import apps
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from core import audit, recordspec
from core.export import table_xlsx, xlsx_response
from core.relations import record_url, status_of

from .permissions import require_perm

PAGE_SIZE = 50


def _model(user, label):
    spec = recordspec.spec_of(label)
    if spec is None:
        raise Http404
    model = apps.get_model(label)
    require_perm(user, f'{model._meta.app_label}.view_{model._meta.model_name}')
    return model, spec


def _columns(model, names):
    return [{'key': n, 'label': recordspec.label_of(model, n)} for n in names]


def _row(obj, names):
    return {'id': obj.pk, 'url': record_url(obj), 'status': status_of(obj), 'cells': recordspec.cells(obj, names)}


class RecordListView(APIView):
    schema = None

    def get(self, request, label):
        model, spec = _model(request.user, label)
        tabs = {key: fn for key, _, fn in spec.tabs}
        tab = request.query_params.get('tab')
        tab = tab if tab in tabs else spec.tabs[0][0]
        qs = model.objects.all().order_by(*spec.order)
        if tabs[tab]:
            qs = tabs[tab](qs)
        q = request.query_params.get('q', '').strip()
        if q and spec.search:
            cond = Q()
            for f in spec.search:
                cond |= Q(**{f'{f}__icontains': q})
            qs = qs.filter(cond)
        title = str(model._meta.verbose_name)
        if request.query_params.get('export') == 'xlsx':
            cols = _columns(model, spec.columns)
            rows = [[recordspec.value_of(o, c['key'])[0] for c in cols] for o in qs]
            return xlsx_response(table_xlsx(title, [c['label'] for c in cols], rows), f'{title}.xlsx')
        try:
            page = min(max(int(request.query_params.get('page', 1)), 1), 10**6)
        except ValueError:
            page = 1
        count = qs.count()
        start = (page - 1) * PAGE_SIZE
        return Response({'title': title, 'tabs': [{'key': k, 'label': n} for k, n, _ in spec.tabs],
                         'columns': _columns(model, spec.columns), 'count': count, 'page': page,
                         'has_more': start + PAGE_SIZE < count,
                         'results': [_row(o, spec.columns) for o in qs[start:start + PAGE_SIZE]],
                         'can_add': request.user.has_perm(f'{model._meta.app_label}.add_{model._meta.model_name}')})


class RecordDetailView(APIView):
    schema = None

    def get(self, request, label, pk):
        model, spec = _model(request.user, label)
        obj = get_object_or_404(model, pk=pk)
        fields = []
        for n in spec.fields:
            text, url = recordspec.value_of(obj, n)
            fields.append({'key': n, 'label': recordspec.label_of(model, n), 'value': text, 'url': url})
        children = []
        for c in spec.children:
            rel = getattr(obj, c.accessor)
            children.append({'key': c.accessor, 'label': c.label, 'columns': _columns(rel.model, c.fields),
                             'rows': [_row(o, c.fields) for o in rel.all().order_by(*c.order)]})
        meta = model._meta
        return Response({'ct': meta.label_lower, 'id': obj.pk, 'title': str(obj), 'kind': str(meta.verbose_name),
                         'status': status_of(obj), 'fields': fields, 'children': children, 'side': list(spec.side),
                         'admin_url': f'/admin/{meta.app_label}/{meta.model_name}/{obj.pk}/change/',
                         'list_url': f'/app/r/{meta.app_label}/{meta.model_name}'})


class RecordHistoryView(APIView):
    schema = None

    def get(self, request, label, pk):
        model, _ = _model(request.user, label)
        get_object_or_404(model, pk=pk)
        return Response({'results': [audit.row_payload(h) for h in audit.rows(model, pk)[:PAGE_SIZE]]})
