import io
import os
import zipfile
from smtplib import SMTPException

from django import forms
from django.apps import apps
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.http import FileResponse, Http404, HttpResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .importer import run_import
from .models import (Approvable, EditRequest, Hold, ImportProfile, Lot, Nonconformance, NonconformancePhoto, is_approver,
                     validate_photo)
from .records import blockers, is_locked


def find_logo():
    for ext in ('svg', 'png', 'jpg'):
        path = settings.DATA_DIR / 'brand' / f'logo.{ext}'
        if path.is_file():
            return path


def brand_logo(request):
    # 로그인 화면에서도 보여야 해서 인증 없이 제공한다
    path = find_logo()
    if path is None:
        raise Http404
    return FileResponse(open(path, 'rb'))


@staff_member_required
def trace(request):
    number = request.GET.get('lot', '').strip()
    lot = Lot.objects.filter(number=number).select_related('item').first() if number else None
    ctx = {'number': number, 'lot': lot, 'title': 'LOT 추적'}
    if lot:
        ctx.update(ancestors=lot.ancestors(), descendants=lot.descendants())
    return render(request, 'core/trace.html', ctx)


class MultiPhotoInput(forms.ClearableFileInput):
    allow_multiple_selected = True

    def __init__(self, attrs=None):
        super().__init__({'accept': 'image/*', 'capture': 'environment', 'multiple': True, **(attrs or {})})


class MultiPhotoField(forms.FileField):
    widget = MultiPhotoInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data]
        out = [super(MultiPhotoField, self).clean(f, initial) for f in files if f]
        for f in out:
            validate_photo(f)
        return out


class QuickNcForm(forms.Form):
    lot = forms.CharField(label='LOT 번호', max_length=100)
    origin = forms.ChoiceField(label='발생 유형', choices=Nonconformance.ORIGINS, initial='PROCESS')
    description = forms.CharField(label='부적합 내용', widget=forms.Textarea(attrs={'rows': 4}))
    defect_qty = forms.DecimalField(label='불량 수량', min_value=0, initial=1)
    photos = MultiPhotoField(label='사진', required=False)

    def clean_lot(self):
        n = self.cleaned_data['lot'].strip()  # 스캐너가 붙이는 공백·줄바꿈 제거
        lot = Lot.objects.filter(number=n).first() or Lot.objects.filter(number__iexact=n).first()
        if not lot:
            raise ValidationError('등록되지 않은 LOT입니다.')
        return lot


@staff_member_required
def nc_quick(request):
    """현장 간편 등록: 필수 5칸만 받고 나머지는 부적합 화면에서 보완한다. 저장하면 보류가 자동 생성된다."""
    if not request.user.has_perm('core.add_nonconformance'):
        raise PermissionDenied
    form = QuickNcForm(request.POST or None, request.FILES or None, initial={'lot': request.GET.get('lot', '').strip()})
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            with transaction.atomic():
                nc = Nonconformance.objects.create(lot=d['lot'], origin=d['origin'], description=d['description'],
                                                   defect_qty=d['defect_qty'], detected_by=request.user)
                for f in d['photos']:
                    NonconformancePhoto.objects.create(nonconformance=nc, file=f)
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, f'{nc.number} 등록됨 — LOT {d["lot"].number} 보류. 나머지 항목은 부적합 화면에서 보완하세요.')
            return redirect(f'{reverse("trace")}?lot={d["lot"].number}')
    return render(request, 'core/nc_quick.html', {'form': form, 'title': '부적합 등록'})


def _get_record(app_label, model_name, pk):
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        raise Http404
    return model, get_object_or_404(model, pk=pk)


def _field_rows(obj):
    rows = []
    for f in obj._meta.concrete_fields:
        value = getattr(obj, f'get_{f.name}_display', lambda: getattr(obj, f.name))()
        rows.append((f.verbose_name, '' if value is None else value))
    return rows


