from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import require_perm
from core.export import document_xlsx, table_xlsx, xlsx_response
from core.models import Item, is_approver
from core.records import edit_unlocked, is_locked
from core.rules import approve, approve_and_log, request_revision_log
from qms.models import SPECIAL, ControlPlanLine, ExcelTemplate, InspectionSpec
from qms.rules import (Stale, compare_specs, diff_text, open_or_new_revision, prev_revision, save_spec, spec_logs,
                       spec_version)

PAGE_SIZE = 50


def _bad(msg, field=None):
    return Response({'detail': msg, 'fields': {field: [msg]} if field else {}}, status=400)
LIST_COLUMNS = ['품번', '품명', '검사 구분', '개정', '상태', '항목 수', '승인자', '승인일']


def _who(u):
    return (u.get_full_name() or u.username) if u else ''


def _day(dt):
    return dt.isoformat() if dt else None


def _num(d):
    return '' if d is None else format(d.normalize(), 'f')


def _status(spec):
    return '승인됨' if spec.approved_at else '초안'


def _filtered(request):
    tab, q = request.query_params.get('tab', 'all'), request.query_params.get('q', '').strip()
    higher = InspectionSpec.objects.filter(item=OuterRef('item'), inspection_type=OuterRef('inspection_type'),
                                           revision__gt=OuterRef('revision'), approved_at__isnull=False)
    qs = (InspectionSpec.objects.select_related('item', 'approved_by').annotate(char_count=Count('characteristics'))
          .annotate(is_current=Q(approved_at__isnull=False) & ~Exists(higher))
          .order_by('item__code', 'inspection_type', '-revision'))
    if tab == 'draft':
        qs = qs.filter(approved_at__isnull=True)
    elif tab == 'approved':
        qs = qs.filter(approved_at__isnull=False)
    elif tab == 'current':
        qs = qs.filter(approved_at__isnull=False).filter(~Exists(higher))
    if q:
        qs = qs.filter(Q(item__code__icontains=q) | Q(item__name__icontains=q))
    return qs


def _row(s):
    return {'id': s.pk, 'item_code': s.item.code, 'item_name': s.item.name, 'inspection_type': s.inspection_type,
            'inspection_type_display': s.get_inspection_type_display(), 'revision': s.revision, 'status': _status(s),
            'is_current': s.is_current, 'char_count': s.char_count, 'approved_by': _who(s.approved_by),
            'approved_at': _day(s.approved_at)}


def _detail(spec, user):
    spec = InspectionSpec.objects.select_related('item', 'approved_by').get(pk=spec.pk)
    prev = prev_revision(spec)
    lines = ControlPlanLine.objects.filter(plan__item=spec.item).select_related('plan').order_by('pk')
    ct = ContentType.objects.get_for_model(InspectionSpec)
    return {
        'id': spec.pk, 'title': str(spec), 'item': {'id': spec.item.pk, 'code': spec.item.code, 'name': spec.item.name},
        'inspection_type': spec.inspection_type, 'inspection_type_display': spec.get_inspection_type_display(),
        'revision': spec.revision, 'sampling': spec.sampling, 'note': spec.note, 'status': _status(spec),
        'approved_by': _who(spec.approved_by), 'approved_at': _day(spec.approved_at),
        'version': spec_version(spec),
        'editable': bool((not is_locked(spec) or edit_unlocked(spec, user)) and user.has_perm('qms.change_inspectionspec')),
        'can_approve': bool(is_approver(user) and not spec.approved_at),
        'can_delete_rows': user.has_perm('qms.delete_characteristic'),
        'prev_id': prev.pk if prev else None,
        'characteristics': [{'id': c.pk, 'name': c.name, 'lsl': _num(c.lsl), 'usl': _num(c.usl), 'unit': c.unit,
                             'special': c.special, 'plan_line': c.plan_line_id, 'spc_url': reverse('spc', args=[c.pk])}
                            for c in spec.characteristics.order_by('pk')],
        'plan_line_options': [{'value': ln.pk, 'label': str(ln)} for ln in lines],
        'special_options': [{'value': v, 'label': '없음' if v == '' else label} for v, label in SPECIAL],
        'diff': compare_specs(prev, spec),
        'templates': [{'id': t.pk, 'name': t.name, 'url': reverse('excel_report', args=[t.pk, spec.pk])}
                      for t in ExcelTemplate.objects.filter(target=ct)],
        'edit_request_url': reverse('edit_request', args=['edit', 'qms', 'inspectionspec', spec.pk]),
    }


def _log(g):
    return {'id': g.pk, 'label': g.label, 'changes': g.changes, 'reason': g.reason, 'status': g.status,
            'status_display': g.get_status_display(), 'requested_by': _who(g.requested_by),
            'requested_at': _day(g.requested_at), 'approved_by': _who(g.approved_by), 'approved_at': _day(g.approved_at),
            'spec_id': g.object_id}


