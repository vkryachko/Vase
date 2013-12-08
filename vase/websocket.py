import asyncio
from asyncio.streams import StreamWriter, StreamReader
import ssl
from .exceptions import BadRequestException
from .wsgi import (
    WsgiHandler,
    WsgiProtocol,
    request_to_wsgi,
)
from base64 import b64encode
from hashlib import sha1
import collections
import struct
from enum import Enum
import os

MAGIC = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


class FrameBuilder:
    @classmethod
    def build(cls, *, fin, opcode, payload, masked):
        if isinstance(payload, str):
            payload = payload.encode('utf-8')

        first_byte = cls._build_first_byte(fin, opcode)

        length_bytes = cls._build_mask_and_length(masked, len(payload))

        mask = b''
        if masked:
            mask = cls._random_mask()
            payload = cls._mask_payload(payload, mask)

        return b''.join([first_byte, length_bytes, mask, payload])


    @classmethod
    def continuation(cls, payload, *, fin=True, masked=True):
        return cls.build(opcode=OpCode.continuation, fin=fin, payload=payload, masked=masked)

    @classmethod
    def text(cls, payload, *, fin=True, masked=True):
        return cls.build(opcode=OpCode.text, fin=fin, payload=payload, masked=masked)

    @classmethod
    def binary(cls, payload, *, fin=True, masked=True):
        return cls.build(opcode=OpCode.binary, fin=fin, payload=payload, masked=masked)

    @classmethod
    def close(cls, code=None, *, payload=b'', masked=True):
        if payload != b'' and code is None:
            code = 1000
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        if code is not None:
            payload = b''.join((struct.pack("!H", code), payload))
        return cls.build(opcode=OpCode.close, fin=True, payload=payload, masked=masked)

    @classmethod
    def ping(cls, payload=b'', *, masked=True):
        return cls.build(opcode=OpCode.ping, fin=True, payload=payload, masked=masked)

    @classmethod
    def pong(cls, payload=b'', *, masked=True):
        return cls.build(opcode=OpCode.pong, fin=True, payload=payload, masked=masked)

    @staticmethod
    def _build_first_byte(fin, opcode):
        first_byte = (1<<7) | opcode.value
        if not fin:
            first_byte = first_byte & 0x7f
        return struct.pack("!B", first_byte)

    @staticmethod
    def _build_mask_and_length(masked, length):
        original_length = length
        extra_length = b''

        if original_length >= 2**16:
            length = 127
        elif original_length > 125:
            length = 126

        if length == 126:
            extra_length = struct.pack('!H', original_length)
        elif length == 127:
            extra_length = struct.pack('!Q', original_length)

        if masked:
            length |= 0x80

        return b''.join((struct.pack('!B', length), extra_length))

    @staticmethod
    def _random_mask():
        return os.urandom(4)

    @staticmethod
    def _mask_payload(payload, mask):
        return bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


class OpCode(Enum):
    """
    WebSocket opcodes as defined in RFC 6455
    """
    continuation = 0
    text = 1
    binary = 2
    close = 8
    ping = 9
    pong = 10

    @property
    def is_ctrl(self):
        return self.value > 0x7


class Frame:
    """
    WebSocket frame
    """
    __slots__ = ('fin', 'opcode', 'payload')
    def __init__(self, fin, opcode, payload):
        self.fin = fin
        self.opcode = opcode
        self.payload = payload

    @property
    def is_ctrl(self):
        """
        Returns True if it is a control frame
        """
        return self.opcode.is_ctrl

    def __repr__(self):  # pragma: no cover
        return "<Frame fin:{} opcode:{} payload:\"{}\">".format(self.fin, self.opcode, self.payload)


class Message:
    __slots__ = ('opcode', 'payload', 'ext_data')
    def __init__(self, opcode, payload=b'', ext_data=b''):
        self.opcode = opcode
        self.payload = payload
        self.ext_data = ext_data

    @property
    def is_ctrl(self):
        """
        Returns True if it is a control frame
        """
        return self.opcode.is_ctrl

    @classmethod
    def close_message(cls, code=None, *, payload=b''):
        """
        Creates a 'close' message with specified reason code and optional message
        """
        if code is not None:
            payload = b''.join((struct.pack("!H", code), payload))
        return cls(OpCode.close, payload)



class WebSocketFormatException(Exception):
    def __init__(self, *args):
        if len(args) > 0:
            self.reason = args[0]
        else:
            self.reason = None
        super().__init__(*args)


