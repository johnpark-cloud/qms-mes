"""records API: 기록 설명서(core/recordspec.py)로 목록·상세·변경 이력을 준다(REC-02).

권한은 그 모델의 view_ 권한. 변경 이력도 view_ 권한이면 본다(미결 #6, 2026-11-13 사용자 결정).
꺼진 모듈은 미들웨어가 주소의 label 인자로 막는다.
"""
from datetime import datetime
from urllib.parse import urlencode

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.forms import modelform_factory
from django.forms.models import model_to_dict
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.views import APIView

from core import audit, modules, recordspec, rules
from core.export import table_xlsx, xlsx_response
from core.grid import record_version
from core.models import Approvable, EditRequest, Lot, Nonconformance, is_approver
from core.records import can_edit_locked, is_locked
from core.relations import record_url, status_of, trace_url

from . import listing
from .permissions import require_perm

PAGE_SIZE = 50
SIDE_TYPES = {'생성': '추가', '변경': '변경', '삭제': '삭제'}


def _model(user, label):
    spec = recordspec.spec_of(label)
    if spec is None:
        raise Http404
    model = apps.get_model(label)
    require_perm(user, f'{model._meta.app_label}.view_{model._meta.model_name}')
    return model, spec


def _columns(model, names, sorts=()):
    return [{'key': n, 'label': recordspec.label_of(model, n), 'sortable': n in sorts} for n in names]


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
        sorts, filters = listing.field_controls(model, spec.columns, model.objects.all())
        qs = listing.apply(qs, request.query_params, sorts, filters, spec.order)
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
                         'columns': _columns(model, spec.columns, sorts), 'filters': listing.public(filters),
                         'count': count, 'page': page,
                         'has_more': start + PAGE_SIZE < count,
                         'results': [_row(o, spec.columns) for o in qs[start:start + PAGE_SIZE]],
                         'can_add': request.user.has_perm(f'{model._meta.app_label}.add_{model._meta.model_name}'),
                         'new_url': _new_url(model, spec)})

    def post(self, request, label):
        """새로 만들기: 설명서 create 칸만, full_clean(칸별 오류) → 저장. 보류 인터록 등은 모델 clean/save가 막는다."""
        model, spec = _create_spec(request.user, label)
        values = request.data.get('values')
        if not isinstance(values, dict):
            raise ValidationError('values가 필요합니다.')
        bad = {k: ['이 화면에서 넣을 수 없는 칸입니다.'] for k in values if k not in spec.create}
        if bad:
            raise ValidationError(bad)
        blank = {k: v for k, v in model_to_dict(model(), fields=spec.create).items() if v is not None}  # 모델 기본값(불량 0 등)
        form = modelform_factory(model, fields=spec.create)({**blank, **values})
        if not form.is_valid():
            raise ValidationError({k: list(v) for k, v in form.errors.items()})
        obj = form.instance
        for name in ('created_by', 'operator'):  # 관리 화면 MasterAdmin.save_model과 같이 만든 사람을 남긴다
            if any(f.name == name for f in model._meta.fields) and not getattr(obj, f'{name}_id'):
                setattr(obj, name, request.user)
        rules.save_with_lock(obj, request.user)
        return Response({'id': obj.pk, 'url': record_url(obj)}, status=201)


def _new_url(model, spec):
    meta = model._meta
    return f'/app/r/{meta.app_label}/{meta.model_name}/new' if spec.create else f'/admin/{meta.app_label}/{meta.model_name}/add/'


def _create_spec(user, label):
    model, spec = _model(user, label)
    if not spec.create:
        raise Http404
    require_perm(user, f'{model._meta.app_label}.add_{model._meta.model_name}')
    return model, spec


class RecordNewView(APIView):
    schema = None

    def get(self, request, label):
        model, spec = _create_spec(request.user, label)
        form = modelform_factory(model, fields=spec.create)()
        return Response({'title': str(model._meta.verbose_name), 'list_url': f'/app/r/{model._meta.app_label}/{model._meta.model_name}',
                         'fields': [recordspec.creator(model, n, form) for n in spec.create],
                         'groups': recordspec.groups_of(spec)})


def _perm(user, model, action):
    return user.has_perm(f'{model._meta.app_label}.{action}_{model._meta.model_name}')


