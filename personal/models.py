from decimal import Decimal

from django.conf import settings
from django.db import models

OWNER = dict(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name='소유자')


class LeaveProfile(models.Model):
    owner = models.OneToOneField(**OWNER)
    hired_on = models.DateField('입사일')

    class Meta:
        verbose_name = verbose_name_plural = '연차 설정'

    def __str__(self):
        return f'입사 {self.hired_on}'


class LeaveUse(models.Model):
    DAYS = [(Decimal('1'), '1일'), (Decimal('0.5'), '반차 (0.5일)'), (Decimal('0.25'), '반반차 (0.25일)')]
    owner = models.ForeignKey(**OWNER)
    used_on = models.DateField('사용일')
    days = models.DecimalField('일수', max_digits=3, decimal_places=2, choices=DAYS, default=Decimal('1'))
    reason = models.CharField('사유', max_length=100, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = '연차 사용'
        ordering = ['-used_on']

    def __str__(self):
        return f'{self.used_on} {self.days}일'


class Payslip(models.Model):
    owner = models.ForeignKey(**OWNER)
    month = models.DateField('급여월 (매월 1일)')
    base_pay = models.DecimalField('기본급 (원)', max_digits=14, decimal_places=0)
    file = models.FileField('명세서 파일', upload_to='personal/%Y/', blank=True)

    class Meta:
        verbose_name = verbose_name_plural = '급여명세'
        ordering = ['-month']
        constraints = [models.UniqueConstraint(fields=['owner', 'month'], name='uniq_payslip_owner_month')]

    def __str__(self):  # 금액은 로그에 남기지 않는다
        return f'{self.month:%Y-%m} 급여'

    def _sum(self, kind):
        return sum((l.amount for l in self.lines.all() if l.kind == kind), Decimal(0))

    @property
    def gross(self):
        return self.base_pay + self._sum(PayLine.PLUS)

    @property
    def deduction(self):
        return self._sum(PayLine.MINUS)

    @property
    def net(self):
        return self.gross - self.deduction


class PayLine(models.Model):
    PLUS, MINUS = 'PLUS', 'MINUS'
    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name='lines', verbose_name='급여명세')
    kind = models.CharField('구분', max_length=5, choices=[(PLUS, '수당'), (MINUS, '공제')])
    name = models.CharField('항목', max_length=50)
    amount = models.DecimalField('금액 (원)', max_digits=14, decimal_places=0)

    class Meta:
        verbose_name = verbose_name_plural = '수당·공제'

    def __str__(self):
        return self.name
