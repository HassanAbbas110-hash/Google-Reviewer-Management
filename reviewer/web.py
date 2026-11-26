"""Loopback-only staff dashboard. Not a public multi-user service."""
import csv
import io
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, abort, redirect, render_template, request, session, Response, url_for, flash
from reviewer.database import STATUS_LABELS
from reviewer.engine import PublishBlocked
from reviewer.google import GoogleError
from reviewer.text import digest

QUEUES = [
    ('todo', 'To do', ('new', 'drafting', 'needs_review', 'failed', 'approved', 'publish_unknown')),
    ('routine', 'Routine drafts', ('needs_review',)),
    ('complaints', 'Complaints & mixed', ('needs_review',)),
    ('holds', 'Sensitive holds', None),
    ('approved', 'Approved, not published', ('approved',)),
    ('failed', 'Failed', ('failed', 'publish_unknown', 'approved')),
    ('investigations', 'Investigations', None),
    ('backlog', 'Before first sync', ('baseline',)),
    ('done', 'Done', ('published', 'already_replied', 'no_reply', 'expired')),
    ('all', 'All', None),
]
NEXT_ACTIONS = ['', 'Review and approve reply', 'Write staff reply', 'Owner to decide', 'Owner to call customer',
                'Check order / payment records', 'Check product batch', 'Wait for customer', 'No public reply']


def in_queue(j, key):
    statuses = dict((k, s) for k, _, s in QUEUES)[key]
    if key == 'routine':
        return j['status'] == 'needs_review' and j['category'] in ('routine', 'rating_only')
    if key == 'complaints':
        return j['status'] == 'needs_review' and j['category'] in ('mixed', 'complaint', 'uncertain')
    if key == 'holds':
        return j['category'] == 'sensitive' and j['status'] not in ('published', 'already_replied', 'no_reply', 'expired')
    if key == 'failed':
        return j['status'] in ('failed', 'publish_unknown') or (j['status'] == 'approved' and bool(j['error']))
    if key == 'investigations':
        return j['investigation'] in ('open', 'in_progress')
    return statuses is None or j['status'] in statuses


