import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.upload_storage import UploadPath, object_key, delete_folder

class CloudUploadsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'UPLOAD_STORAGE':'supabase','STORAGE_ROOT':str(self.root)})
        self.env.start()
        self.objects={}
        def remote(method,suffix,data=None,content_type=None,missing_ok=False):
            if suffix.startswith('object/list/'):
                prefix=json.loads(data)['prefix'].rstrip('/')+'/'
                return json.dumps([{'name':k[len(prefix):],'id':'file'} for k in self.objects if k.startswith(prefix) and '/' not in k[len(prefix):]]).encode()
            if method=='DELETE':
                for key in json.loads(data)['prefixes']:self.objects.pop(key,None)
                return b'[]'
            key=suffix.split('/',2)[2]
            if method=='POST':self.objects[key]=bytes(data);return b'{}'
            if method=='GET':return self.objects.get(key)
        self.mock=patch('backend.upload_storage.call',side_effect=remote);self.mock.start()
    def tearDown(self):
        self.mock.stop();self.env.stop();self.temp.cleanup()
    def path(self,name):
        p=UploadPath(self.root/'uploads'/name);p.parent.mkdir(parents=True,exist_ok=True);return p
    def test_files_survive_disposable_cache_loss(self):
        p=self.path('cvs/private.pdf');p.write_bytes(b'private cv')
        Path(p).unlink()
        self.assertTrue(p.is_file());self.assertEqual(p.read_bytes(),b'private cv')
        p.unlink(missing_ok=True);self.assertFalse(p.is_file())
    def test_gallery_listing_and_selection_survive_restart(self):
        p=self.path('portraits/user1/abc.json');p.write_text('{"style":"Free"}')
        Path(p).unlink();Path(p.parent).rmdir()
        self.assertTrue(p.parent.exists())
        self.assertEqual([x.name for x in p.parent.glob('*.json')],['abc.json'])
        self.assertEqual(p.read_text(),'{"style":"Free"}')
    def test_temp_files_and_non_upload_files_never_leave_server(self):
        for name in ['portraits/user1/.generating','portraits/user1/selection.json.token.tmp']:
            p=self.path(name);p.write_text('local only');self.assertIsNone(object_key(p))
        p=UploadPath(self.root/'outside.txt');p.write_text('outside');self.assertIsNone(object_key(p))
        self.assertEqual(self.objects,{})
    def test_atomic_metadata_persists_only_final_path(self):
        temp=self.path('portraits/user1/selection.json.token.tmp');temp.write_text('{"cv_photo_id":"abc"}')
        target=self.path('portraits/user1/selection.json');temp.replace(target)
        self.assertEqual(list(self.objects),['portraits/user1/selection.json'])
        Path(target).unlink();self.assertIn('abc',target.read_text())
    def test_delete_folder_does_not_delete_other_owners(self):
        self.path('portraits/user1/a.jpg').write_bytes(b'one')
        self.path('portraits/user2/b.jpg').write_bytes(b'two')
        delete_folder(self.path('portraits/user1'))
        self.assertEqual(list(self.objects),['portraits/user2/b.jpg'])
    def test_storage_failure_does_not_report_local_save(self):
        p=self.path('cvs/fail.pdf')
        with patch('backend.upload_storage.call',side_effect=OSError('storage unavailable')):
            with self.assertRaises(OSError):p.write_bytes(b'cv')
        self.assertFalse(Path(p).exists())
