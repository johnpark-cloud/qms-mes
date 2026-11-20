"""엑셀/CSV 일괄 등록(docs/data-flow.md). 열 이름은 ImportProfile.mapping({칸: 열 제목})으로 회사마다 다르게 지정한다.

들여오기 대상은 기록 설명서(core/recordspec.py SPECS)의 create 칸에서 저절로 만든다. 새 기록 종류를 SPECS에 create와 함께
넣으면 그대로 대상이 되고, 저장은 기록 화면과 같은 길(rules.save_new·save_edit)이라 검증·인터록·잠금·이력이 똑같이 걸린다.
종류를 더하거나 빼고 키를 바꿀 때 고칠 곳은 아래 표들뿐이다(마이그레이션 필요 없음):
  EXCLUDED  들여오지 않는 종류            EXTRA    SPECS 밖 대상(품목)
  LEGACY    이미 저장된 설정의 대상 키      LOOKUP   유일 칸이 없는 모델을 가리킬 때 찾는 칸(자동: number·code·username)
  MATCH     고칠 기록을 찾는 키 열(자동: 유일 칸)   RESOLVE  특별한 외래키 찾기(공정 순서·상위 코드)
"""
import csv
import functools
import io
from typing import NamedTuple

from django.apps import apps
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models, transaction
from openpyxl import load_workbook

from . import recordspec, rules
from .modules import MODULES, active, module_of_model


def read_rows(uploaded, header_row):
    """업로드 파일을 {열 제목: 값} 행 목록으로 읽는다. (행 번호, dict)를 돌려준다."""
    if uploaded.name.lower().endswith('.csv'):
        raw = uploaded.read()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp949')  # 한국어 엑셀이 저장한 CSV
        rows = list(csv.reader(io.StringIO(text)))
    else:
        ws = load_workbook(uploaded, read_only=True, data_only=True).active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    header = [str(h).strip() if h is not None else '' for h in rows[header_row - 1]]
    for i, r in enumerate(rows[header_row:], start=header_row + 1):
        r = ['' if v is None else v.strip() if isinstance(v, str) else v for v in r]  # 빈 칸이 'None'으로 저장되지 않게
        if any(v != '' for v in r):
            yield i, dict(zip(header, r))


class Target(NamedTuple):
    key: str  # ImportProfile.target 값
    model: type
    create: tuple  # 새로 만들 때 폼 칸(기록 화면 「새로 만들기」와 같다)
    columns: tuple  # 파일 열이 될 칸: create 중 숨은·JSON·파일 칸을 뺀 것
    edit: tuple  # 키가 맞는 기록을 고칠 때 바꾸는 칸(기록 화면 수정과 같다)
    match: tuple  # 이 칸 값이 같은 기록이 있으면 고친다. 비면 늘 새로 만든다
    lock_parent: str = ''

    @property
    def label(self):
        return str(self.model._meta.verbose_name)


EXCLUDED = {'core.numberrule', 'core.fielddef'}  # 설정 기록: 화면에서만 만든다(data-flow.md 6절)
EXTRA = {'core.item': {'create': ('code', 'name', 'item_type'), 'edit': ('name', 'item_type')}}  # 품목은 전용 화면이라 SPECS 밖
LEGACY = {'core.item': 'item', 'core.workorder': 'work_order'}  # 이미 저장된 설정의 대상 값(바꾸면 데이터 마이그레이션 필요)
LOOKUP_KEYS = ('number', 'code', 'username')  # 외래키가 가리키는 모델에서 이 순서로 첫 유일 칸을 키로 쓴다
LOOKUP = {'qms.auditchecklist': 'name', 'qms.internalaudit': 'name'}  # 유일 칸이 없는 모델: 두 건 이상 맞으면 그 행 오류
MATCH = {'core.codevalue': ('group', 'parent', 'code')}  # 최상위는 묶음+코드, 하위는 상위+코드가 유일(모델 조건)


def _routing_step(text, values):
    from .models import RoutingStep, WorkOrder
    wo = WorkOrder.objects.filter(pk=values.get('work_order') or None).first()
    if wo is None:
        raise ValidationError('작업지시를 먼저 적어야 공정을 찾습니다.')
    step = RoutingStep.objects.filter(item=wo.item_id, process__code=text).order_by('seq').first()
    if step is None:
        raise ValidationError(f"작업지시 {wo.number} 품목의 공정 순서에 공정 코드 '{text}'이(가) 없습니다.")
    return step.pk


