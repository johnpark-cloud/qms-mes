from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin

from core.admin import ApprovalAdminMixin, ReportLinksMixin

from .models import (AuditChecklist, AuditItem, ChangeRequest, Characteristic, ControlPlan, ControlPlanLine,
                     CustomerClaim, CustomerRule, Document, DocumentRevision, Evidence, ExcelTemplate, Gauge, Inspection,
                     InspectionSpec, Measurement, Qualification, Scar)


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
                    Characteristic.objects.create(spec=new, name=c.name, lsl=c.lsl, usl=c.usl, unit=c.unit,
                                                  special=c.special, plan_line=c.plan_line)
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


@admin.register(Gauge)
class GaugeAdmin(SimpleHistoryAdmin):
    list_display = ['number', 'name', 'last_calibrated', 'next_due', 'active']
    list_filter = ['active']
    search_fields = ['number', 'name']


@admin.register(Qualification)
class QualificationAdmin(SimpleHistoryAdmin):
    list_display = ['user', 'inspection_type', 'valid_until', 'basis']
    list_filter = ['inspection_type']


class ControlPlanLineInline(LockedWhenApprovedInline):
    model = ControlPlanLine
    extra = 1
    readonly_fields = ['action_priority']
    fields = ['process', 'characteristic', 'special', 'lsl', 'usl', 'unit', 'method', 'sampling', 'inspection_type',
              'reaction', 'failure_mode', 'severity', 'occurrence', 'detection', 'action_priority']


@admin.register(ControlPlan)
class ControlPlanAdmin(ApprovalAdminMixin, SimpleHistoryAdmin):
    list_display = ['item', 'stage', 'revision', 'is_approved']
    list_filter = ['stage']
    search_fields = ['item__code']
    autocomplete_fields = ['item']
    inlines = [ControlPlanLineInline]
    actions = ['make_specs']

    @admin.action(description='승인된 관리계획서로 검사기준 초안 만들기')
    def make_specs(self, request, queryset):
        made = []
        with transaction.atomic():
            for plan in queryset:
                if not plan.is_approved:
                    self.message_user(request, f'{plan}: 승인 후에 만들 수 있습니다.', messages.ERROR)
                    continue
                for itype, _ in InspectionSpec.TYPES:
                    lines = plan.lines.filter(inspection_type=itype)
                    if not lines:
                        continue
                    top = InspectionSpec.objects.filter(item=plan.item, inspection_type=itype).aggregate(m=Max('revision'))['m']
                    spec = InspectionSpec.objects.create(item=plan.item, inspection_type=itype, revision=(top or 0) + 1,
                                                         sampling=', '.join(sorted({l.sampling for l in lines if l.sampling})),
                                                         note=f'{plan}에서 생성')
                    for l in lines:
                        Characteristic.objects.create(spec=spec, name=l.characteristic, lsl=l.lsl, usl=l.usl, unit=l.unit,
                                                      special=l.special, plan_line=l)
                    made.append(str(spec))
        if made:
            self.message_user(request, f'검사기준 초안: {", ".join(made)}. 확인 후 승인 서명하세요.')


@admin.register(ChangeRequest)
class ChangeRequestAdmin(ApprovalAdminMixin, SimpleHistoryAdmin):
    list_display = ['number', 'item', 'category', 'effective_at', 'is_approved', 'first_article_state']
    list_filter = ['category']
    search_fields = ['number', 'item__code']
    autocomplete_fields = ['item']

    @admin.display(description='초품 검사')
    def first_article_state(self, obj):
        fa = obj.first_article if obj.pk else None
        if fa:
            return format_html('<a href="{}">{} 합격</a>', reverse('admin:qms_inspection_change', args=[fa.pk]), fa)
        return format_html('<strong style="color:#ba2121">미확인 (출하 차단)</strong>') if obj.is_approved else '-'

    def get_readonly_fields(self, request, obj=None):
        return super().get_readonly_fields(request, obj) + ['first_article_state']


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
        (None, {'fields': ['number', 'customer', 'lot', 'description', 'defect_qty', 'received_at', 'nonconformance',
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
