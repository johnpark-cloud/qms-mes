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
