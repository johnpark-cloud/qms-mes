"""records API: 기록 설명서(core/recordspec.py)로 목록·상세·변경 이력을 준다(REC-02).

권한은 그 모델의 view_ 권한. 변경 이력도 view_ 권한이면 본다(미결 #6, 2026-11-13 사용자 결정).
꺼진 모듈은 미들웨어가 주소의 label 인자로 막는다.
"""
import difflib
import json
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
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core import audit, modules, recordspec, rules
from core.export import document_xlsx, table_xlsx, xlsx_response
from core.grid import record_version
from core.models import Approvable, EditRequest, Lot, Nonconformance, is_approver
from core.records import can_edit_locked, is_locked
from core.relations import is_registered, record_url, sheet_url, status_of, trace_url

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


def _sheets(obj):
    """증적(PPAP 요소·심사 증적)에 이어진 문서·기록을 양식지로 연다(W4)."""
    if obj._meta.label_lower not in ('qms.ppapelement', 'qms.evidence'):
        return []
    pairs = (('문서 양식지', obj.document), ('기록 양식지', obj.record))
    return [{'label': label, 'url': url} for label, o in pairs if o is not None and (url := sheet_url(o))]


def _row(obj, names):
    row = {'id': obj.pk, 'url': record_url(obj), 'status': status_of(obj), 'cells': recordspec.cells(obj, names)}
    if sheets := _sheets(obj):
        row['sheets'] = sheets
    return row


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
        if isinstance(values, str):  # 파일 칸이 있으면 multipart: values는 JSON 글, 파일은 칸 이름으로 온다
            try:
                values = json.loads(values)
            except ValueError:
                values = None
        if not isinstance(values, dict):
            raise ValidationError('values가 필요합니다.')
        bad = {k: ['이 화면에서 넣을 수 없는 칸입니다.'] for k in [*values, *request.FILES] if k not in spec.create}
        if bad:
            raise ValidationError(bad)
        obj = rules.save_new(model, spec.create, request.user, values, request.FILES)
        return Response({'id': obj.pk, 'url': record_url(obj)}, status=201)


NO_ADD = {'core.hold', 'qms.ppapelement'}  # 보류는 부적합 등록으로, PPAP 요소는 제출마다 저절로 생긴다
# 새로 만들기가 없는 종류: 주소로 들어오면 어디서 생기는지 알려 준다
NO_CREATE = {'core.nonconformance': '부적합은 부적합 등록 화면에서 등록합니다. 등록하면 LOT이 바로 보류됩니다.',
             'core.hold': '보류는 부적합을 등록하면 저절로 걸리고, 부적합 처분으로만 풀립니다.',
             'qms.ppapelement': 'PPAP 요소는 PPAP 제출을 만들면 저절로 생깁니다.'}


def _new_url(model, spec):
    meta = model._meta
    if meta.label_lower == 'core.nonconformance':
        return '/app/nc-new'  # 보류 인터록이 걸리는 현장 간편 등록
    if meta.label_lower in NO_ADD or not spec.create:
        return None
    return f'/app/r/{meta.app_label}/{meta.model_name}/new'


def _create_spec(user, label):
    model, spec = _model(user, label)
    if not spec.create:
        raise Http404
    require_perm(user, f'{model._meta.app_label}.add_{model._meta.model_name}')
    return model, spec


class RecordNewView(APIView):
    schema = None

    def get(self, request, label):
        if label.lower() in NO_CREATE:
            app_label, name = label.lower().split('.')
            return Response({'detail': NO_CREATE[label.lower()], 'list_url': f'/app/r/{app_label}/{name}',
                             'new_url': '/app/nc-new' if label.lower() == 'core.nonconformance' else None}, status=404)
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
    if label == 'core.nonconformance' and obj.is_approved:
        links.append({'label': '메일 보내기', 'url': f'/app/nc-mail/{obj.pk}'})
    return links + _sheets(obj)


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
        if n == spec.body:  # 본문은 아래 구역(_body)
            continue
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
            'status': status_of(obj), 'fields': fields, 'children': children, 'side': [s for s in spec.side if s == 'history' or is_registered(meta.label_lower)],
            'groups': recordspec.groups_of(spec), 'body': _body(obj, spec),
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


