import datetime

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import Approvable, Item, Lot, Nonconformance


# ---------- 검사 ----------

class InspectionSpec(Approvable):
    INCOMING, PROCESS, OUTGOING = 'INCOMING', 'PROCESS', 'OUTGOING'
    TYPES = [(INCOMING, '수입검사'), (PROCESS, '공정검사'), (OUTGOING, '출하검사')]

    item = models.ForeignKey(Item, on_delete=models.PROTECT, verbose_name='품번')
    inspection_type = models.CharField('검사 구분', max_length=10, choices=TYPES)
    revision = models.PositiveIntegerField('개정번호', default=1)
    sampling = models.CharField('샘플링', max_length=200, blank=True, help_text='예: AQL 0.65 일반검사수준 II, n=5')
    note = models.TextField('비고', blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '검사기준'
        constraints = [models.UniqueConstraint(fields=['item', 'inspection_type', 'revision'], name='uniq_spec_rev')]

    def __str__(self):
        return f'{self.item.code} {self.get_inspection_type_display()} Rev.{self.revision}'

    @classmethod
    def current(cls, item, inspection_type):
        """승인된 최신 개정. 검사는 이 기준에 고정된다."""
        return (cls.objects.filter(item=item, inspection_type=inspection_type, approved_at__isnull=False)
                .order_by('-revision').first())


class Characteristic(models.Model):
    spec = models.ForeignKey(InspectionSpec, on_delete=models.CASCADE, related_name='characteristics', verbose_name='검사기준')
    name = models.CharField('검사항목', max_length=100)
    lsl = models.DecimalField('하한(LSL)', max_digits=14, decimal_places=5, null=True, blank=True)
    usl = models.DecimalField('상한(USL)', max_digits=14, decimal_places=5, null=True, blank=True)
    unit = models.CharField('단위', max_length=20, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '검사항목'

    def __str__(self):
        return f'{self.spec} / {self.name}'

    @property
    def is_variable(self):
        """규격이 있으면 계량형, 없으면 OK/NG 계수형."""
        return self.lsl is not None or self.usl is not None

    def save(self, *args, **kwargs):
        if self.spec.is_approved:
            raise ValidationError('승인된 검사기준의 항목은 수정할 수 없습니다. 새 개정을 만드세요.')
        super().save(*args, **kwargs)


class Inspection(models.Model):
    PASS, FAIL = 'PASS', 'FAIL'

    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name='inspections', verbose_name='LOT')
    spec = models.ForeignKey(InspectionSpec, on_delete=models.PROTECT, verbose_name='검사기준(당시 개정)')
    inspected_at = models.DateTimeField('검사 일시', default=timezone.now)
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                  verbose_name='검사자')
    result = models.CharField('판정', max_length=4, choices=[(PASS, '합격'), (FAIL, '불합격')], blank=True)
    nonconformance = models.OneToOneField(Nonconformance, on_delete=models.PROTECT, null=True, blank=True,
                                          related_name='inspection', verbose_name='부적합')
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '검사'

    def __str__(self):
        return f'{self.lot} {self.spec}'

    def clean(self):
        if self.spec_id and not self.spec.is_approved:
            raise ValidationError('승인되지 않은 검사기준으로는 검사할 수 없습니다.')
        if self.spec_id and self.lot_id and self.spec.item_id != self.lot.item_id:
            raise ValidationError('검사기준의 품번과 LOT의 품번이 다릅니다.')

    def save(self, *args, **kwargs):
        if self.pk and Inspection.objects.filter(pk=self.pk).exclude(result='').exists() and not getattr(self, '_finalizing', False):
            raise ValidationError('판정된 검사는 수정할 수 없습니다.')
        self.clean()
        super().save(*args, **kwargs)

    @transaction.atomic
    def finalize(self):
        """측정값으로 판정한다. 불합격이면 부적합을 만들고, 그 부적합이 계보 전체를 보류한다."""
        if self.result:
            return
        ms = list(self.measurements.select_related('characteristic'))
        missing = set(self.spec.characteristics.values_list('name', flat=True)) - {m.characteristic.name for m in ms}
        if missing:
            raise ValidationError(f'측정값이 없는 항목: {", ".join(sorted(missing))}')
        failed = sorted({m.characteristic.name for m in ms if not m.passed})
        self.result = self.FAIL if failed else self.PASS
        if failed:
            self.nonconformance = Nonconformance.objects.create(
                lot=self.lot, detected_at=self.inspected_at,
                description=f'{self.spec} 불합격: {", ".join(failed)}')
        self._finalizing = True
        self.save()


