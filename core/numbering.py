"""번호 규칙(틀 문자열) 해석과 검사. 문법은 docs/superpowers/specs/2026-11-05-numbering-design.md 4.1절."""
import re
from dataclasses import dataclass

from .models import CodeValue, NumberRule

_LABELS = {label: key for key, label in CodeValue.GROUPS}
_TAIL = re.compile(r'뒤(\d+)')
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