@staff_member_required
def edit_request(request, kind, app_label, model_name, pk):
    """삭제·수정 요청: 사유와 본인 비밀번호. 시스템 관리자는 요청과 동시에 승인·실행된다."""
    model, obj = _get_record(app_label, model_name, pk)
    # 관리 화면이 없는 기록과 보류(부적합과 함께만 삭제)는 요청 대상이 아니다
    if not admin.site.is_registered(model) or model is Hold or kind not in (EditRequest.DELETE, EditRequest.EDIT):
        raise Http404
    if kind == EditRequest.EDIT and not is_locked(obj):
        raise Http404
    if not request.user.has_perm(f'{app_label}.view_{model_name}'):
        raise PermissionDenied
    back = reverse(f'admin:{app_label}_{model_name}_change', args=[pk])
    error = None
    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        if not reason:
            error = '사유를 입력하세요.'
        elif not request.user.check_password(request.POST.get('password', '')):
            error = '비밀번호가 맞지 않습니다.'
        else:
            req = EditRequest.objects.create(kind=kind, target=obj, object_repr=str(obj)[:200], reason=reason,
                                             requested_by=request.user)
            if not request.user.is_superuser:
                messages.success(request, '요청했습니다. 시스템 관리자가 승인하면 처리됩니다.')
                return redirect(back)
            try:
                req.decide(request.user, True)
            except ValidationError as e:  # 예: 다른 기록이 참조 중이라 삭제 불가 → 승인 화면에서 안내
                messages.error(request, ' '.join(e.messages))
                return redirect('edit_request_decide', req.pk)
            if kind == EditRequest.DELETE:
                messages.success(request, f'{req.object_repr} 삭제 완료')
                return redirect(f'admin:{app_label}_{model_name}_changelist')
            return redirect(back)
    title = '삭제 요청' if kind == EditRequest.DELETE else '수정 요청'
    return render(request, 'core/edit_request.html',
                  {'obj': obj, 'req': None, 'kind': kind, 'error': error, 'back': back, 'title': title})


