from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .importer import run_import
from .models import Approvable, ImportProfile, Lot, is_approver


@staff_member_required
def trace(request):
    number = request.GET.get('lot', '').strip()
    lot = Lot.objects.filter(number=number).select_related('item').first() if number else None
    ctx = {'number': number, 'lot': lot, 'title': 'LOT 추적'}
    if lot:
        ctx.update(ancestors=lot.ancestors(), descendants=lot.descendants())
    return render(request, 'core/trace.html', ctx)


def _get_record(app_label, model_name, pk):
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        raise Http404
    return model, get_object_or_404(model, pk=pk)


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
    rows = []
    for f in model._meta.concrete_fields:
        value = getattr(obj, f'get_{f.name}_display', lambda: getattr(obj, f.name))()
        rows.append((f.verbose_name, '' if value is None else value))
    ctx = {'obj': obj, 'rows': rows, 'title': model._meta.verbose_name}
    if hasattr(obj, 'print_table'):  # 예: 출하 → 출하성적서, PPAP → PSW 요소표
        ctx['title'], ctx['table_header'], ctx['table'] = obj.print_table()
    return render(request, 'core/print.html', ctx)
