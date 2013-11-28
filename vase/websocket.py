import asyncio
from asyncio.streams import StreamWriter, StreamReader
import ssl
from .wsgi import WsgiProtocol
from .exceptions import BadRequestException
from base64 import b64encode
from hashlib import sha1
import collections
import struct
from enum import Enum

MAGIC = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

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


class Message:
    __slots__ = ('opcode', 'payload', 'ext_data')
    def __init__(self, opcode, payload, ext_data):
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
    def close_message(cls, reason, *, message=b''):
        """
        Creates a 'close' message with specified reason code and optional message
        """
        return cls(Opcode.close, b'', b'')



class WebSocketFormatException(Exception):
    def __init__(self, *args):
        if len(args) > 0:
            self.reason = args[0]
        else:
            self.reasons = None
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
    def __init__(self, transport, *, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()
        self._loop = loop
        self._transport = transport

    def send(self, msg, later=False):
        opcode = OpCode.text
        if isinstance(msg, bytes):
            opcode = OpCode.binary
        else:
            msg = msg.encode('utf-8')

        self._write_ws(opcode, msg, later)

    def _write_ws(self, opcode, payload, later=False):
        first_byte = bytes([(1<<7) | opcode.value])
        length = len(payload)
        if length <= 125:
            len_bytes = bytes([length])
        elif length < 2**16:
            len_bytes = struct.pack('!BH', 126, length)
        else:
            len_bytes = struct.pack('!BQ', 127, length)
        msg = b''.join([first_byte, len_bytes, payload])
        
        if not later:
            self._transport.write(msg)
        else:
            self._loop.call_soon(lambda: self._transport.write(msg))


class WebSocketProtocol(WsgiProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._in_ws_mode = False
        self._parser = None

    @asyncio.coroutine
    def handle_request(self, message, writer):
        upgrade = False
        websocket = False
        key = None
        version = None
        for name, value in message.headers:
            if name.lower() == b'upgrade' and value.lower() == b'websocket':
                websocket = True
            elif name.lower() == b'connection' and b'upgrade' in value.lower():
                upgrade = True
            elif name.lower() == b'sec-websocket-key':
                key = value
            elif name.lower() == b'sec-websocket-version':
                version = value
        if not upgrade or not websocket or key is None or version != b'13':
            yield from super().handle_request(message, writer)
            return

        wsgienv = self._build_environ(message, writer.transport)

        handler = self._app.initialize_endpoint(wsgienv)
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

        if not (yield from asyncio.coroutine(handler.authorize_request)(wsgienv)):
            writer.write_status(b'401 Anauthorized')
            writer.write_body(b'')
            return            

        self._switch_protocol(message, handler)

        accept = sha1(key + MAGIC).digest()
        writer.write_status(b'101 Switching Protocols')
        writer.write_headers((
            ('Upgrade', 'websocket',),
            ('Connection', 'Upgrade'),
            ('Sec-WebSocket-Accept', b64encode(accept))
        ))
        writer.write_body(b'')

    def _switch_protocol(self, message, handler):
        self._disable_timeout()
        self._ws_handler = handler
        self._ws_handler.on_connect()
        self._in_ws_mode = True
        self._stream_reader = StreamReader(loop=self._loop)
        self._stream_reader.set_transport(self._transport)

        asyncio.async(self._parse_messages())

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
                elif msg.opcode == OpCode.ping:
                    self._ws_handler.transport._write_ws(OpCode.pong, b'')
                self._transport.close()
                return
            self._ws_handler.on_message(msg.payload)

    def connection_lost(self, exc):
        if self._in_ws_mode:
            self._ws_handler.on_close(exc)
        if self._parser is not None:
            self._parser.cancel()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    sslctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
    sslctx.options |= ssl.OP_NO_SSLv2
    sslctx.load_cert_chain(
        certfile='/Users/vladimir/Code/python/tulip/tests/sample.crt',
        keyfile='/Users/vladimir/Code/python/tulip/tests/sample.key')
    # sslctx = None
    asyncio.async(loop.create_server(lambda: WebSocketProtocol(loop=loop),
                        '127.0.0.1', 3000, ssl=sslctx))
    loop.run_forever()
