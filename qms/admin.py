from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin

from core.admin import ApprovalAdminMixin, ReportLinksMixin

from .models import (AuditChecklist, AuditItem, Characteristic, CustomerClaim, CustomerRule, Document,
                     DocumentRevision, Evidence, ExcelTemplate, Inspection, InspectionSpec, Measurement, Scar)


class LockedWhenApprovedInline(admin.TabularInline):
    def _locked(self, obj):
        return obj is not None and obj.is_approved

    def has_add_permission(self, request, obj=None):
        return not self._locked(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not self._locked(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not self._locked(obj) and super().has_delete_permission(request, obj)


class CharacteristicInline(LockedWhenApprovedInline):
    model = Characteristic
    extra = 1
    readonly_fields = ['spc_link']

    @admin.display(description='SPC')
    def spc_link(self, obj):
        if not obj.pk or not obj.is_variable:
            return '-'
        return format_html('<a href="{}" target="_blank">관리도</a>', reverse('spc', args=[obj.pk]))


@admin.register(InspectionSpec)
class InspectionSpecAdmin(ApprovalAdminMixin, SimpleHistoryAdmin):
    list_display = ['item', 'inspection_type', 'revision', 'is_approved']
    list_filter = ['inspection_type']
    search_fields = ['item__code']
    autocomplete_fields = ['item']
    inlines = [CharacteristicInline]
    actions = ['new_revision']

    @admin.action(description='선택한 기준으로 새 개정 만들기(항목 복사)')
    def new_revision(self, request, queryset):
        with transaction.atomic():
            for spec in queryset:
                items = list(spec.characteristics.all())
                top = InspectionSpec.objects.filter(item=spec.item, inspection_type=spec.inspection_type
                                                    ).aggregate(m=Max('revision'))['m']
                new = InspectionSpec.objects.create(item=spec.item, inspection_type=spec.inspection_type,
                                                    revision=top + 1, sampling=spec.sampling, note=spec.note)
                for c in items:
                    Characteristic.objects.create(spec=new, name=c.name, lsl=c.lsl, usl=c.usl, unit=c.unit)
        self.message_user(request, '새 개정을 만들었습니다. 내용을 고친 뒤 승인 서명하세요.')


class MeasurementInline(admin.TabularInline):
    model = Measurement
    extra = 3

    def _done(self, obj):
        return obj is not None and bool(obj.result)

    def has_add_permission(self, request, obj=None):
        return not self._done(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not self._done(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not self._done(obj) and super().has_delete_permission(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # 이 검사의 기준에 속한 항목만 고를 수 있게 한다
        if db_field.name == 'characteristic' and request.resolver_match.kwargs.get('object_id'):
            insp = Inspection.objects.filter(pk=request.resolver_match.kwargs['object_id']).first()
            if insp:
                kwargs['queryset'] = insp.spec.characteristics.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Inspection)
class InspectionAdmin(ReportLinksMixin, SimpleHistoryAdmin):
    list_display = ['lot', 'spec', 'inspected_at', 'inspector', 'result', 'nonconformance']
    list_filter = ['result', 'spec__inspection_type']
    search_fields = ['lot__number']
    autocomplete_fields = ['lot']
    inlines = [MeasurementInline]

    def has_change_permission(self, request, obj=None):
        return not (obj and obj.result) and super().has_change_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        base = ['inspector', 'result', 'nonconformance', 'report_links']
        return base + ['lot', 'spec', 'inspected_at'] if obj else base

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'spec':
            kwargs['queryset'] = InspectionSpec.objects.filter(approved_at__isnull=False)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.inspector = request.user
        super().save_model(request, obj, form, change)

    def response_change(self, request, obj):
        if '_finalize' in request.POST:
            try:
                obj.finalize()
                msg = '합격' if obj.result == obj.PASS else f'불합격 → {obj.nonconformance} 등록, 계보 보류'
                self.message_user(request, f'판정: {msg}', messages.SUCCESS if obj.result == obj.PASS else messages.WARNING)
            except ValidationError as e:
                self.message_user(request, ' '.join(e.messages), messages.ERROR)
            return self.response_post_save_change(request, obj)
        return super().response_change(request, obj)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        obj = self.get_object(request, object_id)
        extra_context = {**(extra_context or {}), 'show_finalize': obj is not None and not obj.result}
        return super().change_view(request, object_id, form_url, extra_context)

    change_form_template = 'qms/inspection_change_form.html'


@admin.register(CustomerRule)
class CustomerRuleAdmin(SimpleHistoryAdmin):
    list_display = ['customer', 'containment_hours', 'corrective_days']


@admin.register(CustomerClaim)
class CustomerClaimAdmin(ReportLinksMixin, SimpleHistoryAdmin):
    list_display = ['number', 'customer', 'lot', 'received_at', 'current_step', 'containment_due', 'corrective_due', 'closed_at']
    search_fields = ['number', 'customer', 'lot__number']
    autocomplete_fields = ['lot']
    readonly_fields = ['nonconformance', 'trace_link', 'containment_due', 'corrective_due', 'current_step', 'report_links']
    fieldsets = [
        (None, {'fields': ['number', 'customer', 'lot', 'description', 'received_at', 'nonconformance',
                           'trace_link', 'containment_due', 'corrective_due', 'current_step', 'report_links']}),
        ('8D', {'fields': [f for f, _ in CustomerClaim.STEPS]}),
        ('종결', {'fields': ['closed_at']}),
    ]

    @admin.display(description='영향 범위')
    def trace_link(self, obj):
        if not obj.lot_id:
            return '-'
        return format_html('<a href="{}?lot={}" target="_blank">LOT 추적 열기</a>', reverse('trace'), obj.lot.number)


@admin.register(Scar)
class ScarAdmin(ReportLinksMixin, SimpleHistoryAdmin):
    list_display = ['number', 'supplier', 'lot', 'issued_at', 'response_due', 'responded_at', 'closed_at']
    search_fields = ['number', 'supplier', 'lot__number']
    autocomplete_fields = ['lot', 'nonconformance']
    readonly_fields = ['report_links']


class RevisionInline(admin.TabularInline):
    model = DocumentRevision
    fields = ['revision', 'file', 'change_note', 'approval_state']
    readonly_fields = ['approval_state']
    extra = 0
    show_change_link = True

    @admin.display(description='승인')
    def approval_state(self, obj):
        return f'{obj.approved_by} {obj.approved_at:%Y-%m-%d}' if obj.is_approved else '미승인'

    def has_change_permission(self, request, obj=None):
        return False  # 개정은 개정 화면에서 등록·승인한다


@admin.register(Document)
class DocumentAdmin(SimpleHistoryAdmin):
    list_display = ['number', 'title', 'doc_type', 'current_revision']
    search_fields = ['number', 'title']
    list_filter = ['doc_type']
    inlines = [RevisionInline]


@admin.register(DocumentRevision)
class DocumentRevisionAdmin(ApprovalAdminMixin, SimpleHistoryAdmin):
    list_display = ['document', 'revision', 'created_at', 'is_approved']
    search_fields = ['document__number', 'document__title']
    autocomplete_fields = ['document']


class EvidenceInline(admin.TabularInline):
    model = Evidence
    extra = 1
    autocomplete_fields = ['document']


@admin.register(AuditItem)
class AuditItemAdmin(SimpleHistoryAdmin):
    list_display = ['checklist', 'clause', 'requirement', 'evidence_count']
    list_filter = ['checklist']
    search_fields = ['clause', 'requirement']
    inlines = [EvidenceInline]

    @admin.display(description='증적 수')
    def evidence_count(self, obj):
        n = obj.evidences.count()
        return n if n else format_html('<strong style="color:#ba2121">미비</strong>')


class AuditItemInline(admin.TabularInline):
    model = AuditItem
    extra = 1
    show_change_link = True


@admin.register(AuditChecklist)
class AuditChecklistAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'standard', 'progress']
    inlines = [AuditItemInline]

    @admin.display(description='증적 확보')
    def progress(self, obj):
        total = obj.items.count()
        done = obj.items.filter(evidences__isnull=False).distinct().count()
        return f'{done}/{total}'


@admin.register(ExcelTemplate)
class ExcelTemplateAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'target']
