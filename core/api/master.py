from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import require_perm
from core.export import table_xlsx, xlsx_response
from core.importer import TARGET_MODELS, preview_import, run_import
from core.models import ImportProfile, Item, Process
from core.grid import table_version
from core.rules import Stale, item_version, save_item, save_table

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


class TableView(APIView):
    """모델 전체를 한 표로 읽고 저장하는 화면(공정·고객사별 기한). 하위 클래스가 model·fields·unique·열을 정한다."""
    schema = None
    model = fields = unique = columns = filename = sheet = None

    def _out(self, user):
        app, name = self.model._meta.app_label, self.model._meta.model_name
        return {'version': table_version(self.model),
                'editable': user.has_perm(f'{app}.add_{name}') or user.has_perm(f'{app}.change_{name}'),
                'can_delete': user.is_superuser,
                'rows': [{'id': o.pk, **{f: getattr(o, f) for f in self.fields}}
                         for o in self.model.objects.order_by(self.unique[0])]}

    def get(self, request):
        require_perm(request.user, f'{self.model._meta.app_label}.view_{self.model._meta.model_name}')
        out = self._out(request.user)
        if request.query_params.get('export') == 'xlsx':
            rows = [[r[f] for f in self.fields] for r in out['rows']]
            return xlsx_response(table_xlsx(self.sheet, self.columns, rows), self.filename)
        return Response(out)

    def put(self, request):
        require_perm(request.user, f'{self.model._meta.app_label}.view_{self.model._meta.model_name}')
        d = request.data
        if not isinstance(d, dict):
            return _bad(BAD_BODY)
        rows = d.get('rows')
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            return _bad('목록이어야 합니다.', 'rows')
        try:
            save_table(self.model, request.user, rows, self.fields, self.unique, d.get('version'))
        except Stale as e:
            return Response({'detail': str(e)}, status=409)
        return Response(self._out(request.user))


class ProcessTableView(TableView):
    model, unique, sheet, filename = Process, ('code',), '공정', '공정.xlsx'
    fields = {'code': 'text', 'name': 'text'}
    columns = ['공정 코드', '공정명']


class ImportProfileListView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'core.view_importprofile')
        return Response([{'id': p.pk, 'name': p.name, 'target': p.target, 'target_display': p.get_target_display(),
                          'header_row': p.header_row, 'mapping': p.mapping} for p in ImportProfile.objects.order_by('name')])


class ImportView(APIView):
    schema = None
    parser_classes = [MultiPartParser]

    def post(self, request):
        d = request.data
        profile = ImportProfile.objects.filter(pk=d.get('profile')).first() if str(d.get('profile', '')).isdecimal() else None
        if profile is None:
            return _bad('가져오기 설정을 선택하세요.', 'profile')
        if not d.get('file'):
            return _bad('파일을 선택하세요.', 'file')
        if d.get('commit') not in ('0', '1'):
            return _bad('commit 값이 올바르지 않습니다.', 'commit')
        opts = TARGET_MODELS[profile.target]._meta  # import_view와 같다: 기존 행을 덮어쓰므로 추가·변경 권한이 모두 필요하다
        for a in ('add', 'change'):
            require_perm(request.user, f'{opts.app_label}.{a}_{opts.model_name}')
        if d['commit'] == '0':
            return Response(preview_import(profile, d['file']))
        count, errors = run_import(profile, d['file'])
        return Response({'count': count, 'errors': errors})
