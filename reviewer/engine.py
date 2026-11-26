"""Review workflow: sync -> classify/draft -> staff review -> approve -> publish.

Rules that keep this safe:
- `self.lock` only guards short database transitions. Model calls and Google
  requests run outside it, so a slow model never freezes the dashboard.
- Publishing claims the job atomically (approved -> publishing). A second click,
  a retry or a second worker cannot send twice.
- If a send's outcome is unknown, the job goes to `publish_unknown` and only a
  readback from Google decides what happened. It is never blindly resent.
"""
import json
import threading
import time
from datetime import datetime
from reviewer.ai import make_draft, check_staff_reply, friendly_error
from reviewer.database import fingerprint, RATINGS
from reviewer.google import GoogleError
from reviewer.mock_google import MockGoogle
from reviewer.policy import classify, route, publish_blockers
from reviewer.text import digest

POLL_SECONDS = 1800
EDITS_PER_MINUTE = 8  # Google allows 10 review-reply edits per minute per profile; keep headroom


class PublishBlocked(ValueError):
    def __init__(self, reasons):
        super().__init__(' '.join(reasons))
        self.reasons = reasons


class Engine:
    def __init__(self, db, google, ai, mock=None):
        self.db = db
        self.google = google
        self.ai = ai
        self.mock = mock or MockGoogle(db)
        self.lock = threading.RLock()
        self.wake = threading.Event()

    # -------------------------------------------------------------- helpers
    def adapter(self, b):
        return self.mock if b.get('is_demo') else self.google

    def _business(self, bid):
        b = self.db.business(bid)
        if not b:
            raise ValueError('Business not found.')
        return b

    def _connection_problem(self, bid, err):
        status = {'auth': 'Reconnect needed', 'permission': 'Access denied', 'quota': 'Rate limited',
                  'network': 'Offline', 'server': 'Google error', 'not_found': 'Location not found'}.get(err.kind, 'Needs attention')
        delay = {'quota': 900, 'network': 300, 'server': 600}.get(err.kind, POLL_SECONDS)
        self.db.update_settings(bid, connection_status=status, last_error=str(err), last_poll=time.time(),
                                next_poll=time.time() + delay)
        self.db.audit(bid, None, 'system', 'Google problem', str(err))

    # ----------------------------------------------------------------- sync
    def poll(self, bid, actor='system'):
        """Fetch all reviews (every page). The first complete sync is a baseline."""
        b = self._business(bid)
        if not b['location']:
            raise ValueError('Connect a Google location first.')
        try:
            reviews = self.adapter(b).reviews(b)
        except GoogleError as err:
            self._connection_problem(bid, err)
            raise
        baseline = not b['baseline_done']
        counts = {'new': 0, 'edited': 0, 'replied_elsewhere': 0, 'skipped_old': 0, 'total': len(reviews)}
        cutoff = time.time() - 29 * 86400
        with self.lock:
            for review in reviews:
                try:
                    created = datetime.fromisoformat(review['createTime'].replace('Z', '+00:00')).timestamp()
                except (KeyError, ValueError, TypeError, AttributeError):
                    created = None
                if created is not None and created < cutoff and not review.get('reviewReply'):
                    # Outside our retention window; the inbox would delete it anyway.
                    counts['skipped_old'] += 1
                    continue
                jid, what = self.db.ingest(bid, review, baseline=baseline)
                if what in counts:
                    counts[what] += 1
                if created is None:
                    self.db.change_job(bid, jid, staff_note='Missing or invalid review date; check manually.', auto_eligible=0)
            self.db.update_settings(bid, baseline_done=1, last_poll=time.time(), next_poll=time.time() + POLL_SECONDS,
                                    last_error='', connection_status='Demo' if b['is_demo'] else 'Connected')
            note = f"{counts['total']} reviews, {counts['new']} new, {counts['edited']} edited"
            if baseline:
                note += ' (first sync: existing reviews kept as a backlog, never auto-published)'
            self.db.audit(bid, None, actor, 'Synced reviews', note)
        self.wake.set()
        return counts

    # ------------------------------------------------------------- drafting
    def request_draft(self, bid, jid, actor):
        """Queue (re)drafting. The background worker does the slow part."""
        with self.lock:
            j = self.db.job(bid, jid)
            if j['status'] in ('published', 'already_replied', 'publishing', 'publish_unknown', 'drafting', 'expired'):
                raise ValueError('This review cannot be redrafted in its current state.')
            self.db.change_job(bid, jid, status='new', draft='', draft_source='', approved_hash='', issues_hard='',
                               issues_soft='', error='', attempts=0, next_attempt=0)
            self.db.audit(bid, jid, actor, 'Draft requested', 'Regenerate' if j['draft'] else '')
        self.wake.set()

    def run_pending(self, limit=50):
        """Draft every waiting review (oldest first). Returns how many were processed."""
        done = 0
        for b in self.db.businesses():
            for j in reversed(self.db.jobs(b['id'], statuses=('new',))):
                if done >= limit or self.db.setting('paused') == '1':
                    return done
                if j['next_attempt'] > time.time():
                    continue
                self.process(b['id'], j['id'])
                done += 1
        return done

    def process(self, bid, jid):
        with self.lock:
            if not self.db.change_job(bid, jid, expect_status='new', status='drafting', error=''):
                return
            b = self._business(bid)
            j = self.db.job(bid, jid)
            recent = self.db.recent_replies(bid)
        review = json.loads(j['payload'])
        text = review.get('comment', '')
        rating = RATINGS.get(review.get('starRating'), 0)
        if not rating:
            with self.lock:
                self.db.change_job(bid, jid, status='needs_review', category='uncertain', route_label='Unknown rating',
                                   staff_note='Google returned no star rating; staff should check.', auto_eligible=0)
            return
        cls = classify(text, rating)
        r = route(cls)
        started = time.perf_counter()
        error = ''
        try:
            result = make_draft(self.ai, b, text, rating, recent)
        except Exception as exc:  # model down / timeout: keep the classification, show a fixable error
            result = None
            error = friendly_error(exc)
        with self.lock:
            current = self.db.job(bid, jid)
            if current['status'] != 'drafting' or current['fingerprint'] != j['fingerprint']:
                return  # review changed or staff acted meanwhile; their state wins
            if result:
                cls_d, r_d = result['classification'], result['route']
                values = dict(category=result['category'], concerns=json.dumps(cls_d['concerns']), route_label=r_d['label'],
                              staff_note=result['staff_note'], auto_eligible=int(bool(r_d['auto_eligible'])),
                              draft=result['reply'], draft_source=result['source'] if result['reply'] else '',
                              issues_hard=' '.join(result['issues_hard']), issues_soft=' '.join(result['issues_soft']),
                              model_calls=result['model_calls'], draft_seconds=result['elapsed'], status='needs_review',
                              facts_version=b['version'], error='')
                investigation, owner = r_d['investigation'], r_d['owner_alert']
            else:
                n = current['attempts'] + 1
                values = dict(category=cls.category, concerns=json.dumps(cls.concerns), route_label=r.label,
                              staff_note=cls.reason, auto_eligible=0, status='failed', attempts=n, error=error,
                              draft_seconds=round(time.perf_counter() - started, 2))
                investigation, owner = r.investigation, r.owner_alert
            if investigation and current['investigation'] == 'none':
                values['investigation'] = 'open'
            self.db.change_job(bid, jid, **values)
            self.db.audit(bid, jid, 'system', 'Classified', f"{values['category']}: {values['staff_note']}")
            if result and result['reply']:
                self.db.audit(bid, jid, 'system', 'Draft created',
                              f"{result['source']} draft in {result['elapsed']}s" + (f", {result['model_calls']} model call(s)" if result['model_calls'] else ''))
            if error:
                self.db.audit(bid, jid, 'system', 'Draft failed', error)
            if investigation and current['investigation'] == 'none':
                self.db.audit(bid, jid, 'system', 'Investigation opened', cls.reason)
            if owner:
                email = bool(b['notify_email'] and self.db.setting('smtp', ''))
                self.db.raise_alert(bid, jid, 'owner_action', state='pending' if email else 'dashboard')
        if result and self._auto_ready(bid, jid):
            try:
                self.approve(bid, jid, 'automatic', expected_fingerprint=j['fingerprint'],
                             expected_hash=digest(result['reply']), automatic=True)
                self.publish(bid, jid, 'automatic', expected_hash=digest(result['reply']), automatic=True)
            except (PublishBlocked, ValueError, GoogleError) as exc:
                self.db.audit(bid, jid, 'automatic', 'Automatic publish skipped', str(exc))

    def _auto_ready(self, bid, jid):
        b, j = self._business(bid), self.db.job(bid, jid)
        if b['publish_mode'] != 'auto' or j['issues_soft'] or j['issues_hard']:
            return False
        trial = dict(j, status='approved', approved_hash=digest(j['draft']), approved_fingerprint=j['fingerprint'],
                     approved_version=b['version'])
        return not publish_blockers(b, trial, paused=self.db.setting('paused') == '1', automatic=True,
                                    staff_approvals=self.db.count_actions(bid, 'Approved'))

    # -------------------------------------------------------- staff actions
    def save_draft(self, bid, jid, actor, text, expected_fingerprint):
        b = self._business(bid)
        text = str(text or '').strip()
        hard, _ = check_staff_reply(text, b)
        with self.lock:
            j = self.db.job(bid, jid)
            if j['status'] not in ('needs_review', 'approved', 'failed', 'baseline', 'new'):
                raise ValueError('This reply cannot be edited in its current state.')
            if expected_fingerprint != j['fingerprint']:
                raise ValueError('The customer changed this review. Reload and check it before editing.')
            if text == (j['draft'] or '').strip():
                return
            source = 'staff'
            self.db.change_job(bid, jid, draft=text, draft_source=source, approved_hash='', status='needs_review',
                               issues_hard=' '.join(hard), issues_soft='', error='', facts_version=b['version'])
            self.db.audit(bid, jid, actor, 'Edited reply', 'Approval cleared' if j['status'] == 'approved' else '')

    def approve(self, bid, jid, actor, *, expected_fingerprint, expected_hash, confirm_commitments=False, automatic=False):
        with self.lock:
            b, j = self._business(bid), self.db.job(bid, jid)
            if j['status'] != 'needs_review':
                raise ValueError('Only a reply waiting for review can be approved.')
            if expected_fingerprint != j['fingerprint']:
                raise ValueError('The customer changed this review. Reload and check the new text.')
            if not (j['draft'] or '').strip():
                raise ValueError('There is no reply to approve. Write one or generate a draft.')
            if expected_hash != digest(j['draft']):
                raise ValueError('The reply changed since you opened it. Reload and check it.')
            if j['category'] == 'sensitive' and j['draft_source'] != 'staff':
                raise ValueError('Sensitive reviews need a reply written by staff.')
            if j['issues_hard']:
                raise ValueError('Fix this first: ' + j['issues_hard'])
            if j['draft_source'] == 'staff':
                hard, commitments = check_staff_reply(j['draft'], b)
                if hard:
                    raise ValueError(' '.join(hard))
                if commitments and not confirm_commitments:
                    raise ValueError('This reply commits the business to: ' + ', '.join(commitments)
                                     + '. Tick "the owner agreed to this" to approve it.')
            self.db.change_job(bid, jid, expect_status='needs_review', status='approved', approved_hash=digest(j['draft']),
                               approved_fingerprint=j['fingerprint'], approved_version=b['version'], approved_by=actor,
                               approved_at=time.time(), error='')
            self.db.audit(bid, jid, actor, 'Approved' if not automatic else 'Auto-approved',
                          f'{j["draft_source"] or "staff"} reply approved')

    def publish(self, bid, jid, actor, *, expected_hash, automatic=False):
        """Send the approved reply. Returns the final status."""
        with self.lock:
            b, j = self._business(bid), self.db.job(bid, jid)
            reasons = publish_blockers(b, j, paused=self.db.setting('paused') == '1', automatic=automatic,
                                       staff_approvals=self.db.count_actions(bid, 'Approved'), expected_hash=expected_hash)
            if self.db.count_actions(bid, 'Publish attempt', time.time() - 60) >= EDITS_PER_MINUTE:
                reasons.append('Google allows about 10 reply changes a minute per profile. Wait a minute and try again.')
            if reasons:
                if j['status'] == 'approved':
                    self.db.audit(bid, jid, actor, 'Publish blocked', ' '.join(reasons))
                raise PublishBlocked(reasons)
            if not self.db.change_job(bid, jid, expect_status='approved', status='publishing', error=''):
                raise PublishBlocked(['Someone else is already publishing this reply.'])
            self.db.audit(bid, jid, actor, 'Publish attempt', f'to {b["name"]} ({b["location"]})')
        google = self.adapter(b)
        # Preflight: never overwrite a reply someone added on Google; never answer an edited review.
        try:
            current = google.review(b, j['resource'])
        except GoogleError as err:
            with self.lock:
                self.db.change_job(bid, jid, status='approved', error='Nothing was sent. ' + str(err))
                self.db.audit(bid, jid, 'system', 'Publish failed', 'Nothing sent: ' + str(err))
            if err.kind == 'auth':
                self._connection_problem(bid, err)
            raise
        if (current.get('reviewReply') or {}).get('comment'):
            with self.lock:
                self.db.ingest(bid, current)
                self.db.change_job(bid, jid, status='already_replied', approved_hash='',
                                   error='A reply already exists on Google; it was kept and ours was not sent.')
                self.db.audit(bid, jid, 'system', 'Publish skipped', 'Existing Google reply preserved')
            return 'already_replied'
        if fingerprint(current) != j['fingerprint']:
            with self.lock:
                self.db.change_job(bid, jid, status='needs_review')  # leave publishing first
                self.db.ingest(bid, current)
                self.db.audit(bid, jid, 'system', 'Publish skipped', 'Customer edited the review; approve again')
            self.wake.set()
            return 'changed'
        try:
            google.reply(b, j['resource'], j['draft'])
        except GoogleError as err:
            with self.lock:
                if err.maybe_sent:
                    self.db.change_job(bid, jid, status='publish_unknown',
                                       error='Google may have received the reply. Use "Check Google" before trying again.')
                    self.db.audit(bid, jid, 'system', 'Publish outcome unknown', str(err))
                    self.db.raise_alert(bid, jid, 'publish_unknown', state='dashboard')
                else:
                    self.db.change_job(bid, jid, status='approved', error='Not sent. ' + str(err))
                    self.db.audit(bid, jid, 'system', 'Publish failed', str(err))
                    if err.kind == 'auth':
                        self._connection_problem(bid, err)
            raise
        with self.lock:
            self.db.change_job(bid, jid, status='published', published_at=time.time(), error='')
            self.db.audit(bid, jid, actor, 'Published', 'Reply is live on Google' if not b['is_demo'] else 'Sent to the fictional demo profile')
        return 'published'

    def reconcile(self, bid, jid, actor):
        """Read Google to settle an unknown send. The only way out of publish_unknown."""
        b, j = self._business(bid), self.db.job(bid, jid)
        if j['status'] not in ('publish_unknown', 'publishing'):
            raise ValueError('Nothing to check for this review.')
        current = self.adapter(b).review(b, j['resource'])
        live = (current.get('reviewReply') or {}).get('comment', '')
        with self.lock:
            if live and live.strip() == j['draft'].strip():
                self.db.change_job(bid, jid, status='published', published_at=time.time(), error='')
                self.db.audit(bid, jid, actor, 'Checked Google', 'Our reply is live; marked published (not resent)')
                return 'published'
            if live:
                self.db.change_job(bid, jid, status='already_replied', error='A different reply is on Google; it was kept.')
                self.db.audit(bid, jid, actor, 'Checked Google', 'A different reply exists; kept it')
                return 'already_replied'
            self.db.change_job(bid, jid, status='approved', error='Google did not receive it. You can publish again.')
            self.db.audit(bid, jid, actor, 'Checked Google', 'No reply on Google; ready to publish again')
            return 'approved'

    def no_reply(self, bid, jid, actor, reason=''):
        with self.lock:
            j = self.db.job(bid, jid)
            if j['status'] in ('published', 'publishing', 'publish_unknown'):
                raise ValueError('This review already has a reply in progress.')
            self.db.change_job(bid, jid, status='no_reply', approved_hash='')
            self.db.audit(bid, jid, actor, 'Marked no reply needed', reason)

    def reopen(self, bid, jid, actor):
        with self.lock:
            j = self.db.job(bid, jid)
            if j['status'] not in ('no_reply', 'baseline'):
                raise ValueError('Only skipped or backlog reviews can be reopened.')
            self.db.change_job(bid, jid, status='needs_review' if j['draft'] else 'new')
            self.db.audit(bid, jid, actor, 'Reopened', '')
        self.wake.set()

    def add_note(self, bid, jid, actor, text):
        text = str(text or '').strip()
        if not text:
            raise ValueError('Write a note first.')
        self.db.job(bid, jid)
        self.db.audit(bid, jid, actor, 'Note', text[:2000])

    def set_next_action(self, bid, jid, actor, action, assignee=''):
        with self.lock:
            self.db.change_job(bid, jid, next_action=str(action or '')[:120], assignee=str(assignee or '')[:80])
            self.db.audit(bid, jid, actor, 'Next action set', f'{action} ({assignee or "unassigned"})')

    def set_investigation(self, bid, jid, actor, state, note=''):
        if state not in ('open', 'in_progress', 'resolved'):
            raise ValueError('Unknown investigation state.')
        note = str(note or '').strip()
        if state == 'resolved' and not note:
            raise ValueError('Describe how the investigation was resolved.')
        with self.lock:
            j = self.db.job(bid, jid)
            if j['investigation'] == state:
                return
            self.db.change_job(bid, jid, investigation=state)
            self.db.audit(bid, jid, actor, 'Investigation ' + state.replace('_', ' '), note)

    def acknowledge_alert(self, bid, aid, actor):
        self.db.update_alert(bid, aid, acknowledged_by=actor, acknowledged_at=time.time())
        self.db.audit(bid, None, actor, 'Alert acknowledged', str(aid))

    def disconnect(self, bid, actor):
        b = self._business(bid)
        with self.lock:
            if not b['is_demo'] and self.google:
                self.google.disconnect(bid)
            self.db.update_settings(bid, consent=0, publish_mode='off', location='', connection_status='Disconnected',
                                    baseline_done=0, is_demo=0, place_id='')
            self.db.forget_google_content(bid)
            self.db.audit(bid, None, actor, 'Disconnected Google',
                          'Token deleted; cached review text removed; open investigations kept without review text')

    # ----------------------------------------------------------------- loop
    def cycle(self):
        self.db.purge()
        if self.db.setting('paused') == '1':
            return
        for b in self.db.businesses():
            if b['location'] and time.time() >= (b['next_poll'] or 0):
                try:
                    self.poll(b['id'])
                except Exception:
                    pass  # recorded on the business; the dashboard shows it
        self.run_pending()
