"""Local SQLite state.

Google review content (text, reviewer name, drafts) is removed after 29 days,
inside Google's 30-day caching limit. Case records (status, staff notes,
investigation history) can outlive the text so open investigations are not
lost; their copy of the review text is scrubbed.

Upgrades are additive. Before changing an older database the file is copied to
data/backups/, so a rollback is "stop the app, copy the backup back".
"""
import hashlib
import json
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = 3
RETENTION_DAYS = 29

BUSINESS_TEXT = ('name', 'facts', 'contact', 'voice', 'language', 'website', 'model', 'examples',
                 'sign_off', 'owner_name', 'notify_email')
KNOWLEDGE = ('name', 'facts', 'contact', 'voice', 'language', 'examples', 'sign_off')
FINAL = ('published', 'already_replied', 'no_reply')
STATUS_LABELS = {
    'new': 'Waiting for draft', 'drafting': 'Drafting', 'needs_review': 'Needs review',
    'approved': 'Approved, not published', 'publishing': 'Publishing', 'publish_unknown': 'Publish result unknown',
    'published': 'Published', 'already_replied': 'Replied on Google', 'failed': 'Draft failed',
    'no_reply': 'No reply needed', 'baseline': 'Before first sync', 'expired': 'Text expired',
}


def fingerprint(review):
    """Customer-authored content only. A change means drafts/approvals are stale."""
    fields = [review.get(k, '') for k in ('comment', 'starRating', 'updateTime')]
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


