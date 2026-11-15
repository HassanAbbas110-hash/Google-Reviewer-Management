"""Loopback-only operator dashboard. Not a public multiuser service."""
import csv
import io
import json
import secrets
import time
from urllib.parse import urlsplit
from flask import Flask,abort,redirect,render_template,request,session,Response
from reviewer.website import extract


def create_app(db,engine,background=False):
    from reviewer.lab import LocalLab,REGRESSION_CASES,csv_text
    lab=LocalLab(db,engine)
    app=Flask(__name__)
    app.extensions['local_lab']=lab
    if background:lab.start()
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
            if not secrets.compare_digest(request.form.get('csrf',''),session['csrf']): abort(403,description='Your form session changed. Reload the business page before submitting again.')
    @app.after_request
    def headers(response):
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        # no-referrer makes Chromium form POSTs send Origin: null.
        # same-origin preserves local form origin while hiding external referrers.
        response.headers['Referrer-Policy']='same-origin'
        return response
    @app.errorhandler(403)
    def forbidden(error):
        if request.accept_mimetypes.best=='application/json':return {'error':'The form session changed. Refresh the page and try again.'},403
        return render_template('message.html',message='The form session could not be verified. Return to the workspace, refresh the page and try again.'),403
    @app.errorhandler(ValueError)
    def invalid(error):
        if request.accept_mimetypes.best=='application/json':return {'error':str(error)},400
        return render_template('message.html',message=str(error)),400
    @app.errorhandler(Exception)
    def unexpected(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error,HTTPException): return error
        if request.accept_mimetypes.best=='application/json':return {'error':'The local operation failed. Check the app terminal and try again.'},503
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
            elif action=='retry-alert':
                if j['investigation']!='open':raise ValueError('Only an open investigation can retry an alert.')
                if j['alert_state']=='failed':db.change_job(bid,jid,alert_state='pending',alert_attempts=0)
            elif action=='resolve': db.change_job(bid,jid,investigation='resolved')
            elif action=='reconcile': engine.process(bid,jid)
            else: abort(404)
        return redirect('/business/'+str(bid))
    @app.route('/business/<int:bid>/demo',methods=['GET','POST'])
    def demo(bid):
        from reviewer.demo import generate_demo,SAMPLES
        b=business(bid); text=''; rating=5; result=None; error=''; elapsed=None; status=200
        if request.method=='POST':
            try:
                if request.form.get('preset'):
                    sample=SAMPLES.get(request.form['preset'])
                    if not sample: raise ValueError('Choose one of the available sample reviews.')
                    text=sample['text']; rating=sample['rating']
                else:
                    text=request.form.get('review',''); rating=int(request.form.get('rating','0'))
                started=time.perf_counter()
                # Same operator lock as settings edits; a draft uses one fact version.
                with engine.lock:
                    b=business(bid)
                    result=generate_demo(b,engine.ai,text,rating)
                elapsed=round(time.perf_counter()-started,1)
            except ValueError as exc: error=str(exc); status=400
            except Exception:
                error='Could not generate a reply. Check that Ollama is running, the saved model name matches ollama list, and the model has enough memory. No Google action was attempted.'
                status=503
        return render_template('demo.html',b=b,samples=SAMPLES,result=result,error=error,text=text,rating=rating,elapsed=elapsed),status
    def local_run(bid,rid):
        business(bid)
        try:return lab.get(bid,rid)
        except ValueError:abort(404)
    @app.get('/business/<int:bid>/lab')
    def lab_home(bid):
        return render_template('lab.html',b=business(bid),run=None,recent=lab.recent(bid))
    @app.post('/business/<int:bid>/lab/start')
    def lab_start(bid):
        business(bid)
        if request.form.get('suite'):
            cases=REGRESSION_CASES if request.form['suite']=='full' else [REGRESSION_CASES[i] for i in (0,2,8,10,16,20,22,4)]
        elif request.form.get('preset'):
            from reviewer.demo import SAMPLES
            sample=SAMPLES.get(request.form['preset'])
            if not sample:raise ValueError('Unknown sample review.')
            cases=[{'id':request.form['preset'],'rating':sample['rating'],'text':sample['text']}]
        elif request.form.get('cases_json'):
            try:cases=json.loads(request.form['cases_json'])
            except json.JSONDecodeError:raise ValueError('The custom cases must be a JSON array.')
        else:cases=[{'id':'custom','text':request.form.get('review',''),'rating':int(request.form.get('rating','0'))}]
        rid=lab.submit(bid,cases);url=f'/business/{bid}/lab/{rid}'
        if request.accept_mimetypes.best=='application/json':return {'id':rid,'url':url},202
        return redirect(url)
    @app.get('/business/<int:bid>/lab/<rid>')
    def lab_page(bid,rid):
        return render_template('lab.html',b=business(bid),run=local_run(bid,rid),recent=lab.recent(bid))
    @app.get('/business/<int:bid>/lab/<rid>/status')
    def lab_status(bid,rid):
        return local_run(bid,rid)
    @app.post('/business/<int:bid>/lab/<rid>/<action>')
    def lab_control(bid,rid,action):
        local_run(bid,rid)
        if action=='cancel':lab.cancel(bid,rid)
        elif action=='resume':lab.resume(bid,rid)
        else:abort(404)
        return redirect(f'/business/{bid}/lab/{rid}')
    @app.get('/business/<int:bid>/lab/<rid>/export.<format>')
    def lab_export(bid,rid,format):
        run=local_run(bid,rid)
        if format=='json':body=json.dumps(run,ensure_ascii=False,indent=2);mime='application/json'
        elif format=='csv':body=csv_text(run);mime='text/csv'
        else:abort(404)
        return Response(body,mimetype=mime,headers={'Content-Disposition':f'attachment; filename=local-evaluation-{rid}.{format}'})
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
