from django import forms
from django.apps import apps
from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from simple_history.admin import SimpleHistoryAdmin

from .models import (BomLine, Hold, ImportProfile, Item, Lot, LotLink, Nonconformance, NonconformancePhoto, Process,
                     RoutingStep, Shipment, WorkOrder, WorkResult)
from .records import blockers, can_edit_locked, delete_record, edit_unlocked, is_locked

admin.site.site_header = admin.site.site_title = 'QMS+MES'
admin.site.index_title = '메뉴'


LOCKED_MSG = '잠긴 기록입니다. 수정 요청 후 승인받아야 수정할 수 있습니다.'


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
        if change and is_locked(obj) and not obj._edit_unlocked:
            try:
                if not form.has_changed():  # 읽기 전용 폼: 저장할 것이 없다
                    raise ValidationError(LOCKED_MSG)
                super().save_model(request, obj, form, change)  # PPAP 제출일처럼 승인 후에도 열린 칸만 통과한다
            except ValidationError:
                request._save_blocked = True
                self.message_user(request, LOCKED_MSG, messages.ERROR)
            return
        super().save_model(request, obj, form, change)
        if unlock:  # 저장이 성공했을 때만 잠금 해제를 소모한다 (changeform_view가 atomic이라 인라인 실패도 되돌린다)
            unlock.status = unlock.USED
            unlock.save()

    def save_formset(self, request, form, formset, change):
        if getattr(form.instance, '_edit_unlocked', False):
            for f in formset.forms:  # 부모의 잠금 해제를 항목(검사항목·관리계획 행 등)에도 넘긴다
                f.instance._edit_unlocked = True
        super().save_formset(request, form, formset, change)

    def log_change(self, request, obj, message):
        if not getattr(request, '_save_blocked', False):  # 저장되지 않은 변경은 기록하지 않는다
            return super().log_change(request, obj, message)

    def response_change(self, request, obj):
        if getattr(request, '_save_blocked', False):
            return redirect(request.path)
        return super().response_change(request, obj)

    def message_user(self, request, message, level=messages.INFO, *args, **kwargs):
        # 막힌 저장·삭제 뒤에 Django가 붙이는 성공 메시지는 거짓이므로 뺀다
        if level == messages.SUCCESS and (getattr(request, '_save_blocked', False) or getattr(request, '_delete_failed', False)):
            return
        super().message_user(request, message, level, *args, **kwargs)

    def get_deleted_objects(self, objs, request):
        # 부적합의 보류처럼 delete_record가 먼저 지우는 기록은 '삭제 불가' 목록에서 뺀다
        deleted, counts, perms_needed, _ = super().get_deleted_objects(objs, request)
        protected = [f'{o._meta.verbose_name}: {o}' for obj in objs for o in blockers(obj)]
        return deleted, counts, perms_needed - {Hold._meta.verbose_name}, protected

    def _delete(self, request, objs, in_view=False):
        try:
            with transaction.atomic():
                for obj in objs:
                    delete_record(obj)
        except ProtectedError as e:
            if in_view:
                transaction.set_rollback(True)  # delete_view 자체의 atomic이라 삭제 기록(LogEntry)까지 되돌린다
            request._delete_failed = True
            self.message_user(request, '먼저 지워야 할 기록: ' + ', '.join(map(str, e.protected_objects)), messages.ERROR)

    def delete_model(self, request, obj):
        self._delete(request, [obj], in_view=True)

    def delete_queryset(self, request, queryset):
        # shortcut: 경합으로 여기서 막히면 '선택 항목 삭제'의 삭제 기록(LogEntry)은 남는다, 감사에 문제되면 액션을 직접 구현
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
    fieldsets = [
        (None, {'fields': ['number', 'item', 'planned_qty']}),
        ('추가 정보', {'classes': ['collapse'], 'fields': ['process', 'due_date', 'status', 'progress_display']}),
    ]
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
        exclude = ['approved_by', 'approved_at']

    def _disposing(self):
        return bool(self.cleaned_data.get('disposition')) and not self.instance.closed_at

    def clean(self):
        data = super().clean()
        if self._disposing():
            if not self.user.check_password(data.get('password') or ''):
                raise forms.ValidationError('MRB 승인 비밀번호가 맞지 않습니다.')
            self.instance.approved_by, self.instance.approved_at = self.user, timezone.now()
        return data

    def _post_clean(self):
        super()._post_clean()  # 폼 값이 instance에 들어간 뒤라야 읽기 전용 칸까지 포함해 판단할 수 있다
        if self._disposing() and (missing := self.instance.missing_fields()):
            self.add_error(None, '보완 필요: ' + ', '.join(missing))


class NcPhotoInline(admin.TabularInline):
    model = NonconformancePhoto
    extra = 1
    fields = ['file', 'caption', 'uploaded_at']
    readonly_fields = ['uploaded_at']
    formfield_overrides = {models.FileField: {'widget': forms.ClearableFileInput(
        attrs={'accept': 'image/*', 'capture': 'environment'})}}

    def _open(self, request, obj):
        # 종결된 부적합의 사진은 본문과 같이 잠긴다
        return not (obj and obj.closed_at) or can_edit_locked(obj, request.user)

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and self._open(request, obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._open(request, obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._open(request, obj)


@admin.register(Nonconformance)
class NonconformanceAdmin(ReportLinksMixin, BaseAdmin):
    form = NonconformanceForm
    list_display = ['number', 'origin', 'lot', 'defect_type', 'detected_at', 'disposition', 'approved_by', 'closed_at']
    list_filter = ['origin', 'disposition', 'defect_type']
    search_fields = ['number', 'lot__number', 'description']
    autocomplete_fields = ['lot', 'process']
    inlines = [NcPhotoInline]
    fieldsets = [
        ('① 구분', {'fields': ['number', 'origin', 'process', 'detected_by', 'detected_at']}),
        ('② 대상', {'fields': ['lot', 'lot_info', 'defect_qty', 'inspected_qty']}),
        ('③ 현상', {'fields': ['defect_type', 'description', 'measured_value', 'special_char'],
                  'description': '사진은 아래 "부적합 사진"에 여러 장 올립니다.'}),
        ('④ 긴급 조치', {'fields': ['contained_qty', 'sorting_result', 'customer_notify', 'customer_notified_on']}),
        ('⑤ 처분', {'fields': ['disposition', 'customer_approval_ref', 'cost']}),
        ('⑥ 후속', {'fields': ['capa_required', 'capa', 'similar_cases']}),
        ('⑦ 승인', {'fields': ['password', 'approved_by', 'approved_at', 'closed_at', 'mailed_at', 'report_links']}),
    ]
    AUTO = ['number', 'lot_info', 'approved_by', 'approved_at', 'closed_at', 'mailed_at', 'report_links', 'similar_cases', 'capa']

    class Media:
        js = ['qms/nc_form.js']

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.closed_at and not can_edit_locked(obj, request.user):
            open_ = Nonconformance.AFTER_APPROVAL
            return [f.name for f in obj._meta.fields if f.name not in open_ and f.name not in self.AUTO] + self.AUTO
        return self.AUTO

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'detected_by':
            kwargs['initial'] = request.user.pk
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description='품번 · 협력사')
    def lot_info(self, obj):
        if not obj.lot_id:
            return 'LOT을 고르고 저장하면 표시됩니다.'
        return format_html('{}<span class="nc-incoming"> · 협력사: {}</span>', obj.lot.item, obj.lot.supplier or '-')

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
