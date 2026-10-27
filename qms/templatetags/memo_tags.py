from django import template

from qms.memo import box_context
from qms.models import Memo

register = template.Library()


@register.inclusion_tag('qms/memo_list.html', takes_context=True)
def memo_box(context, obj):
    if isinstance(obj, Memo):  # 메모에 메모를 달지 않는다
        return {'hide': True}
    return box_context(obj, context['request'].user)