class SpecListView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'qms.view_inspectionspec')
        qs = _filtered(request)
        if request.query_params.get('export') == 'xlsx':
            rows = [[s.item.code, s.item.name, s.get_inspection_type_display(), f'Rev.{s.revision}', _status(s),
                     s.char_count, _who(s.approved_by), s.approved_at.strftime('%Y-%m-%d') if s.approved_at else '']
                    for s in qs]
            return xlsx_response(table_xlsx('검사기준', LIST_COLUMNS, rows), '검사기준.xlsx')
        try:
            page = max(int(request.query_params.get('page', 1)), 1)
        except ValueError:
            page = 1
        count = qs.count()
        start = (page - 1) * PAGE_SIZE
        return Response({'count': count, 'page': page, 'has_more': start + PAGE_SIZE < count,
                         'results': [_row(s) for s in qs[start:start + PAGE_SIZE]]})

    def post(self, request):
        require_perm(request.user, 'qms.add_inspectionspec')
        if not isinstance(request.data, dict):
            return _bad('요청 형식이 올바르지 않습니다.')
        kind = request.data.get('inspection_type')
        item = Item.objects.filter(pk=request.data.get('item')).first() if str(request.data.get('item') or '').isdigit() else None
        if item is None or not isinstance(kind, str) or kind not in dict(InspectionSpec.TYPES):
            return Response({'detail': '품번과 검사 구분을 고르세요.'}, status=400)
        top = InspectionSpec.objects.filter(item=item, inspection_type=kind).order_by('-revision').first()
        if top:
            return Response({'detail': '이미 있는 검사기준입니다. 새 개정으로 만드세요.', 'existing': top.pk}, status=409)
        spec = InspectionSpec.objects.create(item=item, inspection_type=kind)
        return Response(_detail(spec, request.user), status=201)


class SpecDetailView(APIView):
    schema = None

    def get(self, request, pk):
        require_perm(request.user, 'qms.view_inspectionspec')
        return Response(_detail(get_object_or_404(InspectionSpec, pk=pk), request.user))

    def put(self, request, pk):
        spec = get_object_or_404(InspectionSpec, pk=pk)  # 권한은 save_spec이 확인한다
        data = request.data
        if not isinstance(data, dict):
            return _bad('요청 형식이 올바르지 않습니다.')
        rows = data.get('characteristics') or []
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            return _bad('목록이어야 합니다.', 'characteristics')
        try:
            save_spec(spec, request.user, data, rows, data.get('version'))
        except Stale as e:
            return Response({'detail': str(e)}, status=409)
        return Response(_detail(spec, request.user))


class SpecNewRevisionView(APIView):
    schema = None

    def post(self, request, pk):
        require_perm(request.user, 'qms.add_inspectionspec')
        spec = get_object_or_404(InspectionSpec, pk=pk)
        # 옛 개정에서 시작하면 낡은 값이 되살아나므로 같은 품번·구분의 최신 승인본을 기준으로 한다
        spec = InspectionSpec.current(spec.item, spec.inspection_type) or spec
        draft, created = open_or_new_revision(spec)
        return Response({'id': draft.pk, 'created': created})


class SpecApproveView(APIView):
    schema = None

    def post(self, request, pk):
        spec = get_object_or_404(InspectionSpec, pk=pk)
        password, log = request.data.get('password') or '', request.data.get('log')
        if log and not isinstance(log, dict):
            return _bad('log 형식이 올바르지 않습니다.', 'log')
        if log:
            approve_and_log(spec, request.user, password, f'Rev.{spec.revision}', log.get('changes'), log.get('reason'))
        else:
            approve(spec, request.user, password)
        return Response(_detail(spec, request.user))


class SpecRevisionLogView(APIView):
    schema = None

    def get(self, request, pk):
        require_perm(request.user, 'qms.view_inspectionspec')
        spec = get_object_or_404(InspectionSpec, pk=pk)
        logs = spec_logs(spec, confirmed_only=False).select_related('requested_by', 'approved_by')
        return Response({'results': [_log(g) for g in logs],
                         'prefill': {'label': f'Rev.{spec.revision}', 'changes': diff_text(compare_specs(prev_revision(spec), spec))}})

    def post(self, request, pk):
        require_perm(request.user, 'qms.change_inspectionspec')
        spec = get_object_or_404(InspectionSpec, pk=pk)
        g = request_revision_log(spec, request.user, f'Rev.{spec.revision}', request.data.get('changes'), request.data.get('reason'))
        return Response(_log(g), status=201)


class SpecDocumentView(APIView):
    schema = None

    def get(self, request, pk):
        require_perm(request.user, 'qms.view_inspectionspec')
        spec = get_object_or_404(InspectionSpec, pk=pk)
        doc = spec.document()
        if request.query_params.get('export') == 'xlsx':
            name = f'{spec.item.code}_{spec.get_inspection_type_display()}_Rev{spec.revision}.xlsx'
            return xlsx_response(document_xlsx(doc), name)
        return Response(doc)
