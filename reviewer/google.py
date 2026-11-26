"""Google Business Profile adapter (reviews API v4). Tokens live only in the OS credential store.

Verified against Google's documentation on 2026-11-26, see docs/GOOGLE_SETUP.md:
- scope https://www.googleapis.com/auth/business.manage
- GET  mybusiness.googleapis.com/v4/{accounts/*/locations/*}/reviews (pageSize max 50, nextPageToken)
- GET  mybusiness.googleapis.com/v4/{accounts/*/locations/*/reviews/*}
- PUT  mybusiness.googleapis.com/v4/{...reviews/*}/reply  body {"comment": "..."}
- Business Information / Account Management v1 for accounts and locations
"""
import json
import re
from pathlib import Path
import keyring
import requests

SCOPE = 'https://www.googleapis.com/auth/business.manage'
SERVICE = 'WebRift.GoogleReviewerManagement'
RESOURCE = re.compile(r'^accounts/[A-Za-z0-9_-]+/locations/[A-Za-z0-9_-]+(?:/reviews/[A-Za-z0-9_-]+)?$')
REVIEWS_API = 'https://mybusiness.googleapis.com/v4/'


class GoogleError(Exception):
    """kind: auth | permission | quota | not_found | bad_request | network | server.

    `maybe_sent` is True when a write may have reached Google (timeouts, 5xx):
    those must be reconciled by reading back, never blindly retried.
    """
    MESSAGES = {
        'auth': 'Google: sign-in expired or was revoked. Reconnect this business (Connect Google).',
        'permission': 'Google: access denied. Check the API access approval and that this Google account manages the location.',
        'quota': 'Google: rate limit reached. The app will try again later; no action needed unless this repeats.',
        'not_found': 'Google: the review or location no longer exists.',
        'bad_request': 'Google: the request was rejected. Check the reply text and location.',
        'network': 'Google: could not be reached. Check the internet connection.',
        'server': 'Google: temporary server error. The app will try again later.',
    }

    def __init__(self, kind, maybe_sent=False):
        super().__init__(self.MESSAGES.get(kind, 'Google: request failed.'))
        self.kind = kind
        self.maybe_sent = maybe_sent


def classify_error(exc, write=False):
    if isinstance(exc, GoogleError):
        return exc
    try:
        from google.auth.exceptions import RefreshError
        if isinstance(exc, RefreshError):
            return GoogleError('auth')
    except ImportError:  # pragma: no cover
        pass
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        kind = {401: 'auth', 403: 'permission', 404: 'not_found', 429: 'quota'}.get(code)
        if kind:
            return GoogleError(kind)
        if 400 <= code < 500:
            return GoogleError('bad_request')
        return GoogleError('server', maybe_sent=write)
    if isinstance(exc, (requests.Timeout, requests.ConnectionError, TimeoutError, ConnectionError)):
        return GoogleError('network', maybe_sent=write)
    return GoogleError('server', maybe_sent=write)


class Vault:
    def __init__(self, namespace):
        self.service = SERVICE + '.' + namespace

    def _check(self):
        backend = keyring.get_keyring()
        approved = ('keyring.backends.Windows', 'keyring.backends.macOS', 'keyring.backends.SecretService',
                    'keyring.backends.kwallet')
        if backend.priority <= 0 or type(backend).__module__ not in approved:
            raise RuntimeError('Secure OS credential storage unavailable; no plaintext fallback')

    def get(self, bid):
        self._check()
        value = keyring.get_password(self.service, str(bid))
        if not value:
            raise GoogleError('auth')
        return value

    def has(self, bid):
        try:
            self._check()
            return bool(keyring.get_password(self.service, str(bid)))
        except Exception:
            return False

    def put(self, bid, value):
        self._check()
        keyring.set_password(self.service, str(bid), value)

    def delete(self, bid):
        self._check()
        try:
            keyring.delete_password(self.service, str(bid))
        except keyring.errors.PasswordDeleteError:
            pass


