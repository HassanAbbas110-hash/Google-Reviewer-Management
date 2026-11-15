"""Restricted single-page extractor. DNS is resolved and pinned before connecting."""
import http.client
import ipaddress
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import urlsplit


class TextParser(HTMLParser):
    def __init__(self): super().__init__(); self.hidden=0; self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'): self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript') and self.hidden: self.hidden-=1
    def handle_data(self,data):
        if not self.hidden and data.strip(): self.parts.append(data.strip())


def extract(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Use a public HTTPS website on port 443')
    host=parsed.hostname.encode('idna').decode()
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private, local and reserved network addresses are blocked')
    raw=socket.create_connection((addresses[0][4][0],443),timeout=15)
    try:
        with ssl.create_default_context().wrap_socket(raw,server_hostname=host) as connection:
            path=parsed.path or '/'
            if parsed.query: path+='?'+parsed.query
            if any(ord(x)<32 or ord(x)>126 for x in path): raise ValueError('Website path must be URL encoded')
            connection.sendall(('GET '+path+' HTTP/1.1\r\nHost: '+host+'\r\nUser-Agent: WebRiftReviewSetup/1.0\r\nAccept: text/html\r\nConnection: close\r\n\r\n').encode('ascii'))
            response=http.client.HTTPResponse(connection); response.begin()
            if response.status!=200: raise ValueError('Website returned a redirect or error; enter the final HTTPS page URL')
            if 'text/html' not in response.getheader('Content-Type',''): raise ValueError('Only HTML pages are supported')
            body=response.read(512001)
            if len(body)>512000: raise ValueError('Website page is too large')
    finally: raw.close()
    parser=TextParser(); parser.feed(body.decode('utf-8',errors='replace'))
    return '\n'.join(parser.parts)[:12000]
