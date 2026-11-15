"""Browser-compatible form policy plus actual rendered form submission."""
import re
import tempfile
import unittest
from pathlib import Path
from reviewer.database import Database
from reviewer.engine import Engine
from reviewer.web import create_app


class BrowserFormTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/'app.db')
        self.app=create_app(self.db,Engine(self.db,None,None))
        self.app.testing=True
        self.client=self.app.test_client()
        self.base='http://127.0.0.1:8765'
    def tearDown(self): self.tmp.cleanup()
    def form(self):
        page=self.client.get('/',base_url=self.base)
        token=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
        return page,{'csrf':token,'name':'Demo hardware','model':'llama3.2:3b'}
    def test_policy_preserves_browser_origin_for_same_origin_forms(self):
        page,_=self.form()
        # Fetch's append-Origin algorithm uses null for no-referrer form posts.
        self.assertEqual(page.headers['Referrer-Policy'],'same-origin')
    def test_rendered_form_saves_with_real_same_origin_header(self):
        _,data=self.form()
        response=self.client.post('/business',base_url=self.base,data=data,headers={'Origin':self.base})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.db.businesses()[0]['model'],'llama3.2:3b')
    def test_opaque_and_foreign_origins_still_blocked(self):
        _,data=self.form()
        for origin in ('null','https://attacker.example','http://127.0.0.1:9999'):
            with self.subTest(origin=origin):
                self.assertEqual(self.client.post('/business',base_url=self.base,data=data,headers={'Origin':origin}).status_code,403)
        self.assertEqual(self.db.businesses(),[])
    def test_missing_csrf_still_blocked_for_local_origin(self):
        self.form()
        response=self.client.post('/business',base_url=self.base,data={'name':'No token'},headers={'Origin':self.base})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.db.businesses(),[])

if __name__=='__main__': unittest.main()
