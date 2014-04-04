import asyncio
from asyncio.futures import Future
import json
import email.utils
import sys
import re
import random
from datetime import (
    datetime,
    timedelta,
)
from hashlib import md5

from ..handlers import WebSocketHandler


class Handler(object):
    initiates_session = False
    allowed_methods = ('GET',)
    @asyncio.coroutine
    def handle(self, request, writer):
        raise NotImplementedError

    def connection_lost(self, exc):
        pass

    @classmethod
    def go_away(cls, request, writer, message):
        origin = request.get('origin', 'null')
        if origin == 'null':
            origin = '*'
        origin = origin
        writer.write_status(200)

        if not message.endswith('\n'):
            message += '\n'

        msg = message.encode('utf-8')
        writer.write_headers(
            ('Content-Type', 'application/javascript;charset=UTF-8'),
            ('Content-Length', str(len(msg))),
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        )
        writer.write_body(msg)

    @classmethod
    def handle_options(cls, request, writer):
        origin = request.get('origin', 'null')
        if origin == 'null':
            origin = '*'
        origin = origin.encode('utf-8')
        writer.write_status(204)
        date = datetime.utcnow() + timedelta(milliseconds=31536000)

        methods = 'OPTIONS, {}'.format(', '.join(cls.allowed_methods))
        writer.write_headers((
            ('Content-Type', 'application/json;charset=UTF-8'),
            ('Cache-Control', 'public, max-age=31536000'),
            ('Expires', email.utils.format_datetime(date)),
            ('Content-Length', '0'),
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Access-Control-Allow-Methods', methods),
            ('Access-Control-Max-Age', '31536000'),

        ))
        writer.write_body('')

    def not_allowed(self, writer, allowed_methods):
        writer.write_status(405)
        writer.write_headers(
            ('Allow', ','.join(allowed_methods)),
        )
        writer.write_body('')
        writer.close()

    def not_modified(self, writer):
        writer.write_status(304)
        writer.write_body('')
        writer.close()

    def send_500(self, reason, writer):
        msg = reason.encode('utf-8')
        writer.write_status(500)
        writer.write_headers((
            ('Content-Length', str(len(msg))),
        ))
        writer.write_body(msg)
        writer.close()


class InfoHandler(Handler):
    def __init__(self, allow_websocket=True):
        self._allow_websocket = allow_websocket

    @asyncio.coroutine
    def handle(self, request, writer):
        origin = request.get('origin', 'null')
        if origin == 'null':
            origin = '*'
        origin = origin

        if request.method == 'GET':
            data = {
                'websocket': self._allow_websocket,
                'cookie_needed': False,
                'origins': ['*:*'],
                'entropy': random.SystemRandom().randint(1, sys.maxsize)
            }
            content = json.dumps(data).encode('utf-8')
            writer.write_status(200)
            writer.write_headers(
                ('Content-Type', 'application/json;charset=UTF-8'),
                ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0'),
                ('Content-Length', str(len(content))),
                ('Access-Control-Allow-Origin', origin),
                ('Access-Control-Allow-Credentials', 'true'),
            )
            writer.write_body(content)
        elif request.method == 'OPTIONS':
            writer.write_status(204)
            date = datetime.utcnow() + timedelta(milliseconds=31536000)

            methods = 'OPTIONS, {}'.format(', '.join(self.allowed_methods)).encode('utf-8')
            writer.write_headers(
                ('Content-Type', 'application/json;charset=UTF-8'),
                ('Cache-Control', 'public, max-age=31536000'),
                ('Expires', email.utils.format_datetime(date)),
                ('Content-Length', '0'),
                ('Access-Control-Allow-Origin', origin),
                ('Access-Control-Allow-Credentials', 'true'),
                ('Access-Control-Allow-Methods', methods),
                ('Access-Control-Max-Age', '31536000'),
            )
            writer.write_body('')