def create_app(db, engine, background=False, secret_key=None, lab=None):
    from reviewer.lab import LocalLab, SUITES, csv_text
    lab = lab or LocalLab(db, engine)
    app = Flask(__name__)
    app.extensions['local_lab'] = lab
    if background:
        lab.start()
    # A persistent key keeps open pages valid after the app restarts (the old cause of POST /business 403).
    app.secret_key = secret_key or secrets.token_bytes(32)
    app.config.update(MAX_CONTENT_LENGTH=128000, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      # A unique name: other local apps (any Flask app on 127.0.0.1) also use "session" and would
                      # overwrite ours, because cookies are shared across ports.
                      SESSION_COOKIE_NAME='webrift_reviews', PERMANENT_SESSION_LIFETIME=timedelta(days=30))

    def business(bid):
        b = db.business(bid)
        if not b:
            abort(404)
        return b

    def actor():
        name = (session.get('actor') or '').strip()
        if not name:
            raise ValueError('Type your name in "Working as" at the top of the page first, so actions are recorded.')
        return name

    def back(default='/inbox'):
        target = request.form.get('next') or default
        return redirect(target if target.startswith('/') and not target.startswith('//') else default)

    def wants_json():
        return request.accept_mimetypes.best == 'application/json'

    @app.before_request
    def secure():
        if request.host.split(':')[0] not in ('127.0.0.1', 'localhost'):
            abort(400)
        if request.remote_addr not in (None, '127.0.0.1', '::1'):
            abort(403)
        session.permanent = True
        session.setdefault('csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                abort(403)
            if not secrets.compare_digest(request.form.get('csrf', ''), session['csrf']):
                abort(403)

    @app.after_request
    def headers(response):
        response.headers['Content-Security-Policy'] = ("default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
                                                       "frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        # same-origin keeps the Origin header on form posts (no-referrer made Chromium send "null").
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.context_processor
    def shared():
        alerts = [a for a in db.alerts(open_only=True) if a['kind'] == 'owner_action' or a['state'] == 'failed']
        return dict(all_businesses=db.businesses(), paused=db.setting('paused') == '1', actor_name=session.get('actor', ''),
                    open_alerts=alerts, status_labels=STATUS_LABELS, csrf=session.get('csrf', ''), now=time.time())

    @app.template_filter('when')
    def when(ts):
        if not ts:
            return ''
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
            except ValueError:
                return ts
        delta = time.time() - ts
        if delta < 90:
            return 'just now'
        if delta < 3600:
            return f'{int(delta // 60)} min ago'
        if delta < 86400:
            return f'{int(delta // 3600)} h ago'
        return datetime.fromtimestamp(ts).strftime('%d %b %Y %H:%M')

    @app.template_filter('stars')
    def stars(n):
        n = int(n or 0)
        return '★' * n + '☆' * (5 - n) if n else 'No rating'

    @app.errorhandler(403)
    def forbidden(error):
        msg = ('This page was out of date (for example the app restarted, or it was open in an old tab). '
               'Press Back, refresh the page (F5), and submit again. Nothing was changed.')
        if wants_json():
            return {'error': msg}, 403
        return render_template('message.html', title='Please refresh and try again', message=msg), 403

    @app.errorhandler(PublishBlocked)
    def blocked(error):
        if wants_json():
            return {'error': str(error), 'reasons': error.reasons}, 409
        return render_template('message.html', title='Not published', message='Nothing was sent to Google.',
                               reasons=error.reasons), 409

    @app.errorhandler(GoogleError)
    def google_error(error):
        if wants_json():
            return {'error': str(error)}, 502
        return render_template('message.html', title='Google problem', message=str(error)), 502

    @app.errorhandler(ValueError)
    def invalid(error):
        if wants_json():
            return {'error': str(error)}, 400
        return render_template('message.html', title='That did not work', message=str(error)), 400

    @app.errorhandler(Exception)
    def unexpected(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException):
            return error
        app.logger.exception('Unexpected error')
        msg = 'App: something unexpected failed. Open the Status page to check each component, then try again.'
        if wants_json():
            return {'error': msg}, 500
        return render_template('message.html', title='Something went wrong', message=msg), 500

    # ------------------------------------------------------------- general
    @app.get('/')
    def index():
        return redirect('/inbox' if db.businesses() else '/welcome')

    @app.get('/welcome')
    def welcome():
        return render_template('welcome.html')

    @app.post('/actor')
    def set_actor():
        name = request.form.get('actor', '').strip()[:60]
        if not name:
            raise ValueError('Type your name.')
        session['actor'] = name
        return back()

    @app.post('/pause')
    def pause():
        db.set_setting('paused', '0' if db.setting('paused') == '1' else '1')
        return back()

    @app.get('/inbox')
    def inbox():
        db.purge()
        bid = request.args.get('business', type=int)
        queue = request.args.get('queue', 'todo')
        if queue not in dict((k, l) for k, l, _ in QUEUES):
            queue = 'todo'
        status = request.args.get('status', '')
        since = request.args.get('from', '')
        until = request.args.get('to', '')

        def stamp(day, end=False):
            try:
                d = datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                return (d + timedelta(days=1 if end else 0)).timestamp()
            except ValueError:
                return None
        jobs = db.jobs(bid, statuses=(status,) if status else None, since=stamp(since), until=stamp(until, True))
        names = {b['id']: b['name'] for b in db.businesses()}
        for j in jobs:
            j['business_name'] = names.get(j['business_id'], '?')
        counts = {k: sum(1 for j in jobs if in_queue(j, k)) for k, _, _ in QUEUES}
        shown = [j for j in jobs if in_queue(j, queue)]
        return render_template('inbox.html', jobs=shown, counts=counts, queues=QUEUES, queue=queue, bid=bid, status=status,
                               since=since, until=until, drafting=any(j['status'] in ('new', 'drafting') for j in shown))

    # ------------------------------------------------------------ reviews
    @app.get('/business/<int:bid>/review/<int:jid>')
    def review(bid, jid):
        b = business(bid)
        j = db.job(bid, jid)
        return render_template('review.html', b=b, j=j, history=db.history(bid, jid), next_actions=NEXT_ACTIONS,
                               draft_hash=digest(j['draft']), alerts=[a for a in db.alerts(bid) if a['job_id'] == jid])

    @app.get('/business/<int:bid>/review/<int:jid>/state')
    def review_state(bid, jid):
        business(bid)
        j = db.job(bid, jid)
        return {'status': j['status'], 'label': j['status_label'], 'updated': j['updated']}

    @app.post('/business/<int:bid>/review/<int:jid>/<action>')
    def review_action(bid, jid, action):
        business(bid)
        who = actor()
        form = request.form
        here = f'/business/{bid}/review/{jid}'
        if action == 'draft':
            engine.request_draft(bid, jid, who)
        elif action == 'save':
            engine.save_draft(bid, jid, who, form.get('reply', ''), form.get('fingerprint'))
        elif action == 'approve':
            if form.get('reply') is not None and form.get('reply', '').strip() != (db.job(bid, jid)['draft'] or '').strip():
                engine.save_draft(bid, jid, who, form.get('reply', ''), form.get('fingerprint'))
            j = db.job(bid, jid)
            engine.approve(bid, jid, who, expected_fingerprint=form.get('fingerprint'), expected_hash=digest(j['draft'])
                           if form.get('reply') is not None else form.get('hash'),
                           confirm_commitments=form.get('confirm_commitments') == 'on')
        elif action == 'publish':
            engine.publish(bid, jid, who, expected_hash=form.get('hash', ''))
        elif action == 'reconcile':
            engine.reconcile(bid, jid, who)
        elif action == 'note':
            engine.add_note(bid, jid, who, form.get('note', ''))
        elif action == 'next':
            engine.set_next_action(bid, jid, who, form.get('next_action', ''), form.get('assignee', ''))
        elif action == 'investigation':
            engine.set_investigation(bid, jid, who, form.get('state', ''), form.get('note', ''))
        elif action == 'no-reply':
            engine.no_reply(bid, jid, who, form.get('reason', ''))
        elif action == 'reopen':
            engine.reopen(bid, jid, who)
        else:
            abort(404)
        return redirect(here)

    @app.get('/business/<int:bid>/review/<int:jid>/publish')
    def confirm_publish(bid, jid):
        from reviewer.policy import publish_blockers
        b, j = business(bid), db.job(bid, jid)
        reasons = publish_blockers(b, j, paused=db.setting('paused') == '1', expected_hash=j['approved_hash'])
        return render_template('publish.html', b=b, j=j, reasons=reasons)

    # ------------------------------------------------------------ alerts
    @app.post('/business/<int:bid>/alert/<int:aid>/<action>')
    def alert_action(bid, aid, action):
        from reviewer.notifications import retry
        business(bid)
        who = actor()
        if action == 'ack':
            engine.acknowledge_alert(bid, aid, who)
        elif action == 'retry':
            retry(db, bid, aid)
            db.audit(bid, None, who, 'Alert retry requested', str(aid))
        else:
            abort(404)
        return back()

    # ---------------------------------------------------------- businesses
    @app.get('/business/new')
    def new_business():
        return render_template('business.html', b=None, models=_models(), history=[])

    @app.get('/business/<int:bid>')
    def detail(bid):
        b = business(bid)
        approvals = db.count_actions(bid, 'Approved')
        return render_template('business.html', b=b, models=_models(), history=db.history(bid)[:30],
                               approvals=approvals, connected=_connected(b))

    def _models():
        try:
            return engine.ai.models()
        except Exception:
            return []

    def _connected(b):
        if b['is_demo']:
            return True
        try:
            return bool(engine.google and engine.google.connected(b['id']))
        except Exception:
            return False

    @app.post('/business')
    def save():
        who = actor()
        fields = ('name', 'facts', 'contact', 'voice', 'language', 'website', 'model', 'examples', 'sign_off', 'owner_name',
                  'notify_email')
        data = {k: request.form.get(k, '') for k in fields if k in request.form}
        if request.form.get('id'):
            business(int(request.form['id']))
            data['id'] = int(request.form['id'])
        with engine.lock:
            bid = db.save_business(data, actor=who)
        return redirect(f'/business/{bid}')

    @app.post('/business/<int:bid>/settings')
    def settings(bid):
        who = actor()
        with engine.lock:
            b = business(bid)
            if request.form.get('version') != str(b['version']):
                raise ValueError('Business details changed since you opened this page. Refresh and check them again.')
            flags = {k: int(request.form.get(k) == 'on') for k in ('consent', 'facts_approved', 'pilot_verified')}
            mode = request.form.get('publish_mode', 'off')
            if mode not in ('off', 'manual', 'auto'):
                raise ValueError('Unknown publishing mode.')
            if mode != 'off' and not flags['consent']:
                raise ValueError('Publishing needs the owner\'s recorded authorisation first.')
            if mode == 'auto':
                missing = []
                if not flags['facts_approved']:
                    missing.append('approved business facts')
                if not flags['pilot_verified']:
                    missing.append('a signed-off draft-only pilot')
                from reviewer.policy import AUTO_MIN_APPROVALS
                if db.count_actions(bid, 'Approved') < AUTO_MIN_APPROVALS:
                    missing.append(f'at least {AUTO_MIN_APPROVALS} staff-approved drafts')
                if missing:
                    raise ValueError('Automatic publishing needs ' + ', '.join(missing) + '.')
            db.update_settings(bid, **flags, publish_mode=mode, consent_at=time.time() if flags['consent'] and not b['consent'] else b['consent_at'])
            changes = [f'{k}={v}' for k, v in dict(flags, publish_mode=mode).items() if str(b[k]) != str(v)]
            if changes:
                db.audit(bid, None, who, 'Publishing controls changed', ', '.join(changes))
        return redirect(f'/business/{bid}')

    @app.post('/business/<int:bid>/sync')
    def sync(bid):
        business(bid)
        counts = engine.poll(bid, actor())
        flash(f"Synced {counts['total']} reviews: {counts['new']} new, {counts['edited']} edited.")
        return back(f'/inbox?business={bid}')

    @app.post('/business/<int:bid>/disconnect')
    def disconnect(bid):
        business(bid)
        engine.disconnect(bid, actor())
        return redirect(f'/business/{bid}')

    @app.post('/business/<int:bid>/import-facts')
    def import_facts(bid):
        from reviewer.website import extract
        b = business(bid)
        who = actor()
        if request.form.get('decision') == 'approve':
            if not b['pending_facts']:
                raise ValueError('Nothing to approve.')
            text = request.form.get('pending', b['pending_facts']).strip()
            facts = (b['facts'] + '\n' if b['facts'] else '') + text
            sources = (b['facts_sources'] + '\n' if b['facts_sources'] else '') + f"{b['pending_source']} (approved by {who}, {time.strftime('%Y-%m-%d')})"
            with engine.lock:
                db.save_business({'id': bid, 'facts': facts}, actor=who)
                db.update_settings(bid, pending_facts='', pending_source='', pending_at=0, facts_sources=sources)
                db.audit(bid, None, who, 'Website facts approved', b['pending_source'])
        elif request.form.get('decision') == 'discard':
            db.update_settings(bid, pending_facts='', pending_source='', pending_at=0)
            db.audit(bid, None, who, 'Website facts discarded', b['pending_source'])
        else:
            if not b['website']:
                raise ValueError('Save the business website address first.')
            text = extract(b['website'])
            db.update_settings(bid, pending_facts=text[:6000], pending_source=b['website'], pending_at=time.time())
            db.audit(bid, None, who, 'Website text imported for review', b['website'])
        return redirect(f'/business/{bid}#facts')

    @app.post('/demo')
    def demo():
        from reviewer.demo import create_demo_business
        bid = create_demo_business(db, engine.mock, actor())
        return redirect(f'/business/{bid}')

    @app.get('/business/<int:bid>/review-qr.svg')
    def qr(bid):
        import qrcode
        import qrcode.image.svg
        from urllib.parse import urlencode
        b = business(bid)
        if not b['place_id']:
            raise ValueError('Connect a Google location first')
        image = qrcode.make('https://search.google.com/local/writereview?' + urlencode({'placeid': b['place_id']}),
                            image_factory=qrcode.image.svg.SvgPathImage)
        out = io.BytesIO()
        image.save(out)
        return Response(out.getvalue(), mimetype='image/svg+xml')

    # ------------------------------------------------------------ reports
    @app.get('/weekly')
    def weekly():
        from reviewer.reports import weekly_report
        bid = request.args.get('business', type=int)
        if bid:
            business(bid)
        return render_template('weekly.html', report=weekly_report(db, bid, request.args.get('week') or None), bid=bid)

    @app.get('/business/<int:bid>/monthly')
    def monthly(bid):
        from reviewer.reports import monthly_report
        b = business(bid)
        month = request.args.get('month', datetime.now(timezone.utc).strftime('%Y-%m'))
        return render_template('report.html', b=b, report=monthly_report(db, bid, month))

    @app.get('/business/<int:bid>/operations.csv')
    def summary(bid):
        business(bid)
        db.purge()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(['Case', 'Stars', 'Type', 'Status', 'Investigation', 'Next action', 'Assignee', 'Approved by'])
        for j in db.jobs(bid):
            writer.writerow([j['id'], j['rating'], j['category'], j['status'], j['investigation'], j['next_action'],
                             j['assignee'], j['approved_by']])
        return Response(out.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=review-operations.csv'})

    # ------------------------------------------------------------- status
    @app.get('/status')
    def status():
        return render_template('status.html', checks=status_checks(db, engine), default_model=db.setting('default_model', ''),
                               timeout=db.setting('model_timeout', '120'), models=_models())

    @app.get('/status.json')
    def status_json():
        return {'checks': status_checks(db, engine)}

    @app.post('/status/model')
    def set_model():
        who = actor()
        model = request.form.get('default_model', '').strip()
        timeout = request.form.get('timeout', '120')
        if not timeout.isdigit() or not 20 <= int(timeout) <= 600:
            raise ValueError('Timeout must be 20 to 600 seconds.')
        if model and model not in _models():
            raise ValueError(f'"{model}" is not installed. Run: ollama pull {model}')
        db.set_setting('default_model', model)
        db.set_setting('model_timeout', timeout)
        engine.ai.model = model
        engine.ai.timeout = int(timeout)
        for b in db.businesses():
            db.audit(b['id'], None, who, 'Default model changed', model or '(none)')
            break
        return redirect('/status')

    # --------------------------------------------------------------- lab
    def local_run(bid, rid):
        business(bid)
        try:
            return lab.get(bid, rid)
        except ValueError:
            abort(404)

    @app.get('/business/<int:bid>/lab')
    def lab_home(bid):
        return render_template('lab.html', b=business(bid), run=None, recent=lab.recent(bid), suites=SUITES)

    @app.post('/business/<int:bid>/lab/start')
    def lab_start(bid):
        business(bid)
        if request.form.get('suite'):
            if request.form['suite'] not in SUITES:
                raise ValueError('Unknown test suite.')
            cases = SUITES[request.form['suite']]['cases']
        else:
            try:
                rating = int(request.form.get('rating', '0'))
            except ValueError:
                raise ValueError('Choose a star rating.')
            cases = [{'id': 'custom', 'text': request.form.get('review', ''), 'rating': rating}]
        rid = lab.submit(bid, cases)
        url = f'/business/{bid}/lab/{rid}'
        if wants_json():
            return {'id': rid, 'url': url}, 202
        return redirect(url)

    @app.get('/business/<int:bid>/lab/<rid>')
    def lab_page(bid, rid):
        return render_template('lab.html', b=business(bid), run=local_run(bid, rid), recent=lab.recent(bid), suites=SUITES)

    @app.get('/business/<int:bid>/lab/<rid>/status')
    def lab_status(bid, rid):
        return local_run(bid, rid)

    @app.post('/business/<int:bid>/lab/<rid>/<action>')
    def lab_control(bid, rid, action):
        local_run(bid, rid)
        if action == 'cancel':
            lab.cancel(bid, rid)
        elif action == 'resume':
            lab.resume(bid, rid)
        else:
            abort(404)
        return redirect(f'/business/{bid}/lab/{rid}')

    @app.get('/business/<int:bid>/lab/<rid>/export.<fmt>')
    def lab_export(bid, rid, fmt):
        run = local_run(bid, rid)
        if fmt == 'json':
            body, mime = json.dumps(run, ensure_ascii=False, indent=2), 'application/json'
        elif fmt == 'csv':
            body, mime = csv_text(run), 'text/csv'
        else:
            abort(404)
        return Response(body, mimetype=mime, headers={'Content-Disposition': f'attachment; filename=local-evaluation-{rid}.{fmt}'})

    return app


def status_checks(db, engine):
    """One row per component: ok / warn / fail, what is wrong, and how to fix it."""
    checks = [{'name': 'App', 'state': 'ok', 'detail': 'Running on this computer only (127.0.0.1).', 'fix': ''}]
    try:
        result = db.health()
        checks.append({'name': 'Database', 'state': 'ok' if result == 'ok' else 'fail',
                       'detail': f'{db.path} ({result})',
                       'fix': '' if result == 'ok' else 'Stop the app and restore the newest file from data\\backups (see README, "Rollback").'})
    except Exception as exc:
        checks.append({'name': 'Database', 'state': 'fail', 'detail': type(exc).__name__,
                       'fix': 'Check the data folder is not read-only or open in another program.'})
    ai = engine.ai
    default = db.setting('default_model', '')
    try:
        installed = ai.models(fresh=True)
        checks.append({'name': 'Ollama', 'state': 'ok', 'detail': f'Running. Installed: {", ".join(installed) or "none"}',
                       'fix': '' if installed else 'Install a model: ollama pull qwen3:4b'})
        wanted = {default} | {b['model'] for b in db.businesses() if b['model']}
        wanted.discard('')
        missing = sorted(m for m in wanted if m not in installed)
        loaded = ai.loaded()
        checks.append({'name': 'Active model', 'state': 'fail' if missing else ('ok' if wanted else 'warn'),
                       'detail': (f'Default: {default or "not set"}. In memory now: {", ".join(loaded) or "none (first draft will load it)"}.'),
                       'fix': ('Not installed: ' + ', '.join(missing) + '. Run: ollama pull ' + missing[0]) if missing else
                       ('' if wanted else 'Choose a default model on the Status page (recommended: qwen3:4b).')})
    except Exception:
        checks.append({'name': 'Ollama', 'state': 'warn', 'detail': 'Not reachable at 127.0.0.1:11434.',
                       'fix': 'Open the Ollama app (or run "ollama serve"). Until then only blank 4-5 star reviews get drafts; '
                              'everything else waits for staff.'})
    for b in db.businesses():
        state = 'ok' if b['connection_status'] in ('Connected', 'Demo') else ('warn' if b['connection_status'] in ('Not connected', 'Disconnected') else 'fail')
        fix = ''
        if b['connection_status'] == 'Reconnect needed':
            fix = f'Close the app, run Connect-Google.cmd {b["id"]}, sign in as the owner/manager.'
        elif b['connection_status'] in ('Not connected', 'Disconnected') and not b['is_demo']:
            fix = 'Draft-only is fine. To fetch live reviews, see docs\\GOOGLE_SETUP.md.'
        elif state == 'fail':
            fix = b['last_error'] or 'Open the business page for details.'
        mode = {'off': 'publishing off', 'manual': 'manual publishing', 'auto': 'automatic publishing'}[b['publish_mode']]
        checks.append({'name': 'Google: ' + b['name'], 'state': state,
                       'detail': f"{b['connection_status']}; {mode}; last sync {time.strftime('%d %b %H:%M', time.localtime(b['last_poll'])) if b['last_poll'] else 'never'}",
                       'fix': fix})
    alerts = db.alerts(open_only=True)
    failed = [a for a in alerts if a['state'] == 'failed']
    smtp = db.setting('smtp', '')
    checks.append({'name': 'Alerts', 'state': 'fail' if failed else ('warn' if alerts else 'ok'),
                   'detail': f'{len(alerts)} open, {len(failed)} failed email. Email {"configured" if smtp else "not configured (dashboard only)"}.',
                   'fix': 'Open the inbox alert banner and retry or phone the owner.' if failed else ''})
    paused = db.setting('paused') == '1'
    if paused:
        checks.append({'name': 'Processing', 'state': 'warn', 'detail': 'Paused: no drafts or publishing.', 'fix': 'Press "Resume" at the top.'})
    return checks
