"""Owner alerts. Always visible in the dashboard; email is optional (existing SMTP).

Emails never contain review text, reviewer names or customer details.
"""
import json
import re
import smtplib
import ssl
import time
from email.message import EmailMessage

EMAIL = re.compile(r'^[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
MAX_ATTEMPTS = 3
KIND_TEXT = {'owner_action': 'needs your input', 'publish_unknown': 'has a reply whose publishing result is unknown'}


def deliver(db, send):
    """Try each undelivered owner alert once. Safe to call repeatedly (deduplicated by state)."""
    for alert in db.alerts(open_only=True):
        if alert['kind'] != 'owner_action' or alert['state'] not in ('pending', 'retrying'):
            continue
        b = db.business(alert['business_id'])
        if not send or not EMAIL.fullmatch(b.get('notify_email') or ''):
            db.update_alert(b['id'], alert['id'], state='dashboard',
                            last_error='' if send else 'Email is not set up; this alert is shown in the dashboard only.')
            continue
        job = db.job(b['id'], alert['job_id'])
        concerns = ', '.join(c['label'].lower() for c in job['concern_list'] if c.get('sensitive')) or 'a serious concern'
        body = (f"A Google review for {b['name']} needs your input: {concerns}.\n\n"
                f"Open the WebRift Review Manager and look for case #{job['id']}. "
                "The review is held: nothing will be posted publicly until staff write and approve a reply.\n"
                "A public reply does not close the investigation.")
        try:
            send(b['notify_email'], f"WebRift: a review for {b['name']} needs your input", body)
            db.update_alert(b['id'], alert['id'], state='sent', attempts=alert['attempts'] + 1, last_error='', sent_at=time.time())
            db.audit(b['id'], job['id'], 'system', 'Owner alert emailed', b['notify_email'])
        except Exception as exc:
            attempts = alert['attempts'] + 1
            db.update_alert(b['id'], alert['id'], attempts=attempts, state='failed' if attempts >= MAX_ATTEMPTS else 'retrying',
                            last_error=f'Email failed ({type(exc).__name__}). Check SMTP settings on the Status page.')
            if attempts >= MAX_ATTEMPTS:
                db.audit(b['id'], job['id'], 'system', 'Owner alert failed', 'Email could not be delivered; call the owner.')


def retry(db, bid, aid):
    db.update_alert(bid, aid, state='pending', attempts=0, last_error='')


def sender(db, vault):
    config = json.loads(db.setting('smtp', '{}'))
    if not config:
        return None

    def send(to, subject, body):
        if not EMAIL.fullmatch(config['sender']) or not EMAIL.fullmatch(to):
            raise ValueError('Invalid email address')
        msg = EmailMessage()
        msg['From'] = config['sender']
        msg['To'] = to
        msg['Subject'] = subject
        msg.set_content(body)
        with smtplib.SMTP_SSL(config['host'], config['port'], timeout=20, context=ssl.create_default_context()) as smtp:
            smtp.login(config['user'], vault.get('smtp'))
            smtp.send_message(msg)
    return send
