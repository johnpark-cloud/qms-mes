import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from qms.overview import sections
from qms.widgets import WIDGETS, layout_for, save_layout, todo_items, valid_layout, widget_data


class OverviewView(APIView):
    schema = None  # 직렬화기 없이 dict를 그대로 돌려주므로 OpenAPI 문서에는 넣지 않는다

    def get(self, request):
        return Response({'sections': [{'name': name, 'cards': cards} for name, cards in sections(request.user)]})


class TodoView(APIView):
    schema = None  # dict를 그대로 돌려준다

    def get(self, request):
        d = todo_items(request.user)
        widgets = []
        for w in layout_for(request.user):
            widget = WIDGETS[w['key']]
            try:
                data, error = widget_data(widget, request, d, w['size']), False
            except Exception:  # 위젯 하나가 깨져도 화면은 떠야 한다
                logging.getLogger('qms').exception('위젯 불러오기 실패: %s', widget.key)
                data, error = None, True
            widgets.append({**w, 'title': widget.title, 'data': data, 'error': error})
        return Response({'widgets': widgets,
                         'available': [{'key': k, 'title': w.title} for k, w in WIDGETS.items() if w.allowed(request.user)]})


class DashboardSaveView(APIView):
    schema = None

    def post(self, request):
        """본문 [{key, size, x?, y?}]로 내 배치를 저장한다. 빈 배열이면 기본 배치로 돌아간다."""
        if not valid_layout(request.user, request.data):
            return Response({'detail': '저장할 수 없는 위젯 배치입니다.'}, status=400)
        save_layout(request.user, request.data)
        return Response({'ok': True})