class Google:
    def __init__(self, vault):
        self.vault = vault

    def login(self, bid, client_file):
        from google_auth_oauthlib.flow import InstalledAppFlow
        config = json.loads(Path(client_file).read_text())
        if 'installed' not in config:
            raise ValueError('Use a Google "Desktop app" OAuth client file')
        installed = config['installed']
        if installed.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth' or \
                installed.get('token_uri') != 'https://oauth2.googleapis.com/token':
            raise ValueError('Unexpected OAuth endpoints in the client file')
        self.vault._check()
        # Loopback redirect + PKCE, as documented for desktop apps.
        flow = InstalledAppFlow.from_client_config(config, [SCOPE], autogenerate_code_verifier=True)
        credentials = flow.run_local_server(host='127.0.0.1', port=0, access_type='offline', prompt='consent',
                                            timeout_seconds=180)
        if not credentials.refresh_token:
            raise ValueError('Google did not grant offline access')
        self.vault.put(bid, credentials.to_json())

    def session(self, bid):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import AuthorizedSession, Request
        data = json.loads(self.vault.get(bid))
        if data.get('token_uri') != 'https://oauth2.googleapis.com/token':
            raise ValueError('Unexpected token endpoint')
        creds = Credentials.from_authorized_user_info(data, [SCOPE])
        if not creds.valid:
            try:
                creds.refresh(Request())
            except Exception as exc:
                raise classify_error(exc)
            self.vault.put(bid, creds.to_json())
        s = AuthorizedSession(creds)
        s.trust_env = False
        return s

    def _get(self, bid, url, params=None):
        try:
            with self.session(bid) as s:
                r = s.get(url, params=params, timeout=30)
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            raise classify_error(exc)

    def _pages(self, bid, url, key, params=None):
        output, params, seen = [], dict(params or {}), set()
        for _ in range(1000):
            data = self._get(bid, url, params)
            output.extend(data.get(key, []))
            token = data.get('nextPageToken')
            if not token:
                return output
            if token in seen:
                raise ValueError('Repeated Google pagination token')
            seen.add(token)
            params['pageToken'] = token
        raise ValueError('Google pagination limit exceeded')

    def locations(self, bid):
        accounts = self._pages(bid, 'https://mybusinessaccountmanagement.googleapis.com/v1/accounts', 'accounts')
        output = []
        for account in accounts:
            if not re.fullmatch(r'accounts/[A-Za-z0-9_-]+', account['name']):
                continue
            locations = self._pages(bid, 'https://mybusinessbusinessinformation.googleapis.com/v1/' + account['name'] + '/locations',
                                    'locations', {'readMask': 'name,title,storefrontAddress,metadata', 'pageSize': 100})
            for loc in locations:
                resource = account['name'] + '/' + loc['name']
                if RESOURCE.fullmatch(resource):
                    address = ', '.join((loc.get('storefrontAddress') or {}).get('addressLines', []))
                    output.append({'resource': resource, 'title': loc.get('title', resource), 'address': address,
                                   'place_id': (loc.get('metadata') or {}).get('placeId', '')})
        return output

    def _resource(self, business, resource=None):
        if business.get('is_demo'):
            raise ValueError('Demo businesses never talk to Google')
        location = business['location']
        if not RESOURCE.fullmatch(location or '') or '/reviews/' in location:
            raise ValueError('No valid Google location is connected')
        if resource is not None and (not RESOURCE.fullmatch(resource) or not resource.startswith(location + '/reviews/')):
            raise ValueError('Review belongs to another location')
        return resource or location

    def reviews(self, business):
        location = self._resource(business)
        reviews = self._pages(business['id'], REVIEWS_API + location + '/reviews', 'reviews',
                              {'pageSize': 50, 'orderBy': 'updateTime desc'})
        for review in reviews:
            review['name'] = location + '/reviews/' + review['reviewId']
            self._resource(business, review['name'])
        return reviews

    def review(self, business, name):
        self._resource(business, name)
        data = self._get(business['id'], REVIEWS_API + name)
        data['name'] = name
        return data

    def reply(self, business, name, text):
        self._resource(business, name)
        try:
            with self.session(business['id']) as s:
                r = s.put(REVIEWS_API + name + '/reply', json={'comment': text}, timeout=30)
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            raise classify_error(exc, write=True)

    def connected(self, bid):
        return self.vault.has(bid)

    def disconnect(self, bid):
        self.vault.delete(bid)
