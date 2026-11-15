import hashlib,json,tempfile,unittest
from pathlib import Path
from tools.update_local import install,FILES

class UpdateTests(unittest.TestCase):
    def fixture(self,base):
        root=base/'app';bundle=base/'bundle';root.mkdir();(root/'reviewer').mkdir();(root/'reviewer/web.py').write_text('# old');(root/'Start.cmd').write_text('old')
        (root/'data').mkdir();(root/'data/app.db').write_bytes(b'PRIVATE')
        manifest={}
        for name in FILES:
            p=bundle/'payload'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'# new\n');manifest[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        (bundle/'manifest.json').write_text(json.dumps(manifest));return root,bundle
    def test_update_preserves_data_and_backs_up_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,bundle=self.fixture(Path(tmp));backup=install(root,bundle)
            self.assertEqual((root/'data/app.db').read_bytes(),b'PRIVATE');self.assertEqual((backup/'Start.cmd').read_text(),'old')
    def test_corrupt_payload_makes_no_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,bundle=self.fixture(Path(tmp));(bundle/'payload/Start.cmd').write_text('corrupt')
            with self.assertRaises(ValueError):install(root,bundle)
            self.assertEqual((root/'Start.cmd').read_text(),'old')
    def test_path_injection_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,bundle=self.fixture(Path(tmp));(bundle/'manifest.json').write_text('{"../escape":"x"}')
            with self.assertRaises(ValueError):install(root,bundle)
    def test_destination_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,bundle=self.fixture(Path(tmp));outside=Path(tmp)/'outside';outside.mkdir();(root/'tests').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError):install(root,bundle)
