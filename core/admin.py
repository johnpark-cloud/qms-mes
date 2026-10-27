from django import forms
from django.apps import apps
from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from simple_history.admin import SimpleHistoryAdmin

from .models import (BomLine, Hold, ImportProfile, Item, Lot, LotLink, Nonconformance, Process, RoutingStep, Shipment,
                     WorkOrder, WorkResult)
from .records import blockers, can_edit_locked, delete_record, edit_unlocked, is_locked

admin.site.site_header = admin.site.site_title = 'QMS+MES'
admin.site.index_title = '메뉴'


class BaseAdmin(SimpleHistoryAdmin):
    """삭제는 시스템 관리자만. 그 외 사용자는 '삭제 요청'·'수정 요청'으로 관리자 승인을 받는다."""
    change_form_template = 'admin/qms_change_form.html'
    request_links_enabled = True

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop('delete_selected', None)
        return actions

    def get_list_display(self, request):
        # 표시 메서드는 request를 못 받으므로 사용자별 라벨은 열 이름으로 고른다
        cols = list(super().get_list_display(request))
        if self.request_links_enabled:
            cols.append('delete_link' if request.user.is_superuser else 'request_links')
        return cols

    def _delete_url(self, obj):
        return reverse('edit_request', args=['DELETE', obj._meta.app_label, obj._meta.model_name, obj.pk])

    @admin.display(description='요청')
    def request_links(self, obj):
        return format_html('<a href="{}">삭제 요청</a>', self._delete_url(obj))

    @admin.display(description='삭제')
    def delete_link(self, obj):
        return format_html('<a href="{}">삭제</a>', self._delete_url(obj))

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        context['request_links_enabled'] = self.request_links_enabled
        context['record_locked'] = obj is not None and is_locked(obj) and not can_edit_locked(obj, request.user)
        return super().render_change_form(request, context, add, change, form_url, obj)

    def save_model(self, request, obj, form, change):
        unlock = change and edit_unlocked(obj, request.user)
        obj._edit_unlocked = bool(unlock) or request.user.is_superuser
        if change and is_locked(obj) and not obj._edit_unlocked and not form.has_changed():
            return  # 잠긴 기록의 읽기 전용 폼을 그냥 저장하면 Approvable.save가 500을 낸다
        super().save_model(request, obj, form, change)
        if unlock:  # 저장이 성공했을 때만 잠금 해제를 소모한다 (changeform_view가 atomic이라 인라인 실패도 되돌린다)
            unlock.status = unlock.USED
            unlock.save()

    def save_formset(self, request, form, formset, change):
        if getattr(form.instance, '_edit_unlocked', False):
            for f in formset.forms:  # 부모의 잠금 해제를 항목(검사항목·관리계획 행 등)에도 넘긴다
                f.instance._edit_unlocked = True
        super().save_formset(request, form, formset, change)

    def get_deleted_objects(self, objs, request):
        # 부적합의 보류처럼 delete_record가 먼저 지우는 기록은 '삭제 불가' 목록에서 뺀다
        deleted, counts, perms_needed, _ = super().get_deleted_objects(objs, request)
        protected = [f'{o._meta.verbose_name}: {o}' for obj in objs for o in blockers(obj)]
        return deleted, counts, perms_needed - {Hold._meta.verbose_name}, protected

    def _delete(self, request, objs):
        try:
            for obj in objs:
                delete_record(obj)
        except ProtectedError as e:
            transaction.set_rollback(True)  # 삭제 기록(LogEntry)까지 되돌린다
            request._delete_failed = True
            self.message_user(request, '먼저 지워야 할 기록: ' + ', '.join(map(str, e.protected_objects)), messages.ERROR)

    def delete_model(self, request, obj):
        self._delete(request, [obj])

    def delete_queryset(self, request, queryset):
        # shortcut: 경합으로 여기서 막히면 '선택 항목 삭제'의 성공 메시지도 함께 뜬다, 자주 생기면 액션을 직접 구현
        self._delete(request, list(queryset))

    def response_delete(self, request, obj_display, obj_id):
        if getattr(request, '_delete_failed', False):
            return redirect(request.path.rsplit('/delete/', 1)[0] + '/change/')
        return super().response_delete(request, obj_display, obj_id)


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
        if obj and obj.is_approved and not can_edit_locked(obj, request.user):
            return [f.name for f in obj._meta.fields] + ['approval']
        return ['approval']

    def get_exclude(self, request, obj=None):
        return ['approved_by', 'approved_at']


class BomInline(admin.TabularInline):
    model = BomLine
    fk_name = 'parent'
    extra = 1
    autocomplete_fields = ['component']


