import time
from http.cookies import SimpleCookie
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler

STATUS_MAP = BaseHTTPRequestHandler.responses


def status_line(status):
    line = STATUS_MAP[status][0]
    return "{} {}".format(status, line).encode('ascii')

class HttpResponse:
    def __init__(self, body, *, status=200, content_type='text/html'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self._body = body
        self._status = int(status)
        self._cookies = SimpleCookie()
        self._headers = [
            ('Content-Encoding', 'UTF-8'),
            ('Content-Type', content_type),
            ('Content-Length', str(len(body))),
        ]
        self._content_type = content_type

    def __call__(self, start_response):
        status = status_line(self._status)
        start_response(status, self._get_headers())
        return [self._body]


    def set_cookie(self, name, value='', max_age=None, path='/',
                   domain=None, secure=False, httponly=False):
        self._cookies[name] = value
        if max_age is not None:
            self._cookies[name]['max-age'] = max_age
            if not max_age:
                expires_date = 'Thu, 01-Jan-1970 00:00:00 GMT'
            else:
                dt = formatdate(time.time() + max_age)
                expires_date = '%s-%s-%s GMT' % (dt[:7], dt[8:11], dt[12:25])

            self._cookies[name]['expires'] = expires_date


        if path is not None:
            self._cookies[name]['path'] = path
        if domain is not None:
            self._cookies[name]['domain'] = domain
        if secure:
            self._cookies[name]['secure'] = True
        if httponly:
            self._cookies[name]['httponly'] = True

    def delete_cookie(self, key, path='/', domain=None):
        self.set_cookie(key, max_age=0, path=path, domain=domain)

    def _get_headers(self):
        headers = [(x.encode('ascii'), y.encode('ascii')) for x, y in self._headers]
        for c in self._cookies.values():
            headers.append((b'Set-Cookie', c.output(header='').encode('ascii')))
        return headers
