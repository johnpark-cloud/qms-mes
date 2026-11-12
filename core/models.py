import os
import re

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import RegexValidator
from django.db import IntegrityError, models, transaction
from django.db.models import ProtectedError
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from simple_history.models import HistoricalRecords
from simple_history.utils import bulk_create_with_history, bulk_update_with_history

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


class CodeValue(models.Model):
    """번호 부여에 쓰는 코드표. 묶음(group)마다 자릿수·형식이 다르고, 자재 분류는 대·중·소 계층이다."""
    CATEGORY, INDUSTRY, CUSTOMER, MATERIAL = 'category', 'industry', 'customer', 'material'
    MAT_L, MAT_M, MAT_S = 'mat_l', 'mat_m', 'mat_s'
    DOC_KIND, DEPT, DESIGN = 'doc_kind', 'dept', 'design'
    GROUPS = [(CATEGORY, '품목분류'), (INDUSTRY, '산업분류'), (CUSTOMER, '고객사'), (MATERIAL, '자재분류'),
              (MAT_L, '자재 대분류'), (MAT_M, '자재 중분류'), (MAT_S, '자재 소분류'),
              (DOC_KIND, '관리표준 문서구분'), (DEPT, '부서'), (DESIGN, '설계자료분류')]
    PARENT_GROUP = {MAT_L: MATERIAL, MAT_M: MAT_L, MAT_S: MAT_M}
    FORMATS = {CATEGORY: r'\d', MATERIAL: r'\d', MAT_L: r'\d', MAT_M: r'\d', MAT_S: r'\d',
               INDUSTRY: r'[A-Z]', DOC_KIND: r'[A-Z]', DEPT: r'[A-Z]',
               CUSTOMER: r'[A-Z]{2}', DESIGN: r'[A-Z]{2}'}

    group = models.CharField('묶음', max_length=10, choices=GROUPS)
    code = models.CharField('코드', max_length=2)
    name = models.CharField('이름', max_length=100)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT,
                               related_name='children', verbose_name='상위 코드')
    item_type = models.CharField('품목 구분', max_length=4, choices=Item.TYPES, blank=True)
    active = models.BooleanField('사용', default=True)
    sort = models.PositiveIntegerField('정렬', default=0)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '번호 코드값'
        ordering = ['group', 'parent_id', 'sort', 'code']
        constraints = [
            models.UniqueConstraint(fields=['group', 'code'], condition=models.Q(parent__isnull=True),
                                    name='uniq_codevalue_root'),
            models.UniqueConstraint(fields=['parent', 'code'], condition=models.Q(parent__isnull=False),
                                    name='uniq_codevalue_child'),
        ]

    def __str__(self):
        return f'{self.code} {self.name}'

    def clean(self):
        errors = {}
        fmt = self.FORMATS.get(self.group)
        if fmt and not re.fullmatch(fmt, self.code or ''):
            kind = '숫자' if fmt.startswith('\\d') else '영문 대문자'
            errors['code'] = f'이 묶음의 코드는 {kind} {2 if "{2}" in fmt else 1}자리여야 합니다.'
        want = self.PARENT_GROUP.get(self.group)
        if want and (self.parent is None or self.parent.group != want):
            errors['parent'] = f'상위 코드는 {dict(self.GROUPS)[want]} 묶음의 코드여야 합니다.'
        elif not want and self.parent_id:
            errors['parent'] = '이 묶음은 상위 코드를 둘 수 없습니다.'
        if self.group == self.CATEGORY and not self.item_type:
            errors['item_type'] = '품목분류는 품목 구분이 필요합니다.'
        elif self.group not in (self.CATEGORY, self.DESIGN) and self.item_type:
            errors['item_type'] = '이 묶음은 품목 구분을 둘 수 없습니다.'
        if errors:
            raise ValidationError(errors)