def _body(obj, spec):
    """본문 구역(W7): 값과 직전 개정과의 줄 비교 [[' '|'-'|'+', 줄], ...]."""
    if not spec.body:
        return None
    text, prev = getattr(obj, spec.body), getattr(obj, 'previous', None)
    diff = None
    if prev:
        lines = list(difflib.unified_diff(getattr(prev, spec.body).splitlines(), text.splitlines(), lineterm='', n=10**6))[2:]
        diff = [[s[0], s[1:]] for s in lines if not s.startswith('@@')]
    return {'label': recordspec.label_of(type(obj), spec.body), 'value': text, 'prev': str(prev) if prev else None, 'diff': diff}


def _history_table(model, pk):
    """개정 이력(W6): 변경 이력을 오래된 순으로. 처음 저장 = 신규, 칸이 바뀐 저장마다 Rev.n."""
    rows, n = [], 0
    for h in reversed(list(audit.rows(model, pk))):
        p = audit.row_payload(h)
        if h.history_type == '+':
            label = '신규'
        elif p['changes']:
            n += 1
            label = f'Rev.{n}'
        else:
            continue
        cut = lambda s: s if len(s) <= 40 else s[:39] + '…'  # noqa: E731
        rows.append([label, timezone.localtime(h.history_date).strftime('%Y-%m-%d %H:%M'), p['user'],
                     '; '.join(f"{c['field']}: {cut(c['old'])} → {cut(c['new'])}" for c in p['changes']) or '처음 작성'])
    return {'title': '개정 이력', 'columns': ['차수', '일시', '변경자', '변경 내용'], 'rows': rows}


def document_of(obj, spec):
    """양식지(W3): A4 한 장 문서(DocStruct, frontend/src/api/specs.ts). 구역은 recordspec.DOCS, 표는 print_table 또는 하위 기록."""
    model = type(obj)
    title, sections = recordspec.DOCS.get(model._meta.label_lower, (str(model._meta.verbose_name), ()))

    def kv(names):
        return [[recordspec.label_of(model, n), recordspec.value_of(obj, n)[0]] for n in names]

    def who(u):
        return (u.get_full_name() or u.username) if u else ''

    def day(t):
        return timezone.localtime(t).strftime('%Y-%m-%d') if t else ''

    head = [] if sections else kv(spec.fields)
    tables = [{'title': t, 'columns': ['항목', '내용'], 'rows': kv(names)} for t, names in sections]
    if hasattr(obj, 'print_table'):  # 부적합 보고서·출하성적서·PSW
        title, header, rows = obj.print_table()
        rows = [['' if c is None else str(c) for c in r] for r in rows]
        if header[0] == '구역':  # 부적합 ①~⑦: 구역마다 표 하나
            head = []
            for r in rows:
                if r[0]:
                    tables.append({'title': r[0], 'columns': ['항목', '내용'], 'rows': []})
                tables[-1]['rows'].append(r[1:])
        else:
            tables.append({'title': title, 'columns': header, 'rows': rows})
    else:
        for c in spec.children:
            rel = getattr(obj, c.accessor)
            tables.append({'title': c.label, 'columns': [recordspec.label_of(rel.model, n) for n in c.fields],
                           'rows': [list(recordspec.cells(o, c.fields).values()) for o in rel.all().order_by(*c.order)]})
    if model._meta.label_lower in recordspec.HISTORY_DOCS:
        tables.append(_history_table(model, obj.pk))
    # 작성 = 부적합은 발견자, 그 밖은 처음 저장한 사람
    first = obj.history.order_by('history_date', 'history_id').first() if hasattr(obj, 'history') else None
    return {'title': title, 'number': str(obj), 'revision': '', 'draft': hasattr(obj, 'approved_at') and obj.approved_at is None,
            'head': head, 'tables': tables, 'body': getattr(obj, spec.body) if spec.body else None,
            'revisions': obj.revision_rows() if hasattr(obj, 'revision_rows') else None,
            'photos': [{'url': p.file.url, 'caption': p.caption} for p in obj.photos.all()] if hasattr(obj, 'photos') else [],
            'signoff': {'written_by': who(getattr(obj, 'detected_by', None) or (first and first.history_user)), 'written_at': day(first and first.history_date),
                        'approved_by': who(getattr(obj, 'approved_by', None)), 'approved_at': day(getattr(obj, 'approved_at', None))}}


