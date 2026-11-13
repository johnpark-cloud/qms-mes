"""엑셀/CSV 일괄 등록. 열 이름은 ImportProfile.mapping으로 회사마다 다르게 지정한다."""
import csv
import datetime
import io

from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import load_workbook

from .models import Item, WorkOrder
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


def _date(v):
    if v in (None, ''):
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return datetime.date.fromisoformat(str(v).strip()[:10])


def _save(model, key, value, **fields):
    """키로 찾아 고치거나 새로 만든다. 저장 전에 모델 검증(길이·필수·선택지)을 거친다."""
    obj = model.objects.filter(**{key: value}).first() or model(**{key: value})
    for k, v in fields.items():
        setattr(obj, k, v)
    obj.full_clean()
    obj.save()


def _item(row):
    labels = {label: code for code, label in Item.TYPES}
    t = str(row['item_type']).strip()
    item_type = labels.get(t, t)
    if item_type not in dict(Item.TYPES):
        raise ValueError(f'구분 "{t}"은(는) 원자재/반제품/완제품 중 하나여야 합니다')
    _save(Item, 'code', str(row['code']).strip(), name=str(row['name']).strip(), item_type=item_type)


def _work_order(row):
    _save(WorkOrder, 'number', str(row['number']).strip(), item=Item.objects.get(code=str(row['item']).strip()),
          planned_qty=row['planned_qty'], due_date=_date(row.get('due_date')))


READ_ERROR = '파일을 읽을 수 없습니다. 엑셀(.xlsx) 또는 CSV 형식과 제목 행 번호를 확인하세요.'
HANDLERS = {'item': _item, 'work_order': _work_order}
TARGET_MODELS = {'item': Item, 'work_order': WorkOrder}  # 가져오기 권한 확인용 (core.views.import_view)


def _process(profile, uploaded, dry_run):
    """run_import·preview_import 공용. (처리 건수, 오류 목록, 미리보기 행)을 돌려준다. dry_run이면 늘 되돌린다."""
    handler, errors, count, preview = HANDLERS[profile.target], [], 0, []
    module = module_of_model(TARGET_MODELS[profile.target]._meta.label_lower)
    if not active(module):  # 꺼진 모듈(작업지시 → 생산관리)로는 들여오지 않는다(MOD-12)
        return 0, [f'{MODULES[module].name} 모듈이 꺼져 있어 가져올 수 없습니다.'], []
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
                    handler(row)
                count += 1
            except KeyError as e:
                errors.append(f'{line}행: 열 {e} 없음')
            except ValidationError as e:
                errors.append(f'{line}행: {" ".join(e.messages)}')
            except Exception as e:
                errors.append(f'{line}행: {e}')
        if errors or dry_run:
            transaction.set_rollback(True)
    return count, errors, preview


def run_import(profile, uploaded):
    """한 행이라도 틀리면 전체를 되돌린다. (처리 건수, 오류 목록)을 돌려준다."""
    count, errors, _ = _process(profile, uploaded, False)
    return count, errors


def preview_import(profile, uploaded):
    """아무것도 저장하지 않고 run_import 결과를 미리 보여준다."""
    count, errors, rows = _process(profile, uploaded, True)
    return {'count': count, 'errors': errors, 'rows': rows}
