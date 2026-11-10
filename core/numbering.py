"""번호 규칙(틀 문자열) 해석과 검사. 문법은 docs/superpowers/specs/2026-11-05-numbering-design.md 4.1절."""
import re
from dataclasses import dataclass

from django.apps import apps

from .models import CodeValue, Item, NumberRule

_LABELS = {label: key for key, label in CodeValue.GROUPS}
_TAIL = re.compile(r'뒤([0-9]+)')
_TARGETS = {'품번': NumberRule.ITEM, '문서': NumberRule.DOC}


class NumberingError(ValueError):
    """사용자에게 그대로 보이는 한국어 메시지."""


@dataclass(frozen=True)
class Token:
    kind: str  # 'text' | 'code' | 'ref' | 'serial'
    text: str = ''
    group: str = ''
    allowed: tuple = ()
    target: str = ''
    rule: str = ''
    tail: int = 0
    width: int = 0


def _code_width(group):
    return 2 if '{2}' in CodeValue.FORMATS[group] else 1


def _parse_brace(inner):
    parts = inner.split(':')
    head = parts[0]
    if head.startswith('일련'):
        if len(parts) > 1 or not head[2:].isdigit() or int(head[2:]) < 1:
            raise NumberingError(f'{{{inner}}}: 일련번호는 {{일련N}} 꼴(N은 1 이상 숫자)이어야 합니다.')
        return Token('serial', width=int(head[2:]))
    if head in _TARGETS:
        if len(parts) not in (2, 3) or not parts[1]:
            raise NumberingError(f'{{{inner}}}: {{{head}:규칙이름}} 또는 {{{head}:규칙이름:뒤N}} 꼴이어야 합니다.')
        tail = 0
        if len(parts) == 3:
            m = _TAIL.fullmatch(parts[2])
            if not m or int(m.group(1)) < 1:
                raise NumberingError(f'{{{inner}}}: 뒤 N자리는 뒤N(N은 1 이상 숫자) 꼴이어야 합니다.')
            tail = int(m.group(1))
        return Token('ref', target=_TARGETS[head], rule=parts[1], tail=tail)
    if head not in _LABELS:
        raise NumberingError(f'{{{inner}}}: 알 수 없는 코드 묶음 "{head}"입니다.')
    if len(parts) > 2:
        raise NumberingError(f'{{{inner}}}: 콜론은 한 번만 쓸 수 있습니다.')
    allowed = tuple(v for v in parts[1].split(',')) if len(parts) == 2 else ()
    if any(_TAIL.fullmatch(v) for v in allowed):
        raise NumberingError(f'{{{inner}}}: 뒤N은 {{품번:규칙}}·{{문서:규칙}}에만 쓸 수 있습니다.')
    group = _LABELS[head]
    return Token('code', group=group, allowed=allowed, width=_code_width(group))


def parse_pattern(pattern):
    """문법 오류만 검사해 토큰 목록을 돌려준다."""
    tokens, pos = [], 0
    for m in re.finditer(r'\{([^{}]*)\}', pattern):
        _add_text(tokens, pattern[pos:m.start()])
        tokens.append(_parse_brace(m.group(1)))
        pos = m.end()
    _add_text(tokens, pattern[pos:])
    serials = [i for i, t in enumerate(tokens) if t.kind == 'serial']
    if len(serials) != 1 or serials[0] != len(tokens) - 1:
        raise NumberingError('{일련N}은 틀의 맨 끝에 정확히 1개 있어야 합니다.')
    return tokens


def _add_text(tokens, text):
    if '{' in text or '}' in text:
        raise NumberingError('중괄호 { }의 짝이 맞지 않습니다.')
    if text:
        tokens.append(Token('text', text=text, width=len(text)))


def rulebook():
    """전체 규칙(비활성 포함), 이름 -> 규칙."""
    return {r.name: r for r in NumberRule.objects.all()}


def _widths(rule, rules):
    def one(t):
        if t.kind != 'ref':
            return t.width
        if t.tail:
            return t.tail
        if t.rule not in rules:
            raise NumberingError(f'참조하는 규칙 "{t.rule}"이(가) 없습니다.')
        return width(rules[t.rule], rules)
    return [one(t) for t in parse_pattern(rule.pattern)]


def width(rule, rules):
    """번호 전체 글자 수. 모든 토큰 너비가 고정이다."""
    return sum(_widths(rule, rules))


def _reaches(start, rules, seen, goal):
    try:
        tokens = parse_pattern(rules[start].pattern)
    except (KeyError, NumberingError):
        return False
    for t in tokens:
        if t.kind == 'ref' and (t.rule == goal or t.rule not in seen):
            seen.add(t.rule)
            if t.rule == goal or (t.rule in rules and _reaches(t.rule, rules, seen, goal)):
                return True
    return False


