from django.utils.cache import add_never_cache_headers


def no_store_pages(get_response):
    """로그인 사용자의 HTML 화면은 브라우저가 저장하지 않게 한다(no-store).
    저장 후 뒤로가기 때 예전 화면 대신 서버의 최신 내용을 다시 받는다."""
    def middleware(request):
        response = get_response(request)
        if request.user.is_authenticated and response.get('Content-Type', '').startswith('text/html'):
            add_never_cache_headers(response)
        return response
    return middleware


class ModuleGate:
    """꺼진 모듈(core/modules.py)의 화면·API를 닫는다. 일반 사용자는 404, 시스템 관리자는 조회(GET)만.
    SPA 껍데기(/app/)는 기본 플랫폼이라 열리고, React가 me.modules로 「비활성 모듈」 안내를 보인다."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from django.http import Http404, HttpResponseForbidden, JsonResponse

        from core import modules
        key = modules.module_of_request(request, view_kwargs)
        if key == modules.BASE:
            return None
        code = modules.blocked(request, key)
        if code is None:
            return None
        detail = '비활성 모듈입니다.' if code == 404 else '비활성 모듈은 조회만 할 수 있습니다.'
        if request.path_info.startswith('/api/'):
            return JsonResponse({'detail': detail, 'code': 'module_inactive'}, status=code)
        if code == 403:
            return HttpResponseForbidden(detail)
        raise Http404(detail)