class RoutingInline(admin.TabularInline):
    model = RoutingStep
    extra = 1


@admin.register(Item)
class ItemAdmin(BaseAdmin):
    list_display = ['code', 'name', 'item_type']
    search_fields = ['code', 'name']
    list_filter = ['item_type']
    inlines = [BomInline, RoutingInline]


@admin.register(Process)
class ProcessAdmin(BaseAdmin):
    list_display = ['code', 'name']
    search_fields = ['code', 'name']


class WorkResultInline(admin.TabularInline):
    model = WorkResult
    extra = 1
    autocomplete_fields = ['lot']
    fields = ['step', 'lot', 'input_qty', 'good_qty', 'defect_qty', 'operator', 'started_at', 'ended_at']

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # 이 작업지시 품번의 라우팅 공정만 고를 수 있게 한다
        if db_field.name == 'step' and request.resolver_match.kwargs.get('object_id'):
            wo = WorkOrder.objects.filter(pk=request.resolver_match.kwargs['object_id']).first()
            if wo:
                kwargs['queryset'] = wo.item.routing.select_related('process')
        if db_field.name == 'operator':
            kwargs['initial'] = request.user.pk
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(WorkOrder)
class WorkOrderAdmin(BaseAdmin):
    list_display = ['number', 'item', 'process', 'planned_qty', 'due_date', 'status', 'progress_display']
    list_filter = ['status', 'process']
    search_fields = ['number', 'item__code']
    autocomplete_fields = ['item', 'process']
    readonly_fields = ['progress_display']
    inlines = [WorkResultInline]

    @admin.display(description='진도율')
    def progress_display(self, obj):
        p = obj.progress if obj.pk else None
        return '-' if p is None else f'{p:.0f}%'


@admin.register(WorkResult)
class WorkResultAdmin(BaseAdmin):
    list_display = ['work_order', 'step', 'lot', 'input_qty', 'good_qty', 'defect_qty', 'operator', 'started_at']
    list_filter = ['step__process']
    search_fields = ['work_order__number', 'lot__number']
    autocomplete_fields = ['work_order', 'lot']


@admin.register(ImportProfile)
class ImportProfileAdmin(BaseAdmin):
    list_display = ['name', 'target', 'header_row']


class ParentLinkInline(admin.TabularInline):
    model = LotLink
    fk_name = 'child'
    extra = 1
    autocomplete_fields = ['parent']
    verbose_name = verbose_name_plural = '투입 LOT'


@admin.register(Lot)
class LotAdmin(BaseAdmin):
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
class NonconformanceAdmin(ReportLinksMixin, BaseAdmin):
    form = NonconformanceForm
    list_display = ['__str__', 'lot', 'defect_type', 'detected_at', 'disposition', 'approved_by', 'closed_at']
    list_filter = ['disposition', 'defect_type']
    search_fields = ['lot__number', 'description']
    autocomplete_fields = ['lot']

    def get_readonly_fields(self, request, obj=None):
        locked = ['lot', 'description', 'detected_at', 'disposition', 'customer_approval_ref'] if obj and obj.closed_at else []
        return locked + ['approved_by', 'closed_at', 'report_links', 'similar_cases', 'capa']

    @admin.display(description='CAPA')
    def capa(self, obj):
        from qms.admin import capa_links  # CAPA는 qms 앱 기능
        return capa_links(obj, 'NC', f'{obj}: {obj.description}')

    @admin.display(description='유사 과거 사례')
    def similar_cases(self, obj):
        from qms.similar import similar_html  # 재발 방지 검색은 qms 앱 기능
        return similar_html(obj) if obj.pk else '저장 후 표시됩니다.'

    def get_form(self, request, obj=None, **kwargs):
        return type('Form', (super().get_form(request, obj, **kwargs),), {'user': request.user})


@admin.register(Hold)
class HoldAdmin(BaseAdmin):
    list_display = ['lot', 'nonconformance', 'created_at', 'released_at']
    list_filter = [('released_at', admin.EmptyFieldListFilter)]
    request_links_enabled = False  # 보류는 부적합 삭제와 함께만 지워진다

    # 보류는 부적합 등록·처분으로만 생기고 풀린다
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Shipment)
class ShipmentAdmin(ReportLinksMixin, BaseAdmin):
    list_display = ['lot', 'customer', 'qty', 'shipped_at']
    search_fields = ['lot__number', 'customer']
    autocomplete_fields = ['lot']
    readonly_fields = ['report_links']  # 인쇄 = 출하성적서, 고객 엑셀 양식은 매핑 {"A10": "coa_rows"}
