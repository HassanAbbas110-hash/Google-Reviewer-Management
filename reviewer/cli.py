"""Windows-friendly entry point; no API credentials are required to open the UI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from reviewer.database import Database


def backup_config(db,path):
    fields=('name','facts','contact','tone','language','website','model')
    payload={'format':'webrift-config-v1','businesses':[{k:b[k] for k in fields} for b in db.businesses()]}
    path=Path(path)
    with path.open('x',encoding='utf-8') as f: json.dump(payload,f,indent=2,ensure_ascii=False)
    try: path.chmod(0o600)
    except OSError: pass


def restore_config(db,path):
    payload=json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('format')!='webrift-config-v1' or not isinstance(payload.get('businesses'),list): raise ValueError('Not a configuration backup')
    if len(payload['businesses'])>1000: raise ValueError('Backup is too large')
    for item in payload['businesses']:
        db.save_business({k:item.get(k,'') for k in ('name','facts','contact','tone','language','website','model')})


def connect_business(db,google,bid,client_file,choose=input):
    if not db.business(bid): raise ValueError('Add this business in the dashboard first')
    # Replacing credentials is a security boundary: fail closed even if login fails.
    db.update_settings(bid,consent=0,auto_enabled=0,location='',connection_status='Reconnection pending')
    google.login(bid,client_file)
    locations=google.locations(bid)
    if not locations: raise ValueError('No accessible locations. Check Google API access and listing permissions')
    for i,loc in enumerate(locations,1): print(str(i)+'. '+loc['title']+' — '+loc['resource'])
    choice=int(choose('Select this business location number: '))
    if not 1<=choice<=len(locations): raise ValueError('Invalid location selection')
    loc=locations[choice-1]
    db.update_settings(bid,location=loc['resource'],place_id=loc['place_id'],baseline_done=0,auto_enabled=0,consent=0,connection_status='Connected')
    print('Connected. Restart the app, approve facts and record owner consent. First sync only establishes a baseline.')


class InstanceLock:
    """Cross-process OS lock released automatically on crash (Windows + POSIX)."""
    def __init__(self,path): self.path=path; self.file=None
    def __enter__(self):
        self.file=open(self.path,'a+b'); self.file.seek(0); self.file.write(b'0'); self.file.flush(); self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close(); raise ValueError('Another Review Manager process is using this data folder; close it first')
        return self
    def __exit__(self,*args): self.file.close()


def main():
    parser=argparse.ArgumentParser(description='WebRift local Google Review Manager')
    parser.add_argument('--data',default='data',help='Private local data directory')
    sub=parser.add_subparsers(dest='command',required=True)
    serve=sub.add_parser('serve'); serve.add_argument('--port',type=int,default=8765); serve.add_argument('--open-browser',action='store_true')
    connect=sub.add_parser('connect'); connect.add_argument('business',type=int); connect.add_argument('--client',default='credentials.json')
    sub.add_parser('doctor')
    smtp=sub.add_parser('smtp')
    smtp.add_argument('--host',required=True); smtp.add_argument('--port',type=int,default=465)
    smtp.add_argument('--sender',required=True); smtp.add_argument('--user',required=True)
    backup=sub.add_parser('backup'); backup.add_argument('file')
    restore=sub.add_parser('restore'); restore.add_argument('file')
    args=parser.parse_args()
    root=Path(args.data).resolve(); root.mkdir(parents=True,exist_ok=True)
    try: root.chmod(0o700)
    except OSError: pass
    db=Database(root/'reviews.db')
    from reviewer.google import Google,Vault
    from reviewer.ai import Ollama
    from reviewer.engine import Engine
    google=Google(Vault(hashlib.sha256(str(root).encode()).hexdigest()[:16])); ai=Ollama()
    try:
        if args.command=='doctor':
            print('Data folder:',root)
            try: google.vault._check(); print('OS credential store: available')
            except Exception: print('OS credential store: unavailable; Google connection blocked until configured')
            try: print('Local Ollama models:',', '.join(ai.models()) or 'None installed')
            except Exception: print('Ollama: not running at http://127.0.0.1:11434')
            print('Businesses:',len(db.businesses())); return
        if args.command=='backup': backup_config(db,args.file); print('Configuration saved. Protect this file; it contains business information.'); return
        if args.command=='restore': restore_config(db,args.file); print('Businesses imported with automation and consent disabled.'); return
        if args.command=='smtp':
            import getpass
            from reviewer.notifications import EMAIL
            if not EMAIL.fullmatch(args.sender) or not 1<=args.port<=65535: raise ValueError('Invalid sender or port')
            google.vault.put('smtp',getpass.getpass('SMTP app password (stored in OS credential store): '))
            db.set_setting('smtp',json.dumps({'host':args.host,'port':args.port,'sender':args.sender,'user':args.user}))
            print('SMTP configured. Alerts will use your existing email provider and its limits.'); return
        with InstanceLock(root/'app.lock'):
            if args.command=='connect':
                connect_business(db,google,args.business,args.client,input)
                return
            from reviewer.web import create_app
            from werkzeug.serving import make_server
            engine=Engine(db,google,ai); app=create_app(db,engine,background=True)
            stopped=threading.Event()
            def worker():
                while not stopped.is_set():
                    try:
                        engine.cycle()
                        from reviewer.notifications import notify,sender
                        send=sender(db,google.vault)
                        if send and db.setting('paused')!='1':
                            with engine.lock: notify(db,send)
                    except Exception: print('Background cycle failed; no automatic fallback posting occurred.')
                    stopped.wait(30)
            thread=threading.Thread(target=worker,daemon=True)
            server=make_server('127.0.0.1',args.port,app,threaded=True)
            print('WebRift Review Manager: http://127.0.0.1:'+str(args.port))
            print('Keep this window open. Close it before running the Google connect command.')
            thread.start()
            if args.open_browser:
                import webbrowser
                webbrowser.open('http://127.0.0.1:'+str(args.port))
            try: server.serve_forever()
            except KeyboardInterrupt: pass
            finally: stopped.set(); app.extensions['local_lab'].stop(); server.server_close()
    except (ValueError,FileNotFoundError) as exc: parser.exit(1,str(exc)+'\n')
    except Exception as exc: parser.exit(1,'Operation failed ('+type(exc).__name__+'). Check Google access, installed dependencies and secure credential storage.\n')