class IFrameHandler(Handler):
    IFRAME_CONTENT = "<!DOCTYPE html>\n" \
                     "<html>\n" \
                     "<head>\n" \
                     "  <meta http-equiv=\"X-UA-Compatible\" content=\"IE=edge\" />\n" \
                     "  <meta http-equiv=\"Content-Type\" content=\"text/html; charset=UTF-8\" />\n" \
                     "  <script>\n" \
                     "    document.domain = document.domain;\n" \
                     "    _sockjs_onload = function(){SockJS.bootstrap_iframe();};\n" \
                     "  </script>\n" \
                     "  <script src=\"//cdn.sockjs.org/sockjs-0.3.min.js\"></script>\n" \
                     "</head>\n" \
                     "<body>\n" \
                     "  <h2>Don't panic!</h2>\n" \
                     "  <p>This is a SockJS hidden iframe. It's used for cross domain magic.</p>\n" \
                     "</body>\n" \
                     "</html>".encode('utf-8')

    path_re = re.compile("/iframe[0-9-.a-z_]*.html");

    @asyncio.coroutine
    def handle(self, request, writer):
        if request.method != 'GET':
            return self.not_allowed(writer, ['GET'])

        etag = '"0{}"'.format(md5(self.IFRAME_CONTENT).hexdigest())
        etag_header = request.get('If-None-Match', '')

        if etag == etag_header:
            self.not_modified(writer)
            return

        date = datetime.utcnow() + timedelta(milliseconds=31536000)

        writer.write_status(200)
        writer.write_headers(
            ('Content-Type', 'text/html;charset=UTF-8'),
            ('Cache-Control', 'public, max-age=31536000'),
            ('ETag', etag),
            ('Expires', email.utils.format_datetime(date)),
            ('Content-Length', str(len(self.IFRAME_CONTENT))),
        )
        writer.write_body(self.IFRAME_CONTENT)


class WebSocketSockJsHandler(Handler):
    def __init__(self, reader, endpoint, context):
        self._endpoint = endpoint
        self._context = context
        self._reader = reader

    @asyncio.coroutine
    def handle(self, request, writer):
        ws_handler = WebSocketHandler(request, self._reader, writer, self._endpoint, self._context)
        return (yield from ws_handler.handle())


class XhrTransportHandler(Handler):
    initiates_session = True
    allowed_methods = ('POST',)

    def __init__(self, reader, session, context):
        self._session = session
        self._session.endpoint.transport = FakeTransport(session)
        self._context = context
        self._reader = reader

    @asyncio.coroutine
    def handle(self, request, writer):
        if self._session.is_new:
            self._session.is_new = False
            self._session.endpoint.on_connect()
            return self._send_message(request, writer, b'o\n')

        if self._session.closed:
            self.go_away(request, writer, 'c[3000,"Go away!"]')

        if not self._session.outgoing_messages:
            self._session.waiter = Future()
            yield from self._session.waiter

            if self._session.closed:
                self._send_message(request, writer, 'c[3000,"Go away!"]')

        msgs = []
        while self._session.outgoing_messages:
            msgs.append(self._session.outgoing_messages.popleft())
        resp = ("a[" + ','.join(json.dumps(x) for x in msgs) + "]\n").encode('utf-8')
        return self._send_message(request, writer, resp)

    def _send_message(self, request, writer, msg):
        allow = request.get('access-control-request-headers')
        origin = request.get('origin', 'null')
        if origin == 'null':
            origin = '*'
        writer.write_status(200)
        writer.write_headers(
            ('Content-Type', 'application/javascript;charset=UTF-8'),
            ('Content-Length', str(len(msg))),
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        )
        if allow:
            writer.write_headers((
                ('Access-Control-Allow-Headers', allow),
            ))
        writer.write_body(msg)

    def connection_lost(self, exc):
        self._session.attached = False


class FakeTransport(object):
    def __init__(self, session):
        self._session = session

    def send(self, message):
        self._session.outgoing_messages.append(message)
        waiter = self._session.waiter
        if waiter and not waiter.done():
            waiter.set_result(None)

    def close(self):
        self._session.closed = True


