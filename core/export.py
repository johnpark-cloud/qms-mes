"""문서 구조(dict)와 표를 A4 .xlsx로 내보낸다. 인쇄 화면(React)도 같은 문서 구조를 쓴다."""
import re
from io import BytesIO

from django.http import HttpResponse
from django.utils.http import content_disposition_header
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, Side

DRAFT_MARK = '초안 — 승인 전'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
REVISION_COLUMNS = ['개정', '변경 내용', '사유', '신청', '승인', '승인일']
_BOLD = Font(bold=True)
_THIN = Side(style='thin')
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _put(ws, row, column, value):
    """사용자가 쓴 글을 안전하게 쓴다: 제어문자 제거, =+-@로 시작하면 수식이 아니라 글로 둔다."""
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub('', value)
    cell = ws.cell(row=row, column=column, value=value)
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@'):
        cell.data_type = 's'
    return cell


def _save(ws, wb, orientation, fit_height=0):
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = orientation
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, fit_height
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _grid(ws, row, columns, rows):
    """머리 줄(굵게) + 데이터 줄에 얇은 테두리. 다음 빈 줄 번호를 돌려준다."""
    for r, values in enumerate([columns] + [list(x) for x in rows]):
        for c, v in enumerate(values, 1):
            cell = _put(ws, row + r, c, v)
            cell.border = _BOX
            cell.alignment = Alignment(wrap_text=True, vertical='top')
            if r == 0:
                cell.font = _BOLD
    return row + len(rows) + 1


def document_xlsx(doc):
    wb = Workbook()
    ws = wb.active
    width = max([6] + [len(t['columns']) for t in doc['tables']])
    _put(ws, 1, 1, doc['title']).font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    row = 2
    if doc['draft']:
        _put(ws, row, 1, DRAFT_MARK).font = Font(bold=True, color='C00000')
        ws.oddHeader.center.text = DRAFT_MARK
        row += 1
    for i in range(0, len(doc['head']), 2):  # 이름 | 값 두 쌍씩 한 줄
        for j, (k, v) in enumerate(doc['head'][i:i + 2]):
            _put(ws, row, 1 + j * 3, k).font = _BOLD
            _put(ws, row, 2 + j * 3, v)
        row += 1
    row += 1
    for t in doc['tables']:
        _put(ws, row, 1, t['title']).font = _BOLD
        row = _grid(ws, row + 1, t['columns'], t['rows']) + 1
    if doc['revisions'] is not None:  # None = 개정 이력이 없는 문서(검사 성적서)
        _put(ws, row, 1, '개정 이력').font = _BOLD
        row = _grid(ws, row + 1, REVISION_COLUMNS, [[r['label'], r['changes'], r['reason'], r['requested_by'], r['approved_by'],
                                                      r['approved_at']] for r in doc['revisions']]) + 1
    s = doc['signoff']
    _grid(ws, row, ['구분', '이름', '일자'], [['작성', s['written_by'], s['written_at']], ['승인', s['approved_by'], s['approved_at']]])
    for col in 'ABCDEF':
        ws.column_dimensions[col].width = 18
    return _save(ws, wb, 'portrait')


def table_xlsx(title, columns, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r'[\[\]:*?/\\]', '_', title)[:31]
    _grid(ws, 1, columns, rows)
    return _save(ws, wb, 'landscape')


def xlsx_response(data, filename):
    resp = HttpResponse(data, content_type=XLSX)
    resp['Content-Disposition'] = content_disposition_header(True, filename)
    return resp
