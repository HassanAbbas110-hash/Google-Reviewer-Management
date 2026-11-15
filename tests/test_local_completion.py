import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from reviewer.ai import validate_output,Ollama
from reviewer.database import Database
from reviewer.engine import Engine
from reviewer.lab import LocalLab
from reviewer.web import create_app

class CompletionTests(unittest.TestCase):
    def output(self,text):return {'reply':text,'risk':'complaint','reason':'Reported concern'}
    def test_unapproved_parking_help_offer_is_blocked(self):
        self.assertFalse(validate_output(self.output('Glad the advice helped! Sorry parking was tricky—let us know if you need help finding a spot.'),'',{'comment':'Parking was difficult','rating':4}))
    def test_dismissive_felt_language_is_blocked(self):
        self.assertFalse(validate_output(self.output("I'm sorry you had a long wait and felt the staff was rude. Please contact support@example.com."),'support@example.com',{'comment':'Staff were rude','rating':2}))
    def test_service_complaint_is_not_redirected_to_paint_questions(self):
        self.assertFalse(validate_output(self.output('Sorry about the wait. Please contact support@example.com for help with paint questions.'),'support@example.com',{'comment':'Staff were rude when I asked about paint','rating':2}))
    def test_investigation_contact_is_allowed(self):
        text='Sorry to hear about the wait and your concerns about the service. Please email support@example.com so the team can look into what happened.'
        self.assertTrue(validate_output(self.output(text),'support@example.com',{'comment':'Staff were rude','rating':2}))
    def test_model_schema_limits_internal_explanation(self):
        ai=Ollama();captured={}
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'message':{'content':'{"risk":"routine","reason":"Praise","reply":"Glad we could help!"}'}}
        def post(*args,**kwargs):captured.update(kwargs['json']);return Response()
        b=dict(name='Shop',facts='Tools',contact='',tone='Warm',language='English',model='qwen3:4b')
        with patch.object(ai,'models',return_value=['qwen3:4b']),patch.object(ai.session,'post',side_effect=post):ai.generate(b,{'comment':'Great','rating':5})
        self.assertLessEqual(captured['format']['properties']['reason']['maxLength'],180)
        self.assertLessEqual(captured['options']['num_predict'],300)
    def test_resume_does_not_repeat_completed_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db');bid=db.save_business(dict(name='Shop',model='test'));db.update_settings(bid,facts_approved=1)
            class AI:
                calls=0
                def generate(self,*args):self.calls+=1;return {'risk':'routine','reason':'Praise','reply':'Glad we could help!'}
            ai=AI();engine=Engine(db,None,ai);lab=LocalLab(db,engine)
            cases=[dict(id='one',text='Great',rating=5,expected='routine'),dict(id='two',text='Helpful',rating=5,expected='routine')]
            rid=lab.submit(bid,cases)
            first={**cases[0],'status':'draft','risk':'routine','reply':'Saved reply','reason':'Praise','elapsed':1,'route_match':True}
            with db.connect() as c:c.execute("UPDATE lab_runs SET status='running',completed=1,results=? WHERE id=?",(json.dumps([first]),rid))
            lab=LocalLab(db,engine);lab.resume(bid,rid);lab.tick()
            run=lab.get(bid,rid);self.assertEqual(ai.calls,1);self.assertEqual(run['completed'],2);self.assertEqual(run['results'][0]['reply'],'Saved reply')
    def test_failed_alert_can_be_requeued_without_marking_investigation_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db');bid=db.save_business({'name':'Shop'})
            jid=db.ingest(bid,{'name':'accounts/a/locations/b/reviews/c'})
            db.change_job(bid,jid,investigation='open',alert_state='failed',alert_attempts=3)
            app=create_app(db,Engine(db,None,None));app.testing=True;c=app.test_client();c.get('/')
            with c.session_transaction() as s:token=s['csrf']
            r=c.post(f'/business/{bid}/job/{jid}/retry-alert',data={'csrf':token})
            self.assertEqual(r.status_code,302)
            job=db.job(bid,jid);self.assertEqual(job['alert_attempts'],0);self.assertEqual(job['alert_state'],'pending');self.assertEqual(job['investigation'],'open')

    def test_stale_retry_form_does_not_requeue_sent_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db');bid=db.save_business({'name':'Shop'})
            jid=db.ingest(bid,{'name':'accounts/a/locations/b/reviews/c'})
            db.change_job(bid,jid,investigation='open',alert_state='sent',alert_attempts=1)
            app=create_app(db,Engine(db,None,None));c=app.test_client();c.get('/')
            with c.session_transaction() as session:token=session['csrf']
            c.post(f'/business/{bid}/job/{jid}/retry-alert',data={'csrf':token})
            self.assertEqual(db.job(bid,jid)['alert_state'],'sent')
    def test_fact_change_waiting_for_lock_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db');bid=db.save_business({'name':'Shop','model':'test'});db.update_settings(bid,facts_approved=1)
            engine=Engine(db,None,None);lab=LocalLab(db,engine)
            rid=lab.submit(bid,[dict(text='Great',rating=5)])
            class MutatingLock:
                def __enter__(self):db.save_business({'id':bid,'name':'Changed'})
                def __exit__(self,*args):pass
            engine.lock=MutatingLock();lab.tick();run=lab.get(bid,rid)
            self.assertEqual(run['status'],'interrupted');self.assertEqual(run['completed'],0)

