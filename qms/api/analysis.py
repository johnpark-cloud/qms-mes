"""분석 화면 API: 품질 KPI·공급자 평가·SPC 관리도. 숫자 계산은 qms/kpi.py·qms/spc.py(옛 서버 화면과 같은 함수)."""
from urllib.parse import urlencode

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import require_perm
from core.models import Partner
from qms import kpi, spc
from qms.models import Characteristic


def _months(request):
    try:
        return min(max(int(request.query_params.get('months', 6)), 1), 36)
    except ValueError:
        return 6


def _num(v):
    return None if v is None else float(v)


class KpiView(APIView):
    schema = None

    def get(self, request):
        # 옛 화면(qms/views.py kpi_view)과 같은 권한: PPM·COPQ는 클레임·비용 자료라 클레임 보기 권한이 있어야 한다
        require_perm(request.user, 'qms.view_customerclaim')
        months = _months(request)
        show = {area: kpi.can_see(request.user, area) for area in kpi.KPI_DEPARTMENTS}  # 소속 부서 KPI만
        rows = [{'month': r['month'].strftime('%Y-%m'), 'shipped': _num(r['shipped']), 'claims': r['claims'], 'ppm': r['ppm'],
                 'fpy': r['fpy'], 'd3_on_time': r['d3_on_time'], 'copq': _num(r['copq'])}
                for r in kpi.monthly(months)] if show['quality'] else []
        pareto = [{'defect_type': p['defect_type'], 'n': p['n'], 'qty': _num(p['qty']), 'share': p['share'], 'cum': p['cum']}
                  for p in kpi.pareto(months)] if show['quality'] else []
        yields = [{**y, 'input': _num(y['input']), 'good': _num(y['good']), 'defect': _num(y['defect'])}
                  for y in kpi.process_yield(months)] if show['yield'] else []
        return Response({'months': months, 'show': show, 'rows': rows, 'pareto': pareto, 'yields': yields})


class SuppliersView(APIView):
    schema = None

    def get(self, request):
        require_perm(request.user, 'qms.view_scar')
        months = _months(request)
        return Response({'months': months, 'rows': [{**r, 'received': _num(r['received'])} for r in kpi.suppliers(months)],
                         'can_grade': request.user.has_perm('core.change_partner')})


class SupplierGradeView(APIView):
    """공급자 성적표의 「등급 반영」: 거래처 평가 등급·평가일을 고친다(변경 이력은 거래처 이력에 남는다)."""
    schema = None

    def post(self, request):
        require_perm(request.user, 'core.change_partner')
        grade = str(request.data.get('grade') or '')
        if grade not in dict(Partner.GRADE_CHOICES):
            return Response({'detail': '등급은 A·B·C·D 중 하나입니다.'}, status=400)
        partner = get_object_or_404(Partner, pk=request.data.get('partner'))
        if not partner.is_supplier:
            return Response({'detail': '공급자(자재·부품)인 거래처만 등급을 반영합니다.'}, status=400)
        partner.grade, partner.evaluated_on = grade, timezone.localdate()
        partner.full_clean()
        partner.save()
        return Response({'partner': partner.pk, 'grade': partner.grade, 'evaluated_on': partner.evaluated_on.isoformat()})


class SpcView(APIView):
    schema = None

    def get(self, request, pk):
        require_perm(request.user, 'qms.view_measurement')
        char = get_object_or_404(Characteristic.objects.select_related('spec__item'), pk=pk)
        out = {'title': f'SPC · {char.spec.item.code} {char.name}', 'name': char.name, 'item': char.spec.item.code,
               'lsl': _num(char.lsl), 'usl': _num(char.usl), 'unit': char.unit, 'special': char.special}
        try:
            res = spc.control_chart(char.spc_series(limit=100), char.lsl, char.usl)
        except ValueError as e:
            return Response({**out, 'error': str(e)})
        points = []
        for p in res['points']:
            insp = p['label']
            nc = '/app/nc-new?' + urlencode({'lot': insp.lot.number, 'origin': char.spec.inspection_type, 'description':
                                             f'SPC 경보 {char.name}: {", ".join(p["alarms"])} (검사 {insp.pk})'}) if p['alarms'] else None
            points.append({'inspection': insp.pk, 'lot': str(insp.lot), 'lot_id': insp.lot_id,
                           'inspected_at': insp.inspected_at.isoformat() if insp.inspected_at else None,
                           'xbar': _num(p['xbar']), 'r': _num(p['r']), 'alarms': p['alarms'], 'nc_url': nc})
        return Response({**out, 'kind': res['kind'], 'n': res['n'], 'sigma': _num(res['sigma']), 'cpk': _num(res['cpk']),
                         'limits': {k: _num(v) for k, v in res['limits'].items()}, 'points': points})
