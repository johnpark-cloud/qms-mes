from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import require_perm
from core.export import document_xlsx, table_xlsx, xlsx_response
from core.models import Item, Process, is_approver
from core.records import edit_unlocked, is_locked
from core.rules import approve, approve_and_log, request_revision_log
from qms.api.specs import BAD_BODY, PAGE_SIZE, _bad, _day, _log, _num, _status, _who
from qms.models import SPECIAL, ControlPlan, ControlPlanLine, InspectionSpec
from qms.rules import (PLAN_FIELDS, Stale, compare_plans, current_plan, make_specs_from_plan, open_or_new_plan_revision,
                       plan_diff_text, plan_logs, plan_version, prev_plan, save_plan)

LIST_COLUMNS = ['품번', '품명', '단계', '개정', '상태', '항목 수', '승인자', '승인일']


def _filtered(request):
    tab, q = request.query_params.get('tab', 'all'), request.query_params.get('q', '').strip()
    higher = ControlPlan.objects.filter(item=OuterRef('item'), stage=OuterRef('stage'), revision__gt=OuterRef('revision'),
                                        approved_at__isnull=False)
    qs = (ControlPlan.objects.select_related('item', 'approved_by').annotate(line_count=Count('lines'))
          .annotate(is_current=Q(approved_at__isnull=False) & ~Exists(higher))
          .order_by('item__code', 'stage', '-revision'))
    if tab == 'draft':
        qs = qs.filter(approved_at__isnull=True)
    elif tab == 'approved':
        qs = qs.filter(approved_at__isnull=False)
    elif tab == 'current':
        qs = qs.filter(approved_at__isnull=False).filter(~Exists(higher))
    if q:
        qs = qs.filter(Q(item__code__icontains=q) | Q(item__name__icontains=q))
    return qs


def _row(p):
    return {'id': p.pk, 'item_code': p.item.code, 'item_name': p.item.name, 'stage': p.stage, 'stage_display': p.get_stage_display(),
            'revision': p.revision, 'status': _status(p), 'is_current': p.is_current, 'line_count': p.line_count,
            'approved_by': _who(p.approved_by), 'approved_at': _day(p.approved_at)}


def _line(ln):
    d = {f: getattr(ln, f) for f in PLAN_FIELDS}
    d.update(process=ln.process_id, lsl=_num(ln.lsl), usl=_num(ln.usl), id=ln.pk)
    return d


def _detail(plan, user):
    plan = ControlPlan.objects.select_related('item', 'approved_by').get(pk=plan.pk)
    prev = prev_plan(plan)
    return {
        'id': plan.pk, 'title': str(plan), 'item': {'id': plan.item.pk, 'code': plan.item.code, 'name': plan.item.name},
        'stage': plan.stage, 'stage_display': plan.get_stage_display(), 'revision': plan.revision, 'status': _status(plan),
        'approved_by': _who(plan.approved_by), 'approved_at': _day(plan.approved_at), 'version': plan_version(plan),
        'editable': bool((not is_locked(plan) or edit_unlocked(plan, user)) and user.has_perm('qms.change_controlplan')),
        'can_approve': bool(is_approver(user) and not plan.approved_at),
        'can_delete_rows': user.has_perm('qms.delete_controlplanline'),
        'can_make_specs': bool(plan.approved_at and user.has_perm('qms.add_inspectionspec')),
        'prev_id': prev.pk if prev else None,
        'lines': [_line(ln) for ln in plan.lines.order_by('pk')],
        'process_options': [{'value': p.pk, 'label': str(p)} for p in Process.objects.order_by('code')],
        'special_options': [{'value': v, 'label': '없음' if v == '' else label} for v, label in SPECIAL],
        'type_options': [{'value': '', 'label': '없음'}] + [{'value': v, 'label': label} for v, label in InspectionSpec.TYPES],
        'stage_options': [{'value': v, 'label': label} for v, label in ControlPlan.STAGES],
        'diff': compare_plans(prev, plan),
        'edit_request_url': reverse('edit_request', args=['edit', 'qms', 'controlplan', plan.pk]),
    }


