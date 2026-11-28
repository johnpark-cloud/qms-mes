"""연차·급여 새 화면 API. 언제나 로그인한 본인 기록만 읽고 쓴다(시스템 관리자도 남의 것은 못 본다)."""
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.forms import modelform_factory
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from .leave import balance
from .models import LeaveProfile, LeaveUse, PayLine, Payslip


def _num(d):
    return format(Decimal(d).normalize(), 'f')


def _form(model, fields, data, instance=None, files=None):
    form = modelform_factory(model, fields=fields)(data, files, instance=instance)
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
                       'file_url': reverse('payslip_file', args=[s.pk]) if s.file else None} for s in slips],
            'total': total if slips else None,
            'latest_id': Payslip.objects.filter(owner=request.user).values_list('pk', flat=True).first(),  # ordering -month
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


def _lines(raw):
    """수당·공제 줄 JSON을 검사해 저장 전 PayLine 목록으로 바꾼다. 하나라도 틀리면 아무것도 저장하지 않는다."""
    try:
        rows = json.loads(raw or '[]')
        assert isinstance(rows, list) and all(isinstance(r, dict) for r in rows)
    except (ValueError, AssertionError):
        raise ValidationError({'lines': ['수당·공제 형식이 올바르지 않습니다.']})
    out = []
    for i, row in enumerate(rows, 1):
        try:
            out.append(_form(PayLine, ['kind', 'name', 'amount'], row))
        except ValidationError as e:
            msgs = [m for ms in e.message_dict.values() for m in ms]
            raise ValidationError({'lines': [f'{i}번째 줄: {msgs[0]}']})
    return out


class PayslipView(APIView):
    """급여명세 등록·수정·삭제. 파일 때문에 multipart로 받는다(lines는 JSON 문자열).
    삭제는 소유자가 직접 한다: 품질 증적이 아니라 개인 자료라 삭제 요청·승인 흐름을 타지 않는다."""
    schema = None

    def _slip(self, request, pk):  # 남의 것은 있는지도 드러내지 않는다
        return get_object_or_404(Payslip.objects.prefetch_related('lines'), pk=pk, owner=request.user)

    def get(self, request, pk):
        s = self._slip(request, pk)
        return Response({'id': s.pk, 'month': f'{s.month:%Y-%m}', 'base_pay': _num(s.base_pay),
                         'lines': [{'kind': l.kind, 'name': l.name, 'amount': _num(l.amount)} for l in s.lines.all()],
                         'file_name': s.file.name.rsplit('/', 1)[-1] if s.file else None,
                         'file_url': reverse('payslip_file', args=[s.pk]) if s.file else None})

    def post(self, request, pk=None):
        instance = self._slip(request, pk) if pk else Payslip(owner=request.user)
        data = request.data.copy()
        if data.get('file_clear') == '1':
            data['file-clear'] = 'on'  # 기본 위젯(ClearableFileInput)의 '지우기' 칸
        lines = _lines(request.data.get('lines'))
        slip = _form(Payslip, ['month', 'base_pay', 'file'], data, instance, request.FILES)
        with transaction.atomic():
            slip.save()
            slip.lines.all().delete()
            for line in lines:
                line.payslip = slip
            PayLine.objects.bulk_create(lines)
        return Response({'id': slip.pk}, status=200 if pk else 201)

    def delete(self, request, pk):
        self._slip(request, pk).delete()
        return Response(status=204)
