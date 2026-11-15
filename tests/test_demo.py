import tempfile
import unittest
from pathlib import Path
from reviewer.database import Database
from reviewer.demo import generate_demo
from reviewer.engine import Engine
from reviewer.web import create_app


class NoGoogle:
    def __getattr__(self,name): raise AssertionError('Demo must never access Google')


class AI:
    def __init__(self): self.calls=[]
    def generate(self,business,review):
        self.calls.append((business['name'],review))
        return {'reply':'Thank you for your feedback. We appreciate you sharing your experience.','risk':'routine','reason':'Customer feedback'}


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=Database(Path(self.tmp.name)/'app.db')
        self.bid=self.db.save_business({'name':'Demo shop','facts':'Tools and paint','contact':'support@example.com','model':'llama3.2:3b'})
        self.db.update_settings(self.bid,facts_approved=1)
        self.ai=AI(); self.engine=Engine(self.db,NoGoogle(),self.ai)
        self.app=create_app(self.db,self.engine); self.app.testing=True; self.client=self.app.test_client()
    def tearDown(self): self.tmp.cleanup()
    def post(self,**values):
        self.client.get('/business/'+str(self.bid)+'/demo')
        with self.client.session_transaction() as s: token=s['csrf']
        return self.client.post('/business/'+str(self.bid)+'/demo',data={'csrf':token,**values})
    def test_praise_uses_real_generation_interface_without_google_or_consent(self):
        result=generate_demo(self.db.business(self.bid),self.ai,'Excellent friendly service',5)
        self.assertEqual(result['risk'],'routine'); self.assertTrue(result['reply'])
        self.assertEqual(len(self.ai.calls),1)
    def test_complaint_cannot_be_downgraded_by_model(self):
        result=generate_demo(self.db.business(self.bid),self.ai,'The staff were rude and I waited ages',2)
        self.assertEqual(result['risk'],'complaint')
    def test_sensitive_review_held_without_model_call(self):
        result=generate_demo(self.db.business(self.bid),self.ai,'Staff threatened me',1)
        self.assertEqual(result['risk'],'sensitive'); self.assertEqual(result['reply'],''); self.assertFalse(self.ai.calls)
    def test_invalid_model_output_not_shown_as_approved(self):
        class BadAI:
            def generate(self,*args): return {'reply':'We have refunded your money','risk':'routine','reason':'Fine'}
        result=generate_demo(self.db.business(self.bid),BadAI(),'Excellent service',5)
        self.assertEqual(result['status'],'blocked'); self.assertEqual(result['reply'],'')
    def test_requires_approved_facts(self):
        self.db.update_settings(self.bid,facts_approved=0)
        with self.assertRaises(ValueError): generate_demo(self.db.business(self.bid),self.ai,'Good',5)
    def test_invalid_rating_and_too_long_review_rejected(self):
        for text,rating in [('Review',0),('Review',6),('Review',True),('x'*6001,5)]:
            with self.subTest(rating=rating),self.assertRaises(ValueError): generate_demo(self.db.business(self.bid),self.ai,text,rating)
    def test_empty_text_rating_only_is_supported(self):
        result=generate_demo(self.db.business(self.bid),self.ai,'',5)
        self.assertEqual(result['risk'],'routine')
    def test_panel_link_and_custom_review_flow(self):
        page=self.client.get('/business/'+str(self.bid))
        self.assertIn(b'Test local AI',page.data)
        response=self.post(review='Lovely helpful staff',rating='5')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Nothing is posted to Google',response.data)
        self.assertIn(b'Thank you for your feedback',response.data)
        self.assertEqual(self.db.jobs(self.bid),[])
        self.assertEqual(self.db.business(self.bid)['consent'],0)
    def test_preset_flow(self):
        self.assertEqual(self.post(preset='praise').status_code,200)
        self.assertEqual(len(self.ai.calls),1)
    def test_google_jobs_alerts_and_reports_untouched_even_when_live_flags_enabled(self):
        self.db.update_settings(self.bid,consent=1,auto_enabled=1,pilot_verified=1)
        self.post(review='Good shop',rating='5')
        self.assertEqual(self.db.jobs(self.bid),[])
        with self.db.connect() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
    def test_demo_requires_csrf(self):
        self.assertEqual(self.client.post('/business/'+str(self.bid)+'/demo',data={'review':'Hi','rating':'5'}).status_code,403)
    def test_generation_failure_is_actionable_and_does_not_leak_details(self):
        class Failure:
            def generate(self,*args): raise ConnectionError('SECRET_INTERNAL_DETAIL')
        self.engine.ai=Failure()
        r=self.post(review='Great shop',rating='5')
        self.assertEqual(r.status_code,503)
        self.assertIn(b'Ollama',r.data); self.assertNotIn(b'SECRET_INTERNAL_DETAIL',r.data)

if __name__=='__main__': unittest.main()