class NumberRule(models.Model):
    """번호 틀. 문법·검사는 core/numbering.py. 저장 뒤 이름·대상·틀은 바꿀 수 없다(옛 번호 풀이·참조 보존)."""
    ITEM, DOC = 'ITEM', 'DOC'
    TARGETS = [(ITEM, '품번'), (DOC, '문서')]

    name = models.CharField('규칙 이름', max_length=50, unique=True)
    target = models.CharField('대상', max_length=4, choices=TARGETS)
    pattern = models.CharField('틀', max_length=200)
    active = models.BooleanField('사용', default=True)
    sort = models.PositiveIntegerField('정렬', default=0)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '번호 규칙'
        ordering = ['sort', 'id']

    def __str__(self):
        return self.name

    def clean(self):
        from .numbering import NumberingError, check_rule  # numbering이 이 모듈을 가져오므로 늦게 가져온다
        old = NumberRule.objects.filter(pk=self.pk).first() if self.pk else None
        if old:
            locked = {f: '저장된 규칙의 이름·대상·틀은 바꿀 수 없습니다. 새 규칙을 만드세요.'
                      for f in ('name', 'target', 'pattern') if getattr(old, f) != getattr(self, f)}
            if locked:
                raise ValidationError(locked)
            return  # 틀이 그대로면 다시 검사하지 않는다(참조 규칙이 지워져도 사용 중지는 되게)
        try:
            check_rule(self.name, self.target, self.pattern)
        except NumberingError as e:
            raise ValidationError({'pattern': str(e)})


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
            if lot_changed(self, 'lot_id'):
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
    partner = models.ForeignKey('core.Partner', on_delete=models.PROTECT, null=True, blank=True, related_name='lots',
                                limit_choices_to={'is_supplier': True}, verbose_name='거래처')
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
            for link in getattr(stack.pop(), attr).select_related(f'{next_attr}__item'):  # 계보 표의 품번 표시용
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


def lot_changed(obj, field):
    """새 기록이거나 저장된 LOT과 다르면 True. 수정으로 보류·4M 인터록을 건너뛰지 못하게 한다.
    같은 LOT의 지난 기록(수량·메모) 정정은 LOT이 보류여도 막지 않는다."""
    if obj._state.adding:
        return True
    return type(obj).objects.filter(pk=obj.pk).values_list(field, flat=True).first() != getattr(obj, field)


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
        if self.parent_id and lot_changed(self, 'parent_id'):
            self.parent.assert_usable('투입')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


def save_numbered(obj, make, auto_pattern, save, tries=5):
    """새 기록 저장. 자동 번호(auto_pattern 모양)가 동시 등록으로 겹치면(PostgreSQL) 다음 번호로 다시 저장한다.
    모양이 다른 직접 입력 번호는 다시 매기지 않고 중복 오류를 그대로 낸다."""
    for i in range(tries):
        try:
            with transaction.atomic():  # 실패해도 바깥 트랜잭션을 살리는 저장점
                return save()
        except IntegrityError:
            if (i == tries - 1 or not re.fullmatch(auto_pattern, obj.number)
                    or not type(obj).objects.filter(number=obj.number).exists()):
                raise
            obj.number = make()


# shortcut: 하루 999건을 넘으면 순번 정렬이 깨진다, 그 전에 자릿수를 늘린다
def _nc_number():
    """NC-YYMMDD-001: 날짜별 순번. 중간 번호가 지워져도 겹치지 않게 그날 마지막 번호 다음으로 매긴다."""
    prefix = timezone.localtime().strftime('NC-%y%m%d-')
    last = Nonconformance.objects.filter(number__startswith=prefix).order_by('-number').values_list('number', flat=True).first()
    return f'{prefix}{int(last[-3:]) + 1 if last else 1:03d}'