def check_rule(name, target, pattern, rules=None):
    """문법과 의미를 검사한다. 어긋나면 NumberingError."""
    rules = {**(rulebook() if rules is None else rules), name: NumberRule(name=name, target=target, pattern=pattern)}
    tokens = parse_pattern(pattern)
    prev = None
    for t in tokens:
        if t.kind == 'code':
            label = dict(CodeValue.GROUPS)[t.group]
            fmt = CodeValue.FORMATS[t.group]
            for v in t.allowed:
                if not re.fullmatch(fmt, v) or not CodeValue.objects.filter(group=t.group, code=v).exists():
                    raise NumberingError(f'{{{label}}}: 허용 값 "{v}"이(가) 코드표에 없습니다.')
            want = CodeValue.PARENT_GROUP.get(t.group)
            if want and not (prev and prev.group == want):
                raise NumberingError(f'{{{label}}} 바로 앞에는 {{{dict(CodeValue.GROUPS)[want]}}}가 와야 합니다.')
        elif t.kind == 'ref':
            ref = rules.get(t.rule)
            if ref is None:
                raise NumberingError(f'참조하는 규칙 "{t.rule}"이(가) 없습니다.')
            if ref.target != t.target:
                raise NumberingError(f'규칙 "{t.rule}"은(는) {ref.get_target_display()} 규칙이라 '
                                     f'{{{dict((v, k) for k, v in _TARGETS.items())[t.target]}:{t.rule}}}로 쓸 수 없습니다.')
        if t.kind == 'code':
            prev = t
    refs = [t.rule for t in tokens if t.kind == 'ref']
    if name in refs or _reaches(name, rules, set(), name):
        raise NumberingError('규칙이 자기 자신을 되풀이해 참조합니다(순환 참조).')
    for t in tokens:
        if t.kind == 'ref' and t.tail:
            total, bounds = 0, set()
            for w in reversed(_widths(rules[t.rule], rules)):
                total += w
                bounds.add(total)
            if t.tail not in bounds:
                raise NumberingError(f'뒤{t.tail}은(는) 규칙 "{t.rule}"의 토큰 경계에 맞지 않습니다. '
                                     f'가능한 값: {", ".join(map(str, sorted(bounds)))}.')


# ---- 번호 계산·풀이 (설계 6·7절) ----

def next_serial(numbers, prefix, width):
    """prefix 뒤에 width자리 숫자만 붙은 번호의 최댓값 + 1."""
    shape = re.compile(rf'{re.escape(prefix)}([0-9]{{{width}}})')
    used = [int(m.group(1)) for n in numbers if (m := shape.fullmatch(n))]
    nxt = max(used, default=0) + 1
    if nxt > 10 ** width - 1:
        raise NumberingError('일련번호가 다 찼습니다.')
    return str(nxt).zfill(width)


def fields(rule):
    """사용자가 고를 토큰(code·ref), 틀 순서대로."""
    return [t for t in parse_pattern(rule.pattern) if t.kind in ('code', 'ref')]


def codebook():
    """전체 코드값(비활성 포함), (group, parent_id, code) -> 코드값."""
    return {(c.group, c.parent_id, c.code): c for c in CodeValue.objects.all()}


def _table(target):
    """참조 대상 표의 (모델, 번호 필드)."""
    if target == NumberRule.ITEM:
        return Item, 'code'
    return apps.get_model('qms', 'Document'), 'number'


def _lookup(book, t, value, prev):
    """부모 묶음이면 바로 앞 code 값(prev)의 자식에서 찾는다."""
    if CodeValue.PARENT_GROUP.get(t.group):
        return book.get((t.group, prev.pk, value)) if prev else None
    return book.get((t.group, None, value))


def _pieces(rule, rules, tail=0):
    """(토큰, 너비) 목록. tail이면 뒤 tail글자에 해당하는 토큰만."""
    pairs = list(zip(parse_pattern(rule.pattern), _widths(rule, rules)))
    if not tail:
        return pairs
    total = 0
    for i in range(len(pairs) - 1, -1, -1):
        total += pairs[i][1]
        if total == tail:
            return pairs[i:]
    raise NumberingError(f'뒤{tail}은(는) 규칙 "{rule.name}"의 토큰 경계에 맞지 않습니다.')


def _split(pairs, number):
    if len(number) != sum(w for _, w in pairs):
        return None
    out, pos = [], 0
    for t, w in pairs:
        out.append((t, number[pos:pos + w]))
        pos += w
    return out


def _fits(rule, number, rules, tail=0):
    parts = _split(_pieces(rule, rules, tail), number)
    if parts is None:
        return False
    for t, v in parts:
        if t.kind == 'text' and v != t.text:
            return False
        if t.kind == 'code' and (not re.fullmatch(CodeValue.FORMATS[t.group], v) or (t.allowed and v not in t.allowed)):
            return False
        if t.kind == 'serial' and not (v.isascii() and v.isdigit()):
            return False
        if t.kind == 'ref' and not _fits(rules[t.rule], v, rules, t.tail):
            return False
    return True


