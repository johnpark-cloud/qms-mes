"""측정기·설비가 떨어뜨린 CSV를 검사 기록으로 수집한다 (3단계 자동수집의 표준 창구).

CSV 열: lot, type(INCOMING/PROCESS/OUTGOING 또는 수입검사/공정검사/출하검사), characteristic, value
같은 파일 안의 (lot, type) 묶음마다 검사 1건을 만들고 판정한다. 성공한 파일은 done/, 실패한 파일은 error/로 옮긴다.
OPC-UA·PLC·RS-232는 회사마다 작은 어댑터 스크립트가 이 형식의 CSV를 inbox에 쓰게 한다.
"""
import csv
import os
import shutil
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Lot
from qms.models import Inspection, InspectionSpec, Measurement

TYPE_LABELS = {label: code for code, label in InspectionSpec.TYPES}


def ingest(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    groups = {}
    for i, r in enumerate(rows, start=2):
        t = TYPE_LABELS.get(r['type'].strip(), r['type'].strip())
        groups.setdefault((r['lot'].strip(), t), []).append((i, r['characteristic'].strip(), r['value'].strip()))
    made = []
    with transaction.atomic():
        for (lot_no, t), items in groups.items():
            lot = Lot.objects.filter(number=lot_no).first()
            if not lot:
                raise ValueError(f'LOT {lot_no} 없음')
            spec = InspectionSpec.current(lot.item, t)
            if not spec:
                raise ValueError(f'{lot.item.code} {t}: 승인된 검사기준 없음')
            chars = {c.name: c for c in spec.characteristics.all()}
            insp = Inspection.objects.create(lot=lot, spec=spec)
            for line, name, value in items:
                c = chars.get(name)
                if not c:
                    raise ValueError(f'{line}행: 검사항목 "{name}"이(가) {spec}에 없음')
                if c.is_variable:
                    try:
                        number = Decimal(value)
                    except InvalidOperation:
                        number = None
                    if number is None or not number.is_finite():  # NaN·Infinity는 판정을 깨뜨린다
                        raise ValueError(f'{line}행: 숫자가 아님 "{value}"')
                    Measurement.objects.create(inspection=insp, characteristic=c, value=number)
                else:
                    Measurement.objects.create(inspection=insp, characteristic=c, ok=value.upper() in ('OK', '1', 'PASS', '합격'))
            insp.finalize()
            made.append(f'{lot_no} {insp.get_result_display()}')
    return made


class Command(BaseCommand):
    help = 'inbox 폴더의 측정 CSV를 검사 기록으로 수집한다. 작업 스케줄러로 몇 분마다 실행한다.'

    def add_arguments(self, parser):
        parser.add_argument('--inbox', default=os.environ.get('QMS_INBOX_DIR', str(Path(settings.DATA_DIR) / 'inbox')))

    def handle(self, inbox, **opts):
        inbox = Path(inbox)
        for sub in ('done', 'error'):
            (inbox / sub).mkdir(parents=True, exist_ok=True)
        for path in sorted(inbox.glob('*.csv')):
            try:
                made = ingest(path)
                shutil.move(path, inbox / 'done' / path.name)
                self.stdout.write(self.style.SUCCESS(f'{path.name}: {", ".join(made)}'))
            except Exception as e:  # 깨진 파일 하나가 inbox에 남아 뒤 파일까지 막지 않게 모두 error/로 옮긴다
                shutil.move(path, inbox / 'error' / path.name)
                (inbox / 'error' / f'{path.name}.err.txt').write_text(str(e), encoding='utf-8')
                self.stderr.write(f'{path.name}: {e}')
