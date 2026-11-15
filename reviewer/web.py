"""Loopback-only operator dashboard. Not a public multiuser service."""
import csv
import io
import json
import secrets
import time
from urllib.parse import urlsplit
from flask import Flask,abort,redirect,render_template,request,session,Response
from reviewer.website import extract


def create_app(db,engine):
    app=Flask(__name__)
    app.secret_key=secrets.token_bytes(32)
    app.config.update(MAX_CONTENT_LENGTH=64000,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict')
    def business(bid):
        b=db.business(bid)
        if not b: abort(404)
        return b
    @app.before_request
    def secure():
        if request.host.split(':')[0] not in ('127.0.0.1','localhost'): abort(400)
        if request.remote_addr not in (None,'127.0.0.1','::1'): abort(403)
        session.setdefault('csrf',secrets.token_urlsafe(32))
        if request.method=='POST':
            origin=request.headers.get('Origin')
            if origin and origin!=request.host_url.rstrip('/'): abort(403)
            if not secrets.compare_digest(request.form.get('csrf',''),session['csrf']): abort(403)
    @app.after_request
    def headers(response):
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        return response
    @app.errorhandler(ValueError)
    def invalid(error): return render_template('message.html',message=str(error)),400
    @app.errorhandler(Exception)
    def unexpected(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error,HTTPException): return error
        return render_template('message.html',message='Operation failed. Check the Google connection, local model and setup instructions. No credentials are displayed.'),503
    @app.get('/')
    def index():
        db.purge()
        return render_template('dashboard.html',businesses=db.businesses(),b=None,jobs=[],paused=db.setting('paused')=='1')
    @app.get('/business/<int:bid>')
    def detail(bid):
        db.purge(); b=business(bid)
        jobs=db.jobs(bid)
        for j in jobs:
            p=json.loads(j['payload']); j['comment']=p.get('comment',''); j['rating']=p.get('starRating',''); j['reviewer']=p.get('reviewer',{}).get('displayName','Google reviewer')
        return render_template('dashboard.html',businesses=db.businesses(),b=b,jobs=jobs,paused=db.setting('paused')=='1')
    @app.post('/business')
    def save():
        with engine.lock:
            data={k:request.form.get(k,'') for k in ('name','facts','contact','tone','language','website','model')}
            if request.form.get('id'): business(int(request.form['id'])); data['id']=int(request.form['id'])
            bid=db.save_business(data)
        return redirect('/business/'+str(bid))
    @app.post('/business/<int:bid>/settings')
    def settings(bid):
        with engine.lock:
            b=business(bid)
            if request.form.get('version')!=str(b['version']): raise ValueError('Business information changed. Reload before approving settings.')
            flags={k:int(request.form.get(k)=='on') for k in ('consent','facts_approved','auto_enabled','pilot_verified')}
            if flags['auto_enabled'] and not all(flags[k] for k in ('consent','facts_approved','pilot_verified')): raise ValueError('Automation requires recorded owner consent, approved facts and verified pilot')
            db.update_settings(bid,notify_email=request.form.get('notify_email','').strip(),**flags,consent_at=time.time() if flags['consent'] and not b['consent'] else b['consent_at'])
        return redirect('/business/'+str(bid))
    @app.post('/pause')
    def pause():
        with engine.lock: db.set_setting('paused','0' if db.setting('paused')=='1' else '1')
        return redirect('/')
    @app.post('/business/<int:bid>/poll')
    def poll(bid): business(bid); engine.poll(bid); return redirect('/business/'+str(bid))
    @app.post('/business/<int:bid>/job/<int:jid>/<action>')
    def action(bid,jid,action):
        business(bid)
        with engine.lock:
            j=db.job(bid,jid)
            if action=='generate':
                if j['status'] in ('published','already_replied','publishing','publish_unknown'): raise ValueError('This review cannot be regenerated')
                db.change_job(bid,jid,status='pending',attempts=0,next_attempt=0)
                engine.process(bid,jid,allow_auto=False)
            elif action=='approve': engine.approve(bid,jid,request.form.get('reply'),expected_fp=request.form.get('fingerprint'),expected_version=request.form.get('version'))
            elif action=='resolve': db.change_job(bid,jid,investigation='resolved')
            elif action=='reconcile': engine.process(bid,jid)
            else: abort(404)
        return redirect('/business/'+str(bid))
    @app.post('/business/<int:bid>/extract')
    def website(bid):
        b=business(bid)
        text=extract(b['website'])
        return render_template('extracted.html',b=b,text=text)
    @app.post('/business/<int:bid>/disconnect')
    def disconnect(bid):
        with engine.lock:
            business(bid); engine.google.disconnect(bid)
            db.update_settings(bid,consent=0,auto_enabled=0,location='',connection_status='Disconnected')
        return redirect('/business/'+str(bid))
    @app.get('/business/<int:bid>/review-qr.svg')
    def qr(bid):
        import qrcode
        import qrcode.image.svg
        b=business(bid)
        if not b['place_id']: raise ValueError('Connect a Google location first')
        from urllib.parse import urlencode
        image=qrcode.make('https://search.google.com/local/writereview?'+urlencode({'placeid':b['place_id']}),image_factory=qrcode.image.svg.SvgPathImage)
        out=io.BytesIO(); image.save(out)
        return Response(out.getvalue(),mimetype='image/svg+xml')
    @app.get('/business/<int:bid>/monthly')
    def monthly(bid):
        from datetime import datetime,timezone
        from reviewer.reports import monthly_report
        b=business(bid)
        month=request.args.get('month',datetime.now(timezone.utc).strftime('%Y-%m'))
        return render_template('report.html',b=b,report=monthly_report(db,bid,month))
    @app.get('/business/<int:bid>/operations.csv')
    def summary(bid):
        business(bid); db.purge()
        out=io.StringIO(); writer=csv.writer(out)
        writer.writerow(['Local job','Status','Investigation','Processing attempts'])
        for j in db.jobs(bid): writer.writerow([j['id'],j['status'],j['investigation'],j['attempts']])
        return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=review-operations.csv'})
    return app
