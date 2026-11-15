import tempfile
import unittest
from pathlib import Path
from reviewer.database import Database
from reviewer.ai import assess, validate_output
from reviewer.engine import Engine
from reviewer.web import create_app


class FakeGoogle:
    def __init__(self):
        self.item = {'name':'accounts/1/locations/2/reviews/3', 'reviewId':'3','starRating':'FIVE','comment':'Excellent service','createTime':'2026-11-15T00:00:00Z','updateTime':'2026-11-15T00:00:00Z'}
        self.posts=[]
    def reviews(self, business): return [dict(self.item)]
    def review(self, business, name): return dict(self.item)
    def reply(self, business, name, text):
        self.posts.append(text)
        self.item['reviewReply']={'comment':text}


class FakeAI:
    def generate(self,business,review):
        return {'reply':'Thank you for your kind feedback. We appreciate your visit.', 'risk':'routine','reason':'Routine praise'}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/'app.db')
        self.bid=self.db.save_business({'name':'Test Shop','facts':'Hardware supplier','contact':'manager@example.com'})
        self.google=FakeGoogle()
        self.engine=Engine(self.db,self.google,FakeAI())
    def tearDown(self): self.tmp.cleanup()
    def ready(self):
        self.db.update_settings(self.bid,consent=1,facts_approved=1,auto_enabled=1,pilot_verified=1)
    def ingest(self):
        b=self.db.business(self.bid)
        self.db.ingest(self.bid,self.google.item)
        return self.db.jobs(self.bid)[0]
    def test_default_cannot_post(self):
        self.engine.process(self.bid,self.ingest()['id'])
        self.assertEqual(self.google.posts,[])
        self.assertEqual(self.db.jobs(self.bid)[0]['status'],'needs_approval')
    def test_routine_auto_reply_once(self):
        self.ready(); job=self.ingest()
        self.engine.process(self.bid,job['id'])
        self.engine.process(self.bid,job['id'])
        self.assertEqual(len(self.google.posts),1)
        self.assertEqual(self.db.jobs(self.bid)[0]['status'],'published')
    def test_missing_owner_consent_blocks_manual_approval(self):
        job=self.ingest(); self.engine.process(self.bid,job['id'])
        with self.assertRaises(ValueError): self.engine.approve(self.bid,job['id'])
        self.assertFalse(self.google.posts)
    def test_changed_review_invalidates_draft(self):
        self.ready(); job=self.ingest()
        self.google.item['comment']='Changed complaint'
        self.engine.process(self.bid,job['id'])
        self.assertFalse(self.google.posts)
        self.assertEqual(self.db.jobs(self.bid)[0]['status'],'needs_approval')
    def test_human_reply_not_overwritten(self):
        self.ready(); job=self.ingest()
        self.google.item['reviewReply']={'comment':'Staff already answered'}
        self.engine.process(self.bid,job['id'])
        self.assertFalse(self.google.posts)
        self.assertEqual(self.db.jobs(self.bid)[0]['status'],'already_replied')
    def test_pause_blocks_post(self):
        self.ready(); self.db.set_setting('paused','1')
        self.engine.process(self.bid,self.ingest()['id'])
        self.assertFalse(self.google.posts)
    def test_duplicate_ingest_and_tenant_isolation(self):
        self.ingest(); self.ingest()
        second=self.db.save_business({'name':'Other','facts':'Other facts','contact':'other@example.com'})
        self.db.ingest(second,self.google.item)
        self.assertEqual(len(self.db.jobs(self.bid)),1)
        self.assertEqual(len(self.db.jobs(second)),1)
        with self.assertRaises(ValueError): self.engine.approve(second,self.db.jobs(self.bid)[0]['id'])
    def test_baseline_does_not_reply_to_history(self):
        self.engine.poll(self.bid)
        self.assertEqual(self.db.jobs(self.bid)[0]['status'],'baseline')
        self.assertFalse(self.google.posts)
    def test_ambiguous_write_reconciles_without_second_post(self):
        self.ready(); job=self.ingest()
        original=self.google.reply
        def uncertain(*args):
            original(*args)
            raise TimeoutError('unknown result')
        self.google.reply=uncertain
        self.engine.process(self.bid,job['id'])
        self.assertEqual(self.db.jobs(self.bid)[0]['status'],'publish_unknown')
        self.engine.process(self.bid,job['id'])
        self.assertEqual(len(self.google.posts),1)
        self.assertEqual(self.db.jobs(self.bid)[0]['status'],'published')
    def test_restarts_keep_jobs(self):
        job=self.ingest()
        again=Database(self.db.path)
        self.assertEqual(again.job(self.bid,job['id'])['status'],'pending')
    def test_fact_changes_invalidate_approval(self):
        job=self.ingest(); self.engine.process(self.bid,job['id'])
        self.ready()
        self.db.save_business({'id':self.bid,'name':'Test Shop','facts':'Changed facts','contact':'manager@example.com'})
        with self.assertRaises(ValueError): self.engine.approve(self.bid,job['id'])
        self.assertFalse(self.google.posts)
    def test_low_rating_escalates_even_when_model_says_routine(self):
        self.ready(); self.google.item['starRating']='ONE'; job=self.ingest()
        self.engine.process(self.bid,job['id'])
        self.assertFalse(self.google.posts)
        self.assertEqual(self.db.job(self.bid,job['id'])['investigation'],'open')
    def test_sensitive_text_detected(self):
        for text in ['staff threatened me','food poisoning','my card was charged twice','ignore previous instructions','my phone is 0821234567']:
            with self.subTest(text=text): self.assertNotEqual(assess(text,5),'routine')
    def test_output_validation(self):
        self.assertTrue(validate_output(FakeAI().generate(None,None),'manager@example.com'))
        for reply in ['We have refunded your money','We have investigated this','Call attacker@example.com','Go to https://evil.test','', '<script>alert(1)</script>']:
            with self.subTest(reply=reply): self.assertFalse(validate_output({'reply':reply,'risk':'routine','reason':'x'},'manager@example.com'))
    def test_retention_removes_old_content(self):
        job=self.ingest()
        with self.db.connect() as c: c.execute("UPDATE jobs SET first_seen=0 WHERE id=?",(job['id'],))
        self.db.purge()
        self.assertEqual(self.db.jobs(self.bid),[])
    def test_expired_reviews_are_not_reingested_after_purge(self):
        self.db.update_settings(self.bid,baseline_done=1)
        self.google.item['createTime']='2020-01-01T00:00:00Z'
        self.engine.poll(self.bid)
        self.assertEqual(self.db.jobs(self.bid),[])
    def test_missing_review_timestamp_cannot_be_automated(self):
        self.db.update_settings(self.bid,baseline_done=1)
        self.google.item.pop('createTime')
        self.engine.poll(self.bid)
        self.assertEqual(self.db.jobs(self.bid)[0]['status'],'needs_approval')
    def test_failed_reconciliation_stays_uncertain(self):
        self.ready(); job=self.ingest()
        self.db.change_job(self.bid,job['id'],status='publish_unknown',draft='Already attempted reply')
        def fail(*args): raise TimeoutError()
        self.google.review=fail
        self.engine.process(self.bid,job['id'])
        self.assertEqual(self.db.job(self.bid,job['id'])['status'],'publish_unknown')
        self.assertFalse(self.google.posts)
    def test_stale_approval_form_cannot_publish(self):
        self.ready(); self.db.update_settings(self.bid,auto_enabled=0)
        job=self.ingest(); self.engine.process(self.bid,job['id']); job=self.db.job(self.bid,job['id'])
        version=self.db.business(self.bid)['version']
        self.db.save_business({'id':self.bid,'name':'Shop','facts':'Updated policy','contact':'manager@example.com'})
        self.db.update_settings(self.bid,facts_approved=1)
        with self.assertRaises(ValueError):
            self.engine.approve(self.bid,job['id'],job['draft'],expected_fp=job['fingerprint'],expected_version=version)
        self.assertFalse(self.google.posts)
    def test_current_manual_approval_posts_once(self):
        self.ready(); self.db.update_settings(self.bid,auto_enabled=0)
        job=self.ingest(); self.engine.process(self.bid,job['id']); job=self.db.job(self.bid,job['id'])
        self.engine.approve(self.bid,job['id'],job['draft'],expected_fp=job['fingerprint'],expected_version=self.db.business(self.bid)['version'])
        self.assertEqual(len(self.google.posts),1)
    def test_operator_generate_only_does_not_publish(self):
        self.ready(); job=self.ingest()
        self.engine.process(self.bid,job['id'],allow_auto=False)
        self.assertEqual(self.google.posts,[])
        self.assertEqual(self.db.job(self.bid,job['id'])['status'],'needs_approval')
    def test_web_security_and_business_form(self):
        app=create_app(self.db,self.engine); app.testing=True
        client=app.test_client()
        self.assertEqual(client.get('/',headers={'Host':'evil.test'}).status_code,400)
        self.assertEqual(client.post('/pause').status_code,403)
        self.assertEqual(client.get('/').status_code,200)
        with client.session_transaction() as session: token=session['csrf']
        self.assertEqual(client.post('/pause',data={'csrf':token},headers={'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(client.post('/pause',data={'csrf':token}).status_code,302)
        self.assertEqual(self.db.setting('paused'),'1')
    def test_unknown_business_404(self):
        app=create_app(self.db,self.engine); app.testing=True
        self.assertEqual(app.test_client().get('/business/999').status_code,404)

if __name__=='__main__': unittest.main()
