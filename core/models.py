import os

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.db.models import ProtectedError
from django.db.models.signals import post_delete
from django.dispatch import receiver
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
        # 관리자가 승인한 수정 요청 1회분만 잠금을 건너뛴다 (core.admin.BaseAdmin.save_model)
        locked = self.pk and type(self).objects.filter(pk=self.pk, approved_at__isnull=False).exists()
        if locked and not getattr(self, '_edit_unlocked', False):
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

    @property
    def progress(self):
        """진도율(%) = 마지막 공정 양품 합 ÷ 계획 수량."""
        last = self.item.routing.order_by('-seq').first()
        if not last or not self.planned_qty:
            return None
        good = self.results.filter(step=last).aggregate(s=models.Sum('good_qty'))['s'] or 0
        return float(good) / float(self.planned_qty) * 100


class RoutingStep(models.Model):
    """품번별 공정 순서. 작업 실적은 이 순서를 건너뛸 수 없다."""
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='routing', verbose_name='품번')
    seq = models.PositiveSmallIntegerField('순서', help_text='10, 20, 30처럼 띄워 두면 중간에 공정을 넣기 쉽다')
    process = models.ForeignKey(Process, on_delete=models.PROTECT, verbose_name='공정')
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '공정 라우팅'
        ordering = ['item', 'seq']
        constraints = [models.UniqueConstraint(fields=['item', 'seq'], name='uniq_routing_seq')]

    def __str__(self):
        return f'{self.item.code} {self.seq} {self.process.name}'


