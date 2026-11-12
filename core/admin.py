from django import forms
from django.apps import apps
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models, transaction
from django.db.models import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from simple_history.admin import SimpleHistoryAdmin

from .models import (Attachment, BomLine, CodeValue, Department, FieldDef, Hold, ImportProfile, Item, Lot, LotLink, Nonconformance,
                     NonconformancePhoto, NumberRule, Partner, PartnerCertificate, Process, RevisionLog, RoutingStep, Shipment, WorkOrder, WorkResult)
from .records import blockers, can_edit_locked, delete_record, is_locked
from .rules import LOCKED_MSG, begin_edit, child_editable, finish_edit, missing_message, nc_locked_fields, sign_disposition

admin.site.site_header = admin.site.site_title = 'QMS+MES'
admin.site.index_title = '메뉴'
_app_list = admin.site.get_app_list
# 사이드바에 따로 두지 않는 목록이 전체 메뉴에서 들어갈 묶음
INDEX_EXTRA = {'통합 업무 홈': ['qms.memo', 'personal.leaveprofile', 'personal.leaveuse', 'personal.payslip'],
               '품질보증 및 개선': ['qms.documentrevision', 'qms.audititem'],
               '기준정보 및 시스템 관리': ['core.importprofile', 'core.attachment', 'auth.group']}


def grouped_app_list(request, app_label=None):
    """전체 메뉴를 앱(core·qms) 대신 사이드바(core/nav.py)와 같은 업무 묶음으로 보여 준다. 어느 묶음에도 없는 목록은 원래 앱 아래에 남는다."""
    from .nav import NAV, nav_url
    app_list = _app_list(request, app_label)
    if app_label:
        return app_list
    by_url = {m['admin_url']: m for app in app_list for m in app['models']}
    by_key = {f"{app['app_label']}.{m['object_name'].lower()}": m['admin_url'] for app in app_list for m in app['models']}
    groups = []
    for i, (name, items) in enumerate(NAV):
        urls = [nav_url(url).partition('?')[0] for _, url, _ in items]
        urls += [by_key.get(key) for key in INDEX_EXTRA.get(name, [])]
        found = [by_url.pop(url) for url in dict.fromkeys(urls) if url and url in by_url]
        if found:
            groups.append({'name': name, 'app_label': f'group{i}', 'app_url': found[0]['admin_url'],
                           'has_module_perms': True, 'models': found})
    for app in app_list:
        app['models'] = [m for m in app['models'] if m['admin_url'] in by_url]
    return groups + [app for app in app_list if app['models']]


admin.site.get_app_list = grouped_app_list


RELATED_SHOWN = 5


def related_panel(user, groups):
    """상세 화면 '관련 기록' 칸. groups: [(제목, 쿼리셋, 목록 필터[, 표시 함수])]. 볼 권한이 없는 기록 종류는 빼고, 많으면 걸러진 목록으로 보낸다.
    목록 필터는 관리 목록이 받는 한 단계 조건(lot__id__exact 등)만 쓴다. 두 단계 조건은 관리 화면이 막으므로 ''로 두고 건수만 보인다."""
    out = []
    for title, qs, query, *label in groups:
        label = label[0] if label else str
        opts = qs.model._meta
        if not user.has_perm(f'{opts.app_label}.view_{opts.model_name}'):
            continue
        rows = list(qs[:RELATED_SHOWN + 1])
        out.append({'title': title, 'count': qs.count() if len(rows) > RELATED_SHOWN else len(rows),
                    'links': [(label(r), reverse(f'admin:{opts.app_label}_{opts.model_name}_change', args=[r.pk])) for r in rows[:RELATED_SHOWN]],
                    'more': reverse(f'admin:{opts.app_label}_{opts.model_name}_changelist') + f'?{query}'
                    if len(rows) > RELATED_SHOWN and query else ''})
    return out


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
        if obj is not None and obj.pk:
            context['related_lot'], groups = self.related(obj)
            context['related'] = related_panel(request.user, groups)
        return super().render_change_form(request, context, add, change, form_url, obj)

    def related(self, obj):
        """상세 화면 '관련 기록': (LOT, [(제목, 쿼리셋, 목록 필터)]). LOT이 있으면 LOT 이력 조회 링크를 함께 보인다."""
        return None, []

    def save_model(self, request, obj, form, change):
        unlock = begin_edit(obj, request.user)
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
        finish_edit(unlock)  # changeform_view가 atomic이라 인라인 실패도 되돌린다

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
        if meta.model_name == 'nonconformance' and obj.is_approved:
            links.append((reverse('nc_mail', args=[obj.pk]), '메일 보내기'))
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


