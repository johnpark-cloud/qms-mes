"""검사 판정·입고 업무 규칙. 본문은 기존 qms/views.py 코드를 옮긴 것이다(docs/architecture-migration-plan.md 3.2)."""
from decimal import Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max

from core.models import Lot, RevisionLog
from core.rules import LOCKED_MSG, Locked, child_editable, save_with_lock

from .models import Characteristic, Inspection, InspectionSpec, Measurement

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
        if nc:
            if insp.result == Inspection.FAIL:  # 불합격 부적합에만 검사원이 고른 불량유형·수량을 채운다 (SPC 경보 부적합은 그대로)
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


# ---------- 검사기준서 ----------

class Stale(Exception):
    """다른 사람이 먼저 저장했다. API는 409로 바꾼다."""

    def __init__(self, msg='다른 사람이 먼저 고쳤습니다. 다시 불러오세요.'):
        super().__init__(msg)


def new_spec_revision(spec):
    """승인된 기준서의 항목을 복사해 다음 개정(초안)을 만든다. 호출하는 쪽이 트랜잭션 안에서 부른다."""
    items = list(spec.characteristics.all())
    top = InspectionSpec.objects.filter(item=spec.item, inspection_type=spec.inspection_type
                                        ).aggregate(m=Max('revision'))['m']
    new = InspectionSpec.objects.create(item=spec.item, inspection_type=spec.inspection_type,
                                        revision=top + 1, sampling=spec.sampling, note=spec.note)
    for c in items:
        Characteristic.objects.create(spec=new, name=c.name, lsl=c.lsl, usl=c.usl, unit=c.unit,
                                      special=c.special, plan_line=c.plan_line)
    return new


def open_or_new_revision(spec):
    """(열려 있는 초안, 새로 만들었는가). 같은 품번·구분에 미승인 개정이 있으면 그것을 쓴다."""
    with transaction.atomic():
        draft = InspectionSpec.objects.filter(item=spec.item, inspection_type=spec.inspection_type,
                                              approved_at__isnull=True).order_by('-revision').first()
        return (draft, False) if draft else (new_spec_revision(spec), True)


def spec_version(spec):
    """동시 수정 감지 번호: 기준서와 그 항목(삭제 포함)의 이력 중 가장 큰 history_id. 이력이 없으면 0."""
    a = spec.history.aggregate(m=Max('history_id'))['m'] or 0
    b = Characteristic.history.filter(spec_id=spec.pk).aggregate(m=Max('history_id'))['m'] or 0
    return max(a, b)


_ROW_FIELDS = ('name', 'lsl', 'usl', 'unit', 'special')


def _num(v):
    """엑셀에서 붙여 넣은 숫자: 앞뒤 공백·천 단위 쉼표를 없애고 빈 글은 None(규격 없음)."""
    if v is None:
        return None
    return str(v).strip().replace(',', '') or None


def save_spec(spec, user, data, rows, version):
    """기준서 속성과 검사항목 줄을 한꺼번에 저장한다. 하나라도 잘못이면 아무것도 저장하지 않는다.
    오류 키는 characteristics.{줄}.{칸}. 승인 잠금은 save_with_lock이 Locked로 알린다."""
    with transaction.atomic():
        if version is not None and version != spec_version(spec):
            raise Stale()
        own = {c.pk: c for c in spec.characteristics.all()}
        new_rows, changed, deleted = [], [], []
        errors = {}
        for i, row in enumerate(rows):
            key = f'characteristics.{i}'
            cid = row.get('id')
            if cid is not None and (not isinstance(cid, int) or isinstance(cid, bool) or cid not in own):  # 남의 항목을 고치지 못하게 한다
                errors[f'{key}.id'] = ['다른 검사기준의 항목입니다.']
                continue
            if row.get('delete'):
                if cid is not None:
                    deleted.append(own[cid])
                continue
            if cid is None:
                if not any(str(row.get(f) or '').strip() for f in ('name', 'lsl', 'usl', 'unit')):
                    continue  # 빈 줄
                obj = Characteristic(spec=spec)
            else:
                obj = own[cid]
            for f in _ROW_FIELDS:
                if f in row:
                    setattr(obj, f, _num(row[f]) if f in ('lsl', 'usl') else (row[f] or ''))
            if 'plan_line' in row:
                obj.plan_line_id = row['plan_line'] or None
            try:
                obj.full_clean(exclude=['spec'])
            except ValidationError as e:
                for field, msgs in e.message_dict.items():
                    errors[f'{key}.{field}'] = msgs
            (new_rows if cid is None else changed).append(obj)

        perms = ['change_inspectionspec'] + ['add_characteristic'] * bool(new_rows) + \
                ['change_characteristic'] * bool(changed) + ['delete_characteristic'] * bool(deleted)
        if not all(user.has_perm(f'qms.{p}') for p in perms):
            raise PermissionDenied('이 작업을 할 권한이 없습니다.')
        if deleted and not child_editable(spec, user):
            raise Locked(LOCKED_MSG)
        if errors:
            raise ValidationError(errors)

        for f in ('sampling', 'note'):
            if f in data:
                v = '' if data[f] is None else data[f]
                limit = InspectionSpec._meta.get_field(f).max_length
                if not isinstance(v, str):
                    errors[f] = ['글이어야 합니다.']
                elif limit and len(v) > limit:
                    errors[f] = [f'{limit}자 이하로 입력하세요.']
                setattr(spec, f, v)
        if errors:
            raise ValidationError(errors)
        save_with_lock(spec, user, children=changed + new_rows)
        for c in deleted:
            c.delete()
    return spec


