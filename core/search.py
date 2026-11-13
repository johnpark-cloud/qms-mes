from django.apps import apps
from django.urls import reverse
from django.utils.http import urlencode

from .modules import active_set, module_of_model, module_of_path

# (동작 이름, url 이름). 이후 태스크가 항목을 추가한다.
ACTIONS = [('부적합 등록', 'nc_quick'), ('검사 입력', 'inspect'), ('LOT 이력 (추적)', 'trace'), ('KPI', 'kpi'), ('메모', 'memo_new'), ('심사 자료 출력', 'audit_pack'), ('연차·급여', 'me')]
LIMIT = 10
# (앱, 모델, 번호 필드, 표시 이름)
NUMBERED = [('core', 'nonconformance', '부적합'), ('qms', 'capa', 'CAPA'), ('qms', 'customerclaim', '8D'), ('qms', 'scar', 'SCAR')]


def _admin(app, model, obj):
    from .relations import record_url
    return record_url(obj)


def search(user, q):
    q = (q or '').strip()
    out, on, hidden = [], active_set(), 0

    def can(app, model):
        return user.has_perm(f'{app}.view_{model}')

    def add(label, sub, url, exact=False):
        out.append({'label': label, 'sub': sub, 'url': url, 'exact': exact})

    lots = apps.get_model('core', 'lot').objects if can('core', 'lot') else None
    trace = lambda lot: f"{reverse('trace')}?{urlencode({'lot': lot.number})}"
    if lots is not None and q:
        for lot in lots.filter(number__iexact=q).select_related('item')[:1]:
            add(lot.number, f'LOT · {lot.item.code}', trace(lot), exact=True)
    for name, url in ACTIONS:
        if q and q.lower() in name.lower() and module_of_path(reverse(url).lstrip('/')) in on:
            add(name, '동작', reverse(url))
    if len(q) >= 2:
        if lots is not None:
            for lot in lots.filter(number__icontains=q).exclude(number__iexact=q).select_related('item')[:LIMIT]:
                add(lot.number, f'LOT · {lot.item.code}', trace(lot))
        if can('core', 'item'):
            Item = apps.get_model('core', 'item')
            from django.db.models import Q
            for it in Item.objects.filter(Q(code__icontains=q) | Q(name__icontains=q))[:LIMIT]:
                add(it.code, f'품번 · {it.name}', _admin('core', 'item', it))
        for app, model, kind in NUMBERED:
            if not can(app, model):
                continue
            found = apps.get_model(app, model).objects.filter(number__icontains=q)
            if module_of_model(f'{app}.{model}') not in on:  # 꺼진 모듈 기록은 감추지 않고 건수로만(MOD-11)
                hidden += found.count()
                continue
            for o in found[:LIMIT]:
                add(o.number, kind, _admin(app, model, o))
        if lots is not None:
            # 협력사는 LOT의 자유 입력 칸이라 별도 모델이 없다
            sup = lots.filter(supplier__icontains=q).values_list('supplier', flat=True).distinct()[:LIMIT]
            for s in sup:
                add(s, '협력사', reverse('suppliers'))
    if hidden:
        out.insert(0, {'label': f'비활성 모듈 기록 {hidden}건', 'sub': '모듈이 꺼져 있어 열 수 없습니다', 'url': '', 'exact': False})
    return out[:LIMIT]
