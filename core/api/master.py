from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import require_perm
from core.export import table_xlsx, xlsx_response
from core.models import Item, Process
from core.rules import Stale, item_version, save_item

PAGE_SIZE = 50
LIST_COLUMNS = ['품번', '품명', '구분', 'BOM 수', '라우팅 수']
BAD_BODY = '요청 형식이 올바르지 않습니다.'


def _bad(msg, field=None):
    return Response({'detail': msg, 'fields': {field: [msg]} if field else {}}, status=400)


def _num(d):
    return '' if d is None else format(d.normalize(), 'f')


def _filtered(request):
    tab, q = request.query_params.get('tab', 'all'), request.query_params.get('q', '').strip()
    qs = Item.objects.annotate(bom_count=Count('bom_lines', distinct=True),
                               routing_count=Count('routing', distinct=True)).order_by('code')
    if tab in dict(Item.TYPES):
        qs = qs.filter(item_type=tab)
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    return qs


def _row(i):
    return {'id': i.pk, 'code': i.code, 'name': i.name, 'item_type': i.item_type,
            'item_type_display': i.get_item_type_display(), 'bom_count': i.bom_count, 'routing_count': i.routing_count}


def _detail(item, user):
    return {
        'id': item.pk, 'title': str(item), 'code': item.code, 'name': item.name, 'item_type': item.item_type,
        'version': item_version(item),
        'editable': user.has_perm('core.change_item'),
        'can_delete_rows': {'bom': user.has_perm('core.delete_bomline'), 'routing': user.has_perm('core.delete_routingstep')},
        'bom': [{'id': b.pk, 'component': b.component_id, 'qty': _num(b.qty)} for b in item.bom_lines.order_by('pk')],
        'routing': [{'id': r.pk, 'seq': r.seq, 'process': r.process_id} for r in item.routing.all()],
        'item_options': [{'value': i.pk, 'label': str(i)} for i in Item.objects.exclude(pk=item.pk).order_by('code')],
        'process_options': [{'value': p.pk, 'label': str(p)} for p in Process.objects.order_by('code')],
        'type_options': [{'value': v, 'label': label} for v, label in Item.TYPES],
    }


class ItemListView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'core.view_item')
        qs = _filtered(request)
        if request.query_params.get('export') == 'xlsx':
            rows = [[i.code, i.name, i.get_item_type_display(), i.bom_count, i.routing_count] for i in qs]
            return xlsx_response(table_xlsx('품번', LIST_COLUMNS, rows), '품번.xlsx')
        try:
            page = min(max(int(request.query_params.get('page', 1)), 1), 10**6)
        except ValueError:
            page = 1
        count = qs.count()
        start = (page - 1) * PAGE_SIZE
        return Response({'count': count, 'page': page, 'has_more': start + PAGE_SIZE < count,
                         'results': [_row(i) for i in qs[start:start + PAGE_SIZE]]})

    def post(self, request):
        require_perm(request.user, 'core.add_item')
        d = request.data
        if not isinstance(d, dict):
            return _bad(BAD_BODY)
        vals = {f: d.get(f) for f in ('code', 'name', 'item_type')}
        if not all(isinstance(v, str) for v in vals.values()):
            return _bad('품번·품명·구분을 입력하세요.')
        item = Item(**{k: v.strip() for k, v in vals.items()})
        item.full_clean()  # 검증 오류는 API 예외 처리가 400 fields로 바꾼다
        item.save()
        return Response(_detail(item, request.user), status=201)


class ItemDetailView(APIView):
    schema = None

    def get(self, request, pk):
        require_perm(request.user, 'core.view_item')
        return Response(_detail(get_object_or_404(Item, pk=pk), request.user))

    def put(self, request, pk):
        item = get_object_or_404(Item, pk=pk)  # 권한은 save_item이 확인한다
        d = request.data
        if not isinstance(d, dict):
            return _bad(BAD_BODY)
        tables = {}
        for key in ('bom', 'routing'):
            rows = d.get(key) or []
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                return _bad('목록이어야 합니다.', key)
            tables[key] = rows
        try:
            save_item(item, request.user, d, tables['bom'], tables['routing'], d.get('version'))
        except Stale as e:
            return Response({'detail': str(e)}, status=409)
        return Response(_detail(item, request.user))