class PlanListView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'qms.view_controlplan')
        qs = _filtered(request)
        if request.query_params.get('export') == 'xlsx':
            rows = [[p.item.code, p.item.name, p.get_stage_display(), f'Rev.{p.revision}', _status(p), p.line_count,
                     _who(p.approved_by), p.approved_at.strftime('%Y-%m-%d') if p.approved_at else ''] for p in qs]
            return xlsx_response(table_xlsx('관리계획서', LIST_COLUMNS, rows), '관리계획서.xlsx')
        try:
            page = min(max(int(request.query_params.get('page', 1)), 1), 10**6)
        except ValueError:
            page = 1
        count = qs.count()
        start = (page - 1) * PAGE_SIZE
        return Response({'count': count, 'page': page, 'has_more': start + PAGE_SIZE < count,
                         'results': [_row(p) for p in qs[start:start + PAGE_SIZE]]})

    def post(self, request):
        require_perm(request.user, 'qms.add_controlplan')
        if not isinstance(request.data, dict):
            return _bad('요청 형식이 올바르지 않습니다.')
        stage = request.data.get('stage')
        item = Item.objects.filter(pk=request.data.get('item')).first() if str(request.data.get('item') or '').isdigit() else None
        if item is None or not isinstance(stage, str) or stage not in dict(ControlPlan.STAGES):
            return _bad('품번과 단계를 고르세요.')
        try:
            with transaction.atomic():
                top = ControlPlan.objects.filter(item=item, stage=stage).order_by('-revision').first()
                if not top:
                    plan = ControlPlan.objects.create(item=item, stage=stage)
        except IntegrityError:  # 동시에 같은 계획서를 만든 경우(uniq_cp_rev)
            top = ControlPlan.objects.filter(item=item, stage=stage).order_by('-revision').first()
        if top:
            return Response({'detail': '이미 있는 관리계획서입니다. 새 개정으로 만드세요.', 'existing': top.pk}, status=409)
        return Response(_detail(plan, request.user), status=201)


class PlanDetailView(APIView):
    schema = None

    def get(self, request, pk):
        require_perm(request.user, 'qms.view_controlplan')
        return Response(_detail(get_object_or_404(ControlPlan, pk=pk), request.user))

    def put(self, request, pk):
        plan = get_object_or_404(ControlPlan, pk=pk)  # 권한은 save_plan이 확인한다
        data = request.data
        if not isinstance(data, dict):
            return _bad('요청 형식이 올바르지 않습니다.')
        rows = data.get('lines') or []
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            return _bad('목록이어야 합니다.', 'lines')
        try:
            save_plan(plan, request.user, data, rows, data.get('version'))
        except Stale as e:
            return Response({'detail': str(e)}, status=409)
        return Response(_detail(plan, request.user))


class PlanNewRevisionView(APIView):
    schema = None

    def post(self, request, pk):
        require_perm(request.user, 'qms.add_controlplan')
        plan = get_object_or_404(ControlPlan, pk=pk)
        # 옛 개정에서 시작하면 낡은 값이 되살아나므로 같은 품번·단계의 최신 승인본을 기준으로 한다
        plan = current_plan(plan.item, plan.stage) or plan
        draft, created = open_or_new_plan_revision(plan)
        return Response({'id': draft.pk, 'created': created})


class PlanApproveView(APIView):
    schema = None

    def post(self, request, pk):
        plan = get_object_or_404(ControlPlan, pk=pk)
        if not isinstance(request.data, dict):
            return _bad(BAD_BODY)
        password, log = request.data.get('password') or '', request.data.get('log')
        if log and not isinstance(log, dict):
            return _bad('log 형식이 올바르지 않습니다.', 'log')
        with transaction.atomic():
            # 승인자가 본 개정 번호와 다르면 낡은 화면의 서명이므로 거부한다
            if 'version' in request.data and request.data['version'] != plan_version(plan):
                return Response({'detail': str(Stale())}, status=409)
            if log:
                approve_and_log(plan, request.user, password, f'Rev.{plan.revision}', log.get('changes'), log.get('reason'))
            else:
                approve(plan, request.user, password)
        return Response(_detail(plan, request.user))


class PlanRevisionLogView(APIView):
    schema = None

    def get(self, request, pk):
        require_perm(request.user, 'qms.view_controlplan')
        plan = get_object_or_404(ControlPlan, pk=pk)
        logs = plan_logs(plan, confirmed_only=False).select_related('requested_by', 'approved_by')
        return Response({'results': [_log(g) for g in logs],
                         'prefill': {'label': f'Rev.{plan.revision}', 'changes': plan_diff_text(compare_plans(prev_plan(plan), plan))}})

    def post(self, request, pk):
        require_perm(request.user, 'qms.change_controlplan')
        plan = get_object_or_404(ControlPlan, pk=pk)
        if not isinstance(request.data, dict):
            return _bad(BAD_BODY)
        g = request_revision_log(plan, request.user, f'Rev.{plan.revision}', request.data.get('changes'), request.data.get('reason'))
        return Response(_log(g), status=201)


class PlanDocumentView(APIView):
    schema = None

    def get(self, request, pk):
        require_perm(request.user, 'qms.view_controlplan')
        plan = get_object_or_404(ControlPlan, pk=pk)
        doc = plan.document()
        if request.query_params.get('export') == 'xlsx':
            name = f'{plan.item.code}_{plan.get_stage_display()}_관리계획서_Rev{plan.revision}.xlsx'
            return xlsx_response(document_xlsx(doc), name)
        return Response(doc)


class PlanMakeSpecsView(APIView):
    schema = None

    def post(self, request, pk):
        require_perm(request.user, 'qms.add_inspectionspec')
        plan = get_object_or_404(ControlPlan, pk=pk)
        with transaction.atomic():
            made = make_specs_from_plan(plan)  # 미승인이면 ValidationError → 400
        return Response({'made': [{'id': s.pk, 'title': str(s)} for s in made]})