class Nonconformance(models.Model):
    ORIGINS = [('INCOMING', '수입검사·협력사'), ('PROCESS', '공정 내부'), ('OUTGOING', '출하검사'), ('CLAIM', '고객 클레임'),
               ('RETURN', '반품')]
    AFTER_APPROVAL = {'cost', 'customer_notified_on', 'capa_required', 'mailed_at'}  # 승인 뒤에도 기록하는 칸
    INTERLOCK = ['lot', 'detected_at', 'disposition', 'customer_approval_ref']  # 종결 뒤 바뀌면 보류 계산이 어긋나는 칸
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

    def _check_closed_lock(self):
        """종결 뒤 잠금. admin은 core.rules.nc_locked_fields로 같은 칸을 읽기 전용으로 보인다."""
        old = type(self).objects.filter(pk=self.pk, closed_at__isnull=False).first() if self.pk else None
        if old is None:
            return
        changed = {f.name for f in self._meta.concrete_fields if getattr(old, f.attname) != getattr(self, f.attname)}
        if changed & set(self.INTERLOCK):  # 관리자·수정 승인으로도 못 바꾼다 (새 MRB 서명 없이 보류가 풀리거나 남는다)
            raise ValidationError('종결된 부적합의 보류 인터록 칸(LOT·발견 일시·처분·특채 승인번호)은 바꿀 수 없습니다.')
        if changed - self.AFTER_APPROVAL and not getattr(self, '_edit_unlocked', False):  # core.rules.begin_edit
            raise ValidationError('종결된 부적합은 수정할 수 없습니다. 수정 요청 후 승인받아야 합니다.')

    @transaction.atomic
    def save(self, *args, **kwargs):
        self._check_closed_lock()
        self.clean()
        is_new = self._state.adding
        if self.disposition and not self.closed_at:
            self.closed_at = timezone.now()
        if is_new:
            save_numbered(self, _nc_number, r'NC-\d{6}-\d{3}', lambda: super(Nonconformance, self).save(*args, **kwargs))
        else:
            super().save(*args, **kwargs)
        if is_new:
            # 인터록: 해당 LOT과 하위 계보 전체를 자동 보류
            bulk_create_with_history([Hold(lot=lot, nonconformance=self) for lot in [self.lot, *self.lot.descendants()]], Hold)
        elif self.disposition in self.RELEASING:
            holds = list(self.holds.filter(released_at__isnull=True))
            for h in holds:
                h.released_at = self.closed_at
            bulk_update_with_history(holds, Hold, ['released_at'])  # 보류 생성·해제도 변경 이력에 남긴다


PHOTO_EXTS = {'jpg', 'jpeg', 'png', 'heic', 'heif', 'webp'}
PHOTO_MAX_MB = 10


def validate_photo(f):
    if getattr(f, '_committed', False):  # 이미 저장된 사진은 다시 검사하지 않는다 (디스크에서 사라졌어도 행 저장은 된다)
        return
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
    history = HistoricalRecords()

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
    partner = models.ForeignKey('core.Partner', on_delete=models.PROTECT, null=True, blank=True, related_name='shipments',
                                limit_choices_to={'is_customer': True}, verbose_name='거래처')
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
    coa_rows.report_safe = True  # 엑셀 양식(ExcelTemplate.fill)이 호출해도 되는 읽기 전용 메서드

    def clean(self):
        if self.lot_id and lot_changed(self, 'lot_id'):
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


