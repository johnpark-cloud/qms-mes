from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.utils.http import content_disposition_header
from django.shortcuts import get_object_or_404
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import require_perm
from core.export import XLSX, table_xlsx, xlsx_response
from core.importer import (guide, headers, preview_import, run_import, standard_profile, target_of, targets, template_csv,
                           template_xlsx)
from core.modules import active, module_of_model
from core.models import CodeValue, ImportLog, ImportProfile, Item, NumberRule, Process, Project
from core.numbering import (NumberingError, candidates, codebook, default_item_type, describe_text, fields,
                            next_number, parse_pattern, rulebook, _table)
from core.grid import table_version
from core.rules import Stale, item_version, save_item, save_table

PAGE_SIZE = 50
LIST_COLUMNS = ['품번', '품명', '구분', '프로젝트', 'BOM 수', '라우팅 수']
BAD_BODY = '요청 형식이 올바르지 않습니다.'


def _bad(msg, field=None):
    return Response({'detail': msg, 'fields': {field: [msg]} if field else {}}, status=400)


def _num(d):
    return '' if d is None else format(d.normalize(), 'f')


def _filtered(request):
    tab, q = request.query_params.get('tab', 'all'), request.query_params.get('q', '').strip()
    qs = Item.objects.annotate(bom_count=Count('bom_lines', distinct=True),
                               routing_count=Count('routing', distinct=True)).select_related('project').order_by('code')
    if tab in dict(Item.TYPES):
        qs = qs.filter(item_type=tab)
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    return by_project(qs, request)


def by_project(qs, request, field='project'):
    """목록 거르기 ?f_project=번호|none. 품목에 딸린 기록(검사기준서·관리계획서)은 field='item__project'."""
    v = request.query_params.get('f_project', '')
    if v == 'none':
        return qs.filter(**{f'{field}__isnull': True})
    return qs.filter(**{field: int(v)}) if v.isdecimal() else qs


def project_name(item):
    return item.project.name if item.project_id else ''


def _row(i, book, rules):
    return {'id': i.pk, 'code': i.code, 'name': i.name, 'item_type': i.item_type,
            'item_type_display': i.get_item_type_display(), 'project': project_name(i),
            'bom_count': i.bom_count, 'routing_count': i.routing_count,
            'code_parts': describe_text(i.code, NumberRule.ITEM, book, rules)}


def _detail(item, user):
    return {
        'id': item.pk, 'title': str(item), 'code': item.code, 'name': item.name, 'item_type': item.item_type,
        'project': item.project_id,
        'code_parts': describe_text(item.code, NumberRule.ITEM),
        'version': item_version(item),
        'editable': user.has_perm('core.change_item'),
        'can_delete_rows': {'bom': user.has_perm('core.delete_bomline'), 'routing': user.has_perm('core.delete_routingstep')},
        'bom': [{'id': b.pk, 'component': b.component_id, 'qty': _num(b.qty)} for b in item.bom_lines.order_by('pk')],
        'routing': [{'id': r.pk, 'seq': r.seq, 'process': r.process_id} for r in item.routing.all()],
        'item_options': [{'value': i.pk, 'label': str(i)} for i in Item.objects.exclude(pk=item.pk).order_by('code')],
        'process_options': [{'value': p.pk, 'label': str(p)} for p in Process.objects.order_by('code')],
        'type_options': [{'value': v, 'label': label} for v, label in Item.TYPES],
        # 고를 수 있는 것은 사용 중인 프로젝트, 이미 고른 것은 꺼졌어도 보인다
        'project_options': [{'value': p.pk, 'label': f'{p.code} {p.name} ({p.customer})'} for p in
                            Project.objects.filter(Q(active=True) | Q(pk=item.project_id)).select_related('customer')],
    }