class Measurement(models.Model):
    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name='measurements', verbose_name='검사')
    characteristic = models.ForeignKey(Characteristic, on_delete=models.PROTECT, related_name='measurements',
                                       verbose_name='검사항목')
    value = models.DecimalField('측정값', max_digits=14, decimal_places=5, null=True, blank=True)
    ok = models.BooleanField('OK(계수형)', null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '측정값'

    def __str__(self):
        return f'{self.characteristic.name}={self.value if self.value is not None else self.ok}'

    @property
    def passed(self):
        c = self.characteristic
        if not c.is_variable:
            return self.ok is True
        return (self.value is not None and (c.lsl is None or self.value >= c.lsl)
                and (c.usl is None or self.value <= c.usl))

    def clean(self):
        if self.characteristic.spec_id != self.inspection.spec_id:
            raise ValidationError('검사기준에 없는 검사항목입니다.')
        if self.inspection.result:
            raise ValidationError('판정된 검사의 측정값은 수정할 수 없습니다.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


# ---------- 고객 클레임(8D) · 협력사(SCAR) ----------

class CustomerRule(models.Model):
    customer = models.CharField('고객사', max_length=100, unique=True)
    containment_hours = models.PositiveIntegerField('봉쇄(D3) 기한(시간)', default=24)
    corrective_days = models.PositiveIntegerField('대책(D5) 기한(일)', default=10)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '고객사별 8D 기한'

    def __str__(self):
        return self.customer


class CustomerClaim(models.Model):
    STEPS = [('d1_team', 'D1 팀 구성'), ('d2_problem', 'D2 문제 기술'), ('d3_containment', 'D3 봉쇄 조치'),
             ('d4_root_cause', 'D4 근본 원인'), ('d5_corrective', 'D5 시정 조치'), ('d6_verification', 'D6 유효성 확인'),
             ('d7_prevention', 'D7 재발 방지'), ('d8_closure', 'D8 종결·팀 인정')]

    number = models.CharField('클레임 번호', max_length=50, unique=True)
    customer = models.CharField('고객사', max_length=100)
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name='claims', verbose_name='클레임 LOT')
    description = models.TextField('클레임 내용')
    received_at = models.DateTimeField('접수 일시', default=timezone.now)
    nonconformance = models.OneToOneField(Nonconformance, on_delete=models.PROTECT, null=True, blank=True,
                                          related_name='claim', verbose_name='부적합')
    d1_team = models.TextField('D1 팀 구성', blank=True)
    d2_problem = models.TextField('D2 문제 기술', blank=True)
    d3_containment = models.TextField('D3 봉쇄 조치', blank=True, help_text='LOT 추적 화면의 영향 범위를 근거로 기록')
    d4_root_cause = models.TextField('D4 근본 원인', blank=True)
    d5_corrective = models.TextField('D5 시정 조치', blank=True)
    d6_verification = models.TextField('D6 유효성 확인', blank=True)
    d7_prevention = models.TextField('D7 재발 방지', blank=True)
    d8_closure = models.TextField('D8 종결·팀 인정', blank=True)
    closed_at = models.DateTimeField('종결 일시', null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '고객 클레임(8D)'

    def __str__(self):
        return f'{self.number} {self.customer}'

    def _rule(self):
        return CustomerRule.objects.filter(customer=self.customer).first() or CustomerRule(customer=self.customer)

    @property
    def containment_due(self):
        return self.received_at + datetime.timedelta(hours=self._rule().containment_hours)

    @property
    def corrective_due(self):
        return self.received_at + datetime.timedelta(days=self._rule().corrective_days)

    @property
    def current_step(self):
        return next((label for field, label in self.STEPS if not getattr(self, field)), '완료')

    def clean(self):
        if self.closed_at and self.current_step != '완료':
            raise ValidationError(f'{self.current_step}이(가) 비어 있어 종결할 수 없습니다.')

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.clean()
        if self._state.adding and not self.nonconformance_id:
            # 클레임 접수 = 부적합 등록 → 클레임 LOT과 하위 계보 자동 보류
            self.nonconformance = Nonconformance.objects.create(
                lot=self.lot, detected_at=self.received_at, description=f'고객 클레임 {self.number}: {self.description}')
        super().save(*args, **kwargs)


class Scar(models.Model):
    number = models.CharField('SCAR 번호', max_length=50, unique=True)
    supplier = models.CharField('협력사', max_length=100)
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name='scars', verbose_name='자재 LOT')
    nonconformance = models.ForeignKey(Nonconformance, on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='scars', verbose_name='부적합')
    request = models.TextField('요구 내용')
    issued_at = models.DateField('발행일', default=datetime.date.today)
    response_due = models.DateField('회신 기한')
    response = models.TextField('협력사 회신', blank=True)
    responded_at = models.DateField('회신일', null=True, blank=True)
    closed_at = models.DateField('종결일', null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '협력사 시정요구(SCAR)'

    def __str__(self):
        return f'{self.number} {self.supplier}'

    def clean(self):
        if self.closed_at and not self.response:
            raise ValidationError('협력사 회신 없이 종결할 수 없습니다.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


# ---------- 문서 · 심사 증적 ----------

class Document(models.Model):
    number = models.CharField('문서번호', max_length=50, unique=True)
    title = models.CharField('문서명', max_length=200)
    doc_type = models.CharField('종류', max_length=50, blank=True, help_text='예: Control Plan, PFMEA, 작업표준서')
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '문서'

    def __str__(self):
        return f'{self.number} {self.title}'

    @property
    def current_revision(self):
        """유효본 = 승인된 최신 개정."""
        return self.revisions.filter(approved_at__isnull=False).order_by('-approved_at').first()


class DocumentRevision(Approvable):
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name='revisions', verbose_name='문서')
    revision = models.CharField('개정', max_length=20)
    file = models.FileField('원본 파일', upload_to='documents/%Y/')
    change_note = models.TextField('개정 내용')
    created_at = models.DateTimeField('등록 일시', default=timezone.now)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '문서 개정'
        constraints = [models.UniqueConstraint(fields=['document', 'revision'], name='uniq_doc_rev')]

    def __str__(self):
        return f'{self.document.number} Rev.{self.revision}'


class AuditChecklist(models.Model):
    name = models.CharField('체크리스트', max_length=200, help_text='예: 고객사 QSA 2026, IATF 16949 내부심사')
    standard = models.CharField('규격', max_length=100, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '심사 체크리스트'

    def __str__(self):
        return self.name


class AuditItem(models.Model):
    checklist = models.ForeignKey(AuditChecklist, on_delete=models.CASCADE, related_name='items', verbose_name='체크리스트')
    clause = models.CharField('항목 번호', max_length=50)
    requirement = models.TextField('요구사항')
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '심사 항목'
        ordering = ['checklist', 'clause']

    def __str__(self):
        return f'{self.clause} {self.requirement[:40]}'


class Evidence(models.Model):
    item = models.ForeignKey(AuditItem, on_delete=models.CASCADE, related_name='evidences', verbose_name='심사 항목')
    document = models.ForeignKey(Document, on_delete=models.PROTECT, null=True, blank=True, verbose_name='문서')
    record_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, null=True, blank=True, verbose_name='기록 종류')
    record_id = models.PositiveIntegerField('기록 ID', null=True, blank=True)
    record = GenericForeignKey('record_type', 'record_id')
    note = models.CharField('설명', max_length=200, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '증적'

    def __str__(self):
        return str(self.document or self.record or self.note)

    def clean(self):
        if not self.document_id and not (self.record_type_id and self.record_id):
            raise ValidationError('문서나 기록 중 하나는 연결해야 합니다.')


# ---------- 보고서 ----------

class ExcelTemplate(models.Model):
    """고객사 엑셀 양식에 값을 채운다. 양식이 바뀌면 매핑만 고친다."""
    name = models.CharField('양식 이름', max_length=100)
    target = models.ForeignKey(ContentType, on_delete=models.PROTECT, verbose_name='대상 기록')
    file = models.FileField('엑셀 양식', upload_to='templates/')
    mapping = models.JSONField('셀 매핑', help_text='예: {"B3": "number", "B4": "lot.number", "Sheet2!C5": "d4_root_cause"}')
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '엑셀 보고서 양식'

    def __str__(self):
        return self.name

    def fill(self, obj):
        from io import BytesIO

        from openpyxl import load_workbook
        wb = load_workbook(self.file.path)
        for cell, path in self.mapping.items():
            sheet, _, ref = cell.rpartition('!')
            value = obj
            for attr in path.split('.'):
                value = getattr(value, attr, None) if value is not None else None
                value = value() if callable(value) else value
            if isinstance(value, datetime.datetime):
                value = timezone.localtime(value).replace(tzinfo=None)  # 엑셀은 시간대를 저장하지 못한다
            (wb[sheet] if sheet else wb.active)[ref] = '' if value is None else value
        out = BytesIO()
        wb.save(out)
        return out.getvalue()