@staff_member_required
def edit_request_decide(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied('시스템 관리자만 처리할 수 있습니다.')
    req = get_object_or_404(EditRequest, pk=pk)
    obj, error = req.target, None
    back = reverse(f'admin:{req.content_type.app_label}_{req.content_type.model}_change', args=[req.object_id])
    if request.method == 'POST' and req.status == EditRequest.PENDING:
        try:
            req.decide(request.user, 'approve' in request.POST, request.POST.get('reject_reason', '').strip())
        except ValidationError as e:
            error = ' '.join(e.messages)
        else:
            messages.success(request, f'{req} → {req.get_status_display()}')
            return redirect('todo')
    ctx = {'req': req, 'obj': obj, 'error': error, 'back': back, 'title': f'{req.get_kind_display()} 요청 처리',
           'rows': _field_rows(obj) if obj else [],
           'blockers': [f'{o._meta.verbose_name}: {o}' for o in blockers(obj)]
           if obj and req.kind == EditRequest.DELETE and req.status == EditRequest.PENDING else []}
    return render(request, 'core/edit_request.html', ctx)


@staff_member_required
def approve(request, app_label, model_name, pk):
    """승인 서명: 승인자가 비밀번호를 다시 입력해야 승인된다."""
    model, obj = _get_record(app_label, model_name, pk)
    if not issubclass(model, Approvable):
        raise Http404
    if not is_approver(request.user):
        raise PermissionDenied('품질팀장만 승인할 수 있습니다.')
    back = reverse(f'admin:{app_label}_{model_name}_change', args=[pk])
    if obj.is_approved:
        messages.info(request, '이미 승인된 기록입니다.')
        return redirect(back)
    error = None
    if request.method == 'POST':
        if not request.user.check_password(request.POST.get('password', '')):
            error = '비밀번호가 맞지 않습니다.'
        else:
            obj.approved_by, obj.approved_at = request.user, timezone.now()
            try:
                obj.save()
            except ValidationError as e:  # 예: 고객 승인번호 없는 4M 변경
                error = ' '.join(e.messages)
            else:
                messages.success(request, f'{obj} 승인 완료')
                return redirect(back)
    return render(request, 'core/approve.html', {'obj': obj, 'error': error, 'back': back, 'title': '승인 서명'})


class ImportForm(forms.Form):
    profile = forms.ModelChoiceField(ImportProfile.objects.all(), label='가져오기 설정')
    file = forms.FileField(label='엑셀(.xlsx) 또는 CSV 파일')


@staff_member_required
def import_view(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == 'POST' and form.is_valid():
        count, errors = run_import(form.cleaned_data['profile'], form.cleaned_data['file'])
        result = {'count': count, 'errors': errors}
    return render(request, 'core/import.html', {'form': form, 'result': result, 'title': '엑셀 일괄 등록'})


@staff_member_required
def print_view(request, app_label, model_name, pk):
    """인쇄용 화면. 브라우저의 'PDF로 저장'으로 PDF를 만든다."""
    model, obj = _get_record(app_label, model_name, pk)
    if not request.user.has_perm(f'{app_label}.view_{model_name}'):
        raise PermissionDenied
    ctx = {'obj': obj, 'rows': _field_rows(obj), 'title': model._meta.verbose_name}
    if hasattr(obj, 'print_table'):  # 예: 출하 → 출하성적서, PPAP → PSW 요소표
        ctx['title'], ctx['table_header'], ctx['table'] = obj.print_table()
    return render(request, getattr(obj, 'print_template', 'core/print.html'), ctx)


def _approved_nc(pk):
    nc = get_object_or_404(Nonconformance, pk=pk)
    if not nc.is_approved:
        raise Http404
    return nc


@staff_member_required
def nc_mail(request, pk):
    """승인된 부적합 보고 메일: 본문 복사(웹메일 붙여넣기)가 기본, SMTP가 있으면 바로 보내기도 된다."""
    nc = _approved_nc(pk)
    if not request.user.has_perm('core.view_nonconformance'):
        raise PermissionDenied
    title, header, rows = nc.print_table()
    subject = f'[부적합 보고] {nc.number} {nc.lot}'
    ctx = {'nc': nc, 'subject': subject, 'table_header': header, 'table': rows, 'title': '메일 보내기',
           'photos': nc.photos.all(), 'smtp': settings.SMTP_ENABLED}
    action = request.POST.get('action')
    if request.method == 'POST' and action == 'mark_sent':
        Nonconformance.objects.filter(pk=nc.pk).update(mailed_at=timezone.now())  # 승인 잠금(save)을 거치지 않는다
        messages.success(request, '보냈음으로 표시했습니다.')
        return redirect(request.path)
    if request.method == 'POST' and action == 'send' and settings.SMTP_ENABLED:
        ctx['to'] = request.POST.get('to', '')
        to = [a.strip() for a in ctx['to'].split(',') if a.strip()]
        try:
            if not to:
                raise ValidationError('수신자 메일 주소를 입력하세요.')
            for a in to:
                validate_email(a)
        except ValidationError:
            ctx['error'] = '메일 주소 형식이 올바르지 않습니다. 쉼표로 구분해 정확히 입력하세요.'
            return render(request, 'core/nc_mail.html', ctx)
        msg = EmailMessage(subject, render_to_string('core/_nc_mail_body.html', ctx), None, to)
        msg.content_subtype = 'html'
        for p in ctx['photos']:
            with p.file.open('rb') as f:
                msg.attach(os.path.basename(p.file.name), f.read())
        try:
            msg.send()
        except (SMTPException, OSError) as e:
            ctx['error'] = f'메일을 보내지 못했습니다 ({e}). 보냈음 표시는 하지 않았습니다.'
            return render(request, 'core/nc_mail.html', ctx)
        Nonconformance.objects.filter(pk=nc.pk).update(mailed_at=timezone.now())
        messages.success(request, f'{", ".join(to)}로 보냈습니다.')
        return redirect(request.path)
    return render(request, 'core/nc_mail.html', ctx)


@staff_member_required
def nc_photos_zip(request, pk):
    nc = _approved_nc(pk)
    if not request.user.has_perm('core.view_nonconformance'):
        raise PermissionDenied
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:  # 사진은 이미 압축 포맷이라 저장만 한다
        for i, p in enumerate(nc.photos.all(), 1):
            z.write(p.file.path, f'{nc.number}_{i}{os.path.splitext(p.file.name)[1].lower()}')
    return HttpResponse(buf.getvalue(), content_type='application/zip',
                        headers={'Content-Disposition': f'attachment; filename="{nc.number}_photos.zip"'})