class ItemListView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'core.view_item')
        qs = _filtered(request)
        if request.query_params.get('export') == 'xlsx':
            rows = [[i.code, i.name, i.get_item_type_display(), project_name(i), i.bom_count, i.routing_count] for i in qs]
            return xlsx_response(table_xlsx('품번', LIST_COLUMNS, rows), '품번.xlsx')
        try:
            page = min(max(int(request.query_params.get('page', 1)), 1), 10**6)
        except ValueError:
            page = 1
        count = qs.count()
        book, rules = codebook(), list(NumberRule.objects.all())
        start = (page - 1) * PAGE_SIZE
        return Response({'count': count, 'page': page, 'has_more': start + PAGE_SIZE < count,
                         'results': [_row(i, book, rules) for i in qs[start:start + PAGE_SIZE]]})

    def post(self, request):
        require_perm(request.user, 'core.add_item')
        d = request.data
        if not isinstance(d, dict):
            return _bad(BAD_BODY)
        auto = d.get('auto')
        vals = {f: d.get(f) for f in ('code', 'name', 'item_type')}
        if auto is not None:
            if (not isinstance(auto, dict) or type(auto.get('rule')) is not int or not isinstance(auto.get('values'), list)
                    or not all(isinstance(v, str) for v in auto['values'])):
                return _bad('자동 번호 요청 형식이 올바르지 않습니다.')
            vals['code'] = ''  # 서버가 계산한다
            vals['item_type'] = d.get('item_type') or ''
        if not all(isinstance(v, str) for v in vals.values()):
            return _bad('품번·품명·구분을 입력하세요.')
        project = d.get('project')
        if project is not None and type(project) is not int:
            return _bad('프로젝트를 고르세요.', 'project')
        item = Item(**{k: v.strip() for k, v in vals.items()}, project_id=project)
        if auto is None:
            item.full_clean()  # 검증 오류는 API 예외 처리가 400 fields로 바꾼다
            item.save()
            return Response(_detail(item, request.user), status=201)
        rule = NumberRule.objects.filter(pk=auto['rule'], target=NumberRule.ITEM).first()
        if rule is None or _hides_docs(rule, request.user):
            return _bad('번호 규칙을 찾을 수 없습니다.')
        retry = '같은 번호가 방금 사용되었습니다. 다시 시도하세요.'
        try:
            with transaction.atomic():
                item.code = next_number(rule, auto['values'])
                item.item_type = item.item_type or default_item_type(rule, auto['values'])
                if not item.item_type:
                    return _bad('구분을 고르세요.', 'item_type')
                try:
                    item.full_clean()
                except ValidationError as e:
                    if any(err.code == 'unique' for err in e.error_dict.get('code', [])):
                        return _bad(retry, 'code')
                    raise
                item.save()
        except NumberingError as e:
            return _bad(str(e))
        except IntegrityError:
            return _bad(retry, 'code')
        return Response(_detail(item, request.user), status=201)


def _hides_docs(rule, user):
    """문서 열람 권한이 없으면 문서 참조 규칙을 숨긴다(문서번호·제목 노출 방지)."""
    if user.has_perm('qms.view_document'):
        return False
    try:
        return any(t.kind == 'ref' and t.target == NumberRule.DOC for t in parse_pattern(rule.pattern))
    except NumberingError:
        return False


def _ref_ok(rule, rules):
    """틀을 해석할 수 있고 참조 규칙이 모두 남아 있는 규칙만."""
    try:
        return all(t.kind != 'ref' or t.rule in rules for t in parse_pattern(rule.pattern))
    except NumberingError:
        return False


class ItemOptionsView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'core.add_item')
        rules, groups = rulebook(), dict(CodeValue.GROUPS)
        codes = {}
        for c in CodeValue.objects.filter(active=True).order_by('sort', 'code'):
            codes.setdefault(c.group, []).append(c)
        out, names = [], {}  # names: 대상 -> {번호: 이름}, 표마다 한 번만 읽는다
        for rule in NumberRule.objects.filter(target=NumberRule.ITEM, active=True).order_by('sort', 'pk'):
            if not _ref_ok(rule, rules):
                continue
            if _hides_docs(rule, request.user):
                continue
            fs, prev = [], None
            for t in fields(rule):
                if t.kind == 'ref':
                    nums = candidates(t, rules)
                    if t.target not in names:
                        model, field = _table(t.target)
                        names[t.target] = dict(model.objects.values_list(field, 'name' if model is Item else 'title'))
                    fs.append({'kind': 'ref', 'label': t.rule, 'parent': None,
                               'options': [{'code': n, 'name': names[t.target].get(n, '')} for n in nums]})
                    continue
                opts = [{'id': c.pk, 'code': c.code, 'name': c.name, 'item_type': c.item_type, 'parent_id': c.parent_id}
                        for c in codes.get(t.group, []) if not t.allowed or c.code in t.allowed]
                fs.append({'kind': 'code', 'label': groups[t.group],
                           'parent': prev if CodeValue.PARENT_GROUP.get(t.group) else None, 'options': opts})
                prev = len(fs) - 1
            out.append({'id': rule.pk, 'name': rule.name, 'pattern': rule.pattern, 'fields': fs})
        return Response({'rules': out})


class ItemPreviewView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'core.add_item')
        rid = request.query_params.get('rule', '')
        rule = NumberRule.objects.filter(pk=rid, target=NumberRule.ITEM).first() if rid.isdecimal() else None
        if rule is None or _hides_docs(rule, request.user):
            return _bad('번호 규칙을 찾을 수 없습니다.')
        values = request.query_params.getlist('v')
        try:
            return Response({'number': next_number(rule, values), 'item_type': default_item_type(rule, values)})
        except NumberingError as e:
            return _bad(str(e))