def matches(rule, number, rules=None):
    """번호가 규칙 모양에 맞는지(코드값 존재 여부는 보지 않는다)."""
    try:
        return _fits(rule, number, rulebook() if rules is None else rules)
    except (KeyError, NumberingError):  # 틀을 해석할 수 없거나 참조 규칙이 지워짐
        return False


def next_number(rule, values):
    """고른 값(fields(rule) 순서)으로 다음 번호를 계산한다. 어긋나면 NumberingError."""
    if not rule.active:
        raise NumberingError('사용 중지된 규칙입니다.')
    if len(values) != len(fields(rule)):
        raise NumberingError('고른 값의 개수가 규칙과 맞지 않습니다.')
    rules, book, chosen = rulebook(), codebook(), iter(values)
    prefix, prev = '', None
    for t in parse_pattern(rule.pattern):
        if t.kind == 'text':
            prefix += t.text
        elif t.kind == 'code':
            v = next(chosen)
            row = _lookup(book, t, v, prev)
            if (t.allowed and v not in t.allowed) or row is None or not row.active:
                raise NumberingError(f'{dict(CodeValue.GROUPS)[t.group]} {v}: 없거나 사용 중지된 코드입니다.')
            prefix += v
            prev = row
        elif t.kind == 'ref':
            v = next(chosen)
            if t.rule not in rules:
                raise NumberingError(f'참조하는 규칙 "{t.rule}"이(가) 없습니다.')
            model, field = _table(t.target)
            if not (model.objects.filter(**{field: v}).exists() and matches(rules[t.rule], v, rules)):
                label = dict(NumberRule.TARGETS)[t.target]
                raise NumberingError(f'{label} {v}: 없거나 규칙 "{t.rule}" 모양이 아닙니다.')
            prefix += v[-t.tail:] if t.tail else v
        else:
            numbers = []
            for target in (NumberRule.ITEM, NumberRule.DOC):
                model, field = _table(target)
                numbers += model.objects.filter(**{f'{field}__startswith': prefix}).values_list(field, flat=True)
            return prefix + next_serial(numbers, prefix, t.width)


def default_item_type(rule, values):
    """고른 code 값 중 item_type이 있는 마지막 값의 것. 없으면 ''."""
    book, prev, found = codebook(), None, ''
    for t, v in zip(fields(rule), values):
        if t.kind == 'code':
            prev = _lookup(book, t, v, prev)
            if prev and prev.item_type:
                found = prev.item_type
    return found


def candidates(token, rules=None):
    """ref 토큰의 후보: 참조 규칙 모양에 맞는 기존 번호, 정렬."""
    rules = rulebook() if rules is None else rules
    ref = rules.get(token.rule)
    if ref is None:
        return []
    model, field = _table(token.target)
    # shortcut: 표 전체를 읽어 파이썬에서 거른다, 품번·문서가 수만 건이 되면 prefix 조건을 DB로 내린다.
    return sorted(n for n in model.objects.values_list(field, flat=True) if matches(ref, n, rules))


def _explain(rule, number, rules, book, tail=0, serial='일련번호'):
    out, prev = [], None
    for t, v in _split(_pieces(rule, rules, tail), number):
        if t.kind == 'code':
            prev = _lookup(book, t, v, prev)
            out.append((v, prev.name if prev else '미등록'))
        elif t.kind == 'ref':
            out += _explain(rules[t.rule], v, rules, book, t.tail, f'{t.rule} 일련번호')
        elif t.kind == 'serial':
            out.append((v, serial))
    return out


def describe(number, target=None, book=None, rules=None):
    """번호를 자리별 (글자, 뜻)으로 푼다. 대상이 같은 규칙 먼저, 그 안에서 sort 순. 안 맞으면 []."""
    rules = list(NumberRule.objects.all()) if rules is None else rules
    byname = {r.name: r for r in rules}
    book = codebook() if book is None else book
    for rule in sorted(rules, key=lambda r: (r.target != target, r.sort)):
        try:
            if _fits(rule, number, byname):
                return _explain(rule, number, byname, book)
        except (KeyError, NumberingError):  # 설계 10절: 해석할 수 없거나 참조 규칙이 지워진 규칙은 건너뜀
            continue
    return []


def describe_text(number, target=None, book=None, rules=None):
    """describe 결과를 '1 완제품 · V ... · 001 일련번호' 한 줄로."""
    return ' · '.join(f'{c} {n}' for c, n in describe(number, target, book, rules))


def next_revision(values):
    """앞의 Rev./Rev를 뗀 숫자 개정의 최댓값 + 1. 없으면 '0'."""
    nums = [int(m.group(1)) for v in values if (m := re.fullmatch(r'(?:rev\.?\s*)?([0-9]+)', v.strip(), re.I))]
    return str(max(nums) + 1) if nums else '0'
