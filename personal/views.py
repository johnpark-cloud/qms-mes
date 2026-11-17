from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect

from .models import Payslip


@staff_member_required
def me(request):
    return redirect('/app/me')  # 연차·급여는 새 화면(frontend/src/pages/MyLeavePay.tsx, API personal/api.py)


@staff_member_required
def payslip_file(request, pk):
    slip = get_object_or_404(Payslip, pk=pk, owner=request.user)
    if not slip.file:
        raise Http404
    return FileResponse(slip.file.open('rb'), as_attachment=True)
