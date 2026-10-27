import datetime
import os
import shutil
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

KEEP_DAYS = 30


class Command(BaseCommand):
    help = 'DB와 첨부파일을 백업 폴더(예: 회사 NAS)에 복사하고 30일이 지난 백업을 지운다.'

    def add_arguments(self, parser):
        parser.add_argument('dest', nargs='?', default=os.environ.get('QMS_BACKUP_DIR'),
                            help=r'백업 폴더. 예: \\NAS\quality\qms-backup (없으면 환경변수 QMS_BACKUP_DIR)')

    def handle(self, dest, **opts):
        if not dest:
            raise CommandError('백업 폴더를 인자나 QMS_BACKUP_DIR로 지정하세요.')
        db = settings.DATABASES['default']
        if db['ENGINE'] != 'django.db.backends.sqlite3':
            raise CommandError('PostgreSQL은 pg_dump로 백업합니다. README의 2단계 안내를 보세요.')
        root = Path(dest)
        target = root / f'qms-{datetime.datetime.now():%Y%m%d-%H%M%S}'
        target.mkdir(parents=True)
        # 사용 중인 DB도 일관된 사본을 얻기 위해 파일 복사 대신 SQLite 백업 API를 쓴다
        src, out = sqlite3.connect(db['NAME']), sqlite3.connect(target / 'db.sqlite3')
        with out:
            src.backup(out)
        src.close()
        out.close()
        if Path(settings.MEDIA_ROOT).exists():
            shutil.copytree(settings.MEDIA_ROOT, target / 'media')
        private = Path(settings.DATA_DIR) / 'private'  # 개인 급여 파일 (personal.models.private_storage)
        if private.exists():
            shutil.copytree(private, target / 'private')
        cutoff = datetime.datetime.now() - datetime.timedelta(days=KEEP_DAYS)
        for old in root.glob('qms-*'):
            try:
                if datetime.datetime.strptime(old.name[4:], '%Y%m%d-%H%M%S') < cutoff:
                    shutil.rmtree(old)
            except ValueError:
                continue  # 이름 형식이 다른 폴더는 건드리지 않는다
        self.stdout.write(self.style.SUCCESS(f'백업 완료: {target}'))