class XhrStreamingHandler(Handler):
    initiates_session = True
    allowed_methods = ('POST',)

    def __init__(self, reader, session, context):
        self._session = session
        self._session.endpoint.transport = FakeTransport(session)
        self._context = context
        self._reader = reader

    @asyncio.coroutine
    def handle(self, request, writer):
        new = self._session.is_new
        if self._session.is_new:
            self._session.is_new = False
            self._session.endpoint.on_connect()

        origin = request.get('origin', 'null')
        if origin == 'null':
            origin = '*'

        writer.write_status(200)
        writer.write_headers((
            ('Content-Type', 'application/javascript;charset=UTF-8'),
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Transfer-Encoding', 'chunked'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        ))

        body = (hex(2049)[2:] + '\r\n' + 'h' * 2048 + '\n\r\n').encode('utf-8')
        writer.write_body(body)
        if new:
            writer.write_body(b'2\r\no\n\r\n')

        if self._session.closed:
            msg = b'c[3000,"Go away!"]\n'
            length = hex(len(msg)).encode('utf-8')
            writer.write_body(length + b'\r\n' + msg + b'\r\n')
            writer.write_body(b'0\r\n\r\n')
            writer.close()
            return

        written = 0
        written += self._send_messages(writer)
        while True:
            self._session.waiter = Future()
            yield from self._session.waiter
            written += self._send_messages(writer)
            if written >= 4096:
                writer.write(b'0\r\n\r\n')
                writer.close()
                break

    def _send_messages(self, writer):
        msgs = []
        while self._session.outgoing_messages:
            msgs.append(self._session.outgoing_messages.popleft())

        if msgs:
            msg = b'a' + json.dumps(msgs).encode('utf-8') + b'\n'
            size = '{}\r\n'.format(hex(len(msg))[2:]).encode('utf-8')
            out = msg + b'\r\n'
            writer.write(size)
            writer.write(out)
            return len(msg)
        return 0

    @classmethod
    def go_away(cls, request, writer, message):
        origin = request.get('origin', 'null')
        if origin == 'null':
            origin = '*'

        writer.write_status(200)
        writer.write_headers((
            ('Content-Type', 'application/javascript;charset=UTF-8'),
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Transfer-Encoding', 'chunked'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        ))

        body = (hex(2049)[2:] + '\r\n' + 'h' * 2048 + '\n\r\n').encode('utf-8')
        writer.write_body(body)

        if not message.endswith('\n'):
            message += '\n'
        msg = message.encode('utf-8')
        length = hex(len(msg)).encode('utf-8')
        writer.write_body(length + b'\r\n' + msg + b'\r\n')
        writer.write_body(b'0\r\n\r\n')
        writer.close()
        return

    def connection_lost(self, exc):
        self._session.attached = False


class EventSourceHandler(XhrStreamingHandler):
    initiates_session = True
    allowed_methods = ('POST',)

    @asyncio.coroutine
    def handle(self, request, writer):
        new = self._session.is_new
        if self._session.is_new:
            self._session.is_new = False
            self._session.endpoint.on_connect()

        origin = request.get('origin', 'null')
        if origin == 'null':
            origin = '*'

        writer.write_status(200)
        writer.write_headers((
            ('Content-Type', 'text/event-stream;charset=UTF-8'),
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Transfer-Encoding', 'chunked'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        ))
        body = (hex(2) + '\r\n\r\n\r\n').encode('utf-8')
        writer.write_body(body)
        if new:
            writer.write_body(b'b\r\ndata: o\r\n\r\n\r\n')

        written = 0
        written += self._send_messages(writer)
        while True:
            self._session.waiter = Future()
            yield from self._session.waiter
            written += self._send_messages(writer)
            if written >= 4096:
                writer.write(b'0\r\n\r\n')
                writer.close()
                break

    def _send_messages(self, writer):
        msgs = []
        while self._session.outgoing_messages:
            msgs.append(self._session.outgoing_messages.popleft())

        if msgs:
            msg = b'data: a' + json.dumps(msgs).encode('utf-8') + b'\r\n\r\n'
            size = '{}\r\n'.format(hex(len(msg))[2:]).encode('utf-8')
            out = msg + b'\r\n'
            writer.write(size)
            writer.write(out)
            return len(msg)
        return 0


class XhrRecievingHandler(Handler):
    allowed_methods = ('POST',)

    def __init__(self, reader, session, context):
        self._session = session
        self._context = context
        self._reader = reader

    @asyncio.coroutine
    def handle(self, request, writer):
        message = yield from request.body.read()
        if not message:
            return self.send_500('Payload expected.', writer)
        try:
            msgs = json.loads(message.decode('utf-8'))
        except ValueError:
            return self.send_500('Broken JSON encoding.', writer)
        for m in msgs:
            self._session.pending_messages.append(m)
        yield from self._session.consume()

        allow = request.get('access-control-request-headers')
        origin = request.get('origin', 'null')
        if origin == 'null':
            origin = '*'

        writer.write_status(204)
        writer.write_headers(
            ('Content-Type', 'text/plain;charset=UTF-8'),
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        )
        writer.write_body('')


class HtmlFileHandler(XhrStreamingHandler):
    HTML_BODY = r'''
<!doctype html>
<html><head>
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
</head><body><h2>Don't panic!</h2>
  <script>
    document.domain = document.domain;
    var c = parent.%s;
    c.start();
    function p(d) {c.message(d);};
    window.onload = function() {c.stop();};
  </script>
'''.strip()

    @asyncio.coroutine
    def handle(self, request, writer):
        callback = request.GET.get('c')
        if not callback:
            self.send_500('"callback" parameter required', writer)
            return
        new = self._session.is_new
        if self._session.is_new:
            self._session.is_new = False
            self._session.endpoint.on_connect()

        writer.write_status(200)
        writer.write_headers((
            ('Content-Type', 'text/html;charset=UTF-8'),
            ('Transfer-Encoding', 'chunked'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        ))
        write_chunk(writer, (self.HTML_BODY % callback) + '\n' * 1024)

        if new:
            write_chunk(writer, '<script>\np("o");\n</script>\r\n')

        written = 0
        written += self._send_messages(writer)
        while True:
            self._session.waiter = Future()
            yield from self._session.waiter
            written += self._send_messages(writer)
            if written >= 4096:
                writer.write(b'0\r\n\r\n')
                writer.close()
                break

    def _send_messages(self, writer):
        msgs = []
        while self._session.outgoing_messages:
            msgs.append(self._session.outgoing_messages.popleft())

        written = 0
        for msg in msgs:
            msg = '<script>\np(' + json.dumps('a["' + msg + '"]') + ');\n</script>\r\n'
            written += write_chunk(writer, msg)
        return written


def write_chunk(writer, message):
    if not isinstance(message, bytes):
        message = message.encode('utf-8')

    length = (hex(len(message)) + '\r\n').encode('utf-8')
    body = message + b'\r\n'
    to_send = length + body
    writer.write_body(to_send)
    return len(to_send)


class JsonpHandler(XhrStreamingHandler):
    @asyncio.coroutine
    def handle(self, request, writer):
        callback = request.GET.get('c')
        if not callback:
            self.send_500('"callback" parameter required', writer)
            return

        new = self._session.is_new
        if self._session.is_new:
            self._session.is_new = False
            self._session.endpoint.on_connect()
            body = '{}("o");\r\n'.format(callback).encode('utf-8')
            writer.write_status(200)
            writer.write_headers((
                ('Content-Type', 'application/javascript;charset=UTF-8'),
                ('Content-Length', str(len(body))),
                ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            ))
            writer.write_body(body)
            return

        if self._session.closed:
            self.go_away(request, writer, 'c[3000,\\"Go away!\\"]', callback)

        if self._session.outgoing_messages:
            self._send_messages(writer, callback)
            writer.close()
            return

        self._session.waiter = Future()
        yield from self._session.waiter
        self._send_messages(writer, callback)
        writer.close()

    @classmethod
    def go_away(cls, request, writer, message, callback):
        writer.write_status(200)
        msg = "{}(\"{}\");\r\n".format(callback, message)
        writer.write_headers(
            ('Content-Type', 'application/javascript;charset=UTF-8'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0'),
            ('Content-Length', str(len(msg)))
        )
        writer.write_body(msg)
        return

    def _send_messages(self, writer, callback):
        msgs = []
        while self._session.outgoing_messages:
            msgs.append(self._session.outgoing_messages.popleft())
        msgs = 'a' + json.dumps(msgs, separators=(',', ':'))
        msg = '{}({});\r\n'.format(callback, json.dumps(msgs)).encode('utf-8')

        writer.write_status(200)
        writer.write_headers(
            ('Content-Type', 'application;charset=UTF-8'),
            ('Content-Length', str(len(msg))),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        )
        writer.write_body(msg)


class JsonpSendingHandler(XhrRecievingHandler):

    @asyncio.coroutine
    def handle(self, request, writer):
        yield from request._maybe_init_post()
        message = request.POST.get('d')
        if not message:
            message = (yield from request.body.read()).decode('utf-8')
        if not message:
            return self.send_500('Payload expected.', writer)
        try:
            msgs = json.loads(message)
        except ValueError:
            return self.send_500('Broken JSON encoding.', writer)
        for m in msgs:
            self._session.pending_messages.append(m)
        yield from self._session.consume()

        writer.write_status(200)
        writer.write_headers(
            ('Content-Type', 'text/plain;charset=UTF-8'),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Content-Length', '2'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        )
        writer.write_body('ok')