def _code_parent(text, values):
    """상위 코드. 같은 코드가 다른 상위 아래에 또 있으면 '1/2'처럼 위에서부터 '/'로 이어 적는다."""
    from .models import CodeValue
    group = CodeValue.PARENT_GROUP.get(values.get('group'))
    if group is None:
        raise ValidationError('이 묶음은 상위 코드를 두지 않습니다.')
    *above, code = [p.strip() for p in text.split('/')]
    hits = CodeValue.objects.filter(group=group, code=code)
    for depth, p in enumerate(reversed(above), start=1):
        hits = hits.filter(**{'parent__' * depth + 'code': p})
    hits = list(hits.values_list('pk', flat=True)[:2])
    if not hits:
        raise ValidationError(f"{dict(CodeValue.GROUPS)[group]} 코드 '{text}'이(가) 없습니다.")
    if len(hits) > 1:
        raise ValidationError(f"{dict(CodeValue.GROUPS)[group]} 코드 '{text}'이(가) 두 건 이상입니다. "
                              f"상위 코드까지 '1/{code}'처럼 '/'로 이어 적으세요.")
    return hits[0]


RESOLVE = {('core.workresult', 'step'): _routing_step, ('core.codevalue', 'parent'): _code_parent}


def _match(model, columns):
    if model._meta.label_lower in MATCH:
        return MATCH[model._meta.label_lower]
    for n in columns:
        if model._meta.get_field(n).unique:
            return (n,)
    for together in model._meta.unique_together:
        if set(together) <= set(columns):
            return tuple(together)
    return ()


def _target(label, create, edit, hidden=(), lock_parent=''):
    model = apps.get_model(label)
    skip = {f.name for f in model._meta.fields if isinstance(f, (models.JSONField, models.FileField))}
    columns = tuple(n for n in create if n not in hidden and n not in skip)
    return Target(LEGACY.get(label, label), model, tuple(create), columns, tuple(edit), _match(model, columns), lock_parent)


@functools.cache
def targets():
    """{대상 키: Target}. 앱이 다 올라온 뒤 처음 부를 때 만든다."""
    found = [_target(label, **spec) for label, spec in EXTRA.items()]
    found += [_target(label, s.create, s.edit, s.hidden, s.lock_parent)
              for label, s in recordspec.SPECS.items() if s.create and label not in EXCLUDED]
    return {t.key: t for t in found}


def target_choices():
    """ImportProfile.target 선택지. 모델이 호출형으로 받아서 대상이 바뀌어도 마이그레이션이 필요 없다."""
    return sorted(((t.key, t.label) for t in targets().values()), key=lambda c: c[1])


def target_of(profile):
    return targets().get(profile.target)


def lookup_key(model):
    """외래키 칸에 적는 사람이 읽는 키(품번·LOT 번호·아이디 등). 없으면 None."""
    names = {f.name for f in model._meta.fields if f.unique and not f.primary_key}
    return next((n for n in LOOKUP_KEYS if n in names), LOOKUP.get(model._meta.label_lower))


def headers(target):
    """{칸: 표준 열 제목}. 열 제목은 「새로 만들기」 화면의 칸 이름과 같다(data-flow.md 5절)."""
    return {n: recordspec.label_of(target.model, n) for n in target.columns}


def problems():
    """대상 설정 점검: 외래키 칸마다 찾는 방법이 있어야 한다(테스트가 부른다)."""
    bad = []
    for t in targets().values():
        for n in t.columns:
            f = t.model._meta.get_field(n)
            if f.is_relation and (t.model._meta.label_lower, n) not in RESOLVE and not lookup_key(f.related_model):
                bad.append(f'{t.model._meta.label_lower}.{n}')
    return bad


BOOLS = {'예': True, 'y': True, 'yes': True, '1': True, 'true': True, 'o': True,
         '아니오': False, 'n': False, 'no': False, '0': False, 'false': False, 'x': False}


def _text(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)  # 엑셀 숫자 칸(1001.0)
    return str(v).strip()


def _convert(target, f, v, values):
    """파일 값 하나를 폼 값으로: 예/아니오 → bool, 선택지 이름 → 코드, 사람이 읽는 키 → id. 나머지 검사는 폼이 한다."""
    if v == '':
        return ''
    if isinstance(f, models.BooleanField):
        b = BOOLS.get(_text(v).lower())
        if b is None:
            raise ValidationError(f"'{v}'은(는) 예/아니오로 적으세요.")
        return b
    if f.is_relation:
        text = _text(v)
        resolve = RESOLVE.get((target.model._meta.label_lower, f.name))
        if resolve:
            return resolve(text, values)
        rel = f.related_model
        hits = list(rel.objects.filter(**{lookup_key(rel): text}).values_list('pk', flat=True)[:2])
        if not hits:
            raise ValidationError(f"'{text}'이(가) 없습니다.")
        if len(hits) > 1:
            raise ValidationError(f"'{text}'이(가) 두 건 이상이라 하나로 정할 수 없습니다.")
        return hits[0]
    if f.choices:
        return {str(label): code for code, label in f.flatchoices}.get(_text(v), v)
    if isinstance(f, (models.CharField, models.TextField)):
        return _text(v)
    return v


