import asyncio
from asyncio.streams import StreamWriter
from http.cookies import (
    CookieError,
    SimpleCookie
)
from http.client import responses as http_responses
from email.message import Message as EmailMessage
import urllib.parse

from .stream import LimitedReader
from .exceptions import BadRequestException
from .util import MultiDict

from collections import OrderedDict


_DEFAULT_EXHAUST = 2**16
DELIMITER = b'\r\n'

_FORM_URLENCODED = 'application/x-www-form-urlencoded'

RESPONSES = {x: "{} {}".format(x, y) for x, y in http_responses.items()}


class HttpRequest(EmailMessage):
    def __init__(self, method, uri, version, extra={}):
        self.method = method.upper()
        try:
            path, query = uri.split('?')
        except ValueError:
            path, query = uri, ''
        ip, port = extra.get('peername', ('', ''))
        self.path = path
        self.path_info = path
        self.querystring = query
        self.version = version

        self._content_length = 0
        self._body = LimitedReader(None, 0)
        self.POST = MultiDict()
        self._get = None
        self._cookies = None
        self.extra = extra
        self._post_inited = False
        super().__init__()

    def add_header(self, name, value, **params):
        super().add_header(name, value, **params)
        if name.lower() == 'content-length':
            try:
                self._content_length = int(value)
            except ValueError:
                pass

    @property
    def body(self):
        return self._body

    @body.setter
    def body(self, value):
        self._body = LimitedReader(value, self._content_length)

    @property
    def GET(self):
        if self._get is None:
            self._get = MultiDict(urllib.parse.parse_qs(self.querystring, keep_blank_values=True))
        return self._get

    @property
    def COOKIES(self):
        if self._cookies is None:
            try:
                c = SimpleCookie(self.get('cookie', ''))
            except CookieError:  # pragma: no cover
                self._cookies = {}
            else:
                res = {}
                for name, value in c.items():
                    res[name] = value.value
                self._cookies = res
        return self._cookies

    def as_string(self):  # pragma: no cover
        return "{} {} {}\r\n{}".format(self.method,
                                       self.path,
                                       self.version,
                                       super().as_string()
        )

    def is_secure(self):
        return self.extra.get('sslcontext') is not None

    def append_to_last_header(self, value):
        assert self._headers
        name, v = self._headers.pop(-1)
        self._headers.append((name, v + ' ' + value))

    def _has_form(self):
        return self.get('content-type', '').lower() == _FORM_URLENCODED

    @asyncio.coroutine
    def _maybe_init_post(self):
        if self._post_inited:
            return
        if self._has_form():
            body = yield from self.body.read()
            self.POST = MultiDict(urllib.parse.parse_qs(body.decode('utf-8')))
        self._post_inited = True


class HttpWriter(StreamWriter):
    delimiter = DELIMITER

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._headers_sent = False
        self._headers = OrderedDict()
        self._status = RESPONSES[200]
        self.version = '1.1'
        self._chunked = False
        self._content_length = 0

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        assert not self._headers_sent, "Headers have already been sent"
        if isinstance(value, int):
            value = RESPONSES.get(value)
        self._status = value

    def write_status(self, status):
        self.status = status

    def __setitem__(self, key, value):
        assert not self._headers_sent, "Headers have already been sent"
        self._headers[key.lower()] = (key, value)

    def __getitem__(self, item):
        try:
            return self._headers.get(item.lower())[1]
        except KeyError:
            return None

    def __delitem__(self, header):
        assert not self._headers_sent, "Headers have already been sent"
        try:
            del self._headers[header.lower()]
        except KeyError:
            pass

    def __contains__(self, item):
        return item.lower() in self._headers

    def add_headers(self, *headers):
        for name, value in headers:
            self[name] = value

    def items(self):
        return self._headers.values()

    def _maybe_send_headers(self):
        if not self._headers_sent:
            _to_send = 'HTTP/{} {}'.format(self.version, self._status).encode('ascii') + self.delimiter
            for name, value in self.items():
                if isinstance(name, str):
                    name = name.encode('ascii')
                if isinstance(value, str):
                    value = value.encode('latin-1')
                _to_send += name + b': ' + value + self.delimiter

            _to_send += self.delimiter
            self.write(_to_send)
            self._headers_sent = True

    def write_body(self, data):
        self._maybe_send_headers()
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.write(data)

    def writelines(self, data):
        self._maybe_send_headers()
        super().writelines(data)

    def flush(self):
        self._maybe_send_headers()

    def restore(self):
        self._headers_sent = False
        self._headers = OrderedDict()
        self._status = ''

    def _write_chunk(self, data):
        pass


class HttpParser:
    @staticmethod
    @asyncio.coroutine
    def parse(reader):
        l = yield from reader.readline()
        if not l:
            return
        l = l.rstrip(DELIMITER)

        try:
            method, uri, version = (x.decode('ascii') for x in l.split(b' '))
            if version not in ('HTTP/1.1', 'HTTP/1.0'):
                raise ValueError('Unsupported http version {}'.format(version))
        except ValueError:
            raise BadRequestException()

        peer = reader._transport.get_extra_info('peername')
        sslctx = reader._transport.get_extra_info('sslcontext')
        extra = {
            "peername": peer,
            "sslcontext": sslctx,
        }

        request = HttpRequest(method, uri, version, extra)

        while True:
            l = yield from reader.readline()
            if not l:
                return
            if l == DELIMITER:
                break

            l = l.rstrip(DELIMITER)
            if chr(l[0]) not in (' ', '\t'):
                try:
                    name, value = (x.strip().decode('ascii') for x in l.split(b':', 1))
                except ValueError:
                    raise BadRequestException()
                else:
                    request.add_header(name, value)
            else:
                value = l.strip().decode('ascii')
                request.append_to_last_header(value)

        request.body = reader
        yield from request._maybe_init_post()
        return request