def _can_request(obj, kind, user):
    try:
        rules.check_edit_request(obj, kind, user)
    except (Http404, PermissionDenied):
        return False
    return True


CAPA_SOURCE = {'qms.customerclaim': '8D', 'qms.scar': 'SCAR', 'core.nonconformance': 'NC', 'qms.auditfinding': 'AUDIT'}  # qms/admin.py capa_links와 같은 코드


def _links(obj, user):
    """「⋯」 메뉴 바로가기: LOT 이력 추적, CAPA 만들기(관리 화면 추가 폼, 출처 채움 — CAPA 모듈이 켜져 있을 때만)."""
    label = obj._meta.label_lower
    links = []
    lot = obj if isinstance(obj, Lot) else obj.lot if label == 'qms.customerclaim' else None
    if lot:
        links.append({'label': 'LOT 이력 (추적)', 'url': trace_url(lot.number)})
    if label in CAPA_SOURCE and modules.active('qms_capa') and user.has_perm('qms.add_capa'):
        query = {'source': CAPA_SOURCE[label], 'source_type': ContentType.objects.get_for_model(obj).pk, 'source_id': obj.pk,
                 'title': str(obj)[:200]}
        links.append({'label': 'CAPA 만들기', 'url': reverse('admin:qms_capa_add') + '?' + urlencode(query)})
    return links


def _parent_locked(obj, spec):
    return bool(spec.lock_parent) and is_locked(getattr(obj, spec.lock_parent))


def _detail(obj, spec, user):
    model = type(obj)
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
    by_parent = _parent_locked(obj, spec)
    locked = by_parent or is_locked(obj)
    return {'ct': meta.label_lower, 'id': obj.pk, 'title': str(obj), 'kind': str(meta.verbose_name),
            'status': status_of(obj), 'fields': fields, 'children': children, 'side': list(spec.side),
            'groups': recordspec.groups_of(spec),
            'admin_url': f'/admin/{meta.app_label}/{meta.model_name}/{obj.pk}/change/' if user.is_superuser else None,
            'list_url': f'/app/r/{meta.app_label}/{meta.model_name}',
            'version': record_version(obj, ()), 'locked': locked,
            'edit': [recordspec.editor(obj, n) for n in spec.edit],
            'can_change': bool(spec.edit) and _perm(user, model, 'change') and (not locked or not by_parent and can_edit_locked(obj, user)),
            'can_approve': isinstance(obj, Approvable) and not obj.is_approved and is_approver(user),
            'can_dispose': isinstance(obj, Nonconformance) and not obj.closed_at and is_approver(user)
            and _perm(user, model, 'change'),
            'dispose': [recordspec.editor(obj, n) for n in rules.DISPOSE_FIELDS] if isinstance(obj, Nonconformance) else None,
            'can_close': spec.close and not obj.closed_at and _perm(user, model, 'change'),
            'links': _links(obj, user),
            'requests': {'edit': _can_request(obj, EditRequest.EDIT, user),
                         'delete': _can_request(obj, EditRequest.DELETE, user)}}


class RecordDetailView(APIView):
    schema = None

    def get(self, request, label, pk):
        model, spec = _model(request.user, label)
        return Response(_detail(get_object_or_404(model, pk=pk), spec, request.user))

    def patch(self, request, label, pk):
        """범용 저장(REC-05): 설명서의 edit 칸만, full_clean(칸별 오류) → 잠금 규칙 저장. 서명 칸은 받지 않는다(REC-06)."""
        model, spec = _model(request.user, label)
        if not spec.edit:  # 보류 등 읽기 전용 기록
            raise PermissionDenied('이 기록은 화면에서 고칠 수 없습니다.')
        require_perm(request.user, f'{model._meta.app_label}.change_{model._meta.model_name}')
        obj = get_object_or_404(model, pk=pk)
        values = request.data.get('values')
        if not isinstance(values, dict):
            raise ValidationError('values가 필요합니다.')
        bad = {k: ['승인 서명으로만 바꿀 수 있습니다.' if k in recordspec.sign_fields(spec) else '이 화면에서 바꿀 수 없는 칸입니다.']
               for k in values if k not in spec.edit}
        if bad:
            raise ValidationError(bad)
        if _parent_locked(obj, spec) or is_locked(obj) and not can_edit_locked(obj, request.user):
            raise rules.Locked(rules.LOCKED_MSG)
        if request.data.get('version') != record_version(obj, ()):
            return Response({'detail': str(rules.Stale())}, status=409)
        form = modelform_factory(model, fields=spec.edit)({**model_to_dict(obj, fields=spec.edit), **values}, instance=obj)
        if not form.is_valid():
            raise ValidationError({k: list(v) for k, v in form.errors.items()})
        form.instance.validate_constraints()  # 폼은 고칠 수 없는 칸(예: 문서)이 낀 고유 조건을 건너뛴다
        rules.save_with_lock(form.instance, request.user)
        obj = model.objects.get(pk=obj.pk)
        return Response(_detail(obj, spec, request.user))


