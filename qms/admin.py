from itertools import groupby
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from core.admin import ApprovalAdminMixin, BaseAdmin, ReportLinksMixin
from core.models import Nonconformance
from core.records import can_edit_locked
from core.rules import child_editable

from .models import (AuditChecklist, AuditFinding, AuditItem, Capa, ChangeRequest, Characteristic, ControlPlan,
                     ControlPlanLine, CustomerClaim, CustomerRule, Document, DocumentRevision, Evidence, ExcelTemplate, Gauge,
                     Inspection, InspectionSpec, InternalAudit, Measurement, Memo, MemoPhoto, PpapElement, PpapSubmission, Qualification, Scar)
from .rules import new_spec_revision
from .similar import similar_html


class LockedWhenApprovedInline(admin.TabularInline):
    def _locked(self, request, obj):
        return not child_editable(obj, request.user)

    def has_add_permission(self, request, obj=None):
        return not self._locked(request, obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not self._locked(request, obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not self._locked(request, obj) and super().has_delete_permission(request, obj)


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
class InspectionSpecAdmin(ApprovalAdminMixin, BaseAdmin):
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
                new_spec_revision(spec)
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
class InspectionAdmin(ReportLinksMixin, BaseAdmin):
    list_display = ['lot', 'spec', 'inspected_at', 'inspector', 'result', 'nonconformance']
    list_filter = ['result', 'spec__inspection_type']
    search_fields = ['lot__number', 'lot__item__code', 'lot__supplier']
    autocomplete_fields = ['lot']
    inlines = [MeasurementInline]

    def add_view(self, request, form_url='', extra_context=None):
        # 검사는 검사 입력 화면에서 한다 (LOT 스캔·입고 등록·즉시 판정). 지난 검사 소급 입력은 ?full=1
        if request.method == 'GET' and 'full' not in request.GET:
            return redirect('inspect')
        return super().add_view(request, form_url, extra_context)

    def has_change_permission(self, request, obj=None):
        return not (obj and obj.result) and super().has_change_permission(request, obj)

    def related(self, obj):
        return obj.lot, [('부적합', Nonconformance.objects.filter(pk=obj.nonconformance_id), ''),
                         ('검사기준', InspectionSpec.objects.filter(pk=obj.spec_id), '')]

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
class GaugeAdmin(BaseAdmin):
    list_display = ['number', 'name', 'last_calibrated', 'next_due', 'active']
    list_filter = ['active']
    search_fields = ['number', 'name']
    fieldsets = [
        (None, {'fields': ['number', 'name', 'last_calibrated']}),
        ('추가 정보', {'classes': ['collapse'], 'fields': ['interval_days', 'certificate', 'active']}),
    ]


@admin.register(Qualification)
class QualificationAdmin(BaseAdmin):
    list_display = ['user', 'inspection_type', 'valid_until', 'basis']
    list_filter = ['inspection_type']


class ControlPlanLineInline(LockedWhenApprovedInline):
    model = ControlPlanLine
    extra = 1
    readonly_fields = ['action_priority']
    fields = ['process', 'characteristic', 'special', 'lsl', 'usl', 'unit', 'method', 'sampling', 'inspection_type',
              'reaction', 'failure_mode', 'severity', 'occurrence', 'detection', 'action_priority']


@admin.register(ControlPlan)
class ControlPlanAdmin(ApprovalAdminMixin, BaseAdmin):
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
class ChangeRequestAdmin(ApprovalAdminMixin, BaseAdmin):
    list_display = ['number', 'item', 'category', 'effective_at', 'is_approved', 'first_article_state']
    list_filter = ['category']
    search_fields = ['number', 'item__code']
    autocomplete_fields = ['item']

    @admin.display(description='초품 검사')
    def first_article_state(self, obj):
        fa = obj.first_article if obj.pk else None
        if fa:
            return format_html('<a href="{}">{} 합격</a>', reverse('admin:qms_inspection_change', args=[fa.pk]), fa)
        return format_html('<span class="status status--negative">{}</span>', '미확인 (출하 차단)') if obj.is_approved else '-'

    def get_readonly_fields(self, request, obj=None):
        return super().get_readonly_fields(request, obj) + ['first_article_state']


def capa_links(obj, source, title):
    """출처 기록 화면에 연결된 CAPA 목록과 'CAPA 만들기' 버튼."""
    if not obj.pk:
        return '저장 후 만들 수 있습니다.'
    ct = ContentType.objects.get_for_model(obj)
    linked = format_html_join(' · ', '<a href="{}">{} [{}]</a>', (
        (reverse('admin:qms_capa_change', args=[c.pk]), c.number, c.status)
        for c in Capa.objects.filter(source_type=ct, source_id=obj.pk)))
    url = reverse('admin:qms_capa_add') + '?' + urlencode(
        {'source': source, 'source_type': ct.pk, 'source_id': obj.pk, 'title': str(title)[:200]})
    return format_html('{} <a class="button" href="{}">CAPA 만들기</a>', linked, url)


@admin.register(Capa)
class CapaAdmin(BaseAdmin):
    list_display = ['number', 'title', 'source', 'owner', 'due_date', 'status']
    list_filter = ['source']
    search_fields = ['number', 'title', 'root_cause', 'action']
    readonly_fields = ['status', 'source_link']
    fieldsets = [
        (None, {'fields': ['title', 'source', 'action', 'owner', 'due_date']}),
        ('추가 정보', {'classes': ['collapse'], 'fields': ['number', 'source_type', 'source_id', 'source_link', 'status',
                                                         'root_cause', 'done_at']}),
        ('유효성 확인 · 종결', {'fields': ['effective', 'verified_at', 'verified_by', 'verification_note', 'closed_at']}),
    ]

    @admin.display(description='출처 기록')
    def source_link(self, obj):
        rec = obj.source_record if obj.pk else None
        if not rec:
            return '-'
        meta = rec._meta
        return format_html('<a href="{}">{}</a>', reverse(f'admin:{meta.app_label}_{meta.model_name}_change', args=[rec.pk]), rec)

    def get_changeform_initial_data(self, request):
        return {**super().get_changeform_initial_data(request), 'owner': request.user.pk}


class AuditFindingInline(admin.TabularInline):
    model = AuditFinding
    extra = 1
    fields = ['clause', 'grade', 'description', 'capa', 'capa_link']
    readonly_fields = ['capa_link']
    autocomplete_fields = ['capa']

    @admin.display(description='CAPA 만들기')
    def capa_link(self, obj):
        if obj.capa_id or obj.grade not in AuditFinding.NEEDS_CAPA:
            return '-'
        return capa_links(obj, 'AUDIT', f'{obj.audit.name} {obj.clause}: {obj.description}')


@admin.register(InternalAudit)
class InternalAuditAdmin(BaseAdmin):
    list_display = ['name', 'kind', 'planned_date', 'auditor', 'auditee', 'performed_at', 'open_findings', 'closed_at']
    list_filter = ['kind']
    search_fields = ['name', 'auditee']
    inlines = [AuditFindingInline]
    readonly_fields = ['memo_list']
    fieldsets = [
        (None, {'fields': ['name', 'kind', 'planned_date', 'auditor']}),
        ('추가 정보', {'classes': ['collapse'], 'fields': ['scope', 'checklist', 'auditee', 'performed_at', 'closed_at']}),
        ('이번 심사 메모', {'fields': ['memo_list']}),
    ]

    @admin.display(description='이번 심사 메모')
    def memo_list(self, obj):
        """대상 기록별로 묶은 메모와 각 메모의 'CAPA 만들기'."""
        if not obj or not obj.pk:
            return '-'
        memos = sorted(obj.memos.all(), key=lambda m: (m.content_type_id or 0, m.object_id or 0, m.created_at))
        if not memos:
            return '아직 메모가 없습니다.'
        groups = [list(g) for _, g in groupby(memos, key=lambda m: (m.content_type_id, m.object_id))]
        return format_html_join('', '<p><strong>{}</strong></p><ul>{}</ul>', (
            (g[0].target or ('삭제된 기록' if g[0].content_type_id else '미분류'),
             format_html_join('', '<li>{}: {} {}</li>', (
                 (m.get_speaker_kind_display(), m.body, self._memo_capa(obj, m)) for m in g)))
            for g in groups))

    def _memo_capa(self, audit, memo):
        """CAPA 출처로 고를 수 있는 기록에 붙은 메모는 그 기록을 출처로, 나머지는 출처 기록 없이 만든다."""
        title = f'{audit.name}: {memo.body}'
        if memo.content_type and memo.content_type.model in ('nonconformance', 'customerclaim', 'scar') and memo.target:
            return capa_links(memo.target, 'AUDIT', title)
        url = reverse('admin:qms_capa_add') + '?' + urlencode({'source': 'AUDIT', 'title': title[:200]})
        return format_html('<a class="button" href="{}">CAPA 만들기</a>', url)

    @admin.display(description='CAPA 미연결 지적')
    def open_findings(self, obj):
        n = obj.findings.filter(grade__in=AuditFinding.NEEDS_CAPA, capa__isnull=True).count()
        return format_html('<span class="status status--negative">{}</span>', n) if n else 0


class PpapElementInline(admin.TabularInline):
    model = PpapElement
    extra = 0
    fields = ['number', 'name', 'requirement', 'document', 'record_type', 'record_id', 'evidence', 'note']
    readonly_fields = ['number', 'name', 'evidence']
    autocomplete_fields = ['document']
    can_delete = False

    @admin.display(description='증적')
    def evidence(self, obj):
        if obj.record:
            meta = obj.record._meta
            return format_html('<a href="{}" target="_blank">{}</a>',
                               reverse(f'admin:{meta.app_label}_{meta.model_name}_change', args=[obj.record.pk]), obj.record)
        if obj.has_evidence or obj.requirement != 'S' or obj.number == 18:
            return '-'
        return format_html('<span class="status status--negative">{}</span>', '필요')

    def has_add_permission(self, request, obj=None):
        return False  # 18요소는 제출을 만들 때 자동 생성된다

    def has_change_permission(self, request, obj=None):
        locked = obj is not None and obj.is_approved and not can_edit_locked(obj, request.user)
        return not locked and super().has_change_permission(request, obj)


@admin.register(PpapSubmission)
class PpapSubmissionAdmin(ApprovalAdminMixin, ReportLinksMixin, BaseAdmin):
    list_display = ['item', 'customer', 'level', 'reason', 'due_date', 'is_approved', 'submitted_at', 'customer_approved_at']
    search_fields = ['item__code', 'customer']
    autocomplete_fields = ['item']
    inlines = [PpapElementInline]
    fieldsets = [
        (None, {'fields': ['item', 'customer', 'level', 'reason']}),
        ('추가 정보', {'classes': ['collapse'], 'fields': ['due_date', 'submitted_at', 'customer_approved_at', 'approval',
                                                         'report_links']}),
    ]

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj) + ['report_links']
        if obj and not obj.is_approved:
            fields.append('level')  # 요소가 이미 수준에 맞춰 만들어졌다
        # 승인 후에도 제출일·고객 승인일은 기록한다
        return [f for f in fields if f not in PpapSubmission.AFTER_APPROVAL]


@admin.register(CustomerRule)
class CustomerRuleAdmin(BaseAdmin):
    list_display = ['customer', 'containment_hours', 'corrective_days']


@admin.register(CustomerClaim)
class CustomerClaimAdmin(ReportLinksMixin, BaseAdmin):
    list_display = ['number', 'customer', 'lot', 'received_at', 'current_step', 'containment_due', 'corrective_due', 'closed_at']
    search_fields = ['number', 'customer', 'lot__number']
    autocomplete_fields = ['lot']
    list_filter = [('closed_at', admin.EmptyFieldListFilter)]
    readonly_fields = ['nonconformance', 'trace_link', 'containment_due', 'corrective_due', 'current_step', 'report_links',
                       'similar_cases', 'capa']
    fieldsets = [
        (None, {'fields': ['number', 'customer', 'lot', 'description']}),
        ('추가 정보', {'classes': ['collapse'], 'fields': ['defect_qty', 'received_at', 'nonconformance', 'trace_link',
                                                         'containment_due', 'corrective_due', 'current_step', 'report_links']}),
        ('재발 방지', {'fields': ['similar_cases', 'capa']}),
        ('8D', {'fields': [f for f, _ in CustomerClaim.STEPS]}),
        ('종결', {'fields': ['closed_at']}),
    ]

    @admin.display(description='유사 과거 사례')
    def similar_cases(self, obj):
        return similar_html(obj) if obj.pk else '저장 후 표시됩니다.'

    @admin.display(description='CAPA')
    def capa(self, obj):
        return capa_links(obj, '8D', f'{obj}: {obj.description}')

    @admin.display(description='영향 범위')
    def trace_link(self, obj):
        if not obj.lot_id:
            return '-'
        return format_html('<a href="{}?lot={}" target="_blank">LOT 추적 열기</a>', reverse('trace'), obj.lot.number)

    def related(self, obj):
        return obj.lot, [('부적합', Nonconformance.objects.filter(pk=obj.nonconformance_id), '')]


@admin.register(Scar)
class ScarAdmin(ReportLinksMixin, BaseAdmin):
    list_display = ['number', 'supplier', 'lot', 'issued_at', 'response_due', 'responded_at', 'closed_at']
    search_fields = ['number', 'supplier', 'lot__number']
    autocomplete_fields = ['lot', 'nonconformance']
    list_filter = [('closed_at', admin.EmptyFieldListFilter)]
    readonly_fields = ['report_links', 'capa']
    fieldsets = [
        (None, {'fields': ['number', 'supplier', 'lot', 'request', 'response_due']}),
        ('추가 정보', {'classes': ['collapse'], 'fields': ['nonconformance', 'issued_at', 'response', 'responded_at', 'closed_at',
                                                         'capa', 'report_links']}),
    ]

    @admin.display(description='CAPA')
    def capa(self, obj):
        return capa_links(obj, 'SCAR', f'{obj}: {obj.request}')

    def related(self, obj):
        return obj.lot, [('부적합', Nonconformance.objects.filter(pk=obj.nonconformance_id), '')]


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
class DocumentAdmin(BaseAdmin):
    list_display = ['number', 'title', 'doc_type', 'current_revision']
    search_fields = ['number', 'title']
    list_filter = ['doc_type']
    inlines = [RevisionInline]


@admin.register(DocumentRevision)
class DocumentRevisionAdmin(ApprovalAdminMixin, BaseAdmin):
    list_display = ['document', 'revision', 'created_at', 'is_approved']
    search_fields = ['document__number', 'document__title']
    autocomplete_fields = ['document']


class EvidenceInline(admin.TabularInline):
    model = Evidence
    extra = 1
    autocomplete_fields = ['document']


@admin.register(AuditItem)
class AuditItemAdmin(BaseAdmin):
    list_display = ['checklist', 'clause', 'requirement', 'evidence_count']
    list_filter = ['checklist']
    search_fields = ['clause', 'requirement']
    inlines = [EvidenceInline]

    @admin.display(description='증적 수')
    def evidence_count(self, obj):
        n = obj.evidences.count()
        return n if n else format_html('<span class="status status--negative">{}</span>', '미비')


class AuditItemInline(admin.TabularInline):
    model = AuditItem
    extra = 1
    show_change_link = True


@admin.register(AuditChecklist)
class AuditChecklistAdmin(BaseAdmin):
    list_display = ['name', 'standard', 'progress']
    inlines = [AuditItemInline]

    @admin.display(description='증적 확보')
    def progress(self, obj):
        total = obj.items.count()
        done = obj.items.filter(evidences__isnull=False).distinct().count()
        return f'{done}/{total}'


@admin.register(ExcelTemplate)
class ExcelTemplateAdmin(BaseAdmin):
    list_display = ['name', 'target']


class MemoPhotoInline(admin.TabularInline):
    model = MemoPhoto
    extra = 0
    fields = ['file']


@admin.register(Memo)
class MemoAdmin(BaseAdmin):
    """메모 수정은 작성자 본인만. 삭제는 BaseAdmin의 요청 흐름."""
    list_display = ['created_at', 'speaker_kind', 'speaker_name', 'body', 'target', 'audit', 'author']
    list_filter = ['speaker_kind', 'audit']
    search_fields = ['body', 'speaker_name']
    fields = ['body', 'speaker_kind', 'speaker_name', 'audit', 'target', 'author', 'created_at']
    readonly_fields = ['target', 'author', 'created_at']
    inlines = [MemoPhotoInline]

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.author_id == request.user.pk)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.author = request.user
        super().save_model(request, obj, form, change)
