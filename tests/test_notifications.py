import tempfile
import unittest
from pathlib import Path
from reviewer.database import Database
from reviewer.notifications import notify


class NotificationTests(unittest.TestCase):
    def test_alert_success_and_failure_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'x.db')
            bid=db.save_business({'name':'Shop','facts':'Facts','contact':'staff@example.com'})
            db.update_settings(bid,notify_email='owner@example.com')
            jid=db.ingest(bid,{'name':'accounts/a/locations/b/reviews/c','comment':'Complaint'})
            db.change_job(bid,jid,investigation='open')
            sent=[]
            def send(to,subject,body): sent.append((to,subject,body))
            notify(db,send)
            self.assertEqual(db.job(bid,jid)['alert_state'],'sent')
            self.assertNotIn('Complaint',sent[0][2])
            notify(db,send); self.assertEqual(len(sent),1)
            db.change_job(bid,jid,alert_state='pending')
            def failure(*args): raise TimeoutError()
            notify(db,failure)
            self.assertEqual(db.job(bid,jid)['alert_state'],'failed')

if __name__=='__main__': unittest.main()