class RevisionLog(models.Model):
    """사용자가 신청하고 승인자가 확정하는 개정 이력. 확정되면 수정·삭제할 수 없다."""
    PENDING, CONFIRMED = 'PENDING', 'CONFIRMED'
    STATUSES = [(PENDING, '대기'), (CONFIRMED, '확정')]
    LOCKED_MSG = '확정된 개정 이력은 수정할 수 없습니다.'

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, verbose_name='기록 종류')
    object_id = models.PositiveBigIntegerField('기록 번호')
    target = GenericForeignKey('content_type', 'object_id')
    object_repr = models.CharField('대상 기록', max_length=200)
    label = models.CharField('개정', max_length=20)
    changes = models.TextField('변경 내용')
    reason = models.TextField('사유')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                     verbose_name='신청자')
    requested_at = models.DateTimeField('신청 일시', auto_now_add=True)
    status = models.CharField('상태', max_length=9, choices=STATUSES, default=PENDING)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='+', verbose_name='승인자')
    approved_at = models.DateTimeField('승인 일시', null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '개정 이력'
        ordering = ['requested_at', 'pk']

    def __str__(self):
        return f'{self.object_repr} {self.label}'

    def save(self, *args, **kwargs):
        if self.pk and RevisionLog.objects.filter(pk=self.pk, status=self.CONFIRMED).exists():
            raise ValidationError(self.LOCKED_MSG)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == self.CONFIRMED or (self.pk and RevisionLog.objects.filter(pk=self.pk, status=self.CONFIRMED).exists()):
            raise ValidationError(self.LOCKED_MSG)
        return super().delete(*args, **kwargs)


class MasterModel(models.Model):
    """기준정보 공통 칸. 행은 지우지 않고 '사용'을 끈다. 사용자 정의 칸 값은 extra에 둔다."""
    created_at = models.DateTimeField('등록 일시', auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   editable=False, related_name='+', verbose_name='등록자')
    updated_at = models.DateTimeField('수정 일시', auto_now=True)
    active = models.BooleanField('사용', default=True)
    note = models.TextField('비고', blank=True)
    extra = models.JSONField('사용자 정의 칸', default=dict, blank=True)
    history = HistoricalRecords(inherit=True)

    class Meta:
        abstract = True

    def clean(self):
        validate_extra(self)


def validate_extra(obj):
    """사용자 정의 칸(FieldDef) 값 검사. 정의에 없는 키(사용 중지된 칸 포함)는 그대로 둔다."""
    import datetime
    from decimal import Decimal, InvalidOperation
    extra, errors = obj.extra if isinstance(obj.extra, dict) else {}, []
    for d in FieldDef.objects.filter(target=ContentType.objects.get_for_model(type(obj)), active=True):
        v = extra.get(d.key)
        if v in (None, ''):
            if d.required:
                errors.append(f'{d.label}: 값을 입력하세요.')
            continue
        if d.kind == FieldDef.NUMBER:
            try:
                num = Decimal(str(v))
                if isinstance(v, bool) or not num.is_finite():
                    raise InvalidOperation
                extra[d.key] = int(num) if num == num.to_integral_value() else float(num)
            except InvalidOperation:
                errors.append(f'{d.label}: 숫자가 아닙니다.')
        elif d.kind == FieldDef.DATE:
            try:
                datetime.date.fromisoformat(v) if isinstance(v, str) and len(v) == 10 else int('x')
            except ValueError:
                errors.append(f'{d.label}: 날짜 형식(YYYY-MM-DD)이 아닙니다.')
        elif d.kind == FieldDef.BOOL:
            extra[d.key] = bool(v)
        elif d.kind == FieldDef.CHOICE and v not in d.choices:
            errors.append(f'{d.label}: 선택지에 없는 값입니다.')
        elif d.kind in (FieldDef.PARTNER, FieldDef.USER):
            from django.contrib.auth import get_user_model
            model, msg = (Partner, '없는 거래처입니다.') if d.kind == FieldDef.PARTNER else (get_user_model(), '없는 사용자입니다.')
            if not (isinstance(v, int) and not isinstance(v, bool) and model.objects.filter(pk=v).exists()):
                errors.append(f'{d.label}: {msg}')
    obj.extra = extra
    if errors:
        raise ValidationError({'extra': errors})


class Department(MasterModel):
    CYCLE_MSG = '상위 부서가 자기 자신이나 하위 부서일 수 없습니다.'

    code = models.CharField('부서 코드', max_length=10, unique=True)
    name = models.CharField('부서 이름', max_length=60)
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='children',
                               verbose_name='상위 부서')
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+', verbose_name='부서장')
    sort = models.PositiveIntegerField('정렬', default=0)

    class Meta:
        verbose_name = verbose_name_plural = '부서'
        ordering = ['sort', 'code']

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        seen, p = set(), self.parent
        while p is not None and p.pk not in seen:
            if p is self or (self.pk and p.pk == self.pk):
                raise ValidationError({'parent': self.CYCLE_MSG})
            seen.add(p.pk)
            p = p.parent