RATINGS = {'ONE': 1, 'TWO': 2, 'THREE': 3, 'FOUR': 4, 'FIVE': 5}


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.last_backup = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists() and self.path.stat().st_size > 0
        if existed:
            self._backup_if_upgrading()
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS businesses (
             id INTEGER PRIMARY KEY, name TEXT NOT NULL, facts TEXT NOT NULL DEFAULT '',
             contact TEXT NOT NULL DEFAULT '', tone TEXT NOT NULL DEFAULT 'Warm and professional',
             language TEXT NOT NULL DEFAULT 'English', website TEXT NOT NULL DEFAULT '',
             location TEXT NOT NULL DEFAULT '', place_id TEXT NOT NULL DEFAULT '',
             model TEXT NOT NULL DEFAULT '', consent INTEGER DEFAULT 0,
             facts_approved INTEGER DEFAULT 0, auto_enabled INTEGER DEFAULT 0,
             pilot_verified INTEGER DEFAULT 0, baseline_done INTEGER DEFAULT 0,
             version INTEGER DEFAULT 1, connection_status TEXT DEFAULT 'Not connected',
             last_poll REAL DEFAULT 0, last_error TEXT DEFAULT '', consent_at REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS jobs (
             id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
             resource TEXT NOT NULL, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
             first_seen REAL NOT NULL, status TEXT NOT NULL, draft TEXT DEFAULT '',
             risk TEXT DEFAULT '', reason TEXT DEFAULT '', facts_version INTEGER DEFAULT 0,
             attempts INTEGER DEFAULT 0, next_attempt REAL DEFAULT 0,
             investigation TEXT DEFAULT 'none', error TEXT DEFAULT '',
             UNIQUE(business_id,resource));
            CREATE TABLE IF NOT EXISTS events (business_id INTEGER NOT NULL REFERENCES businesses(id),
             occurred REAL NOT NULL, action TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
             id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
             job_id INTEGER, at REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS audit_job ON audit(business_id, job_id);
            CREATE TABLE IF NOT EXISTS alerts (
             id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
             job_id INTEGER NOT NULL, kind TEXT NOT NULL, created REAL NOT NULL,
             state TEXT NOT NULL DEFAULT 'dashboard', attempts INTEGER NOT NULL DEFAULT 0,
             last_error TEXT NOT NULL DEFAULT '', sent_at REAL DEFAULT 0,
             acknowledged_by TEXT NOT NULL DEFAULT '', acknowledged_at REAL DEFAULT 0,
             UNIQUE(business_id, job_id, kind));
            CREATE TABLE IF NOT EXISTS mock_reviews (
             business_id INTEGER NOT NULL, review_id TEXT NOT NULL, data TEXT NOT NULL,
             reply TEXT NOT NULL DEFAULT '', reply_time TEXT NOT NULL DEFAULT '', post_count INTEGER NOT NULL DEFAULT 0,
             PRIMARY KEY (business_id, review_id));
            ''')
            columns = [
                ('businesses', 'notify_email', "TEXT DEFAULT ''"),
                ('businesses', 'voice', "TEXT NOT NULL DEFAULT ''"),
                ('businesses', 'examples', "TEXT NOT NULL DEFAULT ''"),
                ('businesses', 'sign_off', "TEXT NOT NULL DEFAULT ''"),
                ('businesses', 'owner_name', "TEXT NOT NULL DEFAULT ''"),
                ('businesses', 'publish_mode', "TEXT NOT NULL DEFAULT 'off'"),
                ('businesses', 'is_demo', 'INTEGER NOT NULL DEFAULT 0'),
                ('businesses', 'pending_facts', "TEXT NOT NULL DEFAULT ''"),
                ('businesses', 'pending_source', "TEXT NOT NULL DEFAULT ''"),
                ('businesses', 'pending_at', 'REAL DEFAULT 0'),
                ('businesses', 'facts_sources', "TEXT NOT NULL DEFAULT ''"),
                ('businesses', 'next_poll', 'REAL DEFAULT 0'),
                ('jobs', 'alert_state', "TEXT DEFAULT 'pending'"),
                ('jobs', 'alert_attempts', 'INTEGER DEFAULT 0'),
                ('jobs', 'category', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'concerns', "TEXT NOT NULL DEFAULT '[]'"),
                ('jobs', 'route_label', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'staff_note', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'auto_eligible', 'INTEGER NOT NULL DEFAULT 0'),
                ('jobs', 'draft_source', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'issues_hard', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'issues_soft', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'model_calls', 'INTEGER NOT NULL DEFAULT 0'),
                ('jobs', 'approved_hash', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'approved_fingerprint', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'approved_version', 'INTEGER NOT NULL DEFAULT -1'),
                ('jobs', 'approved_by', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'approved_at', 'REAL DEFAULT 0'),
                ('jobs', 'published_at', 'REAL DEFAULT 0'),
                ('jobs', 'next_action', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'assignee', "TEXT NOT NULL DEFAULT ''"),
                ('jobs', 'baseline', 'INTEGER NOT NULL DEFAULT 0'),
                ('jobs', 'updated', 'REAL DEFAULT 0'),
                ('jobs', 'draft_seconds', 'REAL DEFAULT 0'),
            ]
            for table, column, definition in columns:
                if column not in {x[1] for x in c.execute('PRAGMA table_info(' + table + ')')}:
                    c.execute('ALTER TABLE ' + table + ' ADD COLUMN ' + column + ' ' + definition)
            version = int(self._get_setting(c, 'schema', '1'))
            if version < 3:
                # Older statuses -> current ones. Publishing restarts disabled.
                c.execute("UPDATE jobs SET status='new' WHERE status IN ('pending','retry')")
                c.execute("UPDATE jobs SET status='needs_review' WHERE status='needs_approval'")
                c.execute("UPDATE jobs SET baseline=1 WHERE status='baseline'")
                c.execute("UPDATE jobs SET category=risk WHERE category='' AND risk IN ('routine','complaint','sensitive')")
                c.execute("UPDATE businesses SET publish_mode='off', auto_enabled=0")
                c.execute("UPDATE businesses SET voice=tone WHERE voice=''")
            # A crash mid-send leaves 'publishing'; never assume either outcome.
            c.execute("UPDATE jobs SET status='publish_unknown', error='App stopped while publishing; check Google before retrying' "
                      "WHERE status='publishing'")
            c.execute("UPDATE jobs SET status='new' WHERE status='drafting'")
            c.execute("INSERT OR REPLACE INTO settings VALUES ('schema', ?)", (str(SCHEMA),))

    # ------------------------------------------------------------ plumbing
    def _backup_if_upgrading(self):
        c = sqlite3.connect(self.path)
        try:
            row = c.execute("SELECT value FROM settings WHERE key='schema'").fetchone()
            version = int(row[0]) if row else 1
        except sqlite3.Error:
            version = 1
        finally:
            c.close()
        if version < SCHEMA:
            folder = self.path.parent / 'backups'
            folder.mkdir(exist_ok=True)
            target = folder / f'{self.path.stem}-schema{version}-{time.strftime("%Y%m%d-%H%M%S")}.db'
            src = sqlite3.connect(self.path)
            dst = sqlite3.connect(target)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            self.last_backup = target

    @staticmethod
    def _get_setting(c, key, default):
        row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA secure_delete=ON')
        c.execute('PRAGMA journal_mode=WAL')  # dashboard reads never wait on the background worker
        c.execute('PRAGMA synchronous=NORMAL')
        try:
            with c:
                yield c
        finally:
            c.close()

    def setting(self, key, default='0'):
        with self.connect() as c:
            return self._get_setting(c, key, default)

    def set_setting(self, key, value):
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, str(value)))

    def health(self):
        with self.connect() as c:
            return c.execute('PRAGMA quick_check').fetchone()[0]

    # ---------------------------------------------------------- businesses
    def businesses(self):
        with self.connect() as c:
            return [dict(x) for x in c.execute('SELECT * FROM businesses ORDER BY name COLLATE NOCASE, id')]

    def business(self, bid):
        with self.connect() as c:
            x = c.execute('SELECT * FROM businesses WHERE id=?', (bid,)).fetchone()
            return dict(x) if x else None

    def save_business(self, data, actor='system'):
        updating = bool(data.get('id'))
        values = {k: str(data.get(k) or '').strip() for k in BUSINESS_TEXT if k in data or not updating}
        if not updating and not values['language']:
            values['language'] = 'English'
        if 'name' in values and (not values['name'] or len(values['name']) > 200):
            raise ValueError('Business name is required (maximum 200 characters).')
        if any(len(v) > 12000 for v in values.values()):
            raise ValueError('One of the business fields is too long (maximum 12,000 characters).')
        with self.connect() as c:
            if data.get('id'):
                bid = int(data['id'])
                old = c.execute('SELECT * FROM businesses WHERE id=?', (bid,)).fetchone()
                if not old:
                    raise ValueError('Business not found.')
                changed = [k for k in values if str(old[k] or '') != values[k]]
                if not changed:
                    return bid
                sets = [k + '=?' for k in changed]
                if any(k in KNOWLEDGE for k in changed):
                    # Drafts and approvals were made with the old wording; make them stale.
                    sets.append('version=version+1')
                if any(k in ('facts', 'contact') for k in changed):
                    sets.append('facts_approved=0')
                if any(k in KNOWLEDGE for k in changed):
                    sets.append("publish_mode=CASE publish_mode WHEN 'auto' THEN 'manual' ELSE publish_mode END")
                c.execute('UPDATE businesses SET ' + ','.join(sets) + ' WHERE id=?', (*[values[k] for k in changed], bid))
                self._audit(c, bid, None, actor, 'Business details changed', ', '.join(changed))
                return bid
            values.setdefault('voice', '')
            values['tone'] = values['voice'] or 'Warm and professional'
            cols = list(values)
            bid = c.execute('INSERT INTO businesses (' + ','.join(cols) + ') VALUES (' + ','.join('?' * len(cols)) + ')',
                            [values[k] for k in cols]).lastrowid
            self._audit(c, bid, None, actor, 'Business added', values['name'])
            return bid

    def update_settings(self, bid, **values):
        allowed = {'consent', 'facts_approved', 'auto_enabled', 'pilot_verified', 'baseline_done', 'location', 'place_id',
                   'connection_status', 'last_poll', 'last_error', 'consent_at', 'notify_email', 'publish_mode',
                   'is_demo', 'pending_facts', 'pending_source', 'pending_at', 'facts', 'facts_sources', 'next_poll',
                   'model'}
        if not values or set(values) - allowed:
            raise ValueError('Invalid settings')
        if 'publish_mode' in values and values['publish_mode'] not in ('off', 'manual', 'auto'):
            raise ValueError('Invalid publishing mode')
        with self.connect() as c:
            c.execute('UPDATE businesses SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?', (*values.values(), bid))

    # ---------------------------------------------------------------- jobs
    def ingest(self, bid, review, baseline=False):
        """Store a fetched review. Returns (job_id, what_happened)."""
        resource = review.get('name', '')
        if not resource:
            raise ValueError('Missing review resource')
        fp = fingerprint(review)
        reply = (review.get('reviewReply') or {}).get('comment', '')
        now = time.time()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM jobs WHERE business_id=? AND resource=?', (bid, resource)).fetchone()
            if not old:
                status = 'already_replied' if reply else 'baseline' if baseline else 'new'
                jid = c.execute('''INSERT INTO jobs (business_id,resource,payload,fingerprint,first_seen,status,baseline,updated)
                                   VALUES (?,?,?,?,?,?,?,?)''',
                                (bid, resource, json.dumps(review), fp, now, status, int(bool(baseline)), now)).lastrowid
                return jid, 'new'
            jid = old['id']
            if old['fingerprint'] == fp:
                c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(review), jid))
                if reply and old['status'] not in FINAL + ('publishing', 'publish_unknown'):
                    # Someone replied directly on Google: preserve it, never overwrite.
                    c.execute("UPDATE jobs SET status='already_replied', approved_hash='', updated=? WHERE id=?", (now, jid))
                    self._audit(c, bid, jid, 'system', 'Reply found on Google', 'Existing Google reply preserved; local draft not sent.')
                    return jid, 'replied_elsewhere'
                return jid, 'unchanged'
            # Customer edited the review.
            if old['status'] in ('published', 'already_replied'):
                c.execute('UPDATE jobs SET payload=?, fingerprint=?, updated=? WHERE id=?', (json.dumps(review), fp, now, jid))
                self._audit(c, bid, jid, 'system', 'Customer edited review after reply', 'Check whether the public reply still fits.')
                return jid, 'edited_after_reply'
            status = 'already_replied' if reply else ('baseline' if old['status'] == 'baseline' else 'new')
            if old['status'] in ('publishing', 'publish_unknown'):
                status = old['status']  # reconciliation must finish first
            c.execute('''UPDATE jobs SET payload=?, fingerprint=?, status=?, draft='', draft_source='', approved_hash='',
                         issues_hard='', issues_soft='', error='', attempts=0, next_attempt=0, updated=? WHERE id=?''',
                      (json.dumps(review), fp, status, now, jid))
            self._audit(c, bid, jid, 'system', 'Customer edited review', 'Draft and any approval cleared.')
            return jid, 'edited'

    @staticmethod
    def _decorate(row):
        j = dict(row)
        p = json.loads(j['payload'] or '{}')
        j['comment'] = p.get('comment', '')
        j['rating'] = RATINGS.get(p.get('starRating'), 0)
        j['reviewer'] = (p.get('reviewer') or {}).get('displayName') or 'Google reviewer'
        j['created'] = p.get('createTime', '')
        j['google_reply'] = (p.get('reviewReply') or {}).get('comment', '')
        j['concern_list'] = json.loads(j.get('concerns') or '[]')
        j['status_label'] = STATUS_LABELS.get(j['status'], j['status'])
        return j

    def jobs(self, bid=None, statuses=None, since=None, until=None):
        sql, args = 'SELECT * FROM jobs WHERE 1=1', []
        if bid is not None:
            sql += ' AND business_id=?'
            args.append(bid)
        if statuses:
            sql += ' AND status IN (' + ','.join('?' * len(statuses)) + ')'
            args += list(statuses)
        if since:
            sql += ' AND first_seen>=?'
            args.append(since)
        if until:
            sql += ' AND first_seen<?'
            args.append(until)
        with self.connect() as c:
            return [self._decorate(x) for x in c.execute(sql + ' ORDER BY first_seen DESC, id DESC', args)]

    def job(self, bid, jid):
        with self.connect() as c:
            x = c.execute('SELECT * FROM jobs WHERE business_id=? AND id=?', (bid, jid)).fetchone()
            if not x:
                raise ValueError('Review not found for this business.')
            return self._decorate(x)

    JOB_FIELDS = {'status', 'draft', 'risk', 'reason', 'facts_version', 'attempts', 'next_attempt', 'investigation', 'error',
                  'alert_state', 'alert_attempts', 'category', 'concerns', 'route_label', 'staff_note', 'auto_eligible',
                  'draft_source', 'issues_hard', 'issues_soft', 'model_calls', 'approved_hash', 'approved_fingerprint',
                  'approved_version', 'approved_by', 'approved_at', 'published_at', 'next_action', 'assignee', 'baseline',
                  'draft_seconds', 'payload'}

    def change_job(self, bid, jid, expect_status=None, **values):
        """Update a job; with expect_status the change only happens from that status (atomic claim).

        Returns True if a row changed.
        """
        if not values or set(values) - self.JOB_FIELDS:
            raise ValueError('Invalid job fields')
        values['updated'] = time.time()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT status, investigation FROM jobs WHERE business_id=? AND id=?', (bid, jid)).fetchone()
            if not old:
                raise ValueError('Review not found for this business.')
            where, args = 'business_id=? AND id=?', [bid, jid]
            if expect_status is not None:
                states = (expect_status,) if isinstance(expect_status, str) else tuple(expect_status)
                where += ' AND status IN (' + ','.join('?' * len(states)) + ')'
                args += list(states)
            n = c.execute('UPDATE jobs SET ' + ','.join(k + '=?' for k in values) + ' WHERE ' + where,
                          (*values.values(), *args)).rowcount
            if n and values.get('status') in ('published', 'needs_review', 'failed') and values['status'] != old['status']:
                c.execute('INSERT INTO events VALUES (?,?,?)', (bid, time.time(),
                          'needs_approval' if values['status'] == 'needs_review' else values['status']))
            if n and values.get('investigation') == 'open' and old['investigation'] != 'open':
                c.execute('INSERT INTO events VALUES (?,?,?)', (bid, time.time(), 'investigations_opened'))
            return bool(n)

    # --------------------------------------------------------------- audit
    @staticmethod
    def _audit(c, bid, jid, actor, action, detail=''):
        c.execute('INSERT INTO audit (business_id, job_id, at, actor, action, detail) VALUES (?,?,?,?,?,?)',
                  (bid, jid, time.time(), str(actor or 'unknown')[:80], action[:120], str(detail or '')[:2000]))

    def audit(self, bid, jid, actor, action, detail=''):
        with self.connect() as c:
            self._audit(c, bid, jid, actor, action, detail)

    def history(self, bid, jid=None, limit=200):
        with self.connect() as c:
            if jid is None:
                rows = c.execute('SELECT * FROM audit WHERE business_id=? ORDER BY at DESC, id DESC LIMIT ?', (bid, limit))
            else:
                rows = c.execute('SELECT * FROM audit WHERE business_id=? AND job_id=? ORDER BY at, id', (bid, jid))
            return [dict(r) for r in rows]

    def count_actions(self, bid, action, since=0):
        with self.connect() as c:
            return c.execute('SELECT COUNT(*) FROM audit WHERE business_id=? AND action=? AND at>=?', (bid, action, since)).fetchone()[0]

    def recent_replies(self, bid, n=6):
        with self.connect() as c:
            rows = c.execute("SELECT draft FROM jobs WHERE business_id=? AND draft<>'' ORDER BY updated DESC LIMIT ?", (bid, n))
            return [r[0] for r in rows]

    # -------------------------------------------------------------- alerts
    def raise_alert(self, bid, jid, kind, state='pending'):
        """Idempotent: one alert per (business, review, kind)."""
        with self.connect() as c:
            n = c.execute('INSERT OR IGNORE INTO alerts (business_id, job_id, kind, created, state) VALUES (?,?,?,?,?)',
                          (bid, jid, kind, time.time(), state)).rowcount
            if n:
                self._audit(c, bid, jid, 'system', 'Alert raised', kind.replace('_', ' '))
            return bool(n)

    def alerts(self, bid=None, open_only=False):
        sql = '''SELECT a.*, b.name AS business_name FROM alerts a JOIN businesses b ON b.id=a.business_id WHERE 1=1'''
        args = []
        if bid is not None:
            sql += ' AND a.business_id=?'
            args.append(bid)
        if open_only:
            sql += " AND a.acknowledged_at=0"
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql + ' ORDER BY a.created DESC', args)]

    def update_alert(self, bid, aid, **values):
        allowed = {'state', 'attempts', 'last_error', 'sent_at', 'acknowledged_by', 'acknowledged_at'}
        if not values or set(values) - allowed:
            raise ValueError('Invalid alert fields')
        with self.connect() as c:
            n = c.execute('UPDATE alerts SET ' + ','.join(k + '=?' for k in values) + ' WHERE business_id=? AND id=?',
                          (*values.values(), bid, aid)).rowcount
            if not n:
                raise ValueError('Alert not found for this business.')

    # ----------------------------------------------------------- retention
    def scrub(self, c, where, args):
        """Remove Google content but keep the case (status, notes, history)."""
        for row in c.execute('SELECT id, payload FROM jobs WHERE ' + where, args).fetchall():
            p = json.loads(row['payload'] or '{}')
            kept = {'name': p.get('name', ''), 'starRating': p.get('starRating', ''), 'createTime': p.get('createTime', ''),
                    'comment': '', 'expired': True}
            c.execute("UPDATE jobs SET payload=?, draft='', approved_hash='' WHERE id=?", (json.dumps(kept), row['id']))

    def purge(self, now=None):
        now = now or time.time()
        cutoff = now - RETENTION_DAYS * 86400
        with self.connect() as c:
            keep = ("(investigation IN ('open','in_progress') OR EXISTS "
                    "(SELECT 1 FROM audit a WHERE a.job_id=jobs.id AND a.business_id=jobs.business_id AND a.action='Note'))")
            self.scrub(c, 'first_seen<? AND ' + keep + " AND payload NOT LIKE '%\"expired\": true%'", (cutoff,))
            c.execute("UPDATE jobs SET status='expired' WHERE first_seen<? AND status NOT IN ('published','already_replied','no_reply','expired') AND " + keep, (cutoff,))
            gone = [r[0] for r in c.execute('SELECT id FROM jobs WHERE first_seen<? AND NOT ' + keep, (cutoff,))]
            for jid in gone:
                c.execute('DELETE FROM alerts WHERE job_id=?', (jid,))
                c.execute('DELETE FROM audit WHERE job_id=?', (jid,))
            c.execute('DELETE FROM jobs WHERE first_seen<? AND NOT ' + keep, (cutoff,))
            c.execute('DELETE FROM events WHERE occurred<?', (now - 400 * 86400,))

    def forget_google_content(self, bid):
        """On disconnect: drop cached review text for this business, keep open cases."""
        with self.connect() as c:
            keep = "investigation IN ('open','in_progress')"
            self.scrub(c, 'business_id=? AND ' + keep, (bid,))
            gone = [r[0] for r in c.execute('SELECT id FROM jobs WHERE business_id=? AND NOT ' + keep, (bid,))]
            for jid in gone:
                c.execute('DELETE FROM alerts WHERE job_id=?', (jid,))
                c.execute('DELETE FROM audit WHERE job_id=?', (jid,))
            c.execute('DELETE FROM jobs WHERE business_id=? AND NOT ' + keep, (bid,))
