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


SPECIAL = [('', '-'), ('CC', 'CC(핵심·안전)'), ('SC', 'SC(중요)')]


class Characteristic(models.Model):
    spec = models.ForeignKey(InspectionSpec, on_delete=models.CASCADE, related_name='characteristics', verbose_name='검사기준')
    name = models.CharField('검사항목', max_length=100)
    lsl = models.DecimalField('하한(LSL)', max_digits=14, decimal_places=5, null=True, blank=True)
    usl = models.DecimalField('상한(USL)', max_digits=14, decimal_places=5, null=True, blank=True)
    unit = models.CharField('단위', max_length=20, blank=True)
    special = models.CharField('특별특성', max_length=2, choices=SPECIAL, blank=True,
                               help_text='CC·SC는 SPC 경보 시 부적합이 자동 등록된다')
    plan_line = models.ForeignKey('ControlPlanLine', on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='characteristics', verbose_name='관리계획서 항목')
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

    def spc_series(self, limit=30):
        """판정된 측정값을 검사(부분군)별로 시간순으로 묶는다. 같은 품번·검사구분·항목명이면 기준 개정이 달라도 같은 특성."""
        ms = (Measurement.objects
              .filter(characteristic__spec__item=self.spec.item_id, characteristic__spec__inspection_type=self.spec.inspection_type,
                      characteristic__name=self.name, value__isnull=False, inspection__result__in=['PASS', 'FAIL'])
              .select_related('inspection__lot').order_by('-inspection__inspected_at', '-inspection_id', 'pk'))
        groups = {}
        for m in ms:  # shortcut: 최근 limit개 부분군만 읽는다, 장기 추세가 필요하면 기간 선택을 추가
            if m.inspection not in groups and len(groups) >= limit:
                break
            groups.setdefault(m.inspection, []).append(m.value)
        return list(reversed(groups.items()))


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
        quals = Qualification.objects.filter(inspection_type=self.spec.inspection_type)
        # 자격 기록이 하나라도 등록된 검사구분부터 강제한다 (새 회사에서 점진 도입)
        if quals.exists() and not quals.filter(user_id=self.inspector_id, valid_until__gte=timezone.localdate()).exists():
            raise ValidationError(f'{self.inspector or "검사자 미지정"}: {self.spec.get_inspection_type_display()} 판정 자격이 없습니다.')
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
        if self.result == self.PASS:
            self._special_spc_check()

    def _special_spc_check(self):
        """합격이어도 특별특성(CC·SC)의 SPC 경보가 이 검사에서 났으면 부적합을 등록한다 (→ 계보 보류)."""
        from . import spc
        for c in self.spec.characteristics.exclude(special=''):
            if not c.is_variable:
                continue
            try:
                last = spc.control_chart(c.spc_series(), c.lsl, c.usl)['points'][-1]
            except ValueError:
                continue  # 점이 부족하면 아직 관리도를 그릴 수 없다
            if last['label'] == self and last['alarms']:
                self.nonconformance = Nonconformance.objects.create(
                    lot=self.lot, detected_at=self.inspected_at, defect_type='SPC 경보',
                    description=f'특별특성 {c.name}({c.special}) SPC 경보: {", ".join(last["alarms"])} (검사 {self.pk})')
                self.save()
                return