@admin.register(CodeValue)
class CodeValueAdmin(BaseAdmin):
    list_display = ['group', 'code', 'name', 'parent', 'item_type', 'active', 'sort']
    list_filter = ['group', 'active']
    search_fields = ['code', 'name']


@admin.register(NumberRule)
class NumberRuleAdmin(BaseAdmin):
    list_display = ['sort', 'name', 'target', 'pattern', 'active']
    list_filter = ['target', 'active']

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        return fields + ['name', 'target', 'pattern'] if obj else fields

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'pattern' in form.base_fields:
            form.base_fields['pattern'].help_text = (
                '예: KEN-{관리표준 문서구분}{부서}-{일련2}. 코드 {묶음}, 허용 값 {묶음:A,B}, 기존 번호 {품번:규칙}/{문서:규칙}, '
                '뒤 N자리 {품번:규칙:뒤N}, 일련번호 {일련N}(맨 끝 1개).')
        return form


def extra_form_field(d):
    """사용자 정의 칸(FieldDef) 하나를 관리 화면 입력 칸으로."""
    opts = {'label': d.label, 'required': d.required and d.kind != FieldDef.BOOL}
    if d.kind == FieldDef.NUMBER:
        return forms.DecimalField(**opts)
    if d.kind == FieldDef.DATE:
        return forms.DateField(**opts)
    if d.kind == FieldDef.BOOL:
        return forms.BooleanField(**opts)
    if d.kind == FieldDef.CHOICE:
        return forms.ChoiceField(choices=[('', '---------')] + [(c, c) for c in d.choices], **opts)
    if d.kind == FieldDef.PARTNER:
        return forms.ModelChoiceField(Partner.objects.filter(active=True), **opts)
    if d.kind == FieldDef.USER:
        return forms.ModelChoiceField(get_user_model().objects.filter(is_active=True), **opts)
    return forms.CharField(**opts)


class ExtraFieldsForm(forms.ModelForm):
    """extra__<키> 칸 값을 extra(JSON)에 모은다. 정의에 없는 키(사용 중지된 칸 포함)는 그대로 둔다."""
    defs = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for d in self.defs:
            self.fields[f'extra__{d.key}'].initial = (self.instance.extra or {}).get(d.key)

    def clean(self):
        data = super().clean()
        extra = dict(self.instance.extra or {})
        for d in self.defs:
            v = data.get(f'extra__{d.key}')
            if d.kind == FieldDef.DATE and v:
                v = v.isoformat()
            elif d.kind in (FieldDef.PARTNER, FieldDef.USER) and v:
                v = v.pk
            if v in (None, ''):
                extra.pop(d.key, None)
            else:
                extra[d.key] = v
        self.instance.extra = extra
        return data

    def _update_errors(self, errors):
        # 모델 clean()의 extra 오류는 폼에 extra 칸이 없으므로 폼 상단 오류로 보인다
        if hasattr(errors, 'error_dict') and 'extra' in errors.error_dict:
            errors.error_dict.setdefault(NON_FIELD_ERRORS, []).extend(errors.error_dict.pop('extra'))
        super()._update_errors(errors)


