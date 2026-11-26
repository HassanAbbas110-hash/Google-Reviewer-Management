"""Command line entry point. `python -m reviewer serve` is all daily use needs (Start.cmd runs it)."""
import argparse
import hashlib
import json
import os
import secrets
import threading
from pathlib import Path
from reviewer.database import Database

CONFIG_FIELDS = ('name', 'facts', 'contact', 'voice', 'language', 'website', 'model', 'examples', 'sign_off', 'owner_name')


def backup_config(db, path):
    payload = {'format': 'webrift-config-v2', 'businesses': [{k: b[k] for k in CONFIG_FIELDS} for b in db.businesses() if not b['is_demo']]}
    path = Path(path)
    with path.open('x', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def restore_config(db, path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('format') not in ('webrift-config-v1', 'webrift-config-v2') or not isinstance(payload.get('businesses'), list):
        raise ValueError('Not a configuration backup')
    if len(payload['businesses']) > 1000:
        raise ValueError('Backup is too large')
    for item in payload['businesses']:
        data = {k: item.get(k, '') for k in CONFIG_FIELDS}
        if not data['voice']:
            data['voice'] = item.get('tone', '')
        db.save_business(data, actor='restore')


def connect_business(db, google, bid, client_file, choose=input):
    b = db.business(bid)
    if not b:
        raise ValueError('Add this business in the dashboard first')
    if b['is_demo']:
        raise ValueError('The demo business cannot be connected to Google. Add a real business.')
    # Replacing credentials is a security boundary: fail closed even if login fails.
    db.update_settings(bid, consent=0, publish_mode='off', location='', connection_status='Reconnection pending')
    google.login(bid, client_file)
    locations = google.locations(bid)
    if not locations:
        raise ValueError('No accessible locations. Check Google API access approval and that this account manages the listing.')
    print(f'\nBusiness in the app: {b["name"]}\nLocations this Google account can manage:')
    for i, loc in enumerate(locations, 1):
        print(f'  {i}. {loc["title"]}  {loc.get("address", "")}  [{loc["resource"]}]')
    choice = int(choose('Type the number of the location that is "' + b['name'] + '": '))
    if not 1 <= choice <= len(locations):
        raise ValueError('Invalid location selection')
    loc = locations[choice - 1]
    db.update_settings(bid, location=loc['resource'], place_id=loc['place_id'], baseline_done=0, consent=0, publish_mode='off',
                       connection_status='Connected', last_error='', next_poll=0)
    db.audit(bid, None, 'connect', 'Connected Google', f'{loc["title"]} ({loc["resource"]})')
    print('Connected to', loc['title'], '- publishing stays OFF. The first sync only records existing reviews.')


class InstanceLock:
    """Cross-process OS lock released automatically on crash (Windows + POSIX)."""
    def __init__(self, path):
        self.path, self.file = path, None

    def __enter__(self):
        self.file = open(self.path, 'a+b')
        self.file.seek(0)
        self.file.write(b'0')
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ValueError('The Review Manager is already running (another window is open). Use that one, or close it first.')
        return self

    def __exit__(self, *args):
        self.file.close()


def secret_key(root):
    """Persisted so forms stay valid across restarts (fixes the old POST /business 403)."""
    path = root / 'secret.key'
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
    return path.read_bytes()


def build(root):
    from reviewer.ai import make_ai
    from reviewer.engine import Engine
    from reviewer.google import Google, Vault
    db = Database(root / 'reviews.db')
    google = Google(Vault(hashlib.sha256(str(root).encode()).hexdigest()[:16]))
    key = google.vault.get('anthropic') if google.vault.has('anthropic') else os.environ.get('ANTHROPIC_API_KEY', '')
    ai = make_ai(key, db.setting('default_model', ''), int(db.setting('model_timeout', '120')))
    return db, google, ai, Engine(db, google, ai)


def serve(root, port, open_browser):
    import time
    from werkzeug.serving import make_server
    from reviewer.notifications import deliver, sender
    from reviewer.web import create_app
    db, google, ai, engine = build(root)
    if db.last_backup:
        print('Database upgraded. Backup of the previous version:', db.last_backup)
    app = create_app(db, engine, background=True, secret_key=secret_key(root))
    stopped = threading.Event()

    def drafter():
        # Slow model calls happen here, never in a web request.
        while not stopped.is_set():
            try:
                engine.run_pending()
            except Exception as exc:
                print('Drafting worker problem:', type(exc).__name__)
            engine.wake.wait(5)
            engine.wake.clear()

    def syncer():
        while not stopped.is_set():
            try:
                engine.cycle()
                if db.setting('paused') != '1':
                    deliver(db, sender(db, google.vault))
            except Exception as exc:
                print('Background sync problem (nothing was published):', type(exc).__name__)
            stopped.wait(30)

    server = make_server('127.0.0.1', port, app, threaded=True)
    url = f'http://127.0.0.1:{port}'
    print('\n  WebRift Review Manager is running:', url)
    print('  Keep this window open while you work. Close it to stop.\n')
    for target in (drafter, syncer):
        threading.Thread(target=target, daemon=True).start()
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        engine.wake.set()
        app.extensions['local_lab'].stop()
        server.server_close()


def doctor(root):
    """Plain-text version of the Status page."""
    from reviewer.web import status_checks
    db, google, ai, engine = build(root)
    print('Data folder:', root)
    try:
        google.vault._check()
        print('[ok]   OS credential store available')
    except Exception:
        print('[warn] OS credential store unavailable; Google connection blocked until fixed')
    for c in status_checks(db, engine):
        print(f"[{c['state']:4}] {c['name']}: {c['detail']}" + (f"\n       Fix: {c['fix']}" if c['fix'] else ''))


def main():
    parser = argparse.ArgumentParser(description='WebRift local Google Review Manager')
    parser.add_argument('--data', default='data', help='Private local data directory')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('serve', help='Run the dashboard')
    s.add_argument('--port', type=int, default=8765)
    s.add_argument('--open-browser', action='store_true')
    c = sub.add_parser('connect', help='Connect a business to Google (app must be closed)')
    c.add_argument('business', type=int)
    c.add_argument('--client', default='credentials.json')
    sub.add_parser('doctor', help='Check every component')
    smtp = sub.add_parser('smtp', help='Optional: email owner alerts through your SMTP provider')
    smtp.add_argument('--host', required=True)
    smtp.add_argument('--port', type=int, default=465)
    smtp.add_argument('--sender', required=True)
    smtp.add_argument('--user', required=True)
    key = sub.add_parser('apikey', help='Use the Claude API for drafts (stores the key in Windows Credential Manager)')
    key.add_argument('--remove', action='store_true', help='Forget the key and go back to local Ollama')
    sub.add_parser('backup', help='Save business settings (no reviews, no tokens)').add_argument('file')
    sub.add_parser('restore', help='Load business settings from a backup').add_argument('file')
    args = parser.parse_args()
    root = Path(args.data).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == 'doctor':
            return doctor(root)
        if args.command in ('backup', 'restore', 'smtp', 'apikey'):
            db, google, _, _ = build(root)
            if args.command == 'backup':
                backup_config(db, args.file)
                print('Settings saved. Protect this file: it contains business details.')
            elif args.command == 'apikey':
                if args.remove:
                    google.vault.delete('anthropic')
                    print('API key removed. Drafts use local Ollama after the next start.')
                    return
                import getpass
                value = getpass.getpass('Paste your Anthropic API key (input hidden): ').strip()
                if not value.startswith('sk-ant-'):
                    raise ValueError('That does not look like an Anthropic API key (it starts with sk-ant-).')
                google.vault.put('anthropic', value)
                print('Key saved in Windows Credential Manager. Restart the app: drafts now use the Claude API.')
            elif args.command == 'restore':
                restore_config(db, args.file)
                print('Businesses imported with publishing off. Reconnect Google and approve facts again.')
            else:
                import getpass
                from reviewer.notifications import EMAIL
                if not EMAIL.fullmatch(args.sender) or not 1 <= args.port <= 65535:
                    raise ValueError('Invalid sender or port')
                google.vault.put('smtp', getpass.getpass('SMTP app password (stored in Windows Credential Manager): '))
                db.set_setting('smtp', json.dumps({'host': args.host, 'port': args.port, 'sender': args.sender, 'user': args.user}))
                print('SMTP configured. Owner alerts will also be emailed.')
            return
        with InstanceLock(root / 'app.lock'):
            if args.command == 'connect':
                db, google, _, _ = build(root)
                return connect_business(db, google, args.business, args.client, input)
            serve(root, args.port, args.open_browser)
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(1, str(exc) + '\n')
    except Exception as exc:
        parser.exit(1, f'Failed ({type(exc).__name__}). Run Doctor.cmd to see which component needs attention.\n')