class RecordApproveView(APIView):
    schema = None

    def post(self, request, label, pk):
        model, spec = _model(request.user, label)
        if not issubclass(model, Approvable):
            raise Http404
        obj = get_object_or_404(model, pk=pk)
        rules.approve(obj, request.user, request.data.get('password', ''))
        return Response(_detail(model.objects.get(pk=pk), spec, request.user))


class RecordDisposeView(APIView):
    schema = None

    def post(self, request, label, pk):
        """부적합 MRB 처분(REC-08): rules.dispose_nc가 비밀번호·필수칸·처분 규칙·보류 해제를 관리 화면과 같게 처리한다."""
        model, spec = _model(request.user, label)
        if model is not Nonconformance:
            raise Http404
        require_perm(request.user, 'core.change_nonconformance')
        nc = get_object_or_404(model, pk=pk)
        data = {k: v for k, v in request.data.items() if k != 'password'}
        rules.dispose_nc(nc, request.user, request.data.get('password', ''), data)
        return Response(_detail(model.objects.get(pk=pk), spec, request.user))


class RecordCloseView(APIView):
    schema = None

    def post(self, request, label, pk):
        """종결(REC-09): 설명서 close=True인 기록만. change_ 권한, 종결 규칙은 모델 clean."""
        model, spec = _model(request.user, label)
        if not spec.close:
            raise Http404
        require_perm(request.user, f'{model._meta.app_label}.change_{model._meta.model_name}')
        rules.close_record(get_object_or_404(model, pk=pk), request.user)
        return Response(_detail(model.objects.get(pk=pk), spec, request.user))


class RecordRequestView(APIView):
    schema = None

    def post(self, request, label, pk):
        """수정·삭제 요청. 시스템 관리자는 요청과 동시에 실행된다(rules.submit_edit_request)."""
        model, _ = _model(request.user, label)
        obj = get_object_or_404(model, pk=pk)
        kind = request.data.get('kind')
        rules.check_edit_request(obj, kind, request.user)
        req, decide_error = rules.submit_edit_request(obj, request.user, kind, request.data.get('reason'),
                                                      request.data.get('password'))
        deleted = kind == EditRequest.DELETE and req.status == EditRequest.APPROVED
        return Response({'status': req.status, 'deleted': deleted, 'error': decide_error,
                         'decide_url': reverse('edit_request_decide', args=[req.pk]) if decide_error else None}, status=201)


class RecordHistoryView(APIView):
    schema = None

    def get(self, request, label, pk):
        model, _ = _model(request.user, label)
        get_object_or_404(model, pk=pk)
        rows = [audit.row_payload(h) for h in audit.rows(model, pk)[:PAGE_SIZE]]
        # 이 기록에 붙은 첨부·메모의 이력도 같이 보인다(보기 권한이 있을 때). 메모를 다른 기록으로 옮기면 옮긴 뒤 줄은 그쪽에 나온다.
        from core.models import Attachment
        from qms.models import Memo
        ct = ContentType.objects.get_for_model(model)
        for side, name, perm in ((Attachment, '첨부', 'core.view_attachment'), (Memo, '메모', 'qms.view_memo')):
            if not request.user.has_perm(perm):
                continue
            qs = side.history.filter(content_type_id=ct.pk, object_id=pk).select_related('history_user').order_by('-history_date')
            for h in qs[:PAGE_SIZE]:
                r = audit.row_payload(h)
                r.update(kind=name, type=f"{name} {SIDE_TYPES[r['type']]}: {r['object_repr']}")
                rows.append(r)
        rows.sort(key=lambda r: datetime.fromisoformat(r['date']), reverse=True)
        return Response({'results': rows[:PAGE_SIZE]})
