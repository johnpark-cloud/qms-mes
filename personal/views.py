from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .leave import balance
from .models import LeaveUse, Payslip


@staff_member_required
def me(request):
    today = timezone.localdate()
    year = today.year
    slips = list(Payslip.objects.filter(owner=request.user, month__year=year).prefetch_related('lines').order_by('month'))
    total = {k: sum((getattr(s, k) for s in slips), Decimal(0)) for k in ('gross', 'deduction', 'net')}
    return render(request, 'personal/me.html', {
        'title': '연차·급여', 'year': year, 'leave': balance(request.user, today), 'slips': slips, 'total': total,
        'uses': LeaveUse.objects.filter(owner=request.user, used_on__year=year)})


@staff_member_required
def payslip_file(request, pk):
    slip = get_object_or_404(Payslip, pk=pk, owner=request.user)
    if not slip.file:
        raise Http404
    return FileResponse(slip.file.open('rb'), as_attachment=True)
