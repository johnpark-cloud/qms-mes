"""연차·급여 새 화면 API. 언제나 로그인한 본인 기록만 읽고 쓴다(시스템 관리자도 남의 것은 못 본다)."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from .leave import balance
from .models import LeaveProfile, LeaveUse, Payslip


def _num(d):
    return format(Decimal(d).normalize(), 'f')


def _form(model, fields, data, instance=None):
    form = modelform_factory(model, fields=fields)(data, instance=instance)
    if not form.is_valid():
        raise ValidationError({k: list(v) for k, v in form.errors.items()})
    return form.save(commit=False)


class MeView(APIView):
    schema = None

    def get(self, request):
        today = timezone.localdate()
        year = today.year
        slips = list(Payslip.objects.filter(owner=request.user, month__year=year).prefetch_related('lines').order_by('month'))
        leave = balance(request.user, today)
        uses = LeaveUse.objects.filter(owner=request.user)
        # 합계와 같은 기간(입사 기념일 기준)으로 표를 맞춘다. 입사일 미설정이면 올해
        uses = uses.filter(used_on__range=(leave['period_start'], leave['period_end'])) if leave else uses.filter(used_on__year=year)
        profile = LeaveProfile.objects.filter(owner=request.user).first()
        total = {k: _num(sum((getattr(s, k) for s in slips), Decimal(0))) for k in ('gross', 'deduction', 'net')}
        return Response({
            'year': year,
            'hired_on': profile.hired_on.isoformat() if profile else None,
            'leave': leave and {'accrued': leave['accrued'], 'used': _num(leave['used']), 'remaining': _num(leave['remaining']),
                                'period_start': leave['period_start'].isoformat(), 'period_end': leave['period_end'].isoformat()},
            'uses': [{'id': u.pk, 'used_on': u.used_on.isoformat(), 'days': _num(u.days), 'reason': u.reason} for u in uses],
            'days_choices': [{'value': str(v), 'label': label} for v, label in LeaveUse.DAYS],
            'slips': [{'id': s.pk, 'month': f'{s.month:%Y-%m}', 'gross': _num(s.gross), 'deduction': _num(s.deduction), 'net': _num(s.net),
                       'file_url': reverse('payslip_file', args=[s.pk]) if s.file else None,
                       'edit_url': reverse('admin:personal_payslip_change', args=[s.pk])} for s in slips],
            'total': total if slips else None,
            'payslip_add_url': reverse('admin:personal_payslip_add'),
        })

    def post(self, request):  # 연차 사용 등록
        use = _form(LeaveUse, ['used_on', 'days', 'reason'], request.data)
        use.owner = request.user
        use.save()
        return Response({'id': use.pk}, status=201)

    def put(self, request):  # 입사일 설정
        profile = _form(LeaveProfile, ['hired_on'], request.data, LeaveProfile.objects.filter(owner=request.user).first())
        profile.owner = request.user
        profile.save()
        return Response({'hired_on': profile.hired_on.isoformat()})


class LeaveUseView(APIView):
    schema = None

    def delete(self, request, pk):  # 남의 것은 있는지도 드러내지 않는다
        get_object_or_404(LeaveUse, pk=pk, owner=request.user).delete()
        return Response(status=204)
