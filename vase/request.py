import asyncio
import urllib.parse
from http.cookies import CookieError, SimpleCookie

_FORM_URLENCODED = 'application/x-www-form-urlencoded'


class MultiDict(dict):
    def __getitem__(self, key):
        value = super().__getitem__(key)
        return value[0]

    def __setitem__(self, key, value):
        super().__setitem__(key, [value])

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def getlist(self, key, default=[]):
        return super().get(key, default)

    def items(self):
        for key in self:
            yield key, self[key]

    def values(self):
        for key in self:
            yield self[key]

    def lists(self):
        return super().items()

    def __repr__(self):  # pragma: no cover
        return "<MultiDict {}>".format(super().__repr__())


class HttpRequest:
    def __init__(self, http_message):
        self._http_message = http_message
        self.method = http_message.method.upper()
        ip, port = http_message.extra['peername']
        try:
            path, query = http_message.uri.split('?')
        except ValueError:
            path, query = http_message.uri, ''

        self.path = path
        self.path_info = path
        self.querystring = query

        self.POST = MultiDict()
        self._cookies = None
        self._post_inited = False
        self._get = None

    @property
    def body(self):
        return self._http_message.body

    @property
    def GET(self):
        if self._get is None:
            self._get = MultiDict(urllib.parse.parse_qs(self.querystring, keep_blank_values=True))
        return self._get

    @property
    def COOKIES(self):
        if self._cookies is None:
            try:
                c = SimpleCookie(self._http_message.get('cookie', ''))
            except CookieError:  # pragma: no cover
                self._cookies = {}
            else:
                res = {}
                for name, value in c.items():
                    res[name] = value.value
                self._cookies = res
        return self._cookies

    def is_secure(self):
        return self._http_message.extra.get('sslcontext') is None

    def get(self, key, default=None):
        return self._http_message.get(key, default)

    def _has_form(self):
        return self._http_message.get('content-type', '').lower() == _FORM_URLENCODED

    @asyncio.coroutine
    def _maybe_init_post(self):
        if self._post_inited:
            return
        if self._has_form():
            body = yield from self._http_message.body.read()
            self.POST = MultiDict(urllib.parse.parse_qs(body.decode('utf-8')))
        self._post_inited = True