class Partner(MasterModel):
    """협력사·고객사·외주처·교정기관 (한 회사가 여러 구분을 가질 수 있다)."""
    ROLE_MSG = '협력사·고객사·외주처·교정기관 중 하나 이상을 고르세요.'
    NEW, APPROVED, CONDITIONAL, SUSPENDED = 'new', 'approved', 'conditional', 'suspended'
    STATUS_CHOICES = [(NEW, '신규 평가'), (APPROVED, '승인'), (CONDITIONAL, '조건부 승인'), (SUSPENDED, '거래 중지')]
    GRADE_CHOICES = [(g, g) for g in 'ABCD']

    code = models.CharField('거래처 코드', max_length=20, unique=True)
    name = models.CharField('거래처 이름', max_length=100)
    is_supplier = models.BooleanField('협력사', default=False)
    is_customer = models.BooleanField('고객사', default=False)
    is_outsource = models.BooleanField('외주처', default=False)
    is_calibrator = models.BooleanField('교정기관', default=False)
    qc_name = models.CharField('품질 담당자', max_length=30, blank=True)
    qc_phone = models.CharField('품질 담당 전화', max_length=30, blank=True)
    qc_email = models.EmailField('품질 담당 이메일', blank=True)
    status = models.CharField('거래 상태', max_length=12, choices=STATUS_CHOICES, default=NEW)
    grade = models.CharField('평가 등급', max_length=1, choices=GRADE_CHOICES, blank=True)
    evaluated_on = models.DateField('평가일', null=True, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = '거래처'
        ordering = ['code']

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if not (self.is_supplier or self.is_customer or self.is_outsource or self.is_calibrator):
            raise ValidationError(self.ROLE_MSG)


class PartnerCertificate(models.Model):
    STANDARD_CHOICES = [(s, s) for s in ('ISO 9001', 'IATF 16949', 'AS9100', 'ISO 17025', 'ISO 14001', 'NADCAP')] + [('etc', '기타')]

    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name='certificates', verbose_name='거래처')
    standard = models.CharField('인증 규격', max_length=20, choices=STANDARD_CHOICES)
    cert_no = models.CharField('인증 번호', max_length=60, blank=True)
    valid_until = models.DateField('유효 기한')
    file = models.FileField('인증서 파일', upload_to='partner_cert/%Y/', blank=True)  # 기밀 아님 → MEDIA
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '거래처 인증'
        ordering = ['valid_until']

    def __str__(self):
        return f'{self.partner} {self.get_standard_display()}'


def extra_targets():
    """사용자 정의 칸을 붙일 수 있는 모델(MasterModel 하위)의 ContentType 조건."""
    names = [m._meta.model_name for m in apps.get_app_config('core').get_models()
             if issubclass(m, MasterModel) and not m.__name__.startswith('Historical')]
    return models.Q(app_label='core', model__in=names)


