from django.conf import settings

from .nav import HOME, app_href, visible_nav
from .views import find_logo


def _under(path, url):
    base = url.partition('?')[0]
    return base.startswith('/admin/') and base != '/admin/' and path.startswith(base)


def shell(request):
    user = request.user
    groups, where = [], ''
    if user.is_authenticated and user.is_staff:
        here = (request.path, request.get_full_path())
        for name, items in visible_nav(user):
            # 링크는 새 화면으로, 현재 메뉴·묶음 판정은 관리 주소로 (관리 목록 안의 추가·변경 화면도 그 목록의 묶음으로 본다)
            links = [{'label': label, 'url': app_href(url), 'current': url in here, 'admin': url} for label, url in items]
            active = any(l['current'] or _under(request.path, l['admin']) for l in links)
            groups.append({'name': name, 'links': links, 'active': active, 'open': active or name == HOME})
            where = where or (name if active else '')
    # 직접 만든 화면엔 관리 화면이 넣어 주는 이 값이 없어 base.html이 사이드바 블록을 건너뛴다
    # nav_where: 지금 화면이 속한 묶음 이름 (페이지 머리의 '현재 위치')
    return {'is_nav_sidebar_enabled': True, 'nav_groups': groups, 'nav_where': where, 'brand_logo': find_logo() is not None}
