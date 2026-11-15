"""Official Google APIs. Tokens live only in an operating-system credential store."""
import json
import re
from pathlib import Path
import keyring
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import AuthorizedSession, Request
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPE='https://www.googleapis.com/auth/business.manage'
SERVICE='WebRift.GoogleReviewerManagement'
RESOURCE=re.compile(r'^accounts/[A-Za-z0-9_-]+/locations/[A-Za-z0-9_-]+(?:/reviews/[A-Za-z0-9_-]+)?$')


class Vault:
    def __init__(self,namespace): self.service=SERVICE+'.'+namespace
    def _check(self):
        backend=keyring.get_keyring()
        approved=('keyring.backends.Windows','keyring.backends.macOS','keyring.backends.SecretService','keyring.backends.kwallet')
        if backend.priority<=0 or type(backend).__module__ not in approved:
            raise RuntimeError('Secure OS credential storage unavailable; no plaintext fallback')
    def get(self,bid):
        self._check(); value=keyring.get_password(self.service,str(bid))
        if not value: raise ValueError('Connect this business to Google first')
        return value
    def put(self,bid,value): self._check(); keyring.set_password(self.service,str(bid),value)
    def delete(self,bid):
        self._check()
        try: keyring.delete_password(self.service,str(bid))
        except keyring.errors.PasswordDeleteError: pass


class Google:
    def __init__(self,vault): self.vault=vault
    def login(self,bid,client_file):
        config=json.loads(Path(client_file).read_text())
        if 'installed' not in config: raise ValueError('Use a Google Desktop app OAuth credentials file')
        installed=config['installed']
        if installed.get('auth_uri')!='https://accounts.google.com/o/oauth2/auth' or installed.get('token_uri')!='https://oauth2.googleapis.com/token':
            raise ValueError('Unexpected OAuth endpoints')
        self.vault._check()
        flow=InstalledAppFlow.from_client_config(config,[SCOPE],autogenerate_code_verifier=True)
        credentials=flow.run_local_server(host='127.0.0.1',port=0,access_type='offline',prompt='consent',timeout_seconds=180)
        if not credentials.refresh_token: raise ValueError('Google did not grant offline access')
        self.vault.put(bid,credentials.to_json())
    def session(self,bid):
        data=json.loads(self.vault.get(bid))
        if data.get('token_uri')!='https://oauth2.googleapis.com/token': raise ValueError('Unexpected token endpoint')
        creds=Credentials.from_authorized_user_info(data,[SCOPE])
        if not creds.valid:
            creds.refresh(Request()); self.vault.put(bid,creds.to_json())
        s=AuthorizedSession(creds); s.trust_env=False
        return s
    def _get(self,bid,url,params=None):
        with self.session(bid) as s:
            r=s.get(url,params=params,timeout=30); r.raise_for_status(); return r.json()
    def _pages(self,bid,url,key,params=None):
        output=[]; params=dict(params or {}); seen=set()
        for _ in range(1000):
            data=self._get(bid,url,params); output.extend(data.get(key,[]))
            token=data.get('nextPageToken')
            if not token: return output
            if token in seen: raise ValueError('Repeated Google pagination token')
            seen.add(token); params['pageToken']=token
        raise ValueError('Google pagination limit exceeded')
    def locations(self,bid):
        accounts=self._pages(bid,'https://mybusinessaccountmanagement.googleapis.com/v1/accounts','accounts')
        output=[]
        for account in accounts:
            if not re.fullmatch(r'accounts/[A-Za-z0-9_-]+',account['name']): continue
            locations=self._pages(bid,'https://mybusinessbusinessinformation.googleapis.com/v1/'+account['name']+'/locations','locations',{'readMask':'name,title,metadata','pageSize':100})
            for loc in locations:
                resource=account['name']+'/'+loc['name']
                if RESOURCE.fullmatch(resource): output.append({'resource':resource,'title':loc.get('title',resource),'place_id':loc.get('metadata',{}).get('placeId','')})
        return output
    def _resource(self,business,resource=None):
        location=business['location']
        if not RESOURCE.fullmatch(location) or '/reviews/' in location: raise ValueError('Invalid Google location')
        if resource is not None and (not RESOURCE.fullmatch(resource) or not resource.startswith(location+'/reviews/')): raise ValueError('Review belongs to another location')
        return resource or location
    def reviews(self,business):
        location=self._resource(business)
        reviews=self._pages(business['id'],'https://mybusiness.googleapis.com/v4/'+location+'/reviews','reviews',{'pageSize':50,'orderBy':'updateTime desc'})
        for review in reviews:
            review['name']=location+'/reviews/'+review['reviewId']
            self._resource(business,review['name'])
        return reviews
    def review(self,business,name):
        self._resource(business,name)
        data=self._get(business['id'],'https://mybusiness.googleapis.com/v4/'+name); data['name']=name
        return data
    def reply(self,business,name,text):
        self._resource(business,name)
        with self.session(business['id']) as s:
            r=s.put('https://mybusiness.googleapis.com/v4/'+name+'/reply',json={'comment':text},timeout=30)
            r.raise_for_status(); return r.json()
    def disconnect(self,bid): self.vault.delete(bid)
