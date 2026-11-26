import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from reviewer.database import Database
from reviewer.reports import monthly_report

class ReportTests(unittest.TestCase):
    def test_monthly_report_isolated_and_survives_content_purge(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'x.db')
            a=db.save_business({'name':'A'}); b=db.save_business({'name':'B'})
            jid,_=db.ingest(a,{'name':'accounts/a/locations/b/reviews/c','comment':'PRIVATE CONTENT'})
            db.change_job(a,jid,status='published')
            db.change_job(a,jid,status='published')
            db.change_job(a,jid,investigation='open')
            month=datetime.now(timezone.utc).strftime('%Y-%m')
            report=monthly_report(db,a,month)
            self.assertEqual(report['published'],1); self.assertEqual(report['investigations_opened'],1)
            self.assertEqual(monthly_report(db,b,month)['published'],0)
            self.assertNotIn('PRIVATE CONTENT',str(report))
            with db.connect() as c: c.execute('UPDATE jobs SET first_seen=0')
            db.purge()
            self.assertEqual(monthly_report(db,a,month)['published'],1)
    def test_bad_month_rejected(self):
        with self.assertRaises(ValueError): monthly_report(None,1,'garbage')

if __name__=='__main__': unittest.main()
