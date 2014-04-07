import asyncio
from vase.websocket import WebSocketFormatException
from .websocket import (
    WebSocketWriter,
    MAGIC,
    WebSocketParser,
    FrameBuilder,
    OpCode
)

from hashlib import sha1
from base64 import b64encode


class RequestHandler:

    def handle(self, **kwargs):
        raise NotImplementedError

    def persistent_connection(self):
        return False

    def connection_lost(self, exc):
        pass

    def on_timeout(self):
        pass


class CallbackRouteHandler(RequestHandler):
    def __init__(self, request, reader, writer, callback):
        self._request = request
        self._reader = reader
        self._writer = writer
        self._callback = callback

    def handle(self, **kwargs):
        def start_response(status, headers):
            self._writer.write_status(status)
            self._writer.add_headers(*headers)

            def write(data):
                self._writer.write(data)
            return write

        result = yield from self._callback(self._request, start_response, **kwargs)
        self._writer.writelines(result)


class WebSocketHandler(RequestHandler):
    def __init__(self, request, reader, writer, endpoint_factory, context):
        self._request = request
        self._reader = reader
        self._writer = writer
        self._endpoint_factory = endpoint_factory
        self._endpoint = None
        self._context = context

    def handle(self, **kwargs):
        self._endpoint = self._endpoint_factory()
        self._endpoint.bag = self._context

        self._endpoint.transport = WebSocketWriter(self._writer)

        if hasattr(self._endpoint, 'authorize_request'):
            if not (yield from asyncio.coroutine(self._endpoint.authorize_request)(self._request)):
                self._writer.write_status(b'401 Anauthorized')
                self._writer.write_body(b'')
                return

        key = self._request.get('sec-websocket-key', '')
        if not key:
            self._writer.write_status(b'400 Bad Request')
            self._writer.add_headers(
                (b'Content-Length', b'0',),
            )
            self._writer.write_body(b'')
            return

        accept = sha1(key.encode('ascii') + MAGIC).digest()
        self._writer.status = 101
        self._writer.add_headers(
            (b'Upgrade', b'websocket',),
            (b'Connection', b'Upgrade'),
            (b'Sec-WebSocket-Accept', b64encode(accept))
        )
        self._writer.write_body(b'')

        yield from self._switch_protocol()

    def _switch_protocol(self):
        self._endpoint.on_connect()

        yield from self._parse_messages()

    @asyncio.coroutine
    def _parse_messages(self):
        parser = WebSocketParser(self._reader)
        while True:
            try:
                msg = yield from parser.get_message()
            except WebSocketFormatException:
                self._writer.close()
                return
            if msg is None:
                self._writer.close()
                return
            if msg.is_ctrl:
                if msg.opcode == OpCode.close:
                    if not hasattr(self._writer, '_ws_closing'):
                        self._writer.write(FrameBuilder.close(masked=False))
                    self._writer.close()
                    return
                elif msg.opcode == OpCode.ping:
                    self._writer.write(FrameBuilder.pong(masked=False, payload=msg.payload))
            else:
                yield from asyncio.coroutine(self._endpoint.on_message)(msg.payload)

    def persistent_connection(self):
        return True

    def connection_lost(self, exc):
        self._endpoint.on_close(exc)
        if self._writer:
            self._writer.close()

    def on_timeout(self):
        self._writer.write(FrameBuilder.ping(masked=False))
