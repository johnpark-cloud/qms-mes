"""검사 판정·입고 업무 규칙. 본문은 기존 qms/views.py 코드를 옮긴 것이다(docs/architecture-migration-plan.md 3.2)."""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import Lot

from .models import Inspection, Measurement

RECEIVE_MSG = '품목·LOT 번호·입고수량(0보다 큰 숫자)을 모두 입력하세요.'


def measurement(char, raw):
    """입력칸 값 → 저장 전 측정값. 계량형은 숫자, 계수형은 OK/NG."""
    if char.is_variable:
        try:
            value = Decimal(raw.strip())
        except (InvalidOperation, AttributeError):
            return None
        return Measurement(characteristic=char, value=value) if value.is_finite() else None  # NaN·Infinity 거부
    return Measurement(characteristic=char, ok={'OK': True, 'NG': False}.get(raw)) if raw in ('OK', 'NG') else None


def _qty(raw):
    try:
        v = Decimal((raw or '').strip())
    except InvalidOperation:
        return Decimal(0)
    return v if v.is_finite() and v >= 0 else Decimal(0)


def submit_inspection(lot, spec, user, gauge, values, defect_type='', defect_qty=None):
    """판정: 검사·측정값을 만들고 finalize()로 판정한다. 하나라도 거부되면 전부 되돌린다.
    values는 {Characteristic.pk: 입력 문자열}. 실패하면 ValidationError."""
    with transaction.atomic():
        insp = Inspection.objects.create(lot=lot, spec=spec, inspector=user)
        for char in spec.characteristics.all():
            m = measurement(char, values.get(char.pk, ''))
            if m is None:
                raise ValidationError(f'{char.name}: 값을 입력하세요.')
            m.inspection = insp
            m.gauge = gauge if char.is_variable else None
            m.save()
        insp.finalize()
        nc = insp.nonconformance
        if nc:  # 불합격으로 자동 등록된 부적합에 검사원이 고른 불량유형·수량을 채운다
            nc.defect_type = defect_type.strip()[:100]
            nc.defect_qty = _qty(defect_qty)
            nc.inspected_qty, nc.detected_by = lot.qty, user
            nc.save()
    return insp


def receive_lot(number, item, qty_raw, supplier):
    """입고 등록: (LOT, 새로 만들었는지). 검증에 실패하면 ValidationError(RECEIVE_MSG). 권한은 호출하는 쪽이 검사한다."""
    try:
        qty = Decimal(qty_raw.strip())
    except InvalidOperation:
        qty = None
    if not number or not item or qty is None or not qty.is_finite() or qty <= 0:
        raise ValidationError(RECEIVE_MSG)
    return Lot.objects.get_or_create(number=number, defaults={
        'item': item, 'qty': qty, 'supplier': supplier.strip()[:100]})
