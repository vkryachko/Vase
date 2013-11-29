import asyncio
from .exceptions import BadRequestException
from .http import (
    HttpWriter,
    WsgiParser,
)
from hashlib import sha1
from base64 import b64encode
from .websocket import (
    WebSocketWriter,
    WebSocketParser,
    MAGIC,
    OpCode,
)
from .log import logger
import sys

def should_close_conn_immediately(environ):
    result = False
    if environ['SERVER_PROTOCOL'].lower() == 'http/1.0':
        result = True
    conn_header = environ.get('HTTP_CONNECTION', '').lower()
    if conn_header == 'keep-alive':
        result = False
    elif conn_header == 'close':
        result = True
    return result


WEBSOCKET_HEADERS = (
    'HTTP_UPGRADE',
    'HTTP_CONNECTION',
    'HTTP_SEC_WEBSOCKET_KEY',
    'HTTP_SEC_WEBSOCKET_VERSION',
)

def is_websocket_request(environ):
    upgrade = environ.get('HTTP_UPGRADE', '').lower()
    connection = environ.get('HTTP_CONNECTION', '').lower()
    key = environ.get('HTTP_SEC_WEBSOCKET_KEY', None)
    version = environ.get('HTTP_SEC_WEBSOCKET_VERSION', None)
    if upgrade != 'websocket' or 'upgrade' not in connection or key is None or version != '13':
        return False
    return True


def _maybe_log_exception(task):
    try:
        task.result()
    except:
        logger.exception("An exception ocurred while serving request")

class WebServer(asyncio.StreamReaderProtocol):
    KEEP_ALIVE = 20
    def __init__(self, *args, app, loop=None):
        self._app = app
        stream_reader = asyncio.StreamReader(loop=loop)
        super().__init__(stream_reader, None, loop)
        self.reader = self._stream_reader
        self.h_timeout = None
        self._timeout_disabled = False
        self._in_ws_mode = False

    def connection_made(self, transport):
        self._transport = transport
        self.reader.set_transport(transport)

        self.writer = HttpWriter(transport, self,
                                self._stream_reader,
                                self._loop)

        task = asyncio.async(self._handle_client())
        task.add_done_callback(_maybe_log_exception)

        self._reset_timeout()

    def connection_lost(self, exc):
        self.writer = None
        self._stop_timeout()
        super().connection_lost(exc)

    def data_received(self, data):
        self._reset_timeout()
        super().data_received(data)

    @asyncio.coroutine
    def _handle_client(self):
        while True:
            try:
                env = yield from WsgiParser.parse(self.reader)
            except BadRequestException as e:
                self._bad_request(self.writer, e)
                self.writer.close()
                break
            # connection has been closed
            if env is None:
                break

            try:
                yield from self.handle_request(env)
            except BadRequestException as e:
                self._bad_request(self.writer, e)
            except Exception as e:
                self._transport.close()
                raise
            if should_close_conn_immediately(env):
                self.writer.close()
            else:
                yield from env['wsgi.input'].read()
                self.writer.restore()

    def _reset_timeout(self):
        self._stop_timeout()
        if not self._timeout_disabled:
            self.h_timeout = self._loop.call_later(
                self.KEEP_ALIVE, self._handle_timeout)

    def _stop_timeout(self):
        if self.h_timeout is not None:
            self.h_timeout.cancel()
            self.h_timeout = None

    def _handle_timeout(self):
        if not self._in_ws_mode:
            self.writer.close()
        else:
            self._ws_handler.transport._write_ws(OpCode.ping, b'')
            self._reset_timeout()

    @asyncio.coroutine
    def handle_request(self, environ):
        if is_websocket_request(environ):
            yield from self._handle_websocket(environ)
            return
        yield from self._handle_wsgi(environ)

    @asyncio.coroutine
    def _handle_wsgi(self, environ):
        def start_response(status, headers, exc_info=None):
            self.writer.write_status(status)
            self.writer.write_headers(headers)

            return self.writer

        result = yield from self._app(environ, start_response)
        assert self.writer.status_written, 'Wsgi app did not call start_response!'
        if not should_close_conn_immediately(environ):
            self.writer.write_header('Connection', 'Keep-Alive')
        self.writer.writelines(result)

    @asyncio.coroutine
    def _handle_websocket(self, environ):
        writer = self.writer
        handler = self._app.initialize_endpoint(environ)
        if handler is None:
            data = "Not found".encode('utf-8')
            writer.write_status(b'404 Not Found')
            writer.write_headers((
                ('Content-Length', str(len(data))),
            ))
            writer.write_body(data)
            return

        handler.transport = WebSocketWriter(self._transport)
        handler.loop = self._loop

        if hasattr(handler, 'authorize_request'):
            if not (yield from asyncio.coroutine(handler.authorize_request)(environ)):
                writer.write_status(b'401 Anauthorized')
                writer.write_body(b'')
                return

        key = environ['HTTP_SEC_WEBSOCKET_KEY']

        accept = sha1(key.encode('ascii') + MAGIC).digest()
        writer.write_status(b'101 Switching Protocols')
        writer.write_headers((
            ('Upgrade', 'websocket',),
            ('Connection', 'Upgrade'),
            ('Sec-WebSocket-Accept', b64encode(accept))
        ))
        writer.write_body(b'')
        yield from self._switch_protocol(handler)

    def _switch_protocol(self, handler):
        #self._disable_timeout()
        self._ws_handler = handler
        self._in_ws_mode = True
        self._ws_handler.on_connect()

        #self._stream_reader = StreamReader(loop=self._loop)
        #self._stream_reader.set_transport(self._transport)

        yield from self._parse_messages()

    @asyncio.coroutine
    def _parse_messages(self):
        parser = WebSocketParser(self._stream_reader)
        while True:
            msg = yield from parser.get_message()
            if msg is None:
                return
            if msg.is_ctrl:
                if msg.opcode == OpCode.close:
                    self._ws_handler.transport._write_ws(OpCode.close, b'')
                    self._transport.close()
                    return
                elif msg.opcode == OpCode.ping:
                    self._ws_handler.transport._write_ws(OpCode.pong, b'')
            else:
                self._ws_handler.on_message(msg.payload)

    def _bad_request(self, writer, exc):
        writer.write_status(b'400 Bad Request')
        writer.write_header('Content-Type', 'text/plain')
        body = b''
        if exc is not None and len(exc.args):
            body = str(exc.args[0]).encode('utf-8')
        writer.write_header('Content-Length', str(len(body)))
        writer.write_body(body)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    asyncio.async(loop.create_server(lambda: WebServer(loop=loop), 'localhost', 3000))
    loop.run_forever()