class WebSocketParser:
    """
    This object is instantiated for each connection
    """
    def __init__(self, reader):
        self._reader = reader
        self._frames = collections.deque()

    @asyncio.coroutine
    def get_message(self):
        while True:
            frame = yield from self.parse_frame(self._reader)
            if frame is None:
                return
            if frame.is_ctrl:
                return Message(frame.opcode, frame.payload, '')

            if not self._frames and frame.opcode not in (OpCode.binary, OpCode.text):
                raise WebSocketFormatException("The first data frame must be either 'binary' or 'text'")

            if self._frames and frame.opcode != OpCode.continuation:
                raise WebSocketFormatException("Frames belonging to different messages cannot be interleaved")
            self._frames.append(frame)
            if frame.fin:
                return self._build_message()

    def _build_message(self):
        buf = []
        frame = self._frames.popleft()
        opcode = frame.opcode
        buf.append(frame.payload)
        while self._frames:
            frame = self._frames.popleft()
            buf.append(frame.payload)
        payload = b''.join(buf)
        if opcode == OpCode.text:
            payload = payload.decode('utf-8')
        return Message(opcode, payload, b'')

    @classmethod
    def parse_frame(cls, reader):
        data = yield from reader.read(2)
        if not data:
            return None
        first_byte, second_byte = struct.unpack('!BB', data)

        fin = (first_byte >> 7) & 1
        rsv1 = (first_byte >> 6) & 1
        rsv2 = (first_byte >> 5) & 1
        rsv3 = (first_byte >> 4) & 1
        opcode = first_byte & 0xf

        length = (second_byte) & 0x7f

        try:
            opcode = OpCode(opcode)
        except ValueError:
            raise WebSocketFormatException("Unknown opcode received '0x{:X}'".format(opcode))

        if rsv1 or rsv2 or rsv3:
            raise WebSocketFormatException("Reserved bits must be set to 0")

        if opcode.is_ctrl:
            if not fin:
                raise WebSocketFormatException("Control frames MUST NOT be fragmented")
            if length > 125:
                raise WebSocketFormatException("All control frames MUST have a payload length of 125 bytes or less")

        has_mask = (second_byte >> 7) & 1

        if not has_mask:
            raise WebSocketFormatException("Clients MUST mask their frames")


        if length == 126:
            data = yield from reader.read(2)
            if not data:
                return None
            length = struct.unpack_from('!H', data)[0]
        elif length == 127:
            data = yield from reader.read(8)
            if not data:
                return None
            length = struct.unpack_from('!Q', data)[0]

        mask = yield from reader.read(4)
        if not mask:
            return None

        if length:
            payload = yield from reader.read(length)
            if not payload:
                return None
        else:
            payload = b''

        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

        return Frame(fin, opcode, payload)


class WebSocketWriter(StreamWriter):
    def __init__(self, transport):
        self._transport = transport

    def send(self, msg):
        if isinstance(msg, bytes):
            mbytes = FrameBuilder.binary(msg, masked=False)
        else:
            mbytes = FrameBuilder.text(msg, masked=False)

        self._transport.write(mbytes)

    def close(self):
        self._transport._ws_closing = True
        self._transport.write(FrameBuilder.close(masked=False))

def is_websocket_request(req):
    upgrade = req.get('upgrade', '').lower()
    connection = req.get('connection', '').lower()
    key = req.get('sec-websocket-key', None)
    version = req.get('sec-websocket-version', None)
    if upgrade != 'websocket' or 'upgrade' not in connection or key is None or version != '13':
        return False
    return True


class WebSocketWsgiHandler(WsgiHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._in_ws_mode = False
        self._ws_handler = None

    @asyncio.coroutine
    def handle_request(self, request):
        if is_websocket_request(request):
            yield from self.handle_websocket(request)
            return

        yield from super().handle_request(request)

    def on_timeout(self):
        if self._in_ws_mode:
            self._transport.write(FrameBuilder.ping(masked=False))
            return True
        else:
            return super().on_timeout()

    def connection_lost(self, exc):
        if self._ws_handler:
            self._ws_handler.on_close(exc)
        super().connection_lost(exc)

    @asyncio.coroutine
    def handle_websocket(self, request):
        writer = self._writer
        environ = request_to_wsgi(request)
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

        if hasattr(handler, 'authorize_request'):
            if not (yield from asyncio.coroutine(handler.authorize_request)(environ)):
                writer.write_status(b'401 Anauthorized')
                writer.write_body(b'')
                return

        key = environ['HTTP_SEC_WEBSOCKET_KEY']

        accept = sha1(key.encode('ascii') + MAGIC).digest()
        writer.write_status(b'101 Switching Protocols')
        writer.write_headers((
            (b'Upgrade', b'websocket',),
            (b'Connection', b'Upgrade'),
            (b'Sec-WebSocket-Accept', b64encode(accept))
        ))
        writer.write_body(b'')
        yield from self._switch_protocol(handler)

    def _switch_protocol(self, handler):
        self._ws_handler = handler
        self._in_ws_mode = True
        self._ws_handler.on_connect()

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
                self._ws_handler.on_message(msg.payload)


class WebSocketWsgiProtocol(WsgiProtocol):
    handler_factory = WebSocketWsgiHandler
