import datetime
import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

TABLES = ['core_lot', 'core_nonconformance', 'qms_inspection', 'qms_customerclaim', 'qms_documentrevision']


class Command(BaseCommand):
    help = '백업 폴더를 점검한다(리허설). --apply를 주면 현재 데이터를 따로 보관한 뒤 실제로 복원한다.'

    def add_arguments(self, parser):
        parser.add_argument('backup', help=r'backup 명령이 만든 폴더. 예: \\NAS\quality\qms-backup\qms-20261026-180000')
        parser.add_argument('--apply', action='store_true', help='실제로 복원 (서버를 먼저 끄세요)')

    def handle(self, backup, apply, **opts):
        db = settings.DATABASES['default']
        if db['ENGINE'] != 'django.db.backends.sqlite3':
            raise CommandError('PostgreSQL은 pg_restore로 복원합니다.')
        src = Path(backup)
        if not (src / 'db.sqlite3').exists():
            raise CommandError(f'{src}에 db.sqlite3가 없습니다.')

        # 백업 원본을 건드리지 않도록 임시 사본으로 점검한다
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'db.sqlite3'
            shutil.copy2(src / 'db.sqlite3', copy)
            con = sqlite3.connect(copy)
            try:
                status = con.execute('PRAGMA integrity_check').fetchone()[0]
                counts = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in TABLES}
            except sqlite3.DatabaseError as e:
                raise CommandError(f'백업 DB를 읽을 수 없습니다: {e}')
            finally:
                con.close()
        if status != 'ok':
            raise CommandError(f'무결성 검사 실패: {status}')
        self.stdout.write(f'무결성 검사: ok, 첨부파일 폴더: {"있음" if (src / "media").exists() else "없음"}, 개인 파일 폴더: {"있음" if (src / "private").exists() else "없음"}, '
                          f'첨부 보관 폴더: {"있음" if (src / "attachments").exists() else "없음"}')
        for t, n in counts.items():
            self.stdout.write(f'  {t}: {n}건')
        if not apply:
            self.stdout.write(self.style.SUCCESS('리허설 통과. 실제 복원은 --apply를 붙여 실행하세요.'))
            return

        # 복원 전에 지금 데이터를 보관한다 (잘못 복원해도 되돌릴 수 있게)
        keep = Path(settings.DATA_DIR) / f'pre-restore-{datetime.datetime.now():%Y%m%d-%H%M%S}'
        keep.mkdir()
        current, media = Path(db['NAME']), Path(settings.MEDIA_ROOT)
        if current.exists():
            shutil.copy2(current, keep / 'db.sqlite3')
        if media.exists():
            shutil.move(media, keep / 'media')
        for name in ('private', 'attachments'):
            folder = Path(settings.DATA_DIR) / name
            if (src / name).exists() and folder.exists():  # 옛 백업(그 폴더 없음)이면 현재 파일을 그대로 둔다
                shutil.move(folder, keep / name)
        shutil.copy2(src / 'db.sqlite3', current)
        if (src / 'media').exists():
            shutil.copytree(src / 'media', media)
        for name in ('private', 'attachments'):
            if (src / name).exists():
                shutil.copytree(src / name, Path(settings.DATA_DIR) / name)
        self.stdout.write(self.style.SUCCESS(f'복원 완료. 이전 데이터는 {keep}에 보관했습니다.'))
