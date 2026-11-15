"""Polling and reply state machine. Never blindly repeat an uncertain PUT."""
import json
from datetime import datetime,timezone
import threading
import time
from reviewer.database import fingerprint
from reviewer.ai import assess,validate_output,generate_checked

RATINGS={'ONE':1,'TWO':2,'THREE':3,'FOUR':4,'FIVE':5}


class Engine:
    def __init__(self,db,google,ai):
        self.db=db; self.google=google; self.ai=ai; self.lock=threading.RLock()
    def poll(self,bid):
        with self.lock:
            b=self.db.business(bid)
            if not b: raise ValueError('Business not found')
            reviews=self.google.reviews(b) # Full pagination must succeed before baseline commits.
            baseline=not b['baseline_done']
            for review in reviews:
                try:
                    created=datetime.fromisoformat(review['createTime'].replace('Z','+00:00')).timestamp()
                    if created < time.time()-29*86400: continue
                    valid_time=created <= time.time()+300
                except (KeyError,ValueError,TypeError): valid_time=False
                jid=self.db.ingest(bid,review,baseline=baseline)
                if not valid_time:
                    self.db.change_job(bid,jid,status='needs_approval',reason='Missing or invalid review date; inspect manually')
            self.db.update_settings(bid,baseline_done=1,last_poll=time.time(),last_error='',connection_status='Connected')
    def process(self,bid,jid,allow_auto=True):
        with self.lock:
            b=self.db.business(bid); j=self.db.job(bid,jid)
            if self.db.setting('paused')=='1' or j['status'] not in ('pending','retry','publishing','publish_unknown'): return
            try:
                if j['status'] in ('publishing','publish_unknown'):
                    current=self.google.review(b,j['resource'])
                    reply=current.get('reviewReply',{}).get('comment','')
                    if reply==j['draft'] and reply:
                        self.db.change_job(bid,jid,status='published',error='')
                    else:
                        self.db.change_job(bid,jid,status='needs_approval',error='Uncertain previous write: inspect Google before approving again')
                    return
                review=json.loads(j['payload'])
                if review.get('reviewReply'):
                    self.db.change_job(bid,jid,status='already_replied'); return
                rating=RATINGS.get(review.get('starRating'),0)
                text=review.get('comment','')
                risk=assess(text,rating)
                if risk=='sensitive':
                    self.db.change_job(bid,jid,status='needs_approval',risk=risk,reason='Sensitive content requires staff-written reply',investigation='open',facts_version=b['version']); return
                if not b['facts_approved']:
                    self.db.change_job(bid,jid,status='needs_approval',reason='Approve business facts first'); return
                result=generate_checked(self.ai,b,{'comment':text[:6000],'rating':rating})
                risk=result['risk']
                if result['status']!='draft':
                    self.db.change_job(bid,jid,status='needs_approval',draft='',risk=risk,reason=result['reason'],investigation='open' if risk!='routine' else 'none',facts_version=b['version'],error=''); return
                self.db.change_job(bid,jid,status='needs_approval',draft=result['reply'],risk=risk,reason=result['reason'],facts_version=b['version'],investigation='open' if risk!='routine' else 'none',error='')
                if allow_auto and all(b[k] for k in ('consent','facts_approved','auto_enabled','pilot_verified')) and risk=='routine': self._publish(bid,jid)
            except Exception as exc:
                # No response bodies or secrets in user-facing logs.
                j=self.db.job(bid,jid)
                if j['status'] in ('publishing','publish_unknown'):
                    self.db.change_job(bid,jid,status='publish_unknown',error='Publication outcome unknown; readback required')
                else:
                    n=j['attempts']+1
                    self.db.change_job(bid,jid,status='failed' if n>=3 else 'retry',attempts=n,next_attempt=time.time()+min(1800,60*2**n),error='Processing failed ('+type(exc).__name__+'); check Google connection and local model')
    def approve(self,bid,jid,text=None,*,expected_fp=None,expected_version=None):
        with self.lock:
            b=self.db.business(bid); j=self.db.job(bid,jid)
            if j['status']!='needs_approval': raise ValueError('Only a held draft can be approved')
            if expected_fp!=j['fingerprint'] or str(expected_version)!=str(b['version']):
                raise ValueError('The review or business information changed. Reload and review the current draft.')
            if text is not None:
                output={'reply':text.strip(),'risk':j['risk'] or 'sensitive','reason':'Staff-reviewed reply'}
                if not validate_output(output,b['contact']): raise ValueError('Reply failed validation: check length, contacts and unsupported commitments')
                self.db.change_job(bid,jid,draft=output['reply'],facts_version=b['version'])
            self._publish(bid,jid)
    def _publish(self,bid,jid):
        b=self.db.business(bid); j=self.db.job(bid,jid)
        if self.db.setting('paused')=='1': raise ValueError('All publishing is paused')
        if not b['consent'] or not b['facts_approved']: raise ValueError('Owner consent and approved business facts are required')
        if not j['draft'] or j['facts_version']!=b['version']: raise ValueError('Draft is missing or business facts changed; regenerate or edit the draft')
        current=self.google.review(b,j['resource'])
        if current.get('reviewReply'):
            self.db.change_job(bid,jid,status='already_replied',error='Existing Google reply preserved'); return
        if fingerprint(current)!=j['fingerprint']:
            self.db.ingest(bid,current)
            self.db.change_job(bid,jid,status='needs_approval',error='Review changed: draft invalidated'); return
        # Persist BEFORE the network operation: crash/timeout must trigger readback.
        self.db.change_job(bid,jid,status='publishing')
        try:
            self.google.reply(b,j['resource'],j['draft'])
        except Exception:
            self.db.change_job(bid,jid,status='publish_unknown',error='Google write may have succeeded; readback required')
            return
        self.db.change_job(bid,jid,status='published',error='')
    def cycle(self):
        with self.lock:
            self.db.purge()
            if self.db.setting('paused')=='1': return
            for b in self.db.businesses():
                if not b['location']: continue
                try:
                    if time.time()-b['last_poll']>=1800: self.poll(b['id'])
                    for j in self.db.jobs(b['id']):
                        if j['next_attempt']<=time.time(): self.process(b['id'],j['id'])
                except Exception as exc:
                    self.db.update_settings(b['id'],last_poll=time.time(),last_error='Google access failed ('+type(exc).__name__+'); reconnect or check API access',connection_status='Needs attention')