class FieldDef(models.Model):
    """관리 화면에서 기준정보에 더하는 칸. 값은 그 기록의 extra(JSON)에 키로 저장된다."""
    LOCKED_MSG = '저장된 칸의 키·대상은 바꿀 수 없습니다.'
    TEXT, NUMBER, DATE, BOOL, CHOICE, PARTNER, USER = 'text', 'number', 'date', 'bool', 'choice', 'partner', 'user'
    KIND_CHOICES = [(TEXT, '글'), (NUMBER, '수'), (DATE, '날짜'), (BOOL, '예·아니오'), (CHOICE, '선택'),
                    (PARTNER, '거래처'), (USER, '사용자')]

    target = models.ForeignKey(ContentType, on_delete=models.PROTECT, limit_choices_to=extra_targets, verbose_name='대상')
    key = models.CharField('키', max_length=40, validators=[RegexValidator(r'^[a-z][a-z0-9_]*$', '키는 영문 소문자로 시작하고 영문 소문자·숫자·_만 씁니다.')])
    label = models.CharField('이름', max_length=60)
    kind = models.CharField('종류', max_length=10, choices=KIND_CHOICES, default=TEXT)
    choices = models.JSONField('선택지', default=list, blank=True, help_text='종류가 "선택"일 때 ["국민", "신한"]처럼 적습니다.')
    required = models.BooleanField('필수', default=False)
    sort = models.PositiveIntegerField('순서', default=0)
    active = models.BooleanField('사용', default=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '사용자 정의 칸'
        ordering = ['target', 'sort', 'key']
        constraints = [models.UniqueConstraint(fields=['target', 'key'], name='uniq_fielddef_key')]

    def __str__(self):
        return self.label

    def clean(self):
        if self.pk:
            old = FieldDef.objects.filter(pk=self.pk).values('key', 'target_id').first()
            if old and (old['key'] != self.key or old['target_id'] != self.target_id):
                raise ValidationError(self.LOCKED_MSG)
        if self.kind == self.CHOICE and not (isinstance(self.choices, list) and self.choices):
            raise ValidationError({'choices': '종류가 "선택"이면 선택지를 입력하세요.'})


def attachment_storage():
    # MEDIA_ROOT 밖: /media/ 주소로 닿지 않고, 대상 기록 열람 권한을 확인하는 core.views.attachment_download로만 연다
    from django.core.files.storage import FileSystemStorage
    return FileSystemStorage(location=settings.DATA_DIR / 'attachments')


class Attachment(models.Model):
    """어느 업무 기록에나 붙이는 파일(사진·사양서·도면 등). 개인 기록에는 붙이지 않는다."""
    PRIVATE_MSG = '개인 기록에는 첨부할 수 없습니다.'
    KIND_CHOICES = [('photo', '사진'), ('spec', '사양서'), ('drawing', '도면'), ('manual', '매뉴얼'), ('purchase', '구매서류'),
                    ('report', '성적서'), ('warranty', '보증서'), ('cert', '인증서'), ('etc', '기타')]

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, verbose_name='대상 종류')
    object_id = models.PositiveBigIntegerField('대상 번호')
    target = GenericForeignKey('content_type', 'object_id')
    kind = models.CharField('구분', max_length=10, choices=KIND_CHOICES, default='etc')
    file = models.FileField('파일', upload_to='%Y/%m/', storage=attachment_storage)
    title = models.CharField('제목', max_length=200, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    editable=False, related_name='+', verbose_name='올린 사람')
    uploaded_at = models.DateTimeField('올린 일시', auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = verbose_name_plural = '첨부파일'
        ordering = ['-uploaded_at']
        indexes = [models.Index(fields=['content_type', 'object_id'])]

    def __str__(self):
        return self.title

    def clean(self):
        from qms.models import PRIVATE_APPS
        if self.content_type_id and self.content_type.app_label in PRIVATE_APPS:
            raise ValidationError(self.PRIVATE_MSG)

    def save(self, *args, **kwargs):
        if not self.title and self.file:
            self.title = os.path.basename(self.file.name)[:200]
        super().save(*args, **kwargs)


@receiver(post_delete, sender=Attachment)
def _delete_attachment_file(sender, instance, **kwargs):
    transaction.on_commit(lambda: instance.file.delete(save=False))
