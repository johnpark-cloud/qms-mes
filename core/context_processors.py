from django.conf import settings

from .nav import NAV, nav_url
from .views import find_logo


def _under(path, url):
    base = url.partition('?')[0]
    return base.startswith('/admin/') and base != '/admin/' and path.startswith(base)


def shell(request):
    user = request.user
    groups = []
    if user.is_authenticated and user.is_staff:
        here = (request.path, request.get_full_path())
        for name, items in NAV:
            links = [{'label': label, 'url': nav_url(url), 'current': nav_url(url) in here}
                     for label, url, perm in items if perm is None or user.has_perm(perm)]
            if links:
                # 지금 화면이 속한 묶음은 펼친다 (관리 목록 안의 추가·변경 화면도 그 목록의 묶음으로 본다)
                active = any(l['current'] or _under(request.path, l['url']) for l in links)
                groups.append({'name': name, 'links': links, 'active': active, 'open': active or name == '홈'})
    # 직접 만든 화면엔 관리 화면이 넣어 주는 이 값이 없어 base.html이 사이드바 블록을 건너뛴다
    return {'is_nav_sidebar_enabled': True, 'nav_groups': groups, 'brand_logo': find_logo() is not None}