class RecordDocumentView(APIView):
    schema = None

    def get(self, request, label, pk):
        model, spec = _model(request.user, label)
        obj = get_object_or_404(model, pk=pk)
        doc = document_of(obj, spec)
        if request.query_params.get('export') == 'xlsx':
            return xlsx_response(document_xlsx(doc), f"{doc['title']}_{getattr(obj, 'number', obj.pk)}.xlsx")
        return Response(doc)


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


# 기록 설명서 없이 전용 화면이 있는 기록(core/relations.py record_url)도 같은 요청 API를 쓴다
DEDICATED = {'core.item', 'qms.inspectionspec', 'qms.controlplan', 'qms.inspection'}


class RecordRequestView(APIView):
    schema = None

    def post(self, request, label, pk):
        """수정·삭제 요청. 시스템 관리자는 요청과 동시에 실행된다(rules.submit_edit_request)."""
        if label in DEDICATED:
            model = apps.get_model(label)
            require_perm(request.user, f'{model._meta.app_label}.view_{model._meta.model_name}')
        else:
            model, _ = _model(request.user, label)
        obj = get_object_or_404(model, pk=pk)
        kind = request.data.get('kind')
        rules.check_edit_request(obj, kind, request.user)
        req, decide_error = rules.submit_edit_request(obj, request.user, kind, request.data.get('reason'),
                                                      request.data.get('password'))
        deleted = kind == EditRequest.DELETE and req.status == EditRequest.APPROVED
        return Response({'status': req.status, 'deleted': deleted, 'error': decide_error,
                         'decide_url': f'/app/requests/{req.pk}' if decide_error else None}, status=201)


def _request_payload(req):
    from core.records import blockers
    obj = req.target
    rows = []
    for f in obj._meta.concrete_fields if obj else ():
        value = getattr(obj, f'get_{f.name}_display', lambda: getattr(obj, f.name))()  # noqa: B023
        rows.append({'label': str(f.verbose_name), 'value': '' if value is None else str(value)})
    pending_delete = obj and req.kind == EditRequest.DELETE and req.status == EditRequest.PENDING
    return {'id': req.pk, 'kind': req.get_kind_display(), 'status': req.status, 'status_label': req.get_status_display(),
            'object_repr': req.object_repr, 'model': str(req.content_type.model_class()._meta.verbose_name),
            'target_url': obj and record_url(obj), 'reason': req.reason, 'requested_by': str(req.requested_by),
            'requested_at': req.requested_at, 'decided_by': req.decided_by and str(req.decided_by),
            'decided_at': req.decided_at, 'reject_reason': req.reject_reason, 'rows': rows,
            'blockers': [f'{o._meta.verbose_name}: {o}' for o in blockers(obj)] if pending_delete else []}


class EditRequestView(APIView):
    """요청 처리 화면(/app/requests/<번호>): 시스템 관리자만 보고 승인·거절한다(EditRequest.decide)."""
    schema = None

    def get(self, request, pk):
        if not request.user.is_superuser:
            raise PermissionDenied('시스템 관리자만 처리할 수 있습니다.')
        return Response(_request_payload(get_object_or_404(EditRequest, pk=pk)))

    def post(self, request, pk):
        if not request.user.is_superuser:
            raise PermissionDenied('시스템 관리자만 처리할 수 있습니다.')
        req = get_object_or_404(EditRequest, pk=pk)
        approve = request.data.get('approve') is True
        reason = request.data.get('reject_reason')
        reason = reason.strip() if isinstance(reason, str) else ''
        if not approve and not reason:
            raise ValidationError('거절 사유를 입력하세요.')
        req.decide(request.user, approve, reason)
        return Response(_request_payload(req))


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
