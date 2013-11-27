import asyncio
import urllib.parse
from http.cookies import CookieError, SimpleCookie

_FORM_URLENCODED = 'application/x-www-form-urlencoded'


class MultiDict(dict):
    def __getitem__(self, key):
        value = super().__getitem__(key)
        if type(value) is list and value:
            return value[0]
        raise KeyError(key)

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

    def __repr__(self):
        return "<MultiDict {}>".format(super().__repr__())


class HttpRequest:
    def __init__(self, environ):
        self.ENV = environ
        self.method = environ["REQUEST_METHOD"].upper()
        self.path = environ['PATH_INFO']
        self.path_info = environ['PATH_INFO']

        self.POST = MultiDict()
        self._cookies = None
        self._post_inited = False

    @property
    def GET(self):
        if self._get is None:
            self._get = MultiDict(urllib.parse.parse_qs(self.ENV.get('QUERY_STRING')))
        return self._get


    @property
    def COOKIES(self):
        if self._cookies is None:
            try:
                c = SimpleCookie(self.ENV.get('HTTP_COOKIE', ''))
            except CookieError:
                self._cookies = {}
            else:
                res = {}
                for name, value in c.items():
                    res[name] = value.value
                self._cookies = res
        return self._cookies

    def _has_form(self):
        return self.ENV.get('HTTP_CONTENT_TYPE', '') == _FORM_URLENCODED

    @asyncio.coroutine
    def _maybe_init_post(self):
        if self._post_inited:
            return
        if self._has_form():
            body = yield from self.ENV['wsgi.input'].read()
            self.POST = MultiDict(urllib.parse.parse_qs(body.decode('utf-8')))

