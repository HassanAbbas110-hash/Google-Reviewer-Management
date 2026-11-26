"""Dashboard through its normal HTTP entry points (Flask test client)."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from reviewer.database import Database
from reviewer.engine import Engine
from reviewer.lab import LocalLab, csv_text
from reviewer.web import create_app
from tests.test_workflow import ScriptedAI

BASE = 'http://127.0.0.1:8765'
KEY = b'k' * 32


class DownAI(ScriptedAI):
    def models(self, fresh=False):
        import requests
        raise requests.ConnectionError()

    def loaded(self):
        return []


class UpAI(ScriptedAI):
    model = 'qwen3:4b'
    timeout = 120

    def models(self, fresh=False):
        return ['qwen3:4b', 'llama3.2:3b']

    def loaded(self):
        return ['qwen3:4b']

    def available(self, b):
        return True


class WebBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'reviews.db')
        self.engine = Engine(self.db, google=None, ai=UpAI())
        self.app = create_app(self.db, self.engine, secret_key=KEY)
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def token(self, client=None, path='/inbox'):
        page = (client or self.client).get(path, base_url=BASE)
        return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)

    def post(self, path, data=None, client=None, **kw):
        data = dict(data or {})
        data.setdefault('csrf', self.token(client))
        return (client or self.client).post(path, base_url=BASE, data=data, headers={'Origin': BASE}, **kw)

    def login(self, name='Miki'):
        return self.post('/actor', {'actor': name})

    def demo(self):
        self.login()
        r = self.post('/demo')
        bid = int(r.headers['Location'].rsplit('/', 1)[-1])
        self.db.update_settings(bid, facts_approved=1, baseline_done=1)
        self.engine.poll(bid)
        self.engine.run_pending()
        return bid


class FormProtectionTests(WebBase):
    """Regression for 'Save Information -> POST /business 403'."""

    def test_save_business_form_works(self):
        self.login()
        r = self.post('/business', {'name': 'Corner Hardware', 'voice': 'Friendly', 'contact': 'hi@corner.test'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.db.businesses()[0]['name'], 'Corner Hardware')

    def test_form_still_valid_after_app_restart(self):
        self.login()
        token = self.token()
        restarted = create_app(self.db, self.engine, secret_key=KEY)  # same persisted key
        restarted.testing = True
        client = restarted.test_client()
        cookie = self.client.get_cookie('webrift_reviews', domain='127.0.0.1')
        client.set_cookie('webrift_reviews', cookie.value, domain='127.0.0.1')
        r = client.post('/business', base_url=BASE, data={'csrf': token, 'name': 'After restart'}, headers={'Origin': BASE})
        self.assertEqual(r.status_code, 302)

    def test_other_local_apps_session_cookie_does_not_interfere(self):
        self.login()
        self.client.set_cookie('session', 'some-other-flask-app', domain='127.0.0.1')
        self.assertEqual(self.post('/business', {'name': 'Shop'}).status_code, 302)

    def test_protection_still_blocks_forgeries(self):
        self.login()
        token = self.token()
        for origin in ('null', 'https://attacker.example', 'http://127.0.0.1:9999'):
            r = self.client.post('/business', base_url=BASE, data={'csrf': token, 'name': 'X'}, headers={'Origin': origin})
            self.assertEqual(r.status_code, 403, origin)
        r = self.client.post('/business', base_url=BASE, data={'name': 'X'}, headers={'Origin': BASE})
        self.assertEqual(r.status_code, 403)
        self.assertIn('refresh the page', r.text)
        self.assertEqual(self.db.businesses(), [])
        self.assertEqual(self.client.get('/inbox', base_url='http://evil.test').status_code, 400)

    def test_actions_require_a_name(self):
        r = self.post('/business', {'name': 'Shop'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('Working as', r.text)

    def test_security_headers(self):
        r = self.client.get('/inbox', base_url=BASE)
        self.assertEqual(r.headers['Referrer-Policy'], 'same-origin')
        self.assertIn("script-src 'self'", r.headers['Content-Security-Policy'])


class InboxTests(WebBase):
    def test_queues_and_filters(self):
        bid = self.demo()
        other = self.db.save_business({'name': 'Other'})
        page = self.client.get('/inbox?queue=holds', base_url=BASE).text
        self.assertIn('battery started smoking', page)
        self.assertNotIn('right tools', page)
        page = self.client.get('/inbox?queue=routine', base_url=BASE).text
        self.assertIn('right tools', page)
        self.assertEqual(self.client.get(f'/inbox?queue=all&business={other}', base_url=BASE).text.count('class="row'), 0)
        self.assertGreater(self.client.get(f'/inbox?queue=all&business={bid}', base_url=BASE).text.count('class="row'), 5)
        self.assertEqual(self.client.get('/inbox?queue=all&from=2001-01-01&to=2001-01-02', base_url=BASE).text.count('class="row'), 0)
        self.assertIn('Needs the owner', page)  # alert banner

    def test_review_page_explains_routing(self):
        bid = self.demo()
        held = next(j for j in self.db.jobs(bid) if j['comment'].startswith('I was charged twice'))
        page = self.client.get(f'/business/{bid}/review/{held["id"]}', base_url=BASE).text
        self.assertIn('Billing or payment dispute', page)
        self.assertIn('No AI reply is written', page)


class ReviewFlowTests(WebBase):
    def test_approve_confirm_publish_once(self):
        bid = self.demo()
        j = next(j for j in self.db.jobs(bid) if j['comment'].startswith('The team helped'))
        url = f'/business/{bid}/review/{j["id"]}'
        r = self.post(url + '/approve', {'reply': j['draft'], 'fingerprint': j['fingerprint']})
        self.assertEqual(r.status_code, 302)
        confirm = self.client.get(url + '/publish', base_url=BASE).text
        self.assertIn('Publishing is off', confirm)  # draft-only by default
        self.post(f'/business/{bid}/settings', {'version': self.db.business(bid)['version'], 'consent': 'on',
                                                'facts_approved': 'on', 'publish_mode': 'manual'})
        confirm = self.client.get(url + '/publish', base_url=BASE).text
        self.assertIn('Fictional demo profile', confirm)
        self.assertIn('right tools', confirm)  # exact text shown
        h = re.search(r'name="hash" value="([^"]+)"', confirm).group(1)
        self.assertEqual(self.post(url + '/publish', {'hash': h}).status_code, 302)
        self.assertEqual(self.post(url + '/publish', {'hash': h}).status_code, 409)  # second click
        self.assertEqual(self.engine.mock.post_count(bid, 'demo1'), 1)

    def test_edit_after_approval_needs_reapproval(self):
        bid = self.demo()
        j = next(j for j in self.db.jobs(bid) if j['comment'].startswith('The team helped'))
        url = f'/business/{bid}/review/{j["id"]}'
        self.post(url + '/approve', {'reply': j['draft'], 'fingerprint': j['fingerprint']})
        self.post(url + '/save', {'reply': 'Thanks for coming in, glad the tools were right!', 'fingerprint': j['fingerprint']})
        self.assertEqual(self.db.job(bid, j['id'])['status'], 'needs_review')

    def test_auto_mode_needs_owner_consent_and_checked_facts(self):
        bid = self.demo()
        v = lambda: self.db.business(bid)['version']
        r = self.post(f'/business/{bid}/settings', {'version': v(), 'facts_approved': 'on', 'publish_mode': 'auto_most'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('owner', r.text)
        r = self.post(f'/business/{bid}/settings', {'version': v(), 'consent': 'on', 'publish_mode': 'auto_most'})
        self.assertEqual(r.status_code, 400)
        r = self.post(f'/business/{bid}/settings', {'version': v(), 'consent': 'on', 'facts_approved': 'on', 'publish_mode': 'auto_most'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.db.business(bid)['publish_mode'], 'auto_most')

    def test_one_click_and_bulk_publish(self):
        bid = self.demo()
        self.post(f'/business/{bid}/settings', {'version': self.db.business(bid)['version'], 'consent': 'on',
                                                'facts_approved': 'on', 'publish_mode': 'manual'})
        j = next(j for j in self.db.jobs(bid) if j['comment'].startswith('The drill'))
        r = self.post(f'/business/{bid}/review/{j["id"]}/approve-publish', {'reply': j['draft'], 'fingerprint': j['fingerprint']})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.db.job(bid, j['id'])['status'], 'published')
        self.assertIn('ready to send', self.client.get('/inbox', base_url=BASE).text)
        self.post('/publish-ready')
        statuses = {j['comment'][:20]: j['status'] for j in self.db.jobs(bid)}
        self.assertEqual(statuses['The team helped me f'], 'published')
        self.assertEqual(statuses['Excellent prices, but'[:20]], 'needs_review')  # sensitive never bulk-sent
        self.assertEqual(statuses['I was charged twice f'[:20]], 'needs_review')
        self.assertNotIn('ready to send', self.client.get('/inbox', base_url=BASE).text)

    def test_case_tools(self):
        bid = self.demo()
        j = next(j for j in self.db.jobs(bid) if j['comment'].startswith('Excellent prices'))
        url = f'/business/{bid}/review/{j["id"]}'
        self.post(url + '/note', {'note': 'Asked for photos.'})
        self.post(url + '/next', {'next_action': 'Owner to call customer', 'assignee': 'Sam'})
        self.post(url + '/investigation', {'state': 'in_progress', 'note': 'Owner calling'})
        page = self.client.get(url, base_url=BASE).text
        for text in ('Asked for photos.', 'Owner to call customer', 'Investigation in progress', 'Miki'):
            self.assertIn(text, page)


class PagesTests(WebBase):
    def test_status_names_component_and_fix(self):
        self.engine.ai = DownAI()
        page = self.client.get('/status', base_url=BASE).text
        self.assertIn('Ollama', page)
        self.assertIn('ollama serve', page)
        self.assertIn('Database', page)

    def test_status_with_model(self):
        self.demo()
        page = self.client.get('/status', base_url=BASE).text
        self.assertIn('qwen3:4b', page)
        self.assertIn('Demo', page)

    def test_weekly_monthly_export(self):
        bid = self.demo()
        page = self.client.get('/weekly', base_url=BASE).text
        self.assertIn('Bolt &amp; Brush', page)
        self.assertIn('OPEN INVESTIGATIONS', page)
        self.assertEqual(self.client.get(f'/business/{bid}/monthly', base_url=BASE).status_code, 200)
        csv_body = self.client.get(f'/business/{bid}/operations.csv', base_url=BASE).text
        self.assertIn('sensitive', csv_body)
        self.assertNotIn('smoking', csv_body)  # export has no review text

    def test_welcome_and_new_business(self):
        self.assertIn('/welcome', self.client.get('/', base_url=BASE).headers['Location'])
        self.assertIn('Create the demo shop', self.client.get('/welcome', base_url=BASE).text)
        self.assertIn('Approved facts', self.client.get('/business/new', base_url=BASE).text)

    def test_unknown_business_404(self):
        self.assertEqual(self.client.get('/business/999', base_url=BASE).status_code, 404)


class LabTests(WebBase):
    def test_single_review_runs_same_pipeline_without_touching_inbox(self):
        self.login()
        bid = self.db.save_business({'name': 'Shop', 'contact': 'hi@shop.test'})
        self.db.update_settings(bid, facts_approved=1)
        r = self.post(f'/business/{bid}/lab/start', {'review': 'The battery started smoking.', 'rating': '5'})
        rid = r.headers['Location'].rsplit('/', 1)[-1]
        self.app.extensions['local_lab'].tick()
        run = self.client.get(f'/business/{bid}/lab/{rid}/status', base_url=BASE).get_json()
        self.assertEqual(run['results'][0]['category'], 'sensitive')
        self.assertEqual(run['results'][0]['reply'], '')
        self.assertEqual(self.db.jobs(bid), [])
        other = self.db.save_business({'name': 'Other'})
        self.assertEqual(self.client.get(f'/business/{other}/lab/{rid}', base_url=BASE).status_code, 404)

    def test_owner_suite_routes_correctly(self):
        self.login()
        bid = self.db.save_business({'name': 'Shop'})
        self.db.update_settings(bid, facts_approved=1)
        rid = self.post(f'/business/{bid}/lab/start', {'suite': 'owner'}).headers['Location'].rsplit('/', 1)[-1]
        self.app.extensions['local_lab'].tick()
        run = self.app.extensions['local_lab'].get(bid, rid)
        self.assertEqual(run['matches'], run['checked'])
        self.assertEqual(run['checked'], 9)

    def test_csv_cannot_run_spreadsheet_formulas(self):
        out = csv_text({'results': [{'id': '=cmd()', 'text': '@x', 'reply': '+1'}]})
        self.assertIn("'=cmd()", out)
        self.assertIn("'@x", out)


class SmtpTests(unittest.TestCase):
    def test_sender_uses_tls_and_keeps_password_out_of_message(self):
        from reviewer.notifications import sender
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / 'db')
            db.set_setting('smtp', json.dumps(dict(host='smtp.example.com', port=465, user='operator', sender='alerts@example.com')))
            vault = MagicMock()
            vault.get.return_value = 'SECRET'
            smtp = MagicMock()
            with patch('reviewer.notifications.smtplib.SMTP_SSL', return_value=smtp) as tls:
                sender(db, vault)('owner@example.com', 'Subject', 'Body')
            self.assertEqual(tls.call_args.args, ('smtp.example.com', 465))
            msg = smtp.__enter__.return_value.send_message.call_args.args[0]
            self.assertEqual(msg['To'], 'owner@example.com')
            self.assertNotIn('SECRET', str(msg))


if __name__ == '__main__':
    unittest.main()
