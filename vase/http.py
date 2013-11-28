import asyncio
from asyncio.streams import StreamWriter
from urllib.parse import unquote
import sys

from .stream import LimitedReader
from .exceptions import BadRequestException

_DEFAULT_EXHAUST = 2**16
DELIMITER = b'\r\n'


class HttpWriter(StreamWriter):
    delimiter = b'\r\n'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._headers_sent = False
        self._status_written = False
    
    def write_status(self, status, version=b'1.1'):
        assert not self._status_written, "Status has already been written"
        self._status_written = True
        self.write(b'HTTP/' + version + b' ' + status + self.delimiter)

    def write_header(self, name, value):
        assert not self._headers_sent, "Headers have already been sent"
        if type(name) is not bytes:
            name = name.encode('ascii')
        if type(value) is not bytes:
            value = value.encode('ascii')
        self.write(name + b': ' + value + self.delimiter)

    def write_headers(self, headers):
        for name, value in headers:
            self.write_header(name, value)

    def _maybe_finalize_headers(self):
        if not self._headers_sent:
            self.write(self.delimiter)
        self._headers_sent = True

    def write_body(self, data):
        self._maybe_finalize_headers()
        self.write(data)

    def writelines(self, data):
        self._maybe_finalize_headers()
        super().writelines(data)

    def restore(self):
        self._headers_sent = False
        self._status_written = False

    @property
    def status_written(self):
        return self._status_written
    

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
                    headers[hname] += "{}{}".format(sep, value)
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


