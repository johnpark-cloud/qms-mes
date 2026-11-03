"""검사 입력 API. 옛 htmx 화면(qms/views.py inspect_*)과 같은 qms.rules 함수를 쓴다."""
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import require_perm
from core.export import table_xlsx, xlsx_response
from core.models import Hold, Item, Lot
from qms.models import Gauge, Inspection, InspectionSpec
from qms.rules import RECEIVE_MSG, measurement, receive_lot, submit_inspection

from .specs import BAD_BODY, PAGE_SIZE, _bad

PERM = 'qms.add_inspection'
QUEUE_COLUMNS = ['LOT', '품번', '품명', '협력사', '수량', '생성일', '보류']


def _int(v):
    """JSON 정수 또는 ASCII 숫자 글만 id로 받는다(True·'a'·'²'·None·DB 범위 밖은 None)."""
    if isinstance(v, str) and v.isascii() and v.isdigit():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v if 0 <= v < 2**63 else None  # 더 크면 SQLite가 OverflowError를 낸다


def _str(v):
    return v if isinstance(v, str) else ''


def _qty(d):
    return format(d.normalize(), 'f')


def _lot(lot, on_hold=None):
    return {'id': lot.pk, 'number': lot.number, 'item_code': lot.item.code, 'item_name': lot.item.name,
            'supplier': lot.supplier, 'qty': _qty(lot.qty), 'on_hold': lot.on_hold if on_hold is None else on_hold}


def _specs(lot):
    done = set(Inspection.objects.filter(lot=lot).values_list('spec__inspection_type', flat=True))
    return [{'id': s.pk, 'title': str(s), 'inspection_type': s.inspection_type,
             'inspection_type_display': s.get_inspection_type_display(), 'done': s.inspection_type in done}
            for t, _ in InspectionSpec.TYPES if (s := InspectionSpec.current(lot.item, t))]


def _values(raw):
    """{"<id>": 글} → {int id: 글}. 숫자가 아닌 키와 글이 아닌 값은 버린다(그러면 판정이 '값을 입력하세요'로 거부한다)."""
    return {_int(k): v for k, v in raw.items() if isinstance(k, str) and _int(k) is not None and isinstance(v, str)}


class QueueView(APIView):
    """검사 대기: 그 구분의 승인된 기준이 있고 그 구분 검사가 아직 없는 LOT. 오래된 순."""
    schema = None

    def get(self, request):
        require_perm(request.user, PERM)
        tab = request.query_params.get('tab')
        tab = tab if tab in dict(InspectionSpec.TYPES) else InspectionSpec.INCOMING
        q = request.query_params.get('q', '').strip()
        approved = InspectionSpec.objects.filter(item=OuterRef('item'), inspection_type=tab, approved_at__isnull=False)
        qs = (Lot.objects.select_related('item')
              .filter(Exists(approved), ~Exists(Inspection.objects.filter(lot=OuterRef('pk'), spec__inspection_type=tab)))
              .annotate(held=Exists(Hold.objects.filter(lot=OuterRef('pk'), released_at__isnull=True)),
                        spec_id=Subquery(approved.order_by('-revision').values('pk')[:1]))
              .order_by('created_at', 'pk'))
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(item__code__icontains=q) | Q(supplier__icontains=q))
        if request.query_params.get('export') == 'xlsx':
            rows = [[x.number, x.item.code, x.item.name, x.supplier, _qty(x.qty),
                     timezone.localtime(x.created_at).strftime('%Y-%m-%d'), '보류' if x.held else ''] for x in qs]
            return xlsx_response(table_xlsx('검사 대기', QUEUE_COLUMNS, rows), '검사 대기.xlsx')
        try:
            page = min(max(int(request.query_params.get('page', 1)), 1), 10**6)
        except ValueError:
            page = 1
        count = qs.count()
        start = (page - 1) * PAGE_SIZE
        return Response({'count': count, 'page': page, 'has_more': start + PAGE_SIZE < count,
                         'results': [{**_lot(x, x.held), 'created_at': x.created_at.isoformat(), 'spec_id': x.spec_id}
                                     for x in qs[start:start + PAGE_SIZE]]})


class LotLookupView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, PERM)
        number = request.query_params.get('number', '').strip()
        if not number:
            return _bad('LOT 번호를 입력하세요.', 'number')
        lot = Lot.objects.filter(number=number).select_related('item').first()
        if lot:
            return Response({'lot': _lot(lot), 'specs': _specs(lot)})
        body = {'detail': '등록되지 않은 LOT입니다.', 'can_receive': request.user.has_perm('core.add_lot')}
        if body['can_receive']:  # 입고 권한이 없으면 품목·협력사 목록도 주지 않는다
            with_spec = InspectionSpec.objects.filter(approved_at__isnull=False).values('item')
            body['items'] = [{'value': i.pk, 'label': str(i)} for i in Item.objects.filter(pk__in=with_spec).order_by('code')]
            body['suppliers'] = list(Lot.objects.exclude(supplier='').order_by('supplier')
                                     .values_list('supplier', flat=True).distinct())
        return Response(body, status=404)