def prev_revision(spec):
    """같은 품번·구분에서 개정번호가 바로 아래인 기준서."""
    return (InspectionSpec.objects.filter(item=spec.item, inspection_type=spec.inspection_type, revision__lt=spec.revision)
            .order_by('-revision').first())


_CELLS = ('lsl', 'usl', 'unit', 'special', 'plan_line_id')


def _fmt(v):
    if v is None:
        return ''
    return format(v.normalize(), 'f') if hasattr(v, 'normalize') else str(v)


def _cell(c, f):
    return getattr(c, 'plan_line') if f == 'plan_line_id' else getattr(c, f)  # 관리계획서 항목은 번호가 아니라 이름으로


def compare_specs(prev, cur):
    """이전 개정과 비교. 항목은 이름으로 짝짓는다(SPC도 이름으로 이어진다). prev가 None이면 None.
    rows 한 줄의 values는 {칸: [이전, 현재]}(글자)로, diff_text가 쓴다."""
    if prev is None:
        return None
    fields = {f: [getattr(prev, f), getattr(cur, f)] for f in ('sampling', 'note') if getattr(prev, f) != getattr(cur, f)}
    old = {c.name: c for c in prev.characteristics.all()}
    new = {c.name: c for c in cur.characteristics.all()}
    rows = []
    for name in list(old) + [n for n in new if n not in old]:
        o, n = old.get(name), new.get(name)
        if o is None or n is None:
            rows.append({'id': (n or o).pk, 'name': name, 'status': 'added' if o is None else 'removed',
                         'cells': [], 'values': {}})
            continue
        cells = [f for f in _CELLS if getattr(o, f) != getattr(n, f)]
        if cells:
            rows.append({'id': n.pk, 'name': name, 'status': 'changed', 'cells': [c.removesuffix('_id') for c in cells],
                         'values': {c.removesuffix('_id'): [_fmt(_cell(o, c)), _fmt(_cell(n, c))] for c in cells}})
    return {'fields': fields, 'rows': rows}


def _label(model, name):
    return str(model._meta.get_field(name).verbose_name).split('(')[0]  # 하한(LSL) → 하한


def diff_text(diff):
    """비교 결과를 한 줄씩 쓴 글. 이력 남기기의 미리 채움 내용으로 쓴다."""
    if diff is None:
        return '최초 제정'
    lines = [f"{_label(InspectionSpec, f)}: '{o}' → '{n}'" for f, (o, n) in diff['fields'].items()]
    for r in diff['rows']:
        if r['status'] == 'added':
            lines.append(f"항목 추가: {r['name']}")
        elif r['status'] == 'removed':
            lines.append(f"항목 삭제: {r['name']}")
        else:
            cells = ', '.join(f"{_label(Characteristic, c)} {o} → {n}" for c, (o, n) in r['values'].items())
            lines.append(f"항목 변경: {r['name']} ({cells})")
    return '\n'.join(lines) or '변경 없음'


def spec_logs(spec, confirmed_only):
    """같은 품번·구분에서 현재 개정 이하인 모든 개정의 개정 이력. confirmed_only이면 확정만(문서용)."""
    ids = InspectionSpec.objects.filter(item=spec.item, inspection_type=spec.inspection_type,
                                        revision__lte=spec.revision).values_list('pk', flat=True)
    logs = RevisionLog.objects.filter(content_type=ContentType.objects.get_for_model(InspectionSpec), object_id__in=ids)
    return logs.filter(status=RevisionLog.CONFIRMED) if confirmed_only else logs
