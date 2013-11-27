import io
import asyncio
from asyncio.streams import StreamWriter

from .stream import LimitedReader
from .exceptions import BadRequestException

_DEFAULT_EXHAUST = 2**16
DELIMITER = b'\r\n'


class HttpMessage:
    """Class that contains information about the request.

    It is a low level container with no convenience methods, just raw data
    """
    def __init__(self, method, url, version, headers, peername):
        self.method = method
        self.url = url
        self.version = version
        self.headers = headers
        self.content_length = 0
        self.keep_alive = True
        self.peername = peername
        if version.lower() == 'http/1.0':
            self.keep_alive = False
        self._body = io.BytesIO(b'')
        self._raw_stream = None
        for name, value in self.headers:
            if name.lower() == b'content-length':
                try:
                    self.content_length = int(value)
                except ValueError:
                    pass
            elif name.lower() == b'connection':
                lvalue = value.lower()
                if lvalue == 'close':
                    self.keep_alive = False
                elif lvalue == 'keep-alive':
                    self.keep_alive = True


    @property
    def body(self):
        return self._body

    @body.setter
    def body(self, stream):
        self._raw_stream = stream
        self._body = LimitedReader(stream, self.content_length)

    @asyncio.coroutine
    def _exhaust_body(self):
        b = self._body
        while b.bytes_left:
            to_read = b.bytes_left
            if to_read > _DEFAULT_EXHAUST:
                to_read = _DEFAULT_EXHAUST
            yield from b.read(to_read)


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
    

class HttpParser:
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

        peer = reader._transport.get_extra_info('peername')
        ip, port = peer[0], peer[1]

        headers = []
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
                headers.append((name, value))
        msg = HttpMessage(method, url, version, headers, reader._transport.get_extra_info('peername'))
        msg.extras = reader._transport._extra
        msg.body = reader
        return msg