class MasterAdmin(BaseAdmin):
    """기준정보 공통: 등록자 자동 기록, 지우는 대신 '사용'을 끈다. 사용자 정의 칸(FieldDef)을 폼 끝에 붙인다."""
    exclude = ['extra']

    def get_form(self, request, obj=None, change=False, **kwargs):
        defs = list(FieldDef.objects.filter(target=ContentType.objects.get_for_model(self.model), active=True))
        attrs = {'defs': defs, **{f'extra__{d.key}': extra_form_field(d) for d in defs}}
        kwargs['form'] = type('ExtraForm', (ExtraFieldsForm,), attrs)
        kwargs['widgets'] = {'note': forms.Textarea(attrs={'rows': 3}), **kwargs.get('widgets', {})}
        return super().get_form(request, obj, change, **kwargs)

    def get_fieldsets(self, request, obj=None):
        # 이 기준정보의 칸을 먼저 여러 열로, 사용자 정의 칸, 마지막에 사용·비고 (공통 칸이 맨 위에 오지 않게)
        if self.fieldsets:
            return super().get_fieldsets(request, obj)
        fields = self.get_fields(request, obj)
        tail = [f for f in ('active', 'note') if f in fields]
        extra = [f for f in fields if f.startswith('extra__')]
        main = [f for f in fields if f not in tail and f not in extra]
        sets = [(None, {'classes': ['grid'], 'fields': main})]
        if extra:
            sets.append(('사용자 정의 칸', {'classes': ['grid'], 'fields': extra}))
        return sets + [('관리', {'classes': ['grid'], 'fields': tail})]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Department)
class DepartmentAdmin(MasterAdmin):
    list_display = ['code', 'name', 'parent', 'manager', 'sort', 'active']
    list_filter = ['active']
    search_fields = ['code', 'name']


class PartnerCertificateInline(admin.TabularInline):
    model = PartnerCertificate
    extra = 1


@admin.register(Partner)
class PartnerAdmin(MasterAdmin):
    list_display = ['code', 'name', 'status', 'grade', 'is_supplier', 'is_customer', 'is_outsource', 'is_calibrator', 'active']
    list_filter = ['status', 'is_supplier', 'is_customer', 'active']
    search_fields = ['code', 'name', 'qc_name']
    inlines = [PartnerCertificateInline]


@admin.register(Attachment)
class AttachmentAdmin(BaseAdmin):
    """목록·이력 확인용. 파일은 각 기록 화면에서 올린다(대상 기록 열람 권한 확인 때문에)."""
    list_display = ['title', 'kind', 'content_type', 'object_id', 'uploaded_by', 'uploaded_at']
    list_filter = ['kind', 'content_type']
    search_fields = ['title']
    readonly_fields = ['content_type', 'object_id', 'download', 'uploaded_by', 'uploaded_at']
    exclude = ['file']

    @admin.display(description='파일')
    def download(self, obj):
        # FileField 기본 표시는 /media/ 주소라 닿지 않는다: 권한을 확인하는 내려받기 주소로 건다
        return format_html('<a href="{}">{}</a>', reverse('attachment_download', args=[obj.pk]), obj.title) if obj.pk else '-'

    def has_add_permission(self, request):
        return False


@admin.register(FieldDef)
class FieldDefAdmin(BaseAdmin):
    list_display = ['target', 'sort', 'key', 'label', 'kind', 'required', 'active']
    list_filter = ['target', 'kind', 'active']

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        return fields + ['target', 'key'] if obj else fields


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

    def related(self, obj):
        from qms.models import Inspection  # 검사는 qms 앱 기능
        return None, [('LOT', obj.lots.all(), f'work_order__id__exact={obj.pk}'),
                      ('작업 실적', obj.results.select_related('step__process'), f'work_order__id__exact={obj.pk}'),
                      ('검사', Inspection.objects.filter(lot__work_order=obj).select_related('lot', 'spec'),
                       ''),
                      ('부적합', Nonconformance.objects.filter(lot__work_order=obj), '')]


