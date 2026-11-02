from rest_framework.response import Response
from rest_framework.views import APIView

from qms.overview import sections


class OverviewView(APIView):
    schema = None  # 직렬화기 없이 dict를 그대로 돌려주므로 OpenAPI 문서에는 넣지 않는다

    def get(self, request):
        return Response({'sections': [{'name': name, 'cards': cards} for name, cards in sections(request.user)]})
