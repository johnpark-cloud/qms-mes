from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords

APPROVER_GROUP = '품질팀장'


def is_approver(user):
    return user.is_superuser or user.groups.filter(name=APPROVER_GROUP).exists()


class Approvable(models.Model):
    """승인 서명(비밀번호 재확인)으로만 채워지는 승인 필드. core.views.approve가 설정한다."""
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='+', verbose_name='승인자')
    approved_at = models.DateTimeField('승인 일시', null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def is_approved(self):
        return self.approved_at is not None

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk, approved_at__isnull=False).exists():
            raise ValidationError('승인된 기록은 수정할 수 없습니다. 새 개정을 만드세요.')
        super().save(*args, **kwargs)


class Item(models.Model):
    RAW, SEMI, FINISHED = 'RAW', 'SEMI', 'FIN'
    TYPES = [(RAW, '원자재'), (SEMI, '반제품'), (FINISHED, '완제품')]

    code = models.CharField('품번', max_length=50, unique=True)
    name = models.CharField('품명', max_length=200)
    item_type = models.CharField('구분', max_length=4, choices=TYPES)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '품번'

    def __str__(self):
        return f'{self.code} {self.name}'


class Process(models.Model):
    code = models.CharField('공정 코드', max_length=50, unique=True)
    name = models.CharField('공정명', max_length=200)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '공정'

    def __str__(self):
        return f'{self.code} {self.name}'


class BomLine(models.Model):
    parent = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='bom_lines', verbose_name='모품번')
    component = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='+', verbose_name='자품번')
    qty = models.DecimalField('소요량', max_digits=12, decimal_places=4, default=1)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = 'BOM'
        constraints = [models.UniqueConstraint(fields=['parent', 'component'], name='uniq_bom_line')]

    def __str__(self):
        return f'{self.parent.code} ← {self.component.code}'


class WorkOrder(models.Model):
    PLANNED, RUNNING, DONE = 'PLANNED', 'RUNNING', 'DONE'
    STATUSES = [(PLANNED, '계획'), (RUNNING, '진행'), (DONE, '완료')]

    number = models.CharField('작업지시 번호', max_length=50, unique=True)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, verbose_name='품번')
    process = models.ForeignKey(Process, on_delete=models.PROTECT, null=True, blank=True, verbose_name='공정')
    planned_qty = models.DecimalField('계획 수량', max_digits=12, decimal_places=3)
    due_date = models.DateField('납기', null=True, blank=True)
    status = models.CharField('상태', max_length=8, choices=STATUSES, default=PLANNED)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '작업지시'

    def __str__(self):
        return self.number


class ImportProfile(models.Model):
    """회사별 엑셀/CSV 양식의 열 매핑. 코드를 고치지 않고 새 회사 양식을 받기 위한 설정."""
    TARGETS = [('item', '품번'), ('work_order', '작업지시')]

    name = models.CharField('이름', max_length=100, unique=True)
    target = models.CharField('대상', max_length=20, choices=TARGETS)
    header_row = models.PositiveSmallIntegerField('제목 행 번호', default=1)
    mapping = models.JSONField('열 매핑', help_text='예: {"number": "지시번호", "item": "품번", "planned_qty": "수량", "due_date": "납기"}')
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '엑셀 가져오기 설정'

    def __str__(self):
        return self.name


class Lot(models.Model):
    number = models.CharField('LOT/시리얼 번호', max_length=80, unique=True)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, verbose_name='품번')
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='lots', verbose_name='작업지시')
    is_serial = models.BooleanField('시리얼', default=False)
    qty = models.DecimalField('수량', max_digits=12, decimal_places=3, default=1)
    created_at = models.DateTimeField('생성', default=timezone.now)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = 'LOT'

    def __str__(self):
        return self.number

    @property
    def on_hold(self):
        return self.holds.filter(released_at__isnull=True).exists()

    @property
    def lineage_gap(self):
        """원자재가 아닌데 투입 LOT이 없으면 계보 미등록 구간이다."""
        return self.item.item_type != Item.RAW and not self.parent_links.exists()

    def _walk(self, attr, next_attr):
        seen, stack = {}, [self]
        while stack:
            for link in getattr(stack.pop(), attr).select_related(next_attr):
                nxt = getattr(link, next_attr)
                if nxt.pk not in seen and nxt.pk != self.pk:
                    seen[nxt.pk] = nxt
                    stack.append(nxt)
        return list(seen.values())

    def descendants(self):
        """이 LOT이 투입되어 만들어진 모든 하위 LOT."""
        return self._walk('child_links', 'child')

    def ancestors(self):
        return self._walk('parent_links', 'parent')

    def assert_usable(self, action):
        if self.on_hold:
            raise ValidationError(f'{self.number}은(는) 보류 중이라 {action}할 수 없습니다.')


