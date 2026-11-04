"""하위 항목 표(BOM·라우팅·관리계획서 줄 등)를 요청 줄에서 모아 검증하는 공용 도구. 저장은 하지 않는다."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Max


def clean_number(v):
    """앞뒤 공백·천 단위 쉼표를 없앤다. 빈 글은 None."""
    if v is None:
        return None
    return str(v).strip().replace(',', '') or None


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _set(obj, f, kind, v):
    """칸 하나를 넣는다. 형식이 틀리면 오류 글을 돌려준다."""
    if kind == 'fk':
        setattr(obj, f'{f}_id', None if _blank(v) else v)
    elif kind == 'number':
        n = clean_number(v)
        if n is not None:
            try:
                Decimal(n)
            except ArithmeticError:
                return '숫자를 입력하세요.'
        setattr(obj, f, n)
    elif kind == 'int':
        if _blank(v):
            setattr(obj, f, None)
        else:
            try:
                if isinstance(v, bool) or (isinstance(v, float) and v != int(v)):
                    raise ValueError
                setattr(obj, f, int(str(v).strip()) if isinstance(v, str) else int(v))
            except (ValueError, TypeError):
                return '정수를 입력하세요.'
    else:
        setattr(obj, f, '' if v is None else v.strip() if isinstance(v, str) else v)


def collect_rows(rows, own, make, fields, prefix, exclude=(), unique=()):
    """(new, changed, deleted, errors). 새 줄은 저장 전 객체, 고친 줄은 메모리에서만 바뀐 객체다."""
    new, changed, deleted, errors, kept = [], [], [], {}, []
    for i, row in enumerate(rows):
        key = f'{prefix}.{i}'
        rid = row.get('id')
        if rid is not None and (not isinstance(rid, int) or isinstance(rid, bool) or rid not in own):
            errors[f'{key}.id'] = ['다른 기록의 항목입니다.']
            continue
        if row.get('delete'):
            if rid is not None:
                deleted.append(own[rid])
            continue
        if rid is None:
            if all(_blank(row.get(f)) for f in fields):
                continue  # 빈 줄
            obj = make()
        else:
            obj = own[rid]
        bad = set()
        for f, kind in fields.items():
            if f in row:
                msg = _set(obj, f, kind, row[f])
                if msg:
                    errors[f'{key}.{f}'] = [msg]
                    bad.add(f)
        try:
            obj.full_clean(exclude=[*exclude, *bad], validate_constraints=False)
        except ValidationError as e:
            for f, msgs in e.message_dict.items():
                f = f[:-3] if f.endswith('_id') and f[:-3] in fields else f
                errors.setdefault(f'{key}.{f}', msgs)
        (new if rid is None else changed).append(obj)
        kept.append((i, row, obj))
    for f in unique:
        seen = set()
        for i, row, obj in kept:
            v = getattr(obj, f'{f}_id' if fields.get(f) == 'fk' else f)
            if v is None:
                continue
            if v in seen:
                errors.setdefault(f'{prefix}.{i}.{f}', ['같은 값이 두 번 있습니다.'])
            seen.add(v)
    return new, changed, deleted, errors


def table_version(model, **filters):
    """모델 이력(조건에 맞는 것)의 최대 history_id. 없으면 0."""
    return model.history.filter(**filters).aggregate(m=Max('history_id'))['m'] or 0


def record_version(obj, children):
    """기록과 그 하위 표 이력을 합친 동시 수정 감지 번호(각 이력 최대 history_id의 합). children: [(자식 모델, fk 칸 이름)]."""
    # history_id는 모델마다 따로 세므로 max로는 하위 표만 바뀐 것을 놓친다. 각 최대값의 합은 어느 쪽이 바뀌어도 커진다.
    return sum([table_version(type(obj), id=obj.pk)] +
               [table_version(m, **{f'{fk}_id': obj.pk}) for m, fk in children])