class ProjectOptionsView(APIView):
    """품번·검사기준서·관리계획서 목록의 프로젝트 거르기 선택지."""
    schema = None

    def get(self, request):
        require_perm(request.user, 'core.view_item')
        return Response([{'value': 'none', 'label': '프로젝트 없음'}] +
                        [{'value': str(p.pk), 'label': f'{p.name} ({p.customer})'}
                         for p in Project.objects.filter(active=True).select_related('customer')])


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


def _import_perms(target):
    """들여오기는 기존 행을 덮어쓰므로 추가·변경 권한이 모두 필요하다(import_view와 같다)."""
    opts = target.model._meta
    return [f'{opts.app_label}.{a}_{opts.model_name}' for a in ('add', 'change')]


class ImportTargetListView(APIView):
    """빈 양식을 받을 수 있는 종류: 추가·변경 권한이 있고 모듈이 켜진 것만."""
    schema = None

    def get(self, request):
        return Response([{'key': t.key, 'label': t.label, 'headers': headers(t), 'guide': guide(t)}
                         for t in sorted(targets().values(), key=lambda t: t.label)
                         if request.user.has_perms(_import_perms(t)) and active(module_of_model(t.model._meta.label_lower))])


class ImportTemplateView(APIView):
    """종류별 빈 양식(docs/data-flow.md 5절 표준 열 제목). kind=xlsx면 드롭다운·작성 안내가 붙은 엑셀, 아니면 CSV."""
    schema = None

    def get(self, request):
        target = targets().get(request.query_params.get('target', ''))
        if target is None:
            return _bad('들여올 수 없는 종류입니다.', 'target')
        fmt = request.query_params.get('kind', 'csv')
        if fmt not in ('csv', 'xlsx'):
            return _bad('양식 형식은 csv 또는 xlsx입니다.', 'kind')
        for p in _import_perms(target):
            require_perm(request.user, p)
        if fmt == 'xlsx':
            resp = HttpResponse(template_xlsx(target), content_type=XLSX)
        else:
            resp = HttpResponse(template_csv(target), content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = content_disposition_header(True, f'{target.label} 양식.{fmt}')
        return resp


class ImportView(APIView):
    schema = None
    parser_classes = [MultiPartParser]

    def post(self, request):
        d = request.data
        if d.get('target'):  # 빈 양식(표준 열 제목)은 설정 없이 들여온다
            target = targets().get(d['target'])
            if target is None:
                return _bad('들여올 수 없는 종류입니다.', 'target')
            profile = standard_profile(target)
        else:
            profile = ImportProfile.objects.filter(pk=d.get('profile')).first() if str(d.get('profile', '')).isdecimal() else None
        if profile is None:
            return _bad('가져오기 설정을 선택하세요.', 'profile')
        if not d.get('file'):
            return _bad('파일을 선택하세요.', 'file')
        if d.get('commit') not in ('0', '1'):
            return _bad('commit 값이 올바르지 않습니다.', 'commit')
        target = target_of(profile)
        if target is None:
            return _bad('이 가져오기 설정의 대상은 더 이상 들여올 수 없습니다.', 'profile')
        for p in _import_perms(target):
            require_perm(request.user, p)
        if d['commit'] == '0':
            return Response(preview_import(profile, d['file'], request.user))
        with transaction.atomic():
            count, errors = run_import(profile, d['file'], request.user)
            if not errors:
                ImportLog.keep(target.model, target.label, d['file'], request.user, count, profile.name if profile.pk else '')
        return Response({'count': count, 'errors': errors})


LOG_LIMIT = 200  # shortcut: 최근 200건만 보여 준다. 더 오래된 기록을 찾아야 하면 기간 검색을 더한다


class ImportLogListView(APIView):
    """확정한 들여오기 기록(docs/data-flow.md 7.4절). 대상 기록 열람 권한이 있는 것만."""
    schema = None

    def get(self, request):
        logs = [log for log in ImportLog.objects.select_related('user')[:LOG_LIMIT] if log.can_view(request.user)]
        return Response([{'id': log.pk, 'created_at': log.created_at, 'user': log.user.username if log.user else '',
                          'label': log.label, 'file_name': log.file_name, 'count': log.count, 'profile': log.profile,
                          'url': f'/api/core/import/logs/{log.pk}/file/'} for log in logs])


class ImportLogFileView(APIView):
    """원본 파일 그대로 받기. 목록과 같은 권한 검사. 꺼진 모듈이면 없는 것처럼 404."""
    schema = None

    def get(self, request, pk):
        log = get_object_or_404(ImportLog, pk=pk)
        if not request.user.has_perm(f"{log.target.split('.')[0]}.view_{log.target.split('.')[1]}"):
            return Response({'detail': '이 기록을 볼 권한이 없습니다.'}, status=403)
        if not log.can_view(request.user):
            raise Http404
        try:
            return FileResponse(log.file.open('rb'), as_attachment=True, filename=log.file_name)
        except OSError:
            raise Http404('파일이 없습니다.')
