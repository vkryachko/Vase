import asyncio
from .protocol import BaseProcessor
from .websocket import (
    WebSocketWriter,
    MAGIC,
    WebSocketParser,
    FrameBuilder,
    OpCode
)

import re
from urllib.parse import unquote
import sys
from hashlib import sha1
from base64 import b64encode


def request_to_wsgi(request):
    ip, port = request.extra['peername']
    try:
        path, query = request.uri.split('?')
    except ValueError:
        path, query = request.uri, ''

    headers = {}
    for name, value in request.items():
        headers["HTTP_{}".format(name.upper().replace('-', '_'))] = value

    environ = {
        'REQUEST_METHOD': request.method,
        'SCRIPT_NAME': '',
        'PATH_INFO': unquote(path),
        'QUERY_STRING': unquote(query),
        'REMOTE_ADDR': ip,
        'SERVER_PROTOCOL': request.version,
        'REMOTE_PORT': port,
        'wsgi.input': request.body,
        'wsgi.error': sys.stderr,
        'wsgi.version': (1, 0),
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
        'wsgi.url_scheme': 'http' if request.extra.get('sslcontext') is None else 'https',
    }
    environ.update(headers)
    return environ


class RoutingProcessor(BaseProcessor):
    def __init__(self, transport, protocol, reader, writer, *, routes=[]):
        self._routes = routes
        self._handler = None
        super().__init__(transport, protocol, reader, writer)

    @asyncio.coroutine
    def handle_request(self, request):
        environ = request_to_wsgi(request)
        current_route = None
        for route in self._routes:
            if route.matches(environ):
                current_route = route
                break
        if current_route is None:
            return (yield from super().handle_request(request))
        self._handler = current_route.handler_factory(environ, self._reader, self._writer)

        return (yield from self._handler.handle())

    def on_timeout(self):
        self._handler.on_timeout()
        if self._handler.persistent_connection():
            return
        super().on_timeout()

    def connection_lost(self, exc):
        self._handler.connection_lost(exc)


class Route:
    def matches(self, request):
        return True

    def handler_factory(self, environ, reader, writer):
        raise NotImplementedError


class RegExpMatcher:
    def __init__(self, pattern):
        if isinstance(pattern, str):
            pattern = re.compile(pattern)

        self._pattern = pattern

    def matches(self, value):
        return self._pattern.match(value) is not None


class UrlRoute(Route):
    matcher_class = RegExpMatcher

    def __init__(self, pattern):
        self._matcher = self.matcher_class(pattern)

    def matches(self, environ):
        return self._matcher.matches(environ["PATH_INFO"])


class RequestHandler:

    def handle(self):
        raise NotImplementedError

    def persistent_connection(self):
        return False

    def connection_lost(self, exc):
        pass

    def on_timeout(self):
        pass


class CallbackRouteHandler(RequestHandler):
    def __init__(self, environ, reader, writer, callback):
        self._environ = environ
        self._reader = reader
        self._writer = writer
        self._callback = callback

    def handle(self):
        def start_response(status, headers):
            self._writer.write_status(status)
            self._writer.write_headers(headers)
            def write(data):
                self._writer.write(data)
            return write
        result = yield from self._callback(self._environ, start_response)
        self._writer.writelines(result)


class CallbackRoute(UrlRoute):
    def __init__(self, handler_factory, pattern, callback):
        super().__init__(pattern)
        self._handler_factory = handler_factory
        self._callback = callback

    def handler_factory(self, environ, reader, writer):
        return self._handler_factory(environ, reader, writer, self._callback)


class WebSocketHandler(RequestHandler):
    def __init__(self, environ, reader, writer, endpoint_factory):
        self._environ = environ
        self._reader = reader
        self._writer = writer
        self._endpoint_factory = endpoint_factory
        self._endpoint = None

    def handle(self):
        self._endpoint = self._endpoint_factory()
        self._endpoint.bag = {}

        self._endpoint.transport = WebSocketWriter(self._writer)

        if hasattr(self._endpoint, 'authorize_request'):
            if not (yield from asyncio.coroutine(self._endpoint.authorize_request)(self._environ)):
                self._writer.write_status(b'401 Anauthorized')
                self._writer.write_body(b'')
                return

        key = self._environ['HTTP_SEC_WEBSOCKET_KEY']

        accept = sha1(key.encode('ascii') + MAGIC).digest()
        self._writer.write_status(b'101 Switching Protocols')
        self._writer.write_headers((
            (b'Upgrade', b'websocket',),
            (b'Connection', b'Upgrade'),
            (b'Sec-WebSocket-Accept', b64encode(accept))
        ))
        self._writer.write_body(b'')

        yield from self._switch_protocol()

    def _switch_protocol(self):
        self._endpoint.on_connect()

        yield from self._parse_messages()

    @asyncio.coroutine
    def _parse_messages(self):
        parser = WebSocketParser(self._reader)
        while True:
            msg = yield from parser.get_message()
            if msg is None:
                return
            if msg.is_ctrl:
                if msg.opcode == OpCode.close:
                    if not hasattr(self._transport, '_ws_closing'):
                        self._transport.write(FrameBuilder.close(masked=False))
                    self._transport.close()
                    return
                elif msg.opcode == OpCode.ping:
                    self._transport.write(FrameBuilder.pong(masked=False))
            else:
                self._endpoint.on_message(msg.payload)

    def persistent_connection(self):
        return True

    def connection_lost(self, exc):
        self._endpoint.on_close(exc)

    def on_timeout(self):
        self._writer.write(FrameBuilder.ping(masked=False))
