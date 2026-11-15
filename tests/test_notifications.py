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

class NotificationDeliveryTests(unittest.TestCase):
    def test_sender_uses_tls_and_private_metadata_only(self):
        import json
        from unittest.mock import MagicMock,patch
        from reviewer.notifications import sender
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db');db.set_setting('smtp',json.dumps(dict(host='smtp.example.com',port=465,user='operator',sender='alerts@example.com')))
            vault=MagicMock();vault.get.return_value='SECRET';smtp=MagicMock()
            with patch('reviewer.notifications.smtplib.SMTP_SSL',return_value=smtp) as tls:
                send=sender(db,vault);send('owner@example.com','Review requires investigation','Open the local dashboard.')
            self.assertEqual(tls.call_args.args,('smtp.example.com',465));smtp.__enter__.return_value.login.assert_called_once_with('operator','SECRET')
            msg=smtp.__enter__.return_value.send_message.call_args.args[0];self.assertEqual(msg['To'],'owner@example.com');self.assertNotIn('SECRET',str(msg))
    def test_failed_delivery_stops_after_three_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db');bid=db.save_business({'name':'Shop'});db.update_settings(bid,notify_email='owner@example.com')
            jid=db.ingest(bid,{'name':'accounts/a/locations/b/reviews/c'});db.change_job(bid,jid,investigation='open')
            calls=[]
            def fail(*args):calls.append(args);raise TimeoutError()
            for _ in range(5):notify(db,fail)
            self.assertEqual(len(calls),3);self.assertEqual(db.job(bid,jid)['investigation'],'open')