def _message(model, e):
    if not hasattr(e, 'error_dict'):
        return ' '.join(e.messages)
    return ' '.join(m if k == NON_FIELD_ERRORS else f'{recordspec.label_of(model, k)}: {m}'
                    for k, msgs in e.message_dict.items() for m in msgs)


def _existing(target, values):
    """키 열 값이 모두 있으면 그 기록(없으면 None). 비어도 되는 키(상위 코드)는 빈 값끼리 맞춘다."""
    if not target.match or any(n not in values for n in target.match):
        return None
    cond = {}
    for n in target.match:
        f = target.model._meta.get_field(n)
        if values[n] == '' and not f.null:
            return None
        cond[f.attname] = None if values[n] == '' else values[n]
    return target.model.objects.filter(**cond).first()


def _apply(target, row, user):
    """한 행: 키가 맞는 기록이 있으면 기록 화면 수정과 같이 고치고, 없으면 새로 만든다."""
    model, values = target.model, {}
    for n in target.columns:  # 순서대로: 공정 찾기는 앞 칸 작업지시를 쓴다
        if n in row:
            try:
                values[n] = _convert(target, model._meta.get_field(n), row[n], values)
            except ValidationError as e:
                raise ValidationError({n: e.messages})
    obj = _existing(target, values)
    if obj is None:  # 빈 칸은 값 없음 → 모델 기본값
        return rules.save_new(model, target.create, user, {k: v for k, v in values.items() if v != ''})
    fixed = {}
    for n, v in values.items():  # 수정 칸이 아닌 열(품번 등 정체를 바꾸는 칸)은 지금 값과 같아야 한다. 빈 칸은 그대로 둔다
        f = model._meta.get_field(n)
        if n not in target.edit and v != '' and f.to_python(v) != f.value_from_object(obj):
            fixed[n] = ['이미 있는 기록의 이 칸은 들여오기로 바꿀 수 없습니다.']
    if fixed:
        raise ValidationError(fixed)
    if not target.edit:
        raise ValidationError('이미 있는 기록이라 고칠 수 없습니다.')
    rules.assert_editable(obj, user, target.lock_parent)
    return rules.save_edit(obj, target.edit, user, {k: v for k, v in values.items() if k in target.edit})


READ_ERROR = '파일을 읽을 수 없습니다. 엑셀(.xlsx) 또는 CSV 형식과 제목 행 번호를 확인하세요.'


def _process(profile, uploaded, user, dry_run):
    """run_import·preview_import 공용. (처리 건수, 오류 목록, 미리보기 행)을 돌려준다. dry_run이면 늘 되돌린다."""
    errors, count, preview = [], 0, []
    target = target_of(profile)
    if target is None:
        return 0, [f"'{profile.target}'은(는) 들여오기 대상이 아닙니다. 가져오기 설정의 대상을 고치세요."], []
    module = module_of_model(target.model._meta.label_lower)
    if not active(module):  # 꺼진 모듈(작업지시 → 생산관리)로는 들여오지 않는다(MOD-12)
        return 0, [f'{MODULES[module].name} 모듈이 꺼져 있어 가져올 수 없습니다.'], []
    bad = [k for k in profile.mapping if k not in target.columns]
    if bad:
        return 0, [f'열 매핑에 들여올 수 없는 칸이 있습니다: {", ".join(bad)}'], []
    try:
        rows = list(read_rows(uploaded, profile.header_row))
    except Exception:  # 빈 파일, 제목 행이 파일보다 아래, 확장자만 .xlsx, 글자 인코딩을 알 수 없는 CSV 등
        return 0, [READ_ERROR], []
    with transaction.atomic():
        for line, raw in rows:
            try:
                row = {field: raw[col] for field, col in profile.mapping.items()}
                preview.append({'line': line, 'values': {k: '' if v is None else str(v) for k, v in row.items()}})
                with transaction.atomic():
                    _apply(target, row, user)
                count += 1
            except KeyError as e:
                errors.append(f'{line}행: 열 {e} 없음')
            except ValidationError as e:
                errors.append(f'{line}행: {_message(target.model, e)}')
            except Exception as e:
                errors.append(f'{line}행: {e}')
        if errors or dry_run:
            transaction.set_rollback(True)
    return count, errors, preview


def run_import(profile, uploaded, user):
    """한 행이라도 틀리면 전체를 되돌린다. (처리 건수, 오류 목록)을 돌려준다. user는 만든 사람·잠금 판단에 쓴다."""
    count, errors, _ = _process(profile, uploaded, user, False)
    return count, errors


def preview_import(profile, uploaded, user):
    """아무것도 저장하지 않고 run_import 결과를 미리 보여준다."""
    count, errors, rows = _process(profile, uploaded, user, True)
    return {'count': count, 'errors': errors, 'rows': rows}
