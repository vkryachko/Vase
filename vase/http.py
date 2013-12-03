import asyncio
from asyncio.streams import StreamWriter
from urllib.parse import unquote
import sys

from .stream import LimitedReader
from .exceptions import BadRequestException
import http.client

_DEFAULT_EXHAUST = 2**16
DELIMITER = b'\r\n'


class HttpRequest(http.client.HTTPMessage):
    def __init__(self, method, uri, version, extra={}):
        self.method = method
        self.uri = uri
        self.version = version
        self._content_length = 0
        self._body = LimitedReader(None, 0)
        self.extra = extra
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
    

    def as_string(self):  # pragma: no cover
        return "{} {} {}\r\n{}".format(self.method,
                self.uri,
                self.version,
                super().as_string())

    def append_to_last_header(self, value):
        assert self._headers
        name, v = self._headers.pop(-1)
        self._headers.append((name, v + ' ' + value))


class HttpWriter(StreamWriter):
    delimiter = DELIMITER

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._headers_sent = False
        self._headers = []
        self._status = b''
    
    def write_status(self, status, version=b'1.1'):
        assert not self._headers_sent, "Headers have already been sent"
        self._status = b'HTTP/' + version + b' ' + status + self.delimiter

    def write_header(self, name, value):
        assert not self._headers_sent, "Headers have already been sent"
        self._headers.append((name, value))

    def write_headers(self, headers):
        for name, value in headers:
            self.write_header(name, value)

    def _maybe_send_headers(self):
        if not self._headers_sent:
            _to_send = self._status
            have_headers = False
            for name, value in self._headers:
                _to_send += name + b': ' + value + self.delimiter
                have_headers = True
            _to_send += self.delimiter
            self.write(_to_send)
            self._headers_sent = True

    def write_body(self, data):
        self._maybe_send_headers()
        self.write(data)

    def writelines(self, data):
        self._maybe_send_headers()
        super().writelines(data)

    def flush(self):
        self._maybe_send_headers()

    def restore(self):
        self._headers_sent = False
        self._headers = []
        self._status = b''


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
        return request
    

class WsgiParser:
    @staticmethod
    @asyncio.coroutine
    def parse(reader):
        l = yield from reader.readline()
        if not l:
            return
        l = l.rstrip(DELIMITER)
        try:
            method, url, version = (x.decode('ascii') for x in l.split(b' '))
            if version not in ('HTTP/1.1', 'HTTP/1.0'):
                raise ValueError('Unsupported http version {}'.format(version))
        except ValueError:
            raise BadRequestException()

        try:
            path, query = url.split('?')
        except ValueError:
            path = url
            query = ''

        peer = reader._transport.get_extra_info('peername')
        sslctx = reader._transport.get_extra_info('sslcontext')
        ip, port = peer[0], peer[1]

        headers = {}
        while True:
            l = yield from reader.readline()
            if l == DELIMITER:
                break

            l = l.rstrip(DELIMITER)
            try:
                name, value = (x.strip() for x in l.split(b':', 1))
            except ValueError:
                raise BadRequestException()
            else:
                hname = 'HTTP_{}'.format(name.decode('ascii').replace('-', '_').upper())
                if hname not in headers:
                    headers[hname] = value.decode('ascii')
                else:
                    sep = ','
                    if hname == 'HTTP_COOKIE':
                        sep = ';'
                    headers[hname] += "{}{}".format(sep, value.decode('ascii'))
        try:
            content_length = int(headers.get('HTTP_CONTENT_LENGTH', '0'))
        except ValueError:
            content_length = 0
        environ = {
            'REQUEST_METHOD': method,
            'SCRIPT_NAME': '',
            'PATH_INFO': unquote(path),
            'QUERY_STRING': unquote(query),
            'REMOTE_ADDR': ip,
            'SERVER_PROTOCOL': version,
            'REMOTE_PORT': port,
            'wsgi.input': LimitedReader(reader, content_length),
            'wsgi.error': sys.stderr,
            'wsgi.version': (1, 0),
            'wsgi.multithread': False,
            'wsgi.multiprocess': False,
            'wsgi.run_once': False,
            'wsgi.url_scheme': 'http' if sslctx is None else 'https',
        }
        environ.update(headers)
        return environ


