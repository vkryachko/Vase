import asyncio
from enum import Enum

from ..routing import (
    ContextHandlingCallbackRoute,
)
from ..handlers import (
    RequestHandler,
)
from .handlers import (
    InfoHandler,
    IFrameHandler,
    WebSocketSockJsHandler,
    XhrTransportHandler,
    XhrStreamingHandler,
    XhrRecievingHandler,
    EventSourceHandler,
    HtmlFileHandler,
    JsonpHandler,
    JsonpSendingHandler,
)

from collections import deque


def forbid_websocket(cls):
    cls._forbid_websocket = True
    return cls


class Session(object):

    def __init__(self, name):
        self._name = name
        self.pending_messages = deque()
        self.outgoing_messages = deque()
        self.endpoint = None
        self.waiter = None
        self.is_new = True
        self.attached = False
        self.closed = False
        self.terminated = False

    def attach(self, endpoint):
        self.endpoint = endpoint

    @asyncio.coroutine
    def consume(self):
        if self.endpoint:
            while self.pending_messages:
                msg = self.pending_messages.popleft()
                yield from asyncio.coroutine(self.endpoint.on_message)(msg)


class SockJsRoute(ContextHandlingCallbackRoute):

    SOCKJS_ROUTE_MATCH = 'vasesockjsmatch'

    def __init__(self, spec, callback):
        self._session_store = {}
        if spec.pattern.endswith('/'):
            spec.pattern = spec.pattern[:-1]
        spec.pattern += "{%s:.*}" % self.SOCKJS_ROUTE_MATCH

        super().__init__(None, spec, callback)

    def handler_factory(self, request, reader, writer):
        return SockJsHandler(request, reader, writer, self._callback, self._context_map, self._session_store)


class SockJsHandler(RequestHandler):
    def __init__(self, request, reader, writer, endpoint, context, sessions):
        self._request = request
        self._reader = reader
        self._writer = writer
        self._endpoint = endpoint
        self._context = context
        self._sessions = sessions
        self._websocket_enabled = not bool(getattr(self._endpoint, '_forbid_websocket', False))
        self._info_handler = InfoHandler(self._websocket_enabled)
        self._iframe_handler = IFrameHandler()
        self._ws_handler = WebSocketSockJsHandler(reader, endpoint, context)

        self._transport_handlers = {
            'xhr': XhrTransportHandler,
            'xhr_send': XhrRecievingHandler,
            'xhr_streaming': XhrStreamingHandler,
            'eventsource': EventSourceHandler,
            'htmlfile': HtmlFileHandler,
            'jsonp': JsonpHandler,
            'jsonp_send': JsonpSendingHandler,
        }

        self._current_handler = None

        self._session = None

    @asyncio.coroutine
    def handle(self, **kwargs):
        path = kwargs.pop(SockJsRoute.SOCKJS_ROUTE_MATCH, '')
        if not path or path == '/':
            self._writer.status = 200
            content = b'Welcome to SockJS!\n'
            self._writer.add_headers(
                ('Content-Type', 'text/plain;charset=UTF-8'),
                ('Content-Length', str(len(content))),
            )
            self._writer.write_body(content)
            return
        if path == '/info':
            yield from self._info_handler.handle(self._request, self._writer)
            return
        elif self._iframe_handler.path_re.match(path):
            yield from self._iframe_handler.handle(self._request, self._writer)
            return
        elif path == '/websocket':
            yield from self._ws_handler.handle(self._request, self._writer)
            return
        else:
            parts = path[1:].split("/")
            if len(parts) != 3:
                return self.not_found()

            server, session, transport = parts
            if not self._validate_parts(server, session, transport):
                return self.not_found()
            return (yield from self._handle_transport(session, transport))

    def _validate_parts(self, server, session, transport):
        if not server or not session or not transport:
            return False
        if '.' in server or '.' in session:
            return False
        if transport == 'websocket' and not self._websocket_enabled:
            return False
        return True

    @asyncio.coroutine
    def _handle_transport(self, session, transport):
        handler = self._transport_handlers.get(transport)
        if handler is None:
            return self.not_found()

        if self._request.method == 'OPTIONS':
            return handler.handle_options(self._request, self._writer)

        sess = self._sessions.get(session)

        if sess is None:
            if not handler.initiates_session:
                return self.not_found()
            else:
                endpoint = self._instantiate_endpoint()
                if hasattr(endpoint, 'authorize_request'):
                    if not (yield from asyncio.coroutine(sess.authorize_request)(self._request)):
                        self._writer.status = 401
                        self._writer.write_body('')
                        return

                sess = Session(session)
                sess.endpoint = endpoint
                sess.attached = True
                self._sessions[session] = sess
        else:
            if handler.initiates_session:
                if sess.attached:
                    sess.terminated = True
                    return handler.go_away(self._request, self._writer, 'c[2010,"Another connection still open"]')
                elif sess.terminated:
                    return handler.go_away(self._request, self._writer, 'c[1002,"Connection interrupted"]')
                else:
                    sess.attached = True
        self._session = sess

        handler = handler(self._request, sess, self._context)
        self._current_handler = handler
        yield from handler.handle(self._request, self._writer)

    def _instantiate_endpoint(self):
        end = self._endpoint()
        end.bag = self._context
        return end

    def not_found(self):
        content = b'404 Not Found!\n'
        w = self._writer
        w.status = 404
        w['Content-Type'] = 'text/plain; charset=UTF-8'
        w['Content-Length'] = str(len(content))

        self._writer.write_body(content)

    def connection_lost(self, exc):
        if self._current_handler:
            self._current_handler.connection_lost(exc)
