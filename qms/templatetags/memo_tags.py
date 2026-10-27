from django import template

from qms.memo import ATTACHABLE, box_context

register = template.Library()


@register.inclusion_tag('qms/memo_list.html', takes_context=True)
def memo_box(context, obj):
    if obj._meta.label_lower not in ATTACHABLE:
        return {'hide': True}
    return box_context(obj, context['request'].user)
