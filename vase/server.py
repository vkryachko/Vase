import asyncio
from urllib.parse import quote, unquote
import sys
from .http import (
    HttpWriter,
    HttpMessage,
    HttpParser,
    DELIMITER
)
from .exceptions import BadRequestException


class HttpProtocol(asyncio.StreamReaderProtocol):
    KEEP_ALIVE = 40
    def __init__(self, *, loop=None):
        stream_reader = asyncio.StreamReader(loop=loop)
        super().__init__(stream_reader, None, loop)
        self.h_timeout = None
        self._timeout_disabled = False

    def connection_made(self, transport):
        self._transport = transport
        self._stream_reader.set_transport(transport)

        self._stream_writer = HttpWriter(transport, self,
                                           self._stream_reader,
                                           self._loop)
        res = self._handle_client(self._stream_reader,
                                        self._stream_writer)
        if asyncio.tasks.iscoroutine(res):
            asyncio.Task(res, loop=self._loop)
        self._reset_timeout()

    def data_received(self, data):
        self._reset_timeout()
        super().data_received(data)

    def _reset_timeout(self):
        if self.h_timeout is not None:
            self.h_timeout.cancel()
            self.h_timeout = None
        if not self._timeout_disabled:
            self.h_timeout = self._loop.call_later(
                self.KEEP_ALIVE, self._handle_timeout)

    def _disable_timeout(self):
        self._timeout_disabled = True
        self._reset_timeout()

    def _handle_timeout(self):
        self._transport.close()

    def connection_lost(self, exc):
        if self.h_timeout is not None:
            self.h_timeout.cancel()
        super().connection_lost(exc)

    @asyncio.coroutine
    def _handle_client(self, reader, writer):
        while True:
            try:
                msg = yield from HttpParser.parse(reader)
            except BadRequestException as e:
                self._bad_request(writer, e)
                writer.close()
                return
            # connection has been closed
            if msg is None:
                writer.close()
                return

            try:
                yield from self.handle_request(msg, writer)
            except BadRequestException as e:
                self._bad_request(writer, e)
            finally:
                yield from writer.drain()
                writer.restore()
                yield from msg._exhaust_body()
                if not msg.keep_alive:
                    writer.close()

    @asyncio.coroutine
    def handle_request(self, message, writer):
        data = "<h1>It works!</h1>"
        writer.write_status(b'200 OK')
        writer.write_header('Content-Type', 'text/html')
        writer.write_header('Content-Length', str(len(data)))
        writer.write_body(data.encode('utf-8'))

    def _bad_request(self, writer, exc):
        writer.write_status(b'400 Bad Request')
        writer.write_header('Content-Type', 'text/plain')
        body = b''
        if exc is not None and len(exc.args):
            body = str(exc.args[0]).encode('utf-8')
        writer.write_header('Content-Length', str(len(body)))
        writer.write_body(body)

    def _error(self, writer, exc):
        writer.write_status(b'500 Internal Server Error')
        writer.write_header('Content-Type', 'text/plain')
        body = b'Internal error'
        writer.write_header('Content-Length', str(len(body)))
        writer.write_body(body)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    asyncio.async(loop.create_server(lambda: HttpProtocol(loop=loop), 'localhost', 3000))
    loop.run_forever()
