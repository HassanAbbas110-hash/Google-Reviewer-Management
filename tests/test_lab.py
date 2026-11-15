import tempfile
import unittest
from pathlib import Path
from reviewer.database import Database
from reviewer.lab import LocalLab,REGRESSION_CASES,csv_text
from reviewer.engine import Engine
from reviewer.web import create_app

class AI:
    def __init__(self): self.calls=0
    def generate(self,b,review):
        self.calls+=1
        return {'reply':'Glad the advice helped!','risk':'routine','reason':'Positive feedback'}
class NoGoogle:
    def __getattr__(self,key): raise AssertionError('Local lab accessed Google')

class LabTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(Path(self.tmp.name)/'app.db')
        self.bid=self.db.save_business({'name':'Demo','facts':'Tools','contact':'support@example.com','model':'local:test'})
        self.db.update_settings(self.bid,facts_approved=1)
        self.ai=AI();self.engine=Engine(self.db,NoGoogle(),self.ai);self.lab=LocalLab(self.db,self.engine)
        self.case={'id':'praise','text':'Helpful advice','rating':5,'expected':'routine'}
    def tearDown(self):self.tmp.cleanup()
    def test_batch_records_results_without_google_or_live_state(self):
        rid=self.lab.submit(self.bid,[self.case,{'id':'hazard','text':'The battery started smoking','rating':5,'expected':'sensitive'}])
        self.lab.tick()
        run=self.lab.get(self.bid,rid)
        self.assertEqual(run['status'],'done');self.assertEqual(run['completed'],2)
        self.assertEqual(run['matches'],2);self.assertEqual(self.ai.calls,1)
        self.assertIn('No owner action',run['results'][0]['handoff'])
        self.assertIn('investigate',run['results'][1]['handoff'])
        self.assertIn('no alert sent',run['results'][1]['handoff'])
        self.assertEqual(self.db.jobs(self.bid),[])
        with self.db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
    def test_failure_is_visible_and_does_not_discard_later_cases(self):
        class Fail:
            def generate(self,*args):raise ConnectionError('PRIVATE_ERROR')
        self.engine.ai=Fail()
        rid=self.lab.submit(self.bid,[self.case,{'id':'hazard','text':'The charger caught fire','rating':5,'expected':'sensitive'}])
        self.lab.tick();run=self.lab.get(self.bid,rid)
        self.assertEqual(run['completed'],2);self.assertEqual(run['results'][0]['status'],'error')
        self.assertNotIn('PRIVATE_ERROR',str(run));self.assertEqual(run['results'][1]['risk'],'sensitive')
    def test_foreign_business_cannot_access_or_cancel(self):
        rid=self.lab.submit(self.bid,[self.case]);other=self.db.save_business({'name':'Other'})
        with self.assertRaises(ValueError):self.lab.get(other,rid)
        with self.assertRaises(ValueError):self.lab.cancel(other,rid)
    def test_queued_cancel_and_resume(self):
        rid=self.lab.submit(self.bid,[self.case]);self.lab.cancel(self.bid,rid);self.lab.tick()
        self.assertEqual(self.lab.get(self.bid,rid)['status'],'cancelled');self.assertEqual(self.ai.calls,0)
        self.lab.resume(self.bid,rid);self.lab.tick()
        self.assertEqual(self.lab.get(self.bid,rid)['status'],'done')
    def test_restart_retains_checkpoint_and_marks_interrupted(self):
        rid=self.lab.submit(self.bid,[self.case,self.case])
        with self.db.connect() as c:c.execute("UPDATE lab_runs SET status='running' WHERE id=?",(rid,))
        restarted=LocalLab(self.db,self.engine)
        self.assertEqual(restarted.get(self.bid,rid)['status'],'interrupted')
        restarted.resume(self.bid,rid);restarted.tick()
        self.assertEqual(restarted.get(self.bid,rid)['completed'],2)
    def test_fact_change_prevents_stale_evaluation(self):
        rid=self.lab.submit(self.bid,[self.case]);self.db.save_business({'id':self.bid,'name':'Demo','facts':'Changed'})
        self.lab.tick();run=self.lab.get(self.bid,rid)
        self.assertEqual(run['status'],'interrupted');self.assertEqual(self.ai.calls,0)
    def test_queue_limit_and_case_bounds(self):
        with self.assertRaises(ValueError):self.lab.submit(self.bid,[])
        with self.assertRaises(ValueError):self.lab.submit(self.bid,[self.case]*101)
        with self.assertRaises(ValueError):self.lab.submit(self.bid,[{**self.case,'rating':0}])
        self.lab.submit(self.bid,[self.case])
        with self.assertRaises(ValueError):self.lab.submit(self.bid,[self.case])
    def test_regression_set_is_varied_and_labeled(self):
        self.assertEqual(len(REGRESSION_CASES),24)
        self.assertEqual(len({c['id'] for c in REGRESSION_CASES}),24)
        self.assertEqual({c['expected'] for c in REGRESSION_CASES},{'routine','complaint','sensitive'})
    def test_csv_cannot_execute_spreadsheet_formula(self):
        text=csv_text({'results':[{'text':'=HYPERLINK("evil")','reply':'+formula','status':'draft','risk':'routine'}]})
        self.assertIn("'=HYPERLINK",text);self.assertIn("'+formula",text)
    def test_routes_require_csrf_and_isolate_runs(self):
        app=create_app(self.db,self.engine);app.testing=True;client=app.test_client()
        self.assertEqual(client.post(f'/business/{self.bid}/lab/start').status_code,403)
        client.get('/')
        with client.session_transaction() as s:token=s['csrf']
        r=client.post(f'/business/{self.bid}/lab/start',data={'csrf':token,'suite':'quick'},headers={'Accept':'application/json'})
        self.assertEqual(r.status_code,202);rid=r.json['id']
        self.assertEqual(client.get(f'/business/{self.bid}/lab/{rid}/status').status_code,200)
        self.assertEqual(client.get(f'/business/999/lab/{rid}/status').status_code,404)
        self.assertEqual(client.get(f'/business/{self.bid}/lab/{rid}/export.json').status_code,200)
    def test_facts_must_be_approved(self):
        self.db.update_settings(self.bid,facts_approved=0)
        with self.assertRaises(ValueError):self.lab.submit(self.bid,[self.case])

if __name__=='__main__':unittest.main()
