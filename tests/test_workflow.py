"""End-to-end workflow against the fictional Google adapter. No network, no real owner contact."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from reviewer.ai import make_draft
from reviewer.database import Database
from reviewer.demo import create_demo_business
from reviewer.engine import Engine, PublishBlocked
from reviewer.google import GoogleError
from reviewer.notifications import deliver, retry
from reviewer.text import digest

GOOD = {
    'The team helped me find the right tools for my project. Friendly service and a clean shop.':
        "Glad we could help you find the right tools. Hope the project's going well!",
    'No complaints—quick checkout and helpful advice.': 'Love hearing checkout was quick and the advice hit the spot. Cheers!',
    'Helpful advice and fair prices. Parking was difficult.':
        'Glad our advice helped. Sorry finding a parking spot was a hassle, and thanks for flagging it.',
    'I waited a long time for help and the staff were rude when I asked about paint.':
        "I'm sorry you were left waiting when you came in for paint advice. If you're happy to email hello@boltandbrush.test, "
        "we'd like to hear more about what happened.",
    'The drill stopped working after one use.':
        "Sorry to hear the drill stopped working so soon. If you can email hello@boltandbrush.test, we'd like to hear more about what happened.",
    'Always find what I need here. Key cutting was quick too.': 'Always good to hear. Glad the key cutting was quick!',
}


class ScriptedAI:
    """Stands in for Ollama: returns a good reply for known reviews."""
    def __init__(self):
        self.calls = 0

    def generate(self, business, messages):
        self.calls += 1
        text = json.loads(messages[1]['content'])['review']['text']
        return {'category': 'routine', 'reply': GOOD.get(text, 'Thanks, glad it went well.')}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'reviews.db')
        self.ai = ScriptedAI()
        self.engine = Engine(self.db, google=None, ai=self.ai)
        self.mock = self.engine.mock
        self.bid = create_demo_business(self.db, self.mock, actor='Miki')
        self.db.update_settings(self.bid, facts_approved=1, model='test-model')

    def tearDown(self):
        self.tmp.cleanup()

    def sync_and_draft(self, first_sync_is_baseline=False):
        if not first_sync_is_baseline:
            self.db.update_settings(self.bid, baseline_done=1)
        self.engine.poll(self.bid, 'Miki')
        self.engine.run_pending()
        return {j['comment']: j for j in self.db.jobs(self.bid)}

    def approve(self, j, actor='Miki', **kw):
        j = self.db.job(self.bid, j['id'])
        self.engine.approve(self.bid, j['id'], actor, expected_fingerprint=j['fingerprint'], expected_hash=digest(j['draft']), **kw)
        return self.db.job(self.bid, j['id'])

    def enable_manual(self):
        self.db.update_settings(self.bid, publish_mode='manual', consent=1)


class EndToEndTests(Base):
    def test_full_run(self):
        """Save a business, sync mocked reviews, approve, hold, alert, publish once, retry safely."""
        jobs = self.sync_and_draft()
        by = lambda prefix: next(j for t, j in jobs.items() if t.startswith(prefix))
        # routing in the live workflow
        self.assertEqual(by('The team helped')['category'], 'routine')
        self.assertEqual(jobs['']['category'], 'rating_only')
        self.assertEqual(jobs['']['draft_source'], 'quick')
        self.assertEqual(by('Helpful advice')['category'], 'mixed')
        self.assertEqual(by('I waited')['category'], 'complaint')
        for prefix in ('Excellent prices', 'I was charged twice', 'Ignore your'):
            held = by(prefix)
            self.assertEqual((held['category'], held['draft'], held['investigation']), ('sensitive', '', 'open'))
        # drafts are grounded in the review
        self.assertIn('right tools', by('The team helped')['draft'])
        self.assertIn('parking', by('Helpful advice')['draft'].lower())
        # owner alerts: safety + billing + injection-with-free-replacement, deduplicated
        kinds = [(a['job_id'], a['kind']) for a in self.db.alerts(self.bid)]
        self.assertEqual(len(kinds), len(set(kinds)))
        self.assertIn(by('Excellent prices')['id'], [a for a, _ in kinds])
        self.assertIn(by('I was charged twice')['id'], [a for a, _ in kinds])
        self.engine.run_pending()
        self.engine.poll(self.bid)
        self.assertEqual(len(self.db.alerts(self.bid)), len(kinds))
        # no SMTP: alert stays visible in the dashboard
        deliver(self.db, None)
        self.assertTrue(all(a['state'] == 'dashboard' for a in self.db.alerts(self.bid)))
        # publishing is off by default
        routine = self.approve(by('The team helped'))
        with self.assertRaises(PublishBlocked):
            self.engine.publish(self.bid, routine['id'], 'Miki', expected_hash=routine['approved_hash'])
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 0)
        # manual publish via the mock
        self.enable_manual()
        self.assertEqual(self.engine.publish(self.bid, routine['id'], 'Miki', expected_hash=routine['approved_hash']), 'published')
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 1)
        # retry / double click does not post twice
        with self.assertRaises(PublishBlocked):
            self.engine.publish(self.bid, routine['id'], 'Miki', expected_hash=routine['approved_hash'])
        self.engine.poll(self.bid)
        self.engine.run_pending()
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 1)
        self.assertEqual(self.db.job(self.bid, routine['id'])['status'], 'published')
        # sensitive review cannot be published with no staff reply
        held = by('Excellent prices')
        with self.assertRaises(ValueError):
            self.approve(held)
        # audit trail says who did what
        actions = [(h['actor'], h['action']) for h in self.db.history(self.bid, routine['id'])]
        self.assertIn(('Miki', 'Approved'), actions)
        self.assertIn(('Miki', 'Published'), actions)

    def test_demo_and_live_use_identical_decisions(self):
        jobs = self.sync_and_draft()
        b = self.db.business(self.bid)
        for text, j in jobs.items():
            if j['baseline']:
                continue
            demo = make_draft(ScriptedAI(), b, text, j['rating'])
            self.assertEqual(demo['category'], j['category'], text)
            self.assertEqual(demo['route']['label'], j['route_label'], text)
            self.assertEqual(bool(demo['reply']), bool(j['draft']), text)


class PublishingSafetyTests(Base):
    def setUp(self):
        super().setUp()
        self.jobs = self.sync_and_draft()
        self.enable_manual()
        self.job = self.approve(self.jobs['The team helped me find the right tools for my project. Friendly service and a clean shop.'])

    def publish(self, **kw):
        return self.engine.publish(self.bid, self.job['id'], 'Miki', expected_hash=self.job['approved_hash'], **kw)

    def test_concurrent_clicks_post_once(self):
        results = []

        def go():
            try:
                results.append(self.publish())
            except PublishBlocked as e:
                results.append('blocked')
        threads = [threading.Thread(target=go) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count('published'), 1)
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 1)

    def test_timeout_after_google_stored_it_reconciles_without_second_post(self):
        self.mock.fail_next_reply = GoogleError('network', maybe_sent=True)
        self.mock.write_before_fail = True
        with self.assertRaises(GoogleError):
            self.publish()
        self.assertEqual(self.db.job(self.bid, self.job['id'])['status'], 'publish_unknown')
        with self.assertRaises(PublishBlocked):  # cannot just press publish again
            self.publish()
        self.assertEqual(self.engine.reconcile(self.bid, self.job['id'], 'Miki'), 'published')
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 1)
        self.assertTrue(any(a['kind'] == 'publish_unknown' for a in self.db.alerts(self.bid)))

    def test_timeout_before_google_stored_it_allows_one_deliberate_retry(self):
        self.mock.fail_next_reply = GoogleError('network', maybe_sent=True)
        with self.assertRaises(GoogleError):
            self.publish()
        self.assertEqual(self.engine.reconcile(self.bid, self.job['id'], 'Miki'), 'approved')
        self.assertEqual(self.publish(), 'published')
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 1)

    def test_definite_rejection_keeps_approval_and_shows_error(self):
        self.mock.fail_next_reply = GoogleError('quota')
        with self.assertRaises(GoogleError):
            self.publish()
        j = self.db.job(self.bid, self.job['id'])
        self.assertEqual(j['status'], 'approved')
        self.assertIn('rate limit', j['error'])
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 0)

    def test_crash_while_publishing_needs_readback(self):
        self.db.change_job(self.bid, self.job['id'], status='publishing')
        Database(self.db.path)  # app restart
        self.assertEqual(self.db.job(self.bid, self.job['id'])['status'], 'publish_unknown')

    def test_existing_google_reply_is_preserved(self):
        with self.db.connect() as c:
            c.execute("UPDATE mock_reviews SET reply='Owner replied by hand' WHERE review_id='demo1'")
        self.assertEqual(self.publish(), 'already_replied')
        self.assertEqual(self.mock.review(self.db.business(self.bid), self.job['resource'])['reviewReply']['comment'],
                         'Owner replied by hand')
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 0)

    def test_edited_review_requires_fresh_approval(self):
        self.mock.edit(self.bid, 'demo1', 'Great tools, but the battery started smoking.')
        self.assertEqual(self.publish(), 'changed')
        self.engine.run_pending()
        j = self.db.job(self.bid, self.job['id'])
        self.assertEqual((j['status'], j['category'], j['draft']), ('needs_review', 'sensitive', ''))
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 0)

    def test_edited_review_found_by_sync_clears_approval(self):
        self.mock.edit(self.bid, 'demo1', 'Lovely shop, great tools.')
        self.engine.poll(self.bid)
        self.assertEqual(self.db.job(self.bid, self.job['id'])['status'], 'new')
        with self.assertRaises(PublishBlocked):
            self.publish()

    def test_edited_draft_or_business_requires_reapproval(self):
        self.engine.save_draft(self.bid, self.job['id'], 'Miki', 'Changed words.', self.job['fingerprint'])
        with self.assertRaises(PublishBlocked):
            self.publish()
        job = self.approve(self.db.job(self.bid, self.job['id']))
        self.db.save_business({'id': self.bid, 'voice': 'Formal'}, actor='Miki')
        with self.assertRaises(PublishBlocked):
            self.engine.publish(self.bid, job['id'], 'Miki', expected_hash=job['approved_hash'])

    def test_stale_screen_cannot_publish_different_text(self):
        with self.assertRaises(PublishBlocked):
            self.engine.publish(self.bid, self.job['id'], 'Miki', expected_hash=digest('something else'))

    def test_pause_and_consent_block(self):
        self.db.set_setting('paused', '1')
        with self.assertRaises(PublishBlocked):
            self.publish()
        self.db.set_setting('paused', '0')
        self.db.update_settings(self.bid, consent=0)
        with self.assertRaises(PublishBlocked):
            self.publish()

    def test_rate_limit(self):
        for _ in range(8):
            self.db.audit(self.bid, None, 'Miki', 'Publish attempt')
        with self.assertRaisesRegex(PublishBlocked, 'a minute'):
            self.publish()

    def test_staff_commitments_need_confirmation(self):
        held = next(j for t, j in self.jobs.items() if t.startswith('I was charged twice'))
        self.engine.save_draft(self.bid, held['id'], 'Miki', "Sorry about the double charge. We've refunded it.", held['fingerprint'])
        with self.assertRaisesRegex(ValueError, 'owner agreed'):
            self.approve(held)
        self.assertEqual(self.approve(held, confirm_commitments=True)['status'], 'approved')


class AutoPublishTests(Base):
    def test_praise_only_level(self):
        self.db.update_settings(self.bid, publish_mode='auto', consent=1)
        self.sync_and_draft()
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 1)    # praise
        self.assertEqual(self.mock.post_count(self.bid, 'demo2'), 1)    # blank 5 stars
        self.assertEqual(self.mock.post_count(self.bid, 'demo4'), 0)    # mixed waits
        self.assertEqual(self.mock.post_count(self.bid, 'demo6'), 0)    # complaint waits
        self.assertEqual(self.mock.post_count(self.bid, 'demo7'), 0)    # safety held

    def test_most_reviews_level(self):
        self.db.update_settings(self.bid, publish_mode='auto_most', consent=1)
        self.sync_and_draft()
        self.assertEqual(self.mock.post_count(self.bid, 'demo4'), 1)    # mixed parking
        self.assertEqual(self.mock.post_count(self.bid, 'demo6'), 1)    # drill complaint
        for rid in ('demo7', 'demo8', 'demo9'):                          # battery, double charge, injection
            self.assertEqual(self.mock.post_count(self.bid, rid), 0)
        held = [j for j in self.db.jobs(self.bid) if j['category'] == 'sensitive']
        self.assertTrue(held and all(j['status'] == 'needs_review' for j in held))

    def test_auto_needs_owner_consent(self):
        self.db.update_settings(self.bid, publish_mode='auto_most', consent=0)
        self.sync_and_draft()
        self.assertEqual(sum(self.mock.post_count(self.bid, f'demo{i}') for i in range(1, 11)), 0)

    def test_rate_limited_auto_replies_go_out_later(self):
        self.db.update_settings(self.bid, publish_mode='auto_most', consent=1)
        for _ in range(8):
            self.db.audit(self.bid, None, 'x', 'Publish attempt')
        self.sync_and_draft()
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 0)
        with self.db.connect() as c:
            c.execute("UPDATE audit SET at=0 WHERE action='Publish attempt'")
        self.engine.publish_waiting_auto()
        self.assertEqual(self.mock.post_count(self.bid, 'demo1'), 1)

    def test_first_sync_is_baseline_and_never_auto_published(self):
        self.db.update_settings(self.bid, publish_mode='auto_most', consent=1)
        older = {j['comment']: j for j in self.db.jobs(self.bid)}
        self.assertEqual(older['Been coming here for years. Good people.']['status'], 'already_replied')  # kept
        backlog = older['Decent range of paint.']
        self.assertEqual(backlog['status'], 'baseline')
        self.engine.poll(self.bid)
        self.engine.run_pending()
        self.assertEqual(self.db.job(self.bid, backlog['id'])['status'], 'baseline')  # untouched by sync
        self.engine.reopen(self.bid, backlog['id'], 'Miki')
        self.engine.run_pending()
        self.assertEqual(self.db.job(self.bid, backlog['id'])['status'], 'needs_review')
        self.assertEqual(self.mock.post_count(self.bid, 'older2'), 0)  # baseline never auto-published
        self.assertEqual(self.mock.review(self.db.business(self.bid), backlog['resource']).get('reviewReply'), None)

    def test_brand_new_connection_baselines_everything(self):
        bid = self.db.save_business({'name': 'Fresh'})
        self.db.update_settings(bid, is_demo=1, location=self.mock.location(bid), connection_status='Demo')
        self.mock.seed(bid)
        self.engine.poll(bid)
        self.engine.run_pending()
        self.assertEqual({j['status'] for j in self.db.jobs(bid)}, {'baseline'})


class FailureAndConnectionTests(Base):
    def test_model_down_keeps_routing_and_is_recoverable(self):
        class Down:
            def generate(self, *a):
                import requests
                raise requests.ConnectionError()
        self.engine.ai = Down()
        jobs = self.sync_and_draft()
        praise = jobs['The team helped me find the right tools for my project. Friendly service and a clean shop.']
        self.assertEqual((praise['status'], praise['category']), ('failed', 'routine'))
        self.assertIn('Ollama', praise['error'])
        self.assertEqual(jobs['']['status'], 'needs_review')  # blank 5-star still works without a model
        held = next(j for t, j in jobs.items() if t.startswith('I was charged'))
        self.assertEqual(held['status'], 'needs_review')
        self.engine.ai = ScriptedAI()
        self.engine.request_draft(self.bid, praise['id'], 'Miki')
        self.engine.run_pending()
        self.assertEqual(self.db.job(self.bid, praise['id'])['status'], 'needs_review')

    def test_google_errors_mark_connection_without_crashing(self):
        class Expired:
            def reviews(self, b):
                raise GoogleError('auth')
        self.engine.adapter = lambda b: Expired()
        with self.assertRaises(GoogleError):
            self.engine.poll(self.bid)
        b = self.db.business(self.bid)
        self.assertEqual(b['connection_status'], 'Reconnect needed')
        self.assertIn('Reconnect', b['last_error'])
        self.engine.cycle()  # background loop survives

    def test_quota_backs_off(self):
        class Busy:
            def reviews(self, b):
                raise GoogleError('quota')
        self.engine.adapter = lambda b: Busy()
        with self.assertRaises(GoogleError):
            self.engine.poll(self.bid)
        self.assertGreater(self.db.business(self.bid)['next_poll'], time.time() + 600)

    def test_disconnect_removes_cached_text_but_keeps_open_cases(self):
        jobs = self.sync_and_draft()
        held = next(j for t, j in jobs.items() if t.startswith('I was charged'))
        self.engine.add_note(self.bid, held['id'], 'Miki', 'Called the bank.')
        self.engine.disconnect(self.bid, 'Miki')
        left = self.db.jobs(self.bid)
        self.assertTrue(all(j['investigation'] in ('open', 'in_progress') for j in left))
        self.assertTrue(all(j['comment'] == '' for j in left))
        self.assertEqual(self.db.business(self.bid)['publish_mode'], 'off')


class CaseHandlingTests(Base):
    def test_investigation_lifecycle_is_separate_from_publishing(self):
        jobs = self.sync_and_draft()
        held = next(j for t, j in jobs.items() if t.startswith('Excellent prices'))
        self.engine.set_investigation(self.bid, held['id'], 'Miki', 'in_progress', 'Asked owner to call customer')
        self.engine.set_next_action(self.bid, held['id'], 'Miki', 'Owner to call customer', 'Sam')
        self.engine.add_note(self.bid, held['id'], 'Sam', 'Battery batch number noted.')
        with self.assertRaises(ValueError):
            self.engine.set_investigation(self.bid, held['id'], 'Sam', 'resolved')  # needs a resolution note
        self.engine.save_draft(self.bid, held['id'], 'Sam', "Sorry to hear about the battery. We've been in touch directly.",
                               held['fingerprint'])
        self.enable_manual()
        j = self.approve(held, confirm_commitments=True)
        self.engine.publish(self.bid, j['id'], 'Sam', expected_hash=j['approved_hash'])
        self.assertEqual(self.db.job(self.bid, j['id'])['investigation'], 'in_progress')  # publish != resolved
        self.engine.set_investigation(self.bid, held['id'], 'Sam', 'resolved', 'Battery replaced under supplier recall.')
        actions = [h['action'] for h in self.db.history(self.bid, held['id'])]
        for expected in ('Investigation opened', 'Investigation in progress', 'Next action set', 'Note', 'Edited reply',
                         'Approved', 'Published', 'Investigation resolved'):
            self.assertIn(expected, actions)

    def test_email_alerts_retry_then_stay_visible(self):
        self.db.update_settings(self.bid, notify_email='owner@boltandbrush.test')
        self.db.set_setting('smtp', '{"host": "smtp.test"}')
        self.sync_and_draft()
        calls = []

        def fail(*a):
            calls.append(a)
            raise TimeoutError()
        for _ in range(5):
            deliver(self.db, fail)
        owner_alerts = [a for a in self.db.alerts(self.bid) if a['kind'] == 'owner_action']
        self.assertEqual(len(calls), 3 * len(owner_alerts))
        self.assertTrue(all(a['state'] == 'failed' for a in owner_alerts))
        self.assertFalse(any('smoking' in str(c) or 'charged twice' in str(c) for c in calls))  # no review text emailed
        retry(self.db, self.bid, owner_alerts[0]['id'])
        sent = []
        deliver(self.db, lambda *a: sent.append(a))
        self.assertEqual(len(sent), 1)


class IsolationAndRetentionTests(Base):
    def test_business_isolation(self):
        other = self.db.save_business({'name': 'Law Firm'})
        jobs = self.sync_and_draft()
        j = next(iter(jobs.values()))
        with self.assertRaises(ValueError):
            self.db.job(other, j['id'])
        with self.assertRaises(ValueError):
            self.engine.approve(other, j['id'], 'Miki', expected_fingerprint=j['fingerprint'], expected_hash=digest(j['draft']))
        self.assertEqual(self.db.jobs(other), [])
        self.assertEqual(self.db.alerts(other), [])
        with self.assertRaises(ValueError):
            self.db.update_alert(other, self.db.alerts(self.bid)[0]['id'], acknowledged_by='x')

    def test_mock_refuses_real_business_and_real_adapter_refuses_demo(self):
        from reviewer.google import Google
        real = self.db.save_business({'name': 'Real shop'})
        with self.assertRaises(ValueError):
            self.mock.reviews(self.db.business(real))
        with self.assertRaises(ValueError):
            Google(None).reviews(self.db.business(self.bid))

    def test_retention_purges_text_after_29_days(self):
        jobs = self.sync_and_draft()
        later = time.time() + 30 * 86400
        self.db.purge(now=later)
        left = self.db.jobs(self.bid)
        self.assertTrue(left)  # open investigations remain
        self.assertTrue(all(j['comment'] == '' and j['draft'] == '' for j in left))
        self.assertTrue(all(j['investigation'] == 'open' for j in left))

    def test_migration_backs_up_old_database(self):
        import sqlite3
        path = Path(self.tmp.name) / 'old.db'
        c = sqlite3.connect(path)
        c.executescript('''CREATE TABLE businesses (id INTEGER PRIMARY KEY, name TEXT NOT NULL, facts TEXT NOT NULL DEFAULT '',
             contact TEXT NOT NULL DEFAULT '', tone TEXT NOT NULL DEFAULT 'Warm', language TEXT NOT NULL DEFAULT 'English',
             website TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '', place_id TEXT NOT NULL DEFAULT '',
             model TEXT NOT NULL DEFAULT '', consent INTEGER DEFAULT 0, facts_approved INTEGER DEFAULT 0,
             auto_enabled INTEGER DEFAULT 0, pilot_verified INTEGER DEFAULT 0, baseline_done INTEGER DEFAULT 0,
             version INTEGER DEFAULT 1, connection_status TEXT DEFAULT 'Not connected', last_poll REAL DEFAULT 0,
             last_error TEXT DEFAULT '', consent_at REAL DEFAULT 0);
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE jobs (id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, resource TEXT NOT NULL, payload TEXT NOT NULL,
             fingerprint TEXT NOT NULL, first_seen REAL NOT NULL, status TEXT NOT NULL, draft TEXT DEFAULT '', risk TEXT DEFAULT '',
             reason TEXT DEFAULT '', facts_version INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0, next_attempt REAL DEFAULT 0,
             investigation TEXT DEFAULT 'none', error TEXT DEFAULT '', UNIQUE(business_id,resource));
            INSERT INTO businesses (name, tone, auto_enabled, consent) VALUES ('Old shop', 'Cheerful', 1, 1);
            INSERT INTO jobs (business_id, resource, payload, fingerprint, first_seen, status, risk)
             VALUES (1, 'accounts/1/locations/2/reviews/3', '{}', 'x', 0, 'needs_approval', 'complaint');''')
        c.commit()
        c.close()
        db = Database(path)
        self.assertTrue(db.last_backup and db.last_backup.exists())
        b = db.business(1)
        self.assertEqual((b['name'], b['voice'], b['publish_mode'], b['auto_enabled']), ('Old shop', 'Cheerful', 'off', 0))
        with db.connect() as c2:
            row = c2.execute('SELECT status, category FROM jobs').fetchone()
        self.assertEqual(tuple(row), ('needs_review', 'complaint'))
        self.assertIsNone(Database(path).last_backup)  # second start: already current


if __name__ == '__main__':
    unittest.main()
