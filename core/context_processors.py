from django.conf import settings

from .nav import NAV, nav_url
from .views import find_logo


def shell(request):
    user = request.user
    groups = []
    if user.is_authenticated and user.is_staff:
        here = (request.path, request.get_full_path())
        for name, items in NAV:
            links = [{'label': label, 'url': nav_url(url), 'current': nav_url(url) in here}
                     for label, url, perm in items if perm is None or user.has_perm(perm)]
            if links:
                groups.append({'name': name, 'links': links})
    # 직접 만든 화면엔 관리 화면이 넣어 주는 이 값이 없어 base.html이 사이드바 블록을 건너뛴다
    return {'is_nav_sidebar_enabled': True, 'nav_groups': groups, 'brand_logo': find_logo() is not None}
