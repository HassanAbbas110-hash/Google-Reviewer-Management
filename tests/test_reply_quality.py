import unittest
from unittest.mock import patch
from reviewer.ai import Ollama,validate_output


class ReplyQualityTests(unittest.TestCase):
    def output(self,reply,risk='routine',reason='Customer rating'):
        return {'reply':reply,'risk':risk,'reason':reason}
    def test_rating_only_reply_cannot_invent_specific_experience(self):
        output=self.output("We're glad you enjoyed our products and services.")
        self.assertFalse(validate_output(output,'support@example.com',{'comment':'','rating':5}))
    def test_rating_only_praise_has_no_complaint_contact(self):
        output=self.output('Thank you for the five-star rating. Contact support@example.com with concerns.')
        self.assertFalse(validate_output(output,'support@example.com',{'comment':'','rating':5}))
    def test_rating_only_praise_is_brief(self):
        output=self.output('Thank you for your rating. '+('We appreciate your support. '*10))
        self.assertFalse(validate_output(output,'',{'comment':'','rating':5}))
    def test_short_grounded_rating_only_thanks_allowed(self):
        output=self.output('Thank you for the five-star rating! We appreciate your support.')
        self.assertTrue(validate_output(output,'',{'comment':'','rating':5}))
    def test_complaint_does_not_confirm_alleged_staff_rudeness(self):
        output=self.output('We apologize for the wait time and the rudeness you encountered. Please contact support@example.com.','complaint','Service complaint')
        self.assertFalse(validate_output(output,'support@example.com',{'comment':'The staff were rude','rating':2}))
    def test_latest_rudeness_assertion_is_rejected(self):
        output=self.output('Sorry to hear that you experienced a long wait and were treated rudely by our staff. Please contact support@example.com.','complaint','long wait and rudeness')
        self.assertFalse(validate_output(output,'support@example.com',{'comment':'The staff were rude','rating':2}))
    def test_reported_rudeness_can_be_acknowledged_as_concern(self):
        output=self.output("Sorry to hear about your concerns with the wait and service. Please email support@example.com so the team can look into what happened.",'complaint','Reported service concern')
        self.assertTrue(validate_output(output,'support@example.com',{'comment':'The staff were rude','rating':2}))
    def test_acknowledge_concern_without_confirming_incident(self):
        output=self.output("We're sorry to hear about your concerns regarding the service. Please contact support@example.com so the team can look into what happened.",'complaint','Customer reports service concerns')
        self.assertTrue(validate_output(output,'support@example.com',{'comment':'The staff were rude','rating':2}))
    def test_model_warning_not_silently_downgraded(self):
        from reviewer.demo import generate_demo
        class CautiousAI:
            def generate(self,*args): return {'reply':'Thank you for your feedback. We appreciate your support.','risk':'sensitive','reason':'Uncertain interpretation'}
        result=generate_demo({'facts_approved':1,'model':'local:test','contact':''},CautiousAI(),'Excellent service',5)
        self.assertEqual(result['risk'],'sensitive')
    def test_sensitive_warning_survives_rejected_demo_wording(self):
        from reviewer.demo import generate_demo
        class CautiousAI:
            def generate(self,*args): return {'reply':'We appreciate your experience with our products.','risk':'sensitive','reason':'Potential uncertainty'}
        result=generate_demo({'facts_approved':1,'model':'local:test','contact':''},CautiousAI(),'',5)
        self.assertEqual(result['status'],'held')
        self.assertEqual(result['risk'],'sensitive')
    def test_sensitive_warning_survives_rejected_live_wording(self):
        import tempfile
        from pathlib import Path
        from reviewer.database import Database
        from reviewer.engine import Engine
        class CautiousAI:
            def generate(self,*args): return {'reply':'We appreciate your experience with our products.','risk':'sensitive','reason':'Potential uncertainty'}
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'app.db'); bid=db.save_business({'name':'Shop','model':'local:test'})
            db.update_settings(bid,facts_approved=1)
            jid=db.ingest(bid,{'name':'accounts/a/locations/b/reviews/c','starRating':'FIVE','comment':''})
            Engine(db,None,CautiousAI()).process(bid,jid)
            job=db.job(bid,jid)
            self.assertEqual(job['risk'],'sensitive'); self.assertEqual(job['investigation'],'open')
            self.assertEqual(job['status'],'needs_approval')
    def test_adapter_does_not_include_unapproved_fields_or_private_alert_email(self):
        ai=Ollama(); captured={}
        class Reply:
            def raise_for_status(self): pass
            def json(self): return {'message':{'content':'{"reply":"Thank you for your feedback.","risk":"routine","reason":"Praise"}'}}
        def post(url,**kwargs): captured.update(kwargs['json']); return Reply()
        business={'name':'Shop','facts':'Tools','contact':'support@example.com','tone':'Warm','language':'English','model':'local:test','notify_email':'PRIVATE_OWNER','consent':True}
        with patch.object(ai,'models',return_value=['local:test']),patch.object(ai.session,'post',side_effect=post):
            ai.generate(business,{'comment':'Lovely shop','rating':5})
        import json
        sent=json.loads(captured['messages'][-1]['content'])
        self.assertNotIn('notify_email',sent['business']); self.assertNotIn('PRIVATE_OWNER',str(captured))
        self.assertEqual(sent['review']['comment'],'Lovely shop')

if __name__=='__main__': unittest.main()
