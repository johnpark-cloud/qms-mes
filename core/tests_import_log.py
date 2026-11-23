"""3단계 ④ 원본 파일·들여오기 기록(docs/data-flow.md 7.4절): 확정한 파일을 그대로 보관하고 누가·언제·무엇을·몇 건을 남긴다.
기록과 원본은 대상 기록 열람 권한자(시스템 관리자 포함)만 보고 받는다. 영구 보관."""
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import ImportLog, ImportProfile, Item
from core.tests_modules import force_off

CSV = '품번,품명,구분\nN1,새 품목,원자재\n'.encode('utf-8-sig')
LIST = '/api/core/import/logs/'


def temp_imports(test):
    """원본 보관 폴더를 테스트마다 임시 폴더로 바꾼다(data/imports를 건드리지 않게)."""
    tmp = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, tmp, True)
    test.enterContext(override_settings(IMPORT_DIR=tmp))
    return tmp


class ImportLogTest(TestCase):
    def setUp(self):
        self.dir = temp_imports(self)
        self.root = User.objects.create_superuser('root', password='pw')
        self.client = APIClient()
        self.client.force_login(self.root)

    def post(self, commit='1', body=CSV, name='품목 등록.csv'):
        return self.client.post('/api/core/import/', {'target': 'item', 'file': SimpleUploadedFile(name, body),
                                                      'commit': commit}, format='multipart')

    def download(self, log, client=None):
        r = (client or self.client).get(f'{LIST}{log.pk}/file/')
        return r, (b''.join(r.streaming_content) if r.status_code == 200 else b'')

    def test_confirm_keeps_original_and_log(self):
        self.assertEqual(self.post('0').json()['errors'], [])
        self.assertFalse(ImportLog.objects.exists())  # 미리보기는 남기지 않는다
        self.assertEqual(self.post(body='품번,품명,구분\nN1,새 품목,없는구분\n'.encode()).status_code, 200)
        self.assertFalse(ImportLog.objects.exists())  # 오류가 있어 하나도 등록하지 않았으면 남기지 않는다
        self.assertEqual(self.post().json(), {'count': 1, 'errors': []})
        log = ImportLog.objects.get()
        self.assertEqual((log.target, log.label, log.file_name, log.count, log.user), ('core.item', '품목', '품목 등록.csv', 1, self.root))
        self.assertTrue(Path(log.file.path).is_relative_to(self.dir))  # QMS_IMPORT_DIR 아래에 보관
        r, body = self.download(log)
        self.assertEqual(body, CSV)  # 올린 파일 그대로
        self.assertIn('attachment', r['Content-Disposition'])
        row = self.client.get(LIST).json()[0]
        self.assertEqual((row['label'], row['file_name'], row['count'], row['user']), ('품목', '품목 등록.csv', 1, 'root'))
        self.assertEqual(row['url'], f'{LIST}{log.pk}/file/')

    def test_profile_and_old_screen_also_log(self):
        p = ImportProfile.objects.create(name='품번 설정', target='item',
                                         mapping={'code': '품번', 'name': '품명', 'item_type': '구분'})
        self.client.post('/api/core/import/', {'profile': p.pk, 'file': SimpleUploadedFile('a.csv', CSV), 'commit': '1'},
                         format='multipart')
        self.client.post('/import/', {'profile': p.pk, 'file': SimpleUploadedFile('b.csv', CSV.replace(b'N1', b'N2'))})
        self.assertEqual(list(ImportLog.objects.order_by('pk').values_list('file_name', 'profile')),
                         [('a.csv', '품번 설정'), ('b.csv', '품번 설정')])
        self.assertEqual(Item.objects.count(), 2)

    def test_only_target_viewers_see_log_and_file(self):
        self.post()
        log = ImportLog.objects.get()
        other = APIClient()
        nobody = User.objects.create_user('nobody', is_staff=True)
        other.force_login(nobody)
        self.assertEqual(other.get(LIST).json(), [])
        self.assertEqual(self.download(log, other)[0].status_code, 403)
        nobody.user_permissions.add(Permission.objects.get(codename='view_item'))
        nobody = User.objects.get(pk=nobody.pk)  # 권한 캐시를 비운다
        other.force_login(nobody)
        self.assertEqual([r['id'] for r in other.get(LIST).json()], [log.pk])
        self.assertEqual(self.download(log, other)[1], CSV)
        self.assertEqual(self.client.get(f'{LIST}999/file/').status_code, 404)
        self.assertIn(APIClient().get(f'{LIST}{log.pk}/file/').status_code, (401, 403))

    def test_off_module_logs_hidden(self):
        log = ImportLog.objects.create(target='qms.inspection', label='측정 원자료(검사 판정)', file_name='m.csv', count=1,
                                       file=SimpleUploadedFile('m.csv', b'x'))
        self.assertEqual(len(self.client.get(LIST).json()), 1)
        force_off('qms_inspection')
        self.assertEqual(self.client.get(LIST).json(), [])
        self.assertEqual(self.download(log)[0].status_code, 404)

    def test_backup_copies_originals(self):
        self.post()
        live, dest = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, live, True)
        self.addCleanup(shutil.rmtree, dest, True)
        db = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': live / 'x.sqlite3'}}
        with override_settings(DATABASES=db, DATA_DIR=live, MEDIA_ROOT=live / 'media'):
            call_command('backup', str(dest))
        backup = next(dest.iterdir())
        self.assertEqual([p.read_bytes() for p in (backup / 'imports').rglob('*.csv')], [CSV])