@admin.register(WorkResult)
class WorkResultAdmin(BaseAdmin):
    list_display = ['work_order', 'step', 'lot', 'input_qty', 'good_qty', 'defect_qty', 'operator', 'started_at']
    list_filter = ['step__process']
    search_fields = ['work_order__number', 'lot__number']
    autocomplete_fields = ['work_order', 'lot']

    def related(self, obj):
        return obj.lot, [('작업지시', WorkOrder.objects.filter(pk=obj.work_order_id), ''),
                         ('부적합', Nonconformance.objects.filter(lot_id=obj.lot_id), f'lot__id__exact={obj.lot_id}')]


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
    list_filter = ['item__item_type', 'supplier']
    autocomplete_fields = ['item', 'work_order', 'partner']
    inlines = [ParentLinkInline]

    @admin.display(boolean=True, description='보류')
    def is_hold(self, obj):
        return obj.on_hold

    @admin.display(boolean=True, description='계보 미등록')
    def is_gap(self, obj):
        return obj.lineage_gap

    def related(self, obj):
        from qms.models import CustomerClaim, Scar  # 클레임·SCAR는 qms 앱 기능
        q = f'lot__id__exact={obj.pk}'
        return obj, [('작업지시', WorkOrder.objects.filter(pk=obj.work_order_id), ''),
                     ('검사', obj.inspections.select_related('spec').order_by('-inspected_at'), q,
                      lambda i: f"{timezone.localtime(i.inspected_at):%m-%d %H:%M} {i.spec.get_inspection_type_display()} {i.get_result_display() or '판정 전'}"),
                     ('부적합', obj.nonconformances.all(), q),
                     ('보류', obj.holds.select_related('nonconformance'), q),
                     ('출하', obj.shipments.all(), q),
                     ('고객 클레임', CustomerClaim.objects.filter(lot=obj), q),
                     ('SCAR', Scar.objects.filter(lot=obj), q)]


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
            sign_disposition(self.instance, self.user, data.get('password') or '')  # forms.ValidationError와 같은 클래스
        return data

    def _post_clean(self):
        super()._post_clean()  # 폼 값이 instance에 들어간 뒤라야 읽기 전용 칸까지 포함해 판단할 수 있다
        if self._disposing() and (msg := missing_message(self.instance)):
            self.add_error(None, msg)


class NcPhotoInline(admin.TabularInline):
    model = NonconformancePhoto
    extra = 1
    fields = ['file', 'caption', 'uploaded_at']
    readonly_fields = ['uploaded_at']
    formfield_overrides = {models.FileField: {'widget': forms.ClearableFileInput(
        attrs={'accept': 'image/*', 'capture': 'environment'})}}

    def _open(self, request, obj):
        # 종결된 부적합의 사진은 본문과 같이 잠긴다
        return child_editable(obj, request.user)

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
        # 종결 뒤 보류 인터록 칸은 관리자·수정 승인으로도 바꿀 수 없다 (새 MRB 서명 없이 보류가 풀리거나 남는다)
        return self.AUTO + [f for f in nc_locked_fields(obj, request.user) if f not in self.AUTO]

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

    def related(self, obj):
        from qms.models import CustomerClaim, Inspection, Scar  # 검사·클레임·SCAR는 qms 앱 기능
        q = f'nonconformance__id__exact={obj.pk}'
        return obj.lot, [('원 검사', Inspection.objects.filter(nonconformance=obj).select_related('lot', 'spec'), q),
                         ('보류', obj.holds.select_related('lot'), q),
                         ('고객 클레임', CustomerClaim.objects.filter(nonconformance=obj), q),
                         ('SCAR', obj.scars.all(), q)]

    def get_form(self, request, obj=None, **kwargs):
        return type('Form', (super().get_form(request, obj, **kwargs),), {'user': request.user})


@admin.register(Hold)
class HoldAdmin(BaseAdmin):
    list_display = ['lot', 'nonconformance', 'created_at', 'released_at']
    list_filter = [('released_at', admin.EmptyFieldListFilter)]
    request_links_enabled = False  # 보류는 부적합 삭제와 함께만 지워진다
    search_fields = ['lot__number', 'nonconformance__number']

    def related(self, obj):
        return obj.lot, [('부적합', Nonconformance.objects.filter(pk=obj.nonconformance_id), '')]

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
    autocomplete_fields = ['lot', 'partner']
    readonly_fields = ['report_links']  # 인쇄 = 출하성적서, 고객 엑셀 양식은 매핑 {"A10": "coa_rows"}

    def related(self, obj):
        return obj.lot, [('부적합', Nonconformance.objects.filter(lot_id=obj.lot_id), f'lot__id__exact={obj.lot_id}')]


@admin.register(RevisionLog)
class RevisionLogAdmin(BaseAdmin):
    """개정 이력은 화면(API)에서 신청·확정한다. 관리 화면은 읽기 전용이다."""
    list_display = ('object_repr', 'label', 'status', 'requested_by', 'requested_at', 'approved_by')
    readonly_fields = [f.name for f in RevisionLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # 확정 이력은 지울 수 없다. 일괄 삭제 동작도 함께 빠진다

    def get_model_perms(self, request):
        return {}  # 전체 메뉴에는 올리지 않는다. 주소로만 연다