class WorkResult(models.Model):
    """작업 실적: 작업지시의 한 공정에서 투입·양품·불량 수량."""
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name='results', verbose_name='작업지시')
    step = models.ForeignKey(RoutingStep, on_delete=models.PROTECT, related_name='results', verbose_name='공정')
    lot = models.ForeignKey('Lot', on_delete=models.PROTECT, null=True, blank=True, related_name='work_results',
                            verbose_name='생산 LOT')
    input_qty = models.DecimalField('투입 수량', max_digits=12, decimal_places=3)
    good_qty = models.DecimalField('양품 수량', max_digits=12, decimal_places=3)
    defect_qty = models.DecimalField('불량 수량', max_digits=12, decimal_places=3, default=0)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name='작업자')
    started_at = models.DateTimeField('시작', default=timezone.now)
    ended_at = models.DateTimeField('종료', null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '작업 실적'

    def __str__(self):
        return f'{self.work_order} {self.step}'

    def clean(self):
        if not (self.work_order_id and self.step_id):
            return
        wo = self.work_order
        if self.step.item_id != wo.item_id:
            raise ValidationError(f'{self.step}은(는) 작업지시 품번 {wo.item.code}의 라우팅이 아닙니다.')
        if (self.good_qty or 0) + (self.defect_qty or 0) > (self.input_qty or 0):
            raise ValidationError('양품+불량 수량이 투입 수량보다 많습니다.')
        prev = RoutingStep.objects.filter(item=wo.item_id, seq__lt=self.step.seq).order_by('-seq').first()
        if prev and not wo.results.filter(step=prev, good_qty__gt=0).exclude(pk=self.pk).exists():
            raise ValidationError(f'이전 공정 {prev.seq} {prev.process.name}의 양품 실적이 없어 이 공정을 등록할 수 없습니다.')
        if self.lot_id:
            if self.lot.item_id != wo.item_id:
                raise ValidationError('LOT의 품번이 작업지시 품번과 다릅니다.')
            if self._state.adding:
                self.lot.assert_usable('실적 등록')

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
        WorkOrder.objects.filter(pk=self.work_order_id, status=WorkOrder.PLANNED).update(status=WorkOrder.RUNNING)


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
    supplier = models.CharField('협력사', max_length=100, blank=True, help_text='구매 자재 LOT이면 입력 (협력사 성적표에 사용)')
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


def _nc_number():
    """NC-YYMMDD-001: 날짜별 순번. 중간 번호가 지워져도 겹치지 않게 그날 마지막 번호 다음으로 매긴다."""
    prefix = timezone.localtime().strftime('NC-%y%m%d-')
    last = Nonconformance.objects.filter(number__startswith=prefix).order_by('-number').values_list('number', flat=True).first()
    return f'{prefix}{int(last[-3:]) + 1 if last else 1:03d}'


class Nonconformance(models.Model):
    ORIGINS = [('INCOMING', '수입검사·협력사'), ('PROCESS', '공정 내부'), ('OUTGOING', '출하검사'), ('CLAIM', '고객 클레임'),
               ('RETURN', '반품')]
    AFTER_APPROVAL = {'cost', 'customer_notified_on', 'capa_required', 'mailed_at'}  # 승인 뒤에도 기록하는 칸
    REWORK, REPAIR, SCRAP, RETURN, CONCESSION = 'REWORK', 'REPAIR', 'SCRAP', 'RETURN', 'CONCESSION'
    DISPOSITIONS = [(REWORK, '재작업'), (REPAIR, '수리'), (SCRAP, '폐기'), (RETURN, '반품'), (CONCESSION, '특채')]
    RELEASING = {REWORK, REPAIR, CONCESSION}  # 폐기·반품은 보류를 풀지 않는다

    number = models.CharField('부적합 번호', max_length=50, unique=True, default=_nc_number)
    origin = models.CharField('발생 유형', max_length=10, choices=ORIGINS, default='PROCESS')
    process = models.ForeignKey(Process, on_delete=models.PROTECT, null=True, blank=True, verbose_name='발견 공정')
    detected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='+', verbose_name='발견자')
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name='nonconformances', verbose_name='LOT')
    inspected_qty = models.DecimalField('검사·로트 수량', max_digits=12, decimal_places=3, null=True, blank=True)
    description = models.TextField('부적합 내용', help_text='5W1H: 언제·어디서·누가·무엇을·어떻게·왜')
    measured_value = models.CharField('규격 대비 측정값', max_length=200, blank=True, help_text='예: 두께 10.8mm (규격 9.5~10.5)')
    special_char = models.CharField('특별특성', max_length=2, choices=[('CC', 'CC'), ('SC', 'SC')], blank=True)
    contained_qty = models.DecimalField('격리 수량', max_digits=12, decimal_places=3, null=True, blank=True)
    sorting_result = models.TextField('재고·재공·출하분 선별 결과', blank=True)
    customer_notify = models.BooleanField('고객 통보 필요', default=False)
    customer_notified_on = models.DateField('고객 통보일', null=True, blank=True)
    capa_required = models.BooleanField('시정조치 필요', null=True, blank=True)
    detected_at = models.DateTimeField('발견 일시', default=timezone.now)
    defect_type = models.CharField('불량유형', max_length=100, blank=True, help_text='예: 치수, 이물, 외관, 용량 (파레토 집계 단위)')
    defect_qty = models.DecimalField('불량 수량', max_digits=12, decimal_places=3, default=0)
    cost = models.DecimalField('실패비용(원)', max_digits=14, decimal_places=0, default=0,
                               help_text='폐기·재작업·선별·운송 등 이 부적합으로 든 비용')
    disposition = models.CharField('처분', max_length=10, choices=DISPOSITIONS, blank=True)
    customer_approval_ref = models.CharField('고객 특채 승인 문서번호', max_length=100, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    verbose_name='MRB 승인자')
    approved_at = models.DateTimeField('승인 일시', null=True, blank=True)
    closed_at = models.DateTimeField('종결', null=True, blank=True)
    mailed_at = models.DateTimeField('메일 발송 일시', null=True, blank=True)
    history = HistoricalRecords()

    print_template = 'core/nc_print.html'

    class Meta:
        verbose_name = verbose_name_plural = '부적합'

    def __str__(self):
        return f'{self.number} {self.lot}'

    @property
    def is_approved(self):
        return self.approved_at is not None

    def missing_fields(self):
        names = ['defect_type', 'sorting_result', 'contained_qty'] + (['process'] if self.origin in ('PROCESS', 'OUTGOING') else [])
        return [str(self._meta.get_field(n).verbose_name) for n in names if getattr(self, n) in (None, '')]

    def print_table(self):
        """인쇄 화면의 ①~⑦ 요약표 (사진은 nc_print.html이 붙인다)."""
        def d(v, empty='-'):
            return empty if v in (None, '') else v

        def when(t):
            return timezone.localtime(t).strftime('%Y-%m-%d %H:%M') if t else '-'

        notify = '불필요'
        if self.customer_notify:
            notify = f'필요 (통보일 {self.customer_notified_on})' if self.customer_notified_on else '필요 (미통보)'
        rows = [
            ['① 구분', '발생 유형', self.get_origin_display()], ['', '발견 공정', d(self.process)],
            ['', '발견자', d(self.detected_by)], ['', '발견 일시', when(self.detected_at)],
            ['② 대상', 'LOT', self.lot], ['', '품번', self.lot.item], ['', '협력사', d(self.lot.supplier)],
            ['', '불량 수량', self.defect_qty], ['', '검사·로트 수량', d(self.inspected_qty)],
            ['③ 현상', '불량유형', d(self.defect_type)], ['', '상세 내용', self.description],
            ['', '규격 대비 측정값', d(self.measured_value)], ['', '특별특성', d(self.special_char, '해당 없음')],
            ['④ 긴급 조치', '격리 수량', d(self.contained_qty)], ['', '선별 결과', d(self.sorting_result)], ['', '고객 통보', notify],
            ['⑤ 처분', '처분', d(self.get_disposition_display())], ['', '특채 고객 승인번호', d(self.customer_approval_ref)],
            ['', '실패비용(원)', self.cost],
            ['⑥ 후속', '시정조치 필요', {True: '필요', False: '불필요'}.get(self.capa_required, '-')],
            ['⑦ 승인', 'MRB 승인자', d(self.approved_by)], ['', '승인 일시', when(self.approved_at)], ['', '종결', when(self.closed_at)],
        ]
        return '부적합 보고서', ['구역', '항목', '내용'], rows

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


