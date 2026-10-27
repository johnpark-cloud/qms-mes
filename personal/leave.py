"""연차 계산. 입사일 기준: 1년 미만은 개근 개월 수(최대 11), 이후 15일에 2년마다 1일 가산(최대 25)."""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum


def anniversary(hired_on, year):
    # 2월 29일 입사자의 평년 기념일은 2월 28일
    try:
        return hired_on.replace(year=year)
    except ValueError:
        return date(year, 2, 28)


def years_served(hired_on, on):
    n = on.year - hired_on.year
    return n - 1 if on < anniversary(hired_on, on.year) else n


def accrued_days(hired_on, on):
    if on < hired_on:
        return 0
    n = years_served(hired_on, on)
    if n < 1:
        return (on.year - hired_on.year) * 12 + on.month - hired_on.month - (on.day < hired_on.day)
    return min(15 + (n - 1) // 2, 25)


def balance(owner, on):
    from .models import LeaveProfile, LeaveUse
    profile = LeaveProfile.objects.filter(owner=owner).first()
    if profile is None:
        return None
    hired = profile.hired_on
    n = max(years_served(hired, on), 0)
    start = hired if n < 1 else anniversary(hired, hired.year + n)
    end = anniversary(hired, hired.year + n + 1) - timedelta(days=1)
    accrued = accrued_days(hired, on)
    used = LeaveUse.objects.filter(owner=owner, used_on__range=(start, end)).aggregate(s=Sum('days'))['s'] or Decimal(0)
    return {'accrued': accrued, 'used': used, 'remaining': accrued - used, 'period_start': start, 'period_end': end}
