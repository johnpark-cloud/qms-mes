import datetime
import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from .backup import is_sqlite, run_pg

TABLES = ['core_lot', 'core_nonconformance', 'qms_inspection', 'qms_customerclaim', 'qms_documentrevision']


def _pg(db, dbname):
    import psycopg  # PostgreSQL을 쓸 때만 필요
    return psycopg.connect(host=db.get('HOST') or 'localhost', port=db.get('PORT') or 5432, user=db['USER'],
                           password=db.get('PASSWORD') or '', dbname=dbname, autocommit=True)


class Command(BaseCommand):
    help = '백업 폴더를 점검한다(리허설). --apply를 주면 현재 데이터를 따로 보관한 뒤 실제로 복원한다.'

    def add_arguments(self, parser):
        parser.add_argument('backup', help=r'backup 명령이 만든 폴더. 예: \\NAS\quality\qms-backup\qms-20261026-180000')
        parser.add_argument('--apply', action='store_true', help='실제로 복원 (서버를 먼저 끄세요)')

    def handle(self, backup, apply, **opts):
        db = settings.DATABASES['default']
        src = Path(backup)
        dump = src / ('db.sqlite3' if is_sqlite(db) else 'db.dump')
        if not dump.exists():
            raise CommandError(f'{src}에 {dump.name}가 없습니다.')

        counts = self._check_sqlite(dump) if is_sqlite(db) else self._check_pg(db, dump)
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
        media = Path(settings.MEDIA_ROOT)
        if is_sqlite(db):
            current = Path(db['NAME'])
            if current.exists():
                shutil.copy2(current, keep / 'db.sqlite3')
        else:
            run_pg('pg_dump', db, '-Fc', '-f', str(keep / 'db.dump'), db['NAME'])
        if media.exists():
            shutil.move(media, keep / 'media')
        for name in ('private', 'attachments'):
            folder = Path(settings.DATA_DIR) / name
            if (src / name).exists() and folder.exists():  # 옛 백업(그 폴더 없음)이면 현재 파일을 그대로 둔다
                shutil.move(folder, keep / name)
        if is_sqlite(db):
            shutil.copy2(dump, current)
        else:  # 한 트랜잭션: 중간에 실패하면 현재 DB가 그대로 남는다
            run_pg('pg_restore', db, '--clean', '--if-exists', '--no-owner', '--single-transaction', '-d', db['NAME'], str(dump))
        if (src / 'media').exists():
            shutil.copytree(src / 'media', media)
        for name in ('private', 'attachments'):
            if (src / name).exists():
                shutil.copytree(src / name, Path(settings.DATA_DIR) / name)
        self.stdout.write(self.style.SUCCESS(f'복원 완료. 이전 데이터는 {keep}에 보관했습니다.'))

    def _check_sqlite(self, dump):
        # 백업 원본을 건드리지 않도록 임시 사본으로 점검한다
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'db.sqlite3'
            shutil.copy2(dump, copy)
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
        return counts

    def _check_pg(self, db, dump):
        """임시 DB에 실제로 복원해 보고 행 수를 센 뒤 지운다. 운영 DB는 건드리지 않는다."""
        tmp = f'{db["NAME"]}_restore_check'
        with _pg(db, 'postgres') as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{tmp}" WITH (FORCE)')
            admin.execute(f'CREATE DATABASE "{tmp}"')
            try:
                run_pg('pg_restore', db, '--no-owner', '--exit-on-error', '-d', tmp, str(dump))
                with _pg(db, tmp) as con:
                    return {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in TABLES}
            except Exception as e:
                raise CommandError(f'백업을 복원해 볼 수 없습니다: {e}')
            finally:
                admin.execute(f'DROP DATABASE IF EXISTS "{tmp}" WITH (FORCE)')