class Measurement(models.Model):
    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name='measurements', verbose_name='검사')
    characteristic = models.ForeignKey(Characteristic, on_delete=models.PROTECT, related_name='measurements',
                                       verbose_name='검사항목')
    value = models.DecimalField('측정값', max_digits=14, decimal_places=5, null=True, blank=True)
    ok = models.BooleanField('OK(계수형)', null=True, blank=True)
    gauge = models.ForeignKey('Gauge', on_delete=models.PROTECT, null=True, blank=True, verbose_name='계측기')
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
        g = self.gauge
        if g and not g.usable_on(timezone.localtime(self.inspection.inspected_at).date()):
            raise ValidationError(f'계측기 {g.number}은(는) 교정 기한({g.next_due})이 지났거나 사용 중지되어 측정에 쓸 수 없습니다.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Gauge(models.Model):
    """계측기 대장 (IATF 7.1.5). 측정값에 계측기를 적으면 교정 기한을 검사한다."""
    number = models.CharField('관리번호', max_length=50, unique=True)
    name = models.CharField('계측기명', max_length=100, help_text='예: 마이크로미터 0-25mm')
    interval_days = models.PositiveIntegerField('교정 주기(일)', default=365)
    last_calibrated = models.DateField('최근 교정일')
    certificate = models.FileField('교정 성적서', upload_to='gauges/%Y/', blank=True)
    active = models.BooleanField('사용', default=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '계측기'

    def __str__(self):
        return f'{self.number} {self.name}'

    @property
    def next_due(self):
        return self.last_calibrated + datetime.timedelta(days=self.interval_days)

    def usable_on(self, day):
        return self.active and day <= self.next_due


class Qualification(models.Model):
    """검사원 자격 (IATF 7.2). 검사구분에 자격 기록이 생기면 그때부터 자격자만 판정할 수 있다."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='qualifications',
                             verbose_name='검사원')
    inspection_type = models.CharField('검사 구분', max_length=10, choices=InspectionSpec.TYPES)
    valid_until = models.DateField('유효기한')
    basis = models.CharField('근거', max_length=200, help_text='예: 2026-10 수입검사 교육 이수, 실기 평가 합격')
    record = models.FileField('교육 기록', upload_to='training/%Y/', blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '검사원 자격'

    def __str__(self):
        return f'{self.user} {self.get_inspection_type_display()} ~{self.valid_until}'


# ---------- 관리계획서(PFMEA) · 4M 변경 ----------

class ControlPlan(Approvable):
    STAGES = [('PROTO', '시작품'), ('PRELAUNCH', '양산 전'), ('PRODUCTION', '양산')]

    item = models.ForeignKey(Item, on_delete=models.PROTECT, verbose_name='품번')
    stage = models.CharField('단계', max_length=10, choices=STAGES, default='PRODUCTION')
    revision = models.PositiveIntegerField('개정번호', default=1)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '관리계획서(PFMEA)'
        constraints = [models.UniqueConstraint(fields=['item', 'stage', 'revision'], name='uniq_cp_rev')]

    def __str__(self):
        return f'{self.item.code} {self.get_stage_display()} 관리계획서 Rev.{self.revision}'


class ControlPlanLine(models.Model):
    plan = models.ForeignKey(ControlPlan, on_delete=models.CASCADE, related_name='lines', verbose_name='관리계획서')
    process = models.ForeignKey('core.Process', on_delete=models.PROTECT, null=True, blank=True, verbose_name='공정')
    characteristic = models.CharField('특성', max_length=100)
    special = models.CharField('특별특성', max_length=2, choices=SPECIAL, blank=True)
    lsl = models.DecimalField('하한(LSL)', max_digits=14, decimal_places=5, null=True, blank=True)
    usl = models.DecimalField('상한(USL)', max_digits=14, decimal_places=5, null=True, blank=True)
    unit = models.CharField('단위', max_length=20, blank=True)
    method = models.CharField('측정방법', max_length=100, blank=True)
    sampling = models.CharField('샘플링', max_length=100, blank=True)
    inspection_type = models.CharField('검사 구분', max_length=10, choices=InspectionSpec.TYPES, blank=True,
                                       help_text='비우면 검사기준을 만들지 않는다 (예: 설비 조건으로 관리)')
    reaction = models.CharField('이상 시 조치', max_length=200, blank=True)
    failure_mode = models.CharField('잠재 고장모드', max_length=200, blank=True)
    severity = models.PositiveSmallIntegerField('심각도(S)', null=True, blank=True)
    occurrence = models.PositiveSmallIntegerField('발생도(O)', null=True, blank=True)
    detection = models.PositiveSmallIntegerField('검출도(D)', null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '관리계획서 항목'

    def __str__(self):
        return f'{self.plan} / {self.characteristic}'

    @property
    def action_priority(self):
        s, o, d = self.severity, self.occurrence, self.detection
        if None in (s, o, d):
            return ''
        # shortcut: AIAG-VDA AP 표를 단순화한 규칙, 고객이 표 그대로를 요구하면 표 전체로 교체
        if (s >= 9 and (o >= 4 or d >= 7)) or (s >= 7 and o >= 6) or (s >= 5 and o >= 8):
            return 'H'
        if s >= 9 or (s >= 7 and (o >= 4 or d >= 7)) or (s >= 4 and o >= 6):
            return 'M'
        return 'L'

    def save(self, *args, **kwargs):
        if self.plan.is_approved:
            raise ValidationError('승인된 관리계획서의 항목은 수정할 수 없습니다. 새 개정을 만드세요.')
        super().save(*args, **kwargs)


class ChangeRequest(Approvable):
    """4M 변경. 승인 후 적용 일시가 지나면, 그 품번의 합격 검사(초품)가 나오기 전까지 출하를 막는다."""
    CATEGORIES = [('MAN', '사람(Man)'), ('MACHINE', '설비(Machine)'), ('MATERIAL', '자재(Material)'), ('METHOD', '방법(Method)')]

    number = models.CharField('변경 번호', max_length=50, unique=True)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='changes', verbose_name='품번')
    category = models.CharField('4M 구분', max_length=10, choices=CATEGORIES)
    description = models.TextField('변경 내용')
    customer_notice = models.BooleanField('고객 통보 필요', default=True)
    customer_approval_ref = models.CharField('고객 승인 문서번호', max_length=100, blank=True)
    effective_at = models.DateTimeField('적용 일시', default=timezone.now)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '4M 변경'

    def __str__(self):
        return f'{self.number} {self.item.code} {self.get_category_display()}'

    def clean(self):
        if self.approved_at and self.customer_notice and not self.customer_approval_ref:
            raise ValidationError('고객 통보 대상 변경은 고객 승인 문서번호가 있어야 승인할 수 있습니다.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def first_article(self):
        """적용 일시 이후 이 품번의 첫 합격 검사."""
        return (Inspection.objects.filter(lot__item=self.item_id, result=Inspection.PASS, inspected_at__gte=self.effective_at)
                .order_by('inspected_at').first())

    @classmethod
    def awaiting_first_article(cls, item):
        due = cls.objects.filter(item=item, approved_at__isnull=False, effective_at__lte=timezone.now())
        return [c for c in due if not c.first_article]


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
    defect_qty = models.DecimalField('불량 수량', max_digits=12, decimal_places=3, default=0, help_text='고객 PPM 계산에 사용')
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