PHOTO_EXTS = {'jpg', 'jpeg', 'png', 'heic', 'heif', 'webp'}
PHOTO_MAX_MB = 10


def validate_photo(f):
    ext = os.path.splitext(f.name)[1].lower().lstrip('.')
    if ext not in PHOTO_EXTS:
        raise ValidationError(f'사진 파일만 올릴 수 있습니다 ({", ".join(sorted(PHOTO_EXTS))}): {f.name}')
    if f.size > PHOTO_MAX_MB * 1024 * 1024:
        raise ValidationError(f'사진 한 장은 {PHOTO_MAX_MB}MB 이하여야 합니다: {f.name}')


class NonconformancePhoto(models.Model):
    nonconformance = models.ForeignKey(Nonconformance, on_delete=models.CASCADE, related_name='photos', verbose_name='부적합')
    file = models.FileField('사진', upload_to='nc/%Y/', validators=[validate_photo])
    caption = models.CharField('설명', max_length=200, blank=True)
    uploaded_at = models.DateTimeField('올린 일시', default=timezone.now)

    class Meta:
        verbose_name = verbose_name_plural = '부적합 사진'

    def __str__(self):
        return self.caption or os.path.basename(self.file.name)


@receiver(post_delete, sender=NonconformancePhoto)
def _delete_photo_file(sender, instance, **kwargs):
    # 삭제가 롤백되면 파일도 남아야 하므로 커밋 뒤에 지운다 (관리 화면 사진 삭제·부적합 삭제 모두)
    transaction.on_commit(lambda: instance.file.delete(save=False))


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

    COA_HEADER = ['검사항목', '특별특성', 'LSL', 'USL', '단위', '측정값', '판정']

    def print_table(self):
        """인쇄 화면(core.views.print_view)에 붙는 표 = 출하성적서."""
        return '출하성적서', self.COA_HEADER, self.coa_rows()

    def coa_rows(self):
        """출하성적서 표: 이 LOT의 최신 합격 출하검사(없으면 공정검사) 항목별 결과. 엑셀 매핑 예: {"A10": "coa_rows"}"""
        for itype in ('OUTGOING', 'PROCESS'):
            insp = self.lot.inspections.filter(result='PASS', spec__inspection_type=itype).order_by('-inspected_at').first()
            if insp:
                break
        else:
            return []
        rows = []
        for m in insp.measurements.select_related('characteristic').order_by('characteristic_id', 'pk'):
            c = m.characteristic
            value = m.value if c.is_variable else ('OK' if m.ok else 'NG')
            rows.append([c.name, c.special or None, c.lsl, c.usl, c.unit or None, value, '합격' if m.passed else '불합격'])
        return rows

    def clean(self):
        if self.lot_id and self._state.adding:
            self.lot.assert_usable('출하')
            # 4M 변경 후 초품 합격 전에는 출하 금지 (qms 앱이 정의, core는 qms를 import하지 않는다)
            waiting = apps.get_model('qms', 'ChangeRequest').awaiting_first_article(self.lot.item)
            if waiting:
                raise ValidationError(f'4M 변경 {", ".join(c.number for c in waiting)}의 초품 검사 합격 전이라 출하할 수 없습니다.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class EditRequest(models.Model):
    """삭제·수정 요청. 관리자(슈퍼유저)가 승인해야 삭제되거나 승인된 기록의 잠금이 1회 풀린다."""
    DELETE, EDIT = 'DELETE', 'EDIT'
    KINDS = [(DELETE, '삭제'), (EDIT, '수정')]
    PENDING, APPROVED, REJECTED, USED = 'PENDING', 'APPROVED', 'REJECTED', 'USED'
    STATUSES = [(PENDING, '대기'), (APPROVED, '승인'), (REJECTED, '거절'), (USED, '수정 완료')]

    kind = models.CharField('요청 종류', max_length=6, choices=KINDS)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, verbose_name='기록 종류')
    object_id = models.PositiveBigIntegerField('기록 번호')
    target = GenericForeignKey('content_type', 'object_id')
    object_repr = models.CharField('대상 기록', max_length=200)
    reason = models.TextField('사유')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                     verbose_name='요청자')
    requested_at = models.DateTimeField('요청 일시', default=timezone.now)
    status = models.CharField('상태', max_length=8, choices=STATUSES, default=PENDING)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='+', verbose_name='처리자')
    decided_at = models.DateTimeField('처리 일시', null=True, blank=True)
    reject_reason = models.TextField('거절 사유', blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '삭제·수정 요청'
        ordering = ['-requested_at']

    def __str__(self):
        return f'{self.get_kind_display()} 요청: {self.object_repr}'

    @transaction.atomic
    def decide(self, user, approve, reject_reason=''):
        from .records import delete_record
        if not user.is_superuser:
            raise PermissionDenied('시스템 관리자만 처리할 수 있습니다.')
        if self.status != self.PENDING:
            raise ValidationError('이미 처리된 요청입니다.')
        if approve and self.kind == self.DELETE:
            if self.target is None:
                raise ValidationError('대상 기록이 이미 없습니다.')
            try:
                delete_record(self.target)
            except ProtectedError as e:
                raise ValidationError('먼저 지워야 할 기록: ' + ', '.join(map(str, e.protected_objects)))
            self._meta.get_field('target').delete_cached_value(self)  # 지워진 객체를 들고 있으면 save()가 거부한다
        self.status = self.APPROVED if approve else self.REJECTED
        self.decided_by, self.decided_at, self.reject_reason = user, timezone.now(), reject_reason
        self.save()
