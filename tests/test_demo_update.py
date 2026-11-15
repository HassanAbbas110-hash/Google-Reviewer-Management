import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('install_demo_update',Path(__file__).resolve().parents[1]/'tools/install_demo_update.py')
installer=importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)


class UpdateTests(unittest.TestCase):
    def setup_bundle(self,root,bundle):
        (root/'reviewer').mkdir(); (root/'reviewer/web.py').write_text('old code')
        (root/'Start.cmd').write_text('start')
        (root/'data').mkdir(); (root/'data/reviews.db').write_bytes(b'PRIVATE DATA')
        manifest={}
        for name in installer.FILES:
            content=b'# valid python\n' if name.endswith('.py') else b'new template'
            p=bundle/'payload'/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(content)
            manifest[name]=hashlib.sha256(content).hexdigest()
        (bundle/'manifest.json').write_text(json.dumps(manifest))
    def test_installer_preserves_database_and_backs_up_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project'; root.mkdir(); bundle=Path(tmp)/'bundle'
            self.setup_bundle(root,bundle)
            backup=installer.install(root,bundle)
            self.assertEqual((root/'data/reviews.db').read_bytes(),b'PRIVATE DATA')
            self.assertEqual((backup/'reviewer/web.py').read_text(),'old code')
            self.assertEqual((root/'reviewer/web.py').read_text(),'# valid python\n')
    def test_corrupt_bundle_cannot_partially_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project'; root.mkdir(); bundle=Path(tmp)/'bundle'
            self.setup_bundle(root,bundle)
            (bundle/'payload/reviewer/demo.py').write_text('tampered')
            with self.assertRaises(ValueError): installer.install(root,bundle)
            self.assertEqual((root/'reviewer/web.py').read_text(),'old code')

if __name__=='__main__': unittest.main()
