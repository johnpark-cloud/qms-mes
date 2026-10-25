from django import forms
from django.apps import apps
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from simple_history.admin import SimpleHistoryAdmin

from .models import BomLine, Hold, ImportProfile, Item, Lot, LotLink, Nonconformance, Process, Shipment, WorkOrder

admin.site.site_header = admin.site.site_title = 'QMS+MES'
admin.site.index_title = '메뉴'


class ReportLinksMixin:
    """변경 화면에 인쇄(PDF)·엑셀 양식 출력 링크를 붙인다."""

    @admin.display(description='출력')
    def report_links(self, obj):
        if not obj.pk:
            return '-'
        meta = obj._meta
        links = [(reverse('print', args=[meta.app_label, meta.model_name, obj.pk]), '인쇄/PDF')]
        templates = apps.get_model('qms', 'ExcelTemplate').objects.filter(target=ContentType.objects.get_for_model(obj))
        links += [(reverse('excel_report', args=[t.pk, obj.pk]), f'엑셀: {t.name}') for t in templates]
        return format_html_join(' · ', '<a href="{}" target="_blank">{}</a>', links)


class ApprovalAdminMixin:
    """승인 필드는 승인 서명 화면에서만 채워지고, 승인 후에는 전체가 읽기 전용이다."""

    @admin.display(description='승인')
    def approval(self, obj):
        if not obj.pk:
            return '저장 후 승인할 수 있습니다.'
        if obj.is_approved:
            return f'{obj.approved_by} · {obj.approved_at:%Y-%m-%d %H:%M}'
        url = reverse('approve', args=[obj._meta.app_label, obj._meta.model_name, obj.pk])
        return format_html('<a class="button" href="{}">승인 서명</a> (미승인)', url)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_approved:
            return [f.name for f in obj._meta.fields] + ['approval']
        return ['approval']

    def get_exclude(self, request, obj=None):
        return ['approved_by', 'approved_at']


class BomInline(admin.TabularInline):
    model = BomLine
    fk_name = 'parent'
    extra = 1
    autocomplete_fields = ['component']


@admin.register(Item)
class ItemAdmin(SimpleHistoryAdmin):
    list_display = ['code', 'name', 'item_type']
    search_fields = ['code', 'name']
    list_filter = ['item_type']
    inlines = [BomInline]


@admin.register(Process)
class ProcessAdmin(SimpleHistoryAdmin):
    list_display = ['code', 'name']
    search_fields = ['code', 'name']


@admin.register(WorkOrder)
class WorkOrderAdmin(SimpleHistoryAdmin):
    list_display = ['number', 'item', 'process', 'planned_qty', 'due_date', 'status']
    list_filter = ['status', 'process']
    search_fields = ['number', 'item__code']
    autocomplete_fields = ['item', 'process']


@admin.register(ImportProfile)
class ImportProfileAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'target', 'header_row']


class ParentLinkInline(admin.TabularInline):
    model = LotLink
    fk_name = 'child'
    extra = 1
    autocomplete_fields = ['parent']
    verbose_name = verbose_name_plural = '투입 LOT'


@admin.register(Lot)
class LotAdmin(SimpleHistoryAdmin):
    list_display = ['number', 'item', 'work_order', 'qty', 'supplier', 'is_hold', 'is_gap', 'created_at']
    search_fields = ['number', 'item__code', 'supplier']
    autocomplete_fields = ['item', 'work_order']
    inlines = [ParentLinkInline]

    @admin.display(boolean=True, description='보류')
    def is_hold(self, obj):
        return obj.on_hold

    @admin.display(boolean=True, description='계보 미등록')
    def is_gap(self, obj):
        return obj.lineage_gap


class NonconformanceForm(forms.ModelForm):
    password = forms.CharField(label='MRB 승인 비밀번호', required=False, widget=forms.PasswordInput,
                               help_text='처분을 입력할 때 품질팀장 본인의 비밀번호를 다시 입력합니다.')
    user = None  # NonconformanceAdmin.get_form이 요청 사용자로 채운다

    class Meta:
        model = Nonconformance
        exclude = ['approved_by']

    def clean(self):
        data = super().clean()
        if data.get('disposition') and not self.instance.closed_at:
            if not self.user.check_password(data.get('password') or ''):
                raise forms.ValidationError('MRB 승인 비밀번호가 맞지 않습니다.')
            self.instance.approved_by = self.user
        return data


@admin.register(Nonconformance)
class NonconformanceAdmin(ReportLinksMixin, SimpleHistoryAdmin):
    form = NonconformanceForm
    list_display = ['__str__', 'lot', 'defect_type', 'detected_at', 'disposition', 'approved_by', 'closed_at']
    list_filter = ['disposition', 'defect_type']
    search_fields = ['lot__number', 'description']
    autocomplete_fields = ['lot']

    def get_readonly_fields(self, request, obj=None):
        locked = ['lot', 'description', 'detected_at', 'disposition', 'customer_approval_ref'] if obj and obj.closed_at else []
        return locked + ['approved_by', 'closed_at', 'report_links']

    def get_form(self, request, obj=None, **kwargs):
        return type('Form', (super().get_form(request, obj, **kwargs),), {'user': request.user})


@admin.register(Hold)
class HoldAdmin(SimpleHistoryAdmin):
    list_display = ['lot', 'nonconformance', 'created_at', 'released_at']
    list_filter = [('released_at', admin.EmptyFieldListFilter)]

    # 보류는 부적합 등록·처분으로만 생기고 풀린다
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Shipment)
class ShipmentAdmin(SimpleHistoryAdmin):
    list_display = ['lot', 'customer', 'qty', 'shipped_at']
    search_fields = ['lot__number', 'customer']
    autocomplete_fields = ['lot']
