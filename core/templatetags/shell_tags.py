import re

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

# Django 관리 화면 경로의 앱 칸: <li><a href="/admin/core/">MES · 부적합</a></li>
APP_CRUMB = re.compile(r'<li><a href="/admin/[a-z_]+/">[^<]*</a></li>')


@register.filter
def crumb_where(html, where):
    """경로(breadcrumbs)의 앱 이름을 사이드바 묶음 이름으로 바꾼다. 묶음을 모르면 앱 칸을 뺀다(앱 이름은 업무와 안 맞는다)."""
    return mark_safe(APP_CRUMB.sub(format_html('<li>{}</li>', where) if where else '', str(html), count=1))