class ReceiveView(APIView):
    schema = None

    def post(self, request):
        require_perm(request.user, PERM)
        require_perm(request.user, 'core.add_lot')
        d = request.data
        if not isinstance(d, dict):
            return _bad(BAD_BODY)
        qty = d.get('qty')
        qty = str(qty) if isinstance(qty, (int, float)) and not isinstance(qty, bool) else _str(qty)
        item_id = _int(d.get('item'))
        item = Item.objects.filter(pk=item_id).first() if item_id else None
        try:
            lot, created = receive_lot(_str(d.get('number')).strip(), item, qty, _str(d.get('supplier')))
        except ValidationError:
            return _bad(RECEIVE_MSG)
        return Response({'lot': _lot(lot), 'specs': _specs(lot), 'created': created}, status=201 if created else 200)


class FormView(APIView):
    schema = None

    def get(self, request, lot_id, spec_id):
        from qms.views import DEFECT_TYPES  # 옛 화면과 같은 목록(옮기지 않는다)
        require_perm(request.user, PERM)
        lot = get_object_or_404(Lot.objects.select_related('item'), pk=lot_id)
        spec = get_object_or_404(InspectionSpec, pk=spec_id, approved_at__isnull=False)
        today = timezone.localdate()
        return Response({
            'lot': _lot(lot), 'spec': {'id': spec.pk, 'title': str(spec), 'sampling': spec.sampling},
            'characteristics': [{'id': c.pk, 'name': c.name, 'spec_text': c.spec_text(), 'unit': c.unit,
                                 'is_variable': c.is_variable, 'special': c.special}
                                for c in spec.characteristics.order_by('pk')],
            'gauges': [{'value': g.pk, 'label': str(g)} for g in Gauge.objects.filter(active=True).order_by('number')
                       if g.usable_on(today)],
            'defect_types': DEFECT_TYPES,
        })


class CheckView(APIView):
    """입력 즉시 항목별 합부(저장하지 않음). 숫자가 아니거나 OK/NG가 아니면 null."""
    schema = None

    def post(self, request):
        require_perm(request.user, PERM)
        d = request.data
        if not isinstance(d, dict) or not isinstance(d.get('values'), dict) or _int(d.get('spec')) is None:
            return _bad(BAD_BODY)
        spec = get_object_or_404(InspectionSpec, pk=_int(d['spec']))
        raw = d['values']
        results = {}
        for c in spec.characteristics.all():
            if str(c.pk) in raw:
                v = raw[str(c.pk)]
                m = measurement(c, v) if isinstance(v, str) else None
                results[str(c.pk)] = None if m is None else m.passed
        return Response({'results': results})


class SubmitView(APIView):
    """판정. 실패하면 검사·측정값은 하나도 남지 않는다(submit_inspection의 트랜잭션)."""
    schema = None

    def post(self, request):
        require_perm(request.user, PERM)
        d = request.data
        if not isinstance(d, dict):
            return _bad(BAD_BODY)
        if not isinstance(d.get('values'), dict):
            return _bad('측정값 형식이 올바르지 않습니다.', 'values')
        lot_id, spec_id = _int(d.get('lot')), _int(d.get('spec'))
        if lot_id is None or spec_id is None:
            return _bad(BAD_BODY)
        gauge = None
        if d.get('gauge') is not None:
            gauge_id = _int(d['gauge'])
            if gauge_id is None:
                return _bad(BAD_BODY, 'gauge')
            gauge = Gauge.objects.filter(pk=gauge_id).first()
            if gauge is None:
                return _bad('계측기를 찾을 수 없습니다.', 'gauge')
        lot, spec = get_object_or_404(Lot, pk=lot_id), get_object_or_404(InspectionSpec, pk=spec_id)
        qty = d.get('defect_qty')
        qty = str(qty) if isinstance(qty, (int, float)) and not isinstance(qty, bool) else (qty if isinstance(qty, str) else None)
        try:
            insp = submit_inspection(lot, spec, request.user, gauge, _values(d['values']), _str(d.get('defect_type')), qty)
        except ValidationError as e:
            return _bad(' '.join(e.messages))
        nc = insp.nonconformance
        return Response({'id': insp.pk, 'result': insp.result, 'result_display': insp.get_result_display(),
                         'nonconformance': {'id': nc.pk, 'number': nc.number} if nc else None}, status=201)
