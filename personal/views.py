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
    leave = balance(request.user, today)
    uses = LeaveUse.objects.filter(owner=request.user)
    # 합계와 같은 기간(입사 기념일 기준)으로 표를 맞춘다. 입사일 미설정이면 올해
    uses = uses.filter(used_on__range=(leave['period_start'], leave['period_end'])) if leave else uses.filter(used_on__year=year)
    total = {k: sum((getattr(s, k) for s in slips), Decimal(0)) for k in ('gross', 'deduction', 'net')}
    return render(request, 'personal/me.html', {
        'title': '연차·급여', 'year': year, 'leave': leave, 'slips': slips, 'total': total, 'uses': uses})


@staff_member_required
def payslip_file(request, pk):
    slip = get_object_or_404(Payslip, pk=pk, owner=request.user)
    if not slip.file:
        raise Http404
    return FileResponse(slip.file.open('rb'), as_attachment=True)