if __name__=='__main__':unittest.main()

class DiagnosticTests(unittest.TestCase):
    def test_observed_apology_confirms_rude_service(self):
        out={'risk':'complaint','reason':'Wait and service','reply':'We apologize for the long wait and rude service. Please contact support@example.com for help.'}
        self.assertFalse(validate_output(out,'support@example.com',{'comment':'Staff were rude','rating':2}))
    def test_reported_concern_is_allowed(self):
        out={'risk':'complaint','reason':'Service concern','reply':'Sorry to hear about your concerns about rude service. Please email support@example.com so the team can look into what happened.'}
        self.assertTrue(validate_output(out,'support@example.com',{'comment':'Staff were rude','rating':2}))
    def test_parking_rejection_has_specific_safe_diagnostic(self):
        from reviewer.demo import generate_demo
        class AI:
            def generate(self,*args):return {'risk':'complaint','reason':'Parking concern','reply':'Glad the advice helped! Thanks for visiting.'}
        result=generate_demo({'facts_approved':1,'model':'test','contact':''},AI(),'Parking was difficult.',4)
        self.assertIn('parking',result['reason'].lower());self.assertEqual(result['reply'],'');self.assertEqual(result['status'],'blocked')

class ConversationTests(unittest.TestCase):
    def check(self,source,rating,reply):
        return validate_output({'risk':'complaint','reason':'Concern','reply':reply},'support@example.com',{'comment':source,'rating':rating})
    def test_unaddressed_complaint_cannot_receive_praise(self):
        self.assertFalse(self.check('No complaints were addressed by the shop.',5,'Thanks for the 5-star rating! We appreciate your positive feedback.'))
    def test_claim_of_business_observation_is_blocked(self):
        self.assertFalse(self.check('Checkout was slow.',5,'We noticed checkout was slow—let us know how we can improve.'))
    def test_low_rating_needs_useful_handoff(self):
        self.assertFalse(self.check('',1,'Thanks for the one-star rating. We appreciate your feedback.'))
    def test_wait_complaint_cannot_omit_wait(self):
        self.assertFalse(self.check('I waited half an hour and staff were rude.',2,'Sorry about your experience with staff. Please email support@example.com so the team can look into it.'))
    def test_generic_assistance_is_not_investigation_handoff(self):
        self.assertFalse(self.check('The drill stopped working.',2,'Sorry the drill stopped working. Please contact support@example.com for assistance.'))
    def test_grounded_handoff_passes(self):
        self.assertTrue(self.check('The drill stopped working.',2,'Sorry to hear the drill stopped working. Please email support@example.com so the team can look into the problem.'))
    def test_awkward_observed_fragment_is_blocked(self):
        self.assertFalse(self.check('Friendly people and tidy shop.',5,'Great to hear our friendly team and clean shop!'))
