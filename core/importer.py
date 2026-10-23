"""엑셀/CSV 일괄 등록. 열 이름은 ImportProfile.mapping으로 회사마다 다르게 지정한다."""
import csv
import datetime
import io

from django.db import transaction
from openpyxl import load_workbook

from .models import Item, WorkOrder


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
        if any(v not in (None, '') for v in r):
            yield i, dict(zip(header, r))


def _date(v):
    if v in (None, ''):
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return datetime.date.fromisoformat(str(v).strip()[:10])


def _item(row):
    labels = {label: code for code, label in Item.TYPES}
    t = str(row['item_type']).strip()
    item_type = labels.get(t, t)
    if item_type not in dict(Item.TYPES):
        raise ValueError(f'구분 "{t}"은(는) 원자재/반제품/완제품 중 하나여야 합니다')
    Item.objects.update_or_create(code=str(row['code']).strip(), defaults={
        'name': str(row['name']).strip(), 'item_type': item_type})


def _work_order(row):
    WorkOrder.objects.update_or_create(number=str(row['number']).strip(), defaults={
        'item': Item.objects.get(code=str(row['item']).strip()),
        'planned_qty': row['planned_qty'],
        'due_date': _date(row.get('due_date'))})


HANDLERS = {'item': _item, 'work_order': _work_order}


def run_import(profile, uploaded):
    """한 행이라도 틀리면 전체를 되돌린다. (처리 건수, 오류 목록)을 돌려준다."""
    handler, errors, count = HANDLERS[profile.target], [], 0
    with transaction.atomic():
        for line, raw in read_rows(uploaded, profile.header_row):
            try:
                row = {field: raw[col] for field, col in profile.mapping.items()}
                with transaction.atomic():
                    handler(row)
                count += 1
            except KeyError as e:
                errors.append(f'{line}행: 열 {e} 없음')
            except Exception as e:
                errors.append(f'{line}행: {e}')
        if errors:
            transaction.set_rollback(True)
    return count, errors