class LotLink(models.Model):
    """투입 계보: parent LOT이 child LOT에 투입됨 (분할·병합 = N:M)."""
    parent = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name='child_links', verbose_name='투입 LOT')
    child = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name='parent_links', verbose_name='생산 LOT')
    qty = models.DecimalField('투입 수량', max_digits=12, decimal_places=3, default=1)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = 'LOT 계보'
        constraints = [models.UniqueConstraint(fields=['parent', 'child'], name='uniq_lot_link')]

    def __str__(self):
        return f'{self.parent} → {self.child}'

    def clean(self):
        if self.parent_id == self.child_id:
            raise ValidationError('같은 LOT을 자기 자신에 투입할 수 없습니다.')
        if self.parent_id and self.child_id and self.child in self.parent.ancestors():
            raise ValidationError('계보가 순환됩니다.')
        if self.parent_id and self._state.adding:
            self.parent.assert_usable('투입')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Nonconformance(models.Model):
    REWORK, REPAIR, SCRAP, RETURN, CONCESSION = 'REWORK', 'REPAIR', 'SCRAP', 'RETURN', 'CONCESSION'
    DISPOSITIONS = [(REWORK, '재작업'), (REPAIR, '수리'), (SCRAP, '폐기'), (RETURN, '반품'), (CONCESSION, '특채')]
    RELEASING = {REWORK, REPAIR, CONCESSION}  # 폐기·반품은 보류를 풀지 않는다

    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name='nonconformances', verbose_name='LOT')
    description = models.TextField('부적합 내용')
    detected_at = models.DateTimeField('발견 일시', default=timezone.now)
    disposition = models.CharField('처분', max_length=10, choices=DISPOSITIONS, blank=True)
    customer_approval_ref = models.CharField('고객 특채 승인 문서번호', max_length=100, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    verbose_name='MRB 승인자')
    closed_at = models.DateTimeField('종결', null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '부적합'

    def __str__(self):
        return f'NC-{self.pk} {self.lot}'

    def clean(self):
        if not self.disposition:
            return
        if self._state.adding:
            raise ValidationError('처분은 부적합 등록(보류) 후에 입력합니다.')
        if not self.approved_by_id or not is_approver(self.approved_by):
            raise ValidationError('처분에는 품질팀장(MRB 승인자)이 필요합니다.')
        if self.disposition in (self.REWORK, self.REPAIR) and not self.lot.inspections.filter(
                result='PASS', inspected_at__gt=self.detected_at).exists():
            raise ValidationError('재작업·수리는 부적합 발견 이후 재검사 합격 기록이 있어야 보류를 해제합니다.')
        if self.disposition == self.CONCESSION and not self.customer_approval_ref:
            raise ValidationError('특채는 고객 승인 문서번호가 필요합니다.')

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.clean()
        is_new = self._state.adding
        if self.disposition and not self.closed_at:
            self.closed_at = timezone.now()
        super().save(*args, **kwargs)
        if is_new:
            # 인터록: 해당 LOT과 하위 계보 전체를 자동 보류
            Hold.objects.bulk_create(Hold(lot=lot, nonconformance=self) for lot in [self.lot, *self.lot.descendants()])
        elif self.disposition in self.RELEASING:
            self.holds.filter(released_at__isnull=True).update(released_at=self.closed_at)


class Hold(models.Model):
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name='holds')
    nonconformance = models.ForeignKey(Nonconformance, on_delete=models.PROTECT, related_name='holds')
    created_at = models.DateTimeField(default=timezone.now)
    released_at = models.DateTimeField(null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '보류'

    def __str__(self):
        return f'{self.lot} ({self.nonconformance})'


class Shipment(models.Model):
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name='shipments', verbose_name='LOT')
    customer = models.CharField('고객사', max_length=100)
    qty = models.DecimalField('수량', max_digits=12, decimal_places=3)
    shipped_at = models.DateTimeField('출하 일시', default=timezone.now)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '출하'

    def __str__(self):
        return f'{self.lot} → {self.customer}'

    def clean(self):
        if self.lot_id and self._state.adding:
            self.lot.assert_usable('출하')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
