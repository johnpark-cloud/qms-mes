import datetime
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

KEEP_DAYS = 30
PG_BIN = r'C:\Program Files\PostgreSQL\18\bin'  # Windows 기본 설치 위치


def is_sqlite(db):
    return db['ENGINE'] == 'django.db.backends.sqlite3'


def run_pg(tool, db, *args):
    """pg_dump·pg_restore 실행. 위치는 QMS_PG_BIN → PATH → 기본 설치 폴더 순으로 찾는다."""
    exe = (shutil.which(tool, path=os.environ.get('QMS_PG_BIN')) or shutil.which(tool, path=PG_BIN))
    if not exe:
        raise CommandError(f'{tool}을 찾을 수 없습니다. PostgreSQL bin 폴더를 환경변수 QMS_PG_BIN에 지정하세요.')
    env = {**os.environ, 'PGPASSWORD': db.get('PASSWORD') or ''}
    conn = ['-h', db.get('HOST') or 'localhost', '-p', str(db.get('PORT') or 5432), '-U', db['USER']]
    r = subprocess.run([exe, *conn, *args], env=env, capture_output=True)
    if r.returncode:
        raise CommandError(f'{tool} 실패: {r.stderr.decode("utf-8", "replace").strip()}')


class Command(BaseCommand):
    help = 'DB와 첨부파일을 백업 폴더(예: 회사 NAS)에 복사하고 30일이 지난 백업을 지운다.'

    def add_arguments(self, parser):
        parser.add_argument('dest', nargs='?', default=os.environ.get('QMS_BACKUP_DIR'),
                            help=r'백업 폴더. 예: \\NAS\quality\qms-backup (없으면 환경변수 QMS_BACKUP_DIR)')

    def handle(self, dest, **opts):
        if not dest:
            raise CommandError('백업 폴더를 인자나 QMS_BACKUP_DIR로 지정하세요.')
        db = settings.DATABASES['default']
        root = Path(dest)
        target = root / f'qms-{datetime.datetime.now():%Y%m%d-%H%M%S}'
        target.mkdir(parents=True)
        if is_sqlite(db):
            # 사용 중인 DB도 일관된 사본을 얻기 위해 파일 복사 대신 SQLite 백업 API를 쓴다
            src, out = sqlite3.connect(db['NAME']), sqlite3.connect(target / 'db.sqlite3')
            with out:
                src.backup(out)
            src.close()
            out.close()
        else:  # PostgreSQL: pg_dump는 사용 중에도 한 시점의 일관된 사본을 만든다
            try:
                run_pg('pg_dump', db, '-Fc', '-f', str(target / 'db.dump'), db['NAME'])
            except CommandError:
                shutil.rmtree(target)  # 반쯤 만든 폴더를 백업으로 착각하지 않게
                raise
        if Path(settings.MEDIA_ROOT).exists():
            shutil.copytree(settings.MEDIA_ROOT, target / 'media')
        # private: 개인 급여 파일(personal.models.private_storage), attachments: 업무 첨부(core.models.attachment_storage)
        for name in ('private', 'attachments'):
            folder = Path(settings.DATA_DIR) / name
            if folder.exists():
                shutil.copytree(folder, target / name)
        cutoff = datetime.datetime.now() - datetime.timedelta(days=KEEP_DAYS)
        for old in root.glob('qms-*'):
            try:
                if datetime.datetime.strptime(old.name[4:], '%Y%m%d-%H%M%S') < cutoff:
                    shutil.rmtree(old)
            except ValueError:
                continue  # 이름 형식이 다른 폴더는 건드리지 않는다
        self.stdout.write(self.style.SUCCESS(f'백업 완료: {target}'))
