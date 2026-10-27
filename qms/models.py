import datetime

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import Approvable, Item, Lot, Nonconformance, validate_photo


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
        if self.spec.is_approved and not getattr(self, '_edit_unlocked', False):  # 부모 수정 승인 1회분(BaseAdmin.save_formset)
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
                lot=self.lot, detected_at=self.inspected_at, origin=self.spec.inspection_type,
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
                    lot=self.lot, detected_at=self.inspected_at, defect_type='SPC 경보', origin='PROCESS',
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
        if self.plan.is_approved and not getattr(self, '_edit_unlocked', False):
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
                lot=self.lot, detected_at=self.received_at, origin='CLAIM', description=f'고객 클레임 {self.number}: {self.description}')
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


# ---------- CAPA · 내부심사 · PPAP ----------

def _capa_number():
    """CAPA-YYMMDD-001: 날짜별 순번. 같은 순간 두 화면에서 만들면 저장 시 중복 오류로 막힌다(번호 고쳐 저장)."""
    prefix = timezone.localtime().strftime('CAPA-%y%m%d-')
    return f'{prefix}{Capa.objects.filter(number__startswith=prefix).count() + 1:03d}'

class Capa(models.Model):
    """시정·예방조치. 8D·SCAR·심사 지적·SPC·부적합 어디서 나왔든 한 목록에서 유효성 확인까지 추적한다."""
    SOURCES = [('8D', '고객 클레임(8D)'), ('SCAR', '협력사(SCAR)'), ('AUDIT', '내부심사'), ('SPC', 'SPC 경보'),
               ('NC', '부적합'), ('OTHER', '기타')]

    number = models.CharField('CAPA 번호', max_length=50, unique=True, default=_capa_number)
    title = models.CharField('제목', max_length=200)
    source = models.CharField('출처', max_length=10, choices=SOURCES)
    source_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, null=True, blank=True, verbose_name='출처 기록 종류',
                                    limit_choices_to=models.Q(app_label='qms', model__in=['customerclaim', 'scar', 'auditfinding'])
                                    | models.Q(app_label='core', model='nonconformance'))
    source_id = models.PositiveIntegerField('출처 기록 ID', null=True, blank=True)
    source_record = GenericForeignKey('source_type', 'source_id')
    root_cause = models.TextField('근본 원인', blank=True)
    action = models.TextField('조치 내용')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='capas', verbose_name='담당자')
    due_date = models.DateField('기한')
    done_at = models.DateField('조치 완료일', null=True, blank=True)
    effective = models.BooleanField('유효성', null=True, blank=True, help_text='비움 = 미확인, 예 = 유효, 아니오 = 무효(새 CAPA 필요)')
    verified_at = models.DateField('유효성 확인일', null=True, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='+', verbose_name='확인자')
    verification_note = models.TextField('확인 근거', blank=True, help_text='예: 3개월간 재발 0건, 관련 LOT 공정능력 Cpk 1.67')
    closed_at = models.DateField('종결일', null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = 'CAPA(시정조치)'

    def __str__(self):
        return f'{self.number} {self.title}'

    @property
    def status(self):
        if self.closed_at:
            return '종결'
        if self.done_at:
            return '유효성 확인 대기'
        return '기한 초과' if self.due_date and self.due_date < timezone.localdate() else '진행'

    def clean(self):
        if self.effective is not None and not (self.done_at and self.verified_at and self.verified_by_id):
            raise ValidationError('유효성은 조치 완료 후 확인일·확인자와 함께 기록합니다.')
        if self.closed_at and self.effective is not True:
            raise ValidationError('유효성 확인 결과가 "유효"여야 종결할 수 있습니다. 무효면 새 CAPA를 만드세요.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
        if self.source_type_id and self.source_type.model == 'auditfinding':  # 심사 지적에서 만들면 지적에 연결
            AuditFinding.objects.filter(pk=self.source_id, capa__isnull=True).update(capa=self)


class InternalAudit(models.Model):
    """내부심사 계획·실시 (IATF 9.2). 중·경부적합 지적은 CAPA가 연결돼야 종결된다."""
    KINDS = [('INTERNAL', '내부'), ('CUSTOMER', '고객'), ('CERT', '인증')]

    name = models.CharField('심사명', max_length=200, help_text='예: 2026 상반기 공정심사 - 조립')
    kind = models.CharField('구분', max_length=10, choices=KINDS, default='INTERNAL')
    scope = models.TextField('범위(공정·조항)', blank=True)
    checklist = models.ForeignKey(AuditChecklist, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='체크리스트')
    planned_date = models.DateField('계획일')
    auditor = models.CharField('심사원', max_length=100)
    auditee = models.CharField('피심사 부서', max_length=100, blank=True)
    performed_at = models.DateField('실시일', null=True, blank=True)
    closed_at = models.DateField('종결일', null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '내부심사'
        ordering = ['-planned_date']

    def __str__(self):
        return f'{self.name} ({self.planned_date})'

    def clean(self):
        if self.closed_at:
            if not self.performed_at:
                raise ValidationError('실시일 없이 종결할 수 없습니다.')
            if self.pk and self.findings.filter(grade__in=AuditFinding.NEEDS_CAPA, capa__isnull=True).exists():
                raise ValidationError('CAPA가 연결되지 않은 중·경부적합 지적이 있어 종결할 수 없습니다.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class AuditFinding(models.Model):
    GRADES = [('MAJOR', '중부적합'), ('MINOR', '경부적합'), ('OBS', '관찰'), ('OFI', '개선기회')]
    NEEDS_CAPA = ['MAJOR', 'MINOR']

    audit = models.ForeignKey(InternalAudit, on_delete=models.CASCADE, related_name='findings', verbose_name='심사')
    clause = models.CharField('조항', max_length=50, blank=True)
    grade = models.CharField('등급', max_length=5, choices=GRADES)
    description = models.TextField('지적 내용')
    capa = models.ForeignKey(Capa, on_delete=models.PROTECT, null=True, blank=True, related_name='findings', verbose_name='CAPA')
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '심사 지적'

    def __str__(self):
        return f'{self.audit.name} {self.clause} {self.get_grade_display()}'


# AIAG PPAP 4판 18요소와 제출 수준(1~5)별 요구: S 제출, R 보관, * 고객 지정
# shortcut: 표준 표 그대로, 고객 특별 요구(CSR)가 다르면 요소 화면에서 '요구'를 직접 고친다
PPAP_ELEMENTS = [
    (1, '설계 기록', 'RSS*R'), (2, '설계 변경 문서', 'RSS*R'), (3, '고객 엔지니어링 승인', 'RRS*R'),
    (4, 'DFMEA', 'RRS*R'), (5, '공정 흐름도', 'RRS*R'), (6, 'PFMEA', 'RRS*R'), (7, '관리계획서', 'RRS*R'),
    (8, '측정시스템 분석(MSA)', 'RRS*R'), (9, '치수 측정 결과', 'RSS*R'), (10, '재료·성능 시험 결과', 'RSS*R'),
    (11, '초기 공정 능력 연구', 'RRS*R'), (12, '공인 시험실 문서', 'RSS*R'), (13, '외관 승인 보고서(AAR)', 'SSS*R'),
    (14, '샘플 제품', 'RSS*R'), (15, '마스터 샘플', 'RRR*R'), (16, '검사 보조구', 'RRR*R'),
    (17, '고객 특별 요구사항', 'RRS*R'), (18, '부품 제출 보증서(PSW)', 'SSSSR'),
]
PSW = 18


class PpapSubmission(Approvable):
    """PPAP 제출. 승인 서명 = 내부 PSW 서명이며, '제출(S)' 요소에 증적이 모두 있어야 한다."""
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='ppaps', verbose_name='품번')
    customer = models.CharField('고객사', max_length=100)
    level = models.PositiveSmallIntegerField('제출 수준', choices=[(i, f'Level {i}') for i in range(1, 6)], default=3)
    reason = models.CharField('제출 사유', max_length=200, help_text='예: 신규 부품, 설계 변경, 4M 변경(공정 변경)')
    due_date = models.DateField('제출 기한', null=True, blank=True)
    submitted_at = models.DateField('제출일', null=True, blank=True)
    customer_approved_at = models.DateField('고객 승인일', null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = 'PPAP 제출'

    def __str__(self):
        return f'PPAP {self.item.code} {self.customer} Level {self.level}'

    def missing_elements(self):
        return [e for e in self.elements.filter(requirement='S').exclude(number=PSW) if not e.has_evidence]

    def clean(self):
        if self.approved_at and self.pk and (missing := self.missing_elements()):
            raise ValidationError(f'제출(S) 요소에 증적이 없습니다: {", ".join(f"{e.number}.{e.name}" for e in missing)}')

    AFTER_APPROVAL = {'submitted_at', 'customer_approved_at'}  # PSW 서명 후에도 기록하는 칸

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.clean()
        old = PpapSubmission.objects.filter(pk=self.pk, approved_at__isnull=False).first() if self.pk else None
        if old and not getattr(self, '_edit_unlocked', False):
            changed = {f.name for f in self._meta.concrete_fields if getattr(old, f.attname) != getattr(self, f.attname)}
            if changed - self.AFTER_APPROVAL:
                raise ValidationError('PSW 승인 후에는 제출일·고객 승인일만 기록할 수 있습니다.')
            return models.Model.save(self, *args, **kwargs)  # Approvable의 승인 후 잠금을 이 두 칸에만 풀어 준다
        adding = self._state.adding
        super().save(*args, **kwargs)
        if adding:
            self._create_elements()

    def _create_elements(self):
        plan = ControlPlan.objects.filter(item=self.item, approved_at__isnull=False).order_by('-revision').first()
        dim = (Inspection.objects.filter(lot__item=self.item, result=Inspection.PASS, spec__inspection_type=InspectionSpec.OUTGOING)
               .order_by('-inspected_at').first())
        auto = {6: plan, 7: plan, 9: dim}  # 이미 있는 기록으로 채울 수 있는 요소
        for number, name, req in PPAP_ELEMENTS:
            rec = auto.get(number)
            PpapElement.objects.create(
                submission=self, number=number, name=name, requirement=req[self.level - 1],
                record_type=ContentType.objects.get_for_model(rec) if rec else None, record_id=rec.pk if rec else None,
                note='이 제출서 자체' if number == PSW else ('자동 연결' if rec else ''))

    def print_table(self):
        return ('부품 제출 보증서(PSW)', ['번호', '요소', '요구', '증적', '비고'],
                [[e.number, e.name, e.get_requirement_display(), str(e.document or e.record or '') or None, e.note or None]
                 for e in self.elements.order_by('number')])


class PpapElement(models.Model):
    REQUIREMENTS = [('S', '제출'), ('R', '보관'), ('*', '고객 지정')]

    submission = models.ForeignKey(PpapSubmission, on_delete=models.CASCADE, related_name='elements', verbose_name='PPAP')
    number = models.PositiveSmallIntegerField('번호')
    name = models.CharField('요소', max_length=100)
    requirement = models.CharField('요구', max_length=1, choices=REQUIREMENTS)
    document = models.ForeignKey(Document, on_delete=models.PROTECT, null=True, blank=True, verbose_name='문서')
    record_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, null=True, blank=True, verbose_name='기록 종류')
    record_id = models.PositiveIntegerField('기록 ID', null=True, blank=True)
    record = GenericForeignKey('record_type', 'record_id')
    note = models.CharField('비고', max_length=200, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = 'PPAP 요소'
        ordering = ['submission', 'number']

    def __str__(self):
        return f'{self.number}. {self.name}'

    @property
    def has_evidence(self):
        return bool(self.document_id or (self.record_type_id and self.record_id))

    def save(self, *args, **kwargs):
        if self.submission.is_approved and not getattr(self, '_edit_unlocked', False):
            raise ValidationError('PSW 승인 후에는 요소를 수정할 수 없습니다.')
        super().save(*args, **kwargs)


# ---------- 보고서 ----------

USER_FIELDS = {'username', 'first_name', 'last_name', 'get_full_name'}


class ExcelTemplate(models.Model):
    """고객사 엑셀 양식에 값을 채운다. 양식이 바뀌면 매핑만 고친다."""
    name = models.CharField('양식 이름', max_length=100)
    target = models.ForeignKey(ContentType, on_delete=models.PROTECT, verbose_name='대상 기록',
                               limit_choices_to=~models.Q(app_label__in=['personal', 'auth', 'admin', 'sessions', 'contenttypes']))
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
                if attr == 'password' or isinstance(value, AbstractBaseUser) and attr not in USER_FIELDS:
                    value = None  # 사용자 계정은 이름만 내보낸다 (암호·메일·개인 자료 차단)
                    break
                value = getattr(value, attr, None) if value is not None else None
                value = value() if callable(value) else value
            ws = wb[sheet] if sheet else wb.active
            if isinstance(value, list):  # 표(예: coa_rows)는 지정 셀부터 오른쪽·아래로 채운다
                top = ws[ref]
                for i, row in enumerate(value):
                    for j, v in enumerate(row):
                        ws.cell(row=top.row + i, column=top.column + j, value=v)
                continue
            if isinstance(value, datetime.datetime):
                value = timezone.localtime(value).replace(tzinfo=None)  # 엑셀은 시간대를 저장하지 못한다
            ws[ref] = '' if value is None else value
        out = BytesIO()
        wb.save(out)
        return out.getvalue()


# ---------- 현장 메모 ----------

class Memo(models.Model):
    """심사원·감독관·고객의 말을 그 자리에서 관련 기록에 남긴다. 대상이 비면 '미분류'."""
    SPEAKERS = [('AUDITOR', '심사원'), ('INSPECTOR', '감독관'), ('CUSTOMER', '고객'), ('INTERNAL', '내부'), ('OTHER', '기타')]

    body = models.TextField('내용')
    speaker_kind = models.CharField('말한 사람', max_length=10, choices=SPEAKERS, default='AUDITOR')
    speaker_name = models.CharField('이름', max_length=100, blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, null=True, blank=True, verbose_name='대상 기록 종류')
    object_id = models.PositiveIntegerField('대상 기록 ID', null=True, blank=True)
    target = GenericForeignKey('content_type', 'object_id')
    audit = models.ForeignKey(InternalAudit, on_delete=models.SET_NULL, null=True, blank=True, related_name='memos',
                              verbose_name='심사')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+', verbose_name='작성자')
    created_at = models.DateTimeField('작성 일시', default=timezone.now)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '현장 메모'
        ordering = ['created_at']
        indexes = [models.Index(fields=['content_type', 'object_id'])]

    def __str__(self):
        return f'{self.get_speaker_kind_display()}: {self.body[:40]}'


class MemoPhoto(models.Model):
    memo = models.ForeignKey(Memo, on_delete=models.CASCADE, related_name='photos', verbose_name='메모')
    file = models.FileField('사진', upload_to='memo/%Y/', validators=[validate_photo])
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '메모 사진'


class DashboardLayout(models.Model):
    """사용자별 첫 화면 위젯 배치. [{'key': 위젯 키, 'size': 'normal'|'wide'}] 순서대로 그린다."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name='사용자')
    widgets = models.JSONField('위젯 배치', default=list)

    class Meta:
        verbose_name = verbose_name_plural = '대시보드 배치'
