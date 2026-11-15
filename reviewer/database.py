"""Local state. Google review content expires after 29 days, including drafts."""
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def fingerprint(review):
    fields=[review.get(k,'') for k in ('comment','starRating','updateTime')]
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()


class Database:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
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
            CREATE TABLE IF NOT EXISTS events (business_id INTEGER NOT NULL REFERENCES businesses(id), occurred REAL NOT NULL, action TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            ''')
        with self.connect() as c:
            for table,column,definition in [('businesses','notify_email',"TEXT DEFAULT ''"),('jobs','alert_state',"TEXT DEFAULT 'pending'"),('jobs','alert_attempts','INTEGER DEFAULT 0')]:
                if column not in {x[1] for x in c.execute('PRAGMA table_info('+table+')')}:
                    c.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+definition)
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=15); c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA secure_delete=ON')
        try:
            with c: yield c
        finally: c.close()
    def businesses(self):
        with self.connect() as c: return [dict(x) for x in c.execute('SELECT * FROM businesses ORDER BY id')]
    def business(self,bid):
        with self.connect() as c:
            x=c.execute('SELECT * FROM businesses WHERE id=?',(bid,)).fetchone()
            return dict(x) if x else None
    def save_business(self,data):
        fields=('name','facts','contact','tone','language','website','model')
        values=[str(data.get(k,{'tone':'Warm and professional','language':'English'}.get(k,''))).strip() for k in fields]
        if not values[0] or len(values[0])>200: raise ValueError('Business name required; maximum 200 characters')
        if any(len(v)>12000 for v in values): raise ValueError('Business field too long')
        with self.connect() as c:
            if data.get('id'):
                bid=int(data['id'])
                c.execute('UPDATE businesses SET '+','.join(k+'=?' for k in fields)+',version=version+1,facts_approved=0,auto_enabled=0 WHERE id=?',(*values,bid))
                return bid
            return c.execute('INSERT INTO businesses ('+','.join(fields)+') VALUES (?,?,?,?,?,?,?)',values).lastrowid
    def update_settings(self,bid,**values):
        allowed={'consent','facts_approved','auto_enabled','pilot_verified','baseline_done','location','place_id','connection_status','last_poll','last_error','consent_at','notify_email'}
        if not values or set(values)-allowed: raise ValueError('Invalid settings')
        with self.connect() as c:
            c.execute('UPDATE businesses SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),bid))
    def setting(self,key,default='0'):
        with self.connect() as c:
            x=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            return x[0] if x else default
    def set_setting(self,key,value):
        with self.connect() as c: c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,str(value)))
    def ingest(self,bid,review,baseline=False):
        resource=review.get('name','')
        if not resource: raise ValueError('Missing review resource')
        fp=fingerprint(review)
        with self.connect() as c:
            old=c.execute('SELECT * FROM jobs WHERE business_id=? AND resource=?',(bid,resource)).fetchone()
            if old and old['fingerprint']==fp:
                # Preserve ambiguous writes for reconciliation, not re-generation.
                if review.get('reviewReply') and old['status'] not in ('publishing','publish_unknown','published'):
                    c.execute("UPDATE jobs SET status='already_replied',payload=? WHERE id=?",(json.dumps(review),old['id']))
                return old['id']
            status='already_replied' if review.get('reviewReply') else 'needs_approval' if old else 'baseline' if baseline else 'pending'
            c.execute('''INSERT INTO jobs (business_id,resource,payload,fingerprint,first_seen,status)
             VALUES (?,?,?,?,?,?) ON CONFLICT(business_id,resource) DO UPDATE SET
             payload=excluded.payload,fingerprint=excluded.fingerprint,status=excluded.status,
             draft='',facts_version=0,attempts=0,error='',next_attempt=0''',
             (bid,resource,json.dumps(review),fp,time.time(),status))
            return c.execute('SELECT id FROM jobs WHERE business_id=? AND resource=?',(bid,resource)).fetchone()[0]
    def jobs(self,bid):
        with self.connect() as c: return [dict(x) for x in c.execute('SELECT * FROM jobs WHERE business_id=? ORDER BY id DESC',(bid,))]
    def job(self,bid,jid):
        with self.connect() as c:
            x=c.execute('SELECT * FROM jobs WHERE business_id=? AND id=?',(bid,jid)).fetchone()
            if not x: raise ValueError('Review not found for this business')
            return dict(x)
    def change_job(self,bid,jid,**values):
        allowed={'status','draft','risk','reason','facts_version','attempts','next_attempt','investigation','error','alert_state','alert_attempts'}
        if not values or set(values)-allowed: raise ValueError('Invalid job fields')
        with self.connect() as c:
            old=c.execute('SELECT status,investigation FROM jobs WHERE business_id=? AND id=?',(bid,jid)).fetchone()
            if not old: raise ValueError('Review not found for this business')
            c.execute('UPDATE jobs SET '+','.join(k+'=?' for k in values)+' WHERE business_id=? AND id=?',(*values.values(),bid,jid))
            if values.get('status') in ('published','needs_approval','failed') and values['status']!=old['status']:
                c.execute('INSERT INTO events VALUES (?,?,?)',(bid,time.time(),values['status']))
            if values.get('investigation')=='open' and old['investigation']!='open':
                c.execute('INSERT INTO events VALUES (?,?,?)',(bid,time.time(),'investigations_opened'))
    def purge(self):
        with self.connect() as c:
            c.execute('DELETE FROM jobs WHERE first_seen < ?',(time.time()-29*86400,))
            c.execute('DELETE FROM events WHERE occurred < ?',(time.time()-400*86400,))
