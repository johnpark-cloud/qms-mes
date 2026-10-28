from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

def private_storage():
    # MEDIA_ROOT 밖이라 어떤 /media/ 주소로도 닿지 않는다 (소유자 전용 화면만 연다)
    return FileSystemStorage(location=settings.DATA_DIR / 'private')


OWNER = dict(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name='소유자')


class LeaveProfile(models.Model):
    owner = models.OneToOneField(**OWNER)
    hired_on = models.DateField('입사일')

    class Meta:
        verbose_name = verbose_name_plural = '연차 설정'

    def __str__(self):  # 삭제 확인 화면·변경 로그에 입사일을 남기지 않는다
        return '연차 설정'


class LeaveUse(models.Model):
    # 저장값(decimal_places=2) 그대로 써야 수정 화면에서 기존 값이 선택된다
    DAYS = [(Decimal('1.00'), '1일'), (Decimal('0.50'), '반차 (0.5일)'), (Decimal('0.25'), '반반차 (0.25일)')]
    owner = models.ForeignKey(**OWNER)
    used_on = models.DateField('사용일')
    days = models.DecimalField('일수', max_digits=3, decimal_places=2, choices=DAYS, default=Decimal('1.00'))
    reason = models.CharField('사유', max_length=100, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = '연차 사용'
        ordering = ['-used_on']

    def __str__(self):  # 삭제 확인 화면·변경 로그에 날짜·일수를 남기지 않는다
        return '연차 사용'


class Payslip(models.Model):
    owner = models.ForeignKey(**OWNER)
    month = models.DateField('급여월 (매월 1일)')
    base_pay = models.DecimalField('기본급 (원)', max_digits=14, decimal_places=0)
    file = models.FileField('명세서 파일', upload_to='personal/%Y/', storage=private_storage, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = '급여명세'
        ordering = ['-month']
        constraints = [models.UniqueConstraint(fields=['owner', 'month'], name='uniq_payslip_owner_month')]

    def __str__(self):  # 금액은 로그에 남기지 않는다
        return f'{self.month:%Y-%m} 급여'

    def clean(self):
        if self.month:
            self.month = self.month.replace(day=1)
        if self.owner_id and self.month and Payslip.objects.filter(owner_id=self.owner_id, month=self.month).exclude(pk=self.pk).exists():
            raise ValidationError('이미 등록된 급여월입니다.')

    def save(self, *args, **kwargs):
        old = Payslip.objects.filter(pk=self.pk).values_list('file', flat=True).first() if self.pk else None
        super().save(*args, **kwargs)
        if old and old != self.file.name:  # 바뀐 명세서 파일의 옛 파일만 지운다
            transaction.on_commit(lambda: self.file.storage.delete(old))

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


@receiver(post_delete, sender=Payslip)
def _delete_payslip_file(sender, instance, **kwargs):
    # 삭제가 롤백되면 파일도 남아야 하므로 커밋 뒤에 지운다 (급여명세 삭제·사용자 삭제 모두)
    if instance.file:
        transaction.on_commit(lambda: instance.file.delete(save=False))


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
