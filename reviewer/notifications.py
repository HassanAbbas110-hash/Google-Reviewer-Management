"""Optional email alerts. Never include customer review text or private details."""
import json
import re
import smtplib
import ssl
from email.message import EmailMessage

EMAIL=re.compile(r'^[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')


def notify(db,send):
    for business in db.businesses():
        if not EMAIL.fullmatch(business['notify_email']): continue
        for job in db.jobs(business['id']):
            if job['investigation']!='open' or job['alert_state']=='sent' or job['alert_attempts']>=3: continue
            state='sent'
            try:
                send(business['notify_email'],'WebRift: a review needs investigation',
                     'A review for '+business['name']+' needs staff investigation. Open Google Business Profile or ask your WebRift operator to review local case '+str(job['id'])+'. A public reply does not mean the issue is resolved.')
            except Exception: state='failed'
            db.change_job(business['id'],job['id'],alert_state=state,alert_attempts=job['alert_attempts']+1)


def sender(db,vault):
    config=json.loads(db.setting('smtp','{}'))
    if not config: return None
    def send(to,subject,body):
        if not EMAIL.fullmatch(config['sender']) or not EMAIL.fullmatch(to): raise ValueError('Invalid email address')
        msg=EmailMessage(); msg['From']=config['sender']; msg['To']=to; msg['Subject']=subject; msg.set_content(body)
        with smtplib.SMTP_SSL(config['host'],config['port'],timeout=20,context=ssl.create_default_context()) as smtp:
            smtp.login(config['user'],vault.get('smtp')); smtp.send_message(msg)
    return send
