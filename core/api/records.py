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
        obj = rules.save_new(model, spec.create, request.user, values)
        return Response({'id': obj.pk, 'url': record_url(obj)}, status=201)


NO_ADD = {'core.hold', 'qms.ppapelement'}  # 보류는 부적합 등록으로, PPAP 요소는 제출마다 저절로 생긴다


def _new_url(model, spec):
    meta = model._meta
    if meta.label_lower == 'core.nonconformance':
        return '/app/nc-new'  # 보류 인터록이 걸리는 현장 간편 등록
    if meta.label_lower in NO_ADD:
        return None
    # 파일·JSON 칸이 필수인 양식(엑셀 양식·가져오기 설정 등)만 관리 화면 추가 폼
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
        # 처음 값: 담당자는 나, 그 밖은 주소 ?칸=값(예: CAPA 만들기 → 출처·제목). create에 없는 칸은 버린다
        init = {'owner': str(request.user.pk)} if 'owner' in spec.create else {}
        init.update({k: v for k, v in request.query_params.items() if k in spec.create})
        fields = []
        for n in spec.create:
            d = recordspec.creator(model, n, form)
            if n in init:
                d['value'] = init[n] in ('1', 'true', 'True') if d['type'] == 'bool' else init[n]
            if n in spec.hidden:
                d['hidden'] = True
            fields.append(d)
        return Response({'title': str(model._meta.verbose_name), 'list_url': f'/app/r/{model._meta.app_label}/{model._meta.model_name}',
                         'fields': fields,
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


def capa_new_url(obj, title=None):
    """CAPA 새로 만들기 화면 주소(출처·제목 채움). obj는 CAPA_SOURCE 기록."""
    query = {'source': CAPA_SOURCE[obj._meta.label_lower], 'source_type': ContentType.objects.get_for_model(obj).pk,
             'source_id': obj.pk, 'title': (title or str(obj))[:200]}
    return '/app/r/qms/capa/new?' + urlencode(query)


def repeat_title(group):
    from qms.due import REPEAT_DAYS  # core → qms는 함수 안에서만(docs/architecture.md 의존 방향)
    return f"반복 부적합: {group['item'].code} {group['defect_type']} (최근 {REPEAT_DAYS}일 {len(group['ncs'])}건)"


def _notices(obj, user):
    """기록 위 안내 띠. 반복 부적합이면 CAPA를 제안한다(CAPA 모듈이 켜져 있을 때만)."""
    if not isinstance(obj, Nonconformance) or not modules.active('qms_capa'):
        return []
    from qms.due import REPEAT_DAYS, repeat_group_of
    group = repeat_group_of(obj)
    if not group:
        return []
    message = (f"같은 품번({group['item'].code})·같은 유형({group['defect_type']}) 부적합이 최근 {REPEAT_DAYS}일 동안 "
               f"CAPA 없이 {len(group['ncs'])}건입니다. 시정조치(CAPA)를 만드세요.")
    can = user.has_perm('qms.add_capa')
    return [{'message': message, 'label': 'CAPA 만들기' if can else '',
             'url': capa_new_url(group['latest'], repeat_title(group)) if can else ''}]


def _links(obj, user):
    """「⋯」 메뉴 바로가기: LOT 이력 추적, CAPA 만들기(새로 만들기 화면, 출처 채움 — CAPA 모듈이 켜져 있을 때만)."""
    label = obj._meta.label_lower
    links = []
    lot = obj if isinstance(obj, Lot) else obj.lot if label == 'qms.customerclaim' else None
    if lot:
        links.append({'label': 'LOT 이력 (추적)', 'url': trace_url(lot.number)})
    if label in CAPA_SOURCE and modules.active('qms_capa') and user.has_perm('qms.add_capa'):
        links.append({'label': 'CAPA 만들기', 'url': capa_new_url(obj)})
    return links


def _child_add_url(rel, parent, user):
    """하위 표의 「추가」: 하위 기록에 새로 만들기 칸이 있고 부모 외래키가 그 칸이면 부모를 채운 새로 만들기 화면."""
    model = rel.model
    child = recordspec.SPECS.get(model._meta.label_lower)
    fk = getattr(rel, 'field', None)
    if not child or not fk or fk.name not in child.create or not _perm(user, model, 'add'):
        return None
    key = modules.module_of_model(model._meta.label_lower)
    if key and not modules.active(key):
        return None
    return f'/app/r/{model._meta.app_label}/{model._meta.model_name}/new?{urlencode({fk.name: parent.pk})}'


def _parent_locked(obj, spec):
    return bool(spec.lock_parent) and is_locked(getattr(obj, spec.lock_parent))


def _detail(obj, spec, user):
    model = type(obj)
    fields = []
    for n in spec.fields:
        text, url = recordspec.value_of(obj, n)
        fields.append({'key': n, 'label': recordspec.label_of(model, n), 'value': text, 'url': url})
    meta = model._meta
    by_parent = _parent_locked(obj, spec)
    locked = by_parent or is_locked(obj)
    children = []
    for c in spec.children:
        rel = getattr(obj, c.accessor)
        children.append({'key': c.accessor, 'label': c.label, 'columns': _columns(rel.model, c.fields),
                         'rows': [_row(o, c.fields) for o in rel.all().order_by(*c.order)],
                         'add_url': None if locked else _child_add_url(rel, obj, user)})
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
            'notices': _notices(obj, user),
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
        rules.assert_editable(obj, request.user, spec.lock_parent)
        if request.data.get('version') != record_version(obj, ()):
            return Response({'detail': str(rules.Stale())}, status=409)
        rules.save_edit(obj, spec.edit, request.user, values)
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
