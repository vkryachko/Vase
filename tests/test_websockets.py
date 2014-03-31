import unittest
import unittest.mock
import asyncio
from vase.websocket import (
    WebSocketParser,
    WebSocketWriter,
    WebSocketFormatException,
    OpCode,
    FrameBuilder,
    Message
)
from io import BytesIO
import gc
from asyncio import test_utils
import struct
import os


class FrameBuilderTests(unittest.TestCase):
    def test_build_first_byte(self):
        EXPECTED = (
            (False, OpCode.continuation, b'\x00'),
            (True, OpCode.continuation, b'\x80'),
            (False, OpCode.text, b'\x01'),
            (True, OpCode.text, b'\x81'),
            (False, OpCode.binary, b'\x02'),
            (True, OpCode.binary, b'\x82'),
            (False, OpCode.close, b'\x08'),
            (True, OpCode.close, b'\x88'),
            (False, OpCode.ping, b'\x09'),
            (True, OpCode.ping, b'\x89'),
            (False, OpCode.pong, b'\x0A'),
            (True, OpCode.pong, b'\x8A'),
        )
        for fin, opcode, result in EXPECTED:
            self.assertEqual(FrameBuilder._build_first_byte(fin=fin, opcode=opcode), result)

    def test_build_mask_and_length(self):
        EXPECTED = (
            (False, 15, b'\x0f'),
            (True, 117, b'\xf5'),
            (False, 356, b'\x7e\x01d'),
            (True, 524, b'\xfe\x02\x0c'),
            (False, 67449, b'\x7f\x00\x00\x00\x00\x00\x01\x07y'),
            (True, 483905743843783, b'\xff\x00\x01\xb8\x1c\x15\xf7q\xc7'),
        )
        for masked, length, result in EXPECTED:
            self.assertEqual(FrameBuilder._build_mask_and_length(masked, length), result)

    def test_mask_payload(self):
        EXPECTED = (
            # (Payload, Mask, Result)
            (b"Hello", b'\xb4\x8dA\xa2', b'\xfc\xe8-\xce\xdb'),
            (b"World", b'K\xb5n^', b'\x1c\xda\x1c2/'),
        )
        for payload, mask, result in EXPECTED:
            self.assertEqual(FrameBuilder._mask_payload(payload, mask), result)

    def test_build(self):
        frame = FrameBuilder.text("Hello world", masked=False)
        self.assertEqual(frame, b'\x81\x0bHello world')


    @unittest.mock.patch.object(FrameBuilder, 'build')
    def test_text_frame(self, _build_method):
        data = "Hello"
        FrameBuilder.text(data)
        _build_method.assert_called_with(opcode=OpCode.text, fin=True, masked=True, payload=data)

    @unittest.mock.patch.object(FrameBuilder, 'build')
    def test_binary_frame(self, _build_method):
        data = b"Hello"
        FrameBuilder.binary(data)
        _build_method.assert_called_with(opcode=OpCode.binary, fin=True, masked=True, payload=data)

    @unittest.mock.patch.object(FrameBuilder, 'build')
    def test_close_frame(self, _build_method):
        data = b"Hello"
        code = 1002
        expected_data = struct.pack("!H", code) + data
        FrameBuilder.close(1002, payload=data)
        _build_method.assert_called_with(opcode=OpCode.close, fin=True, masked=True, payload=expected_data)
        FrameBuilder.close()
        _build_method.assert_called_with(opcode=OpCode.close, fin=True, masked=True, payload=b'')
        frame = FrameBuilder.close(payload=data)
        expected_payload = struct.pack('!H', 1000) + data
        _build_method.assert_called_with(opcode=OpCode.close, fin=True, masked=True, payload=expected_payload)

        frame = FrameBuilder.close(code, payload=data.decode('utf-8'))
        expected_payload = struct.pack('!H', code) + data
        _build_method.assert_called_with(opcode=OpCode.close, fin=True, masked=True, payload=expected_payload)

    @unittest.mock.patch.object(FrameBuilder, 'build')
    def test_ping_frame(self, _build_method):
        data = b"Hello"
        FrameBuilder.ping(data)
        _build_method.assert_called_with(opcode=OpCode.ping, fin=True, masked=True, payload=data)
        
        FrameBuilder.ping(data, masked=False)
        _build_method.assert_called_with(opcode=OpCode.ping, fin=True, masked=False, payload=data)

        FrameBuilder.ping(masked=False)
        _build_method.assert_called_with(opcode=OpCode.ping, fin=True, masked=False, payload=b'')

    @unittest.mock.patch.object(FrameBuilder, 'build')
    def test_pong_frame(self, _build_method):
        data = b"Hello"
        FrameBuilder.pong(data)
        _build_method.assert_called_with(opcode=OpCode.pong, fin=True, masked=True, payload=data)
        
        FrameBuilder.pong(data, masked=False)
        _build_method.assert_called_with(opcode=OpCode.pong, fin=True, masked=False, payload=data)

        FrameBuilder.pong(masked=False)
        _build_method.assert_called_with(opcode=OpCode.pong, fin=True, masked=False, payload=b'')


class MessageTests(unittest.TestCase):
    def test_is_ctrl(self):
        m1 = Message(OpCode.text)
        m2 = Message(OpCode.close)

        self.assertFalse(m1.is_ctrl)
        self.assertTrue(m2.is_ctrl)

    def test_close_message(self):
        m1 = Message.close_message()
        self.assertEqual(m1.opcode, OpCode.close)

        m2 = Message.close_message(1000, payload=b'hello')
        self.assertEqual(m2.opcode, OpCode.close)
        self.assertEqual(m2.payload, b''.join((struct.pack("!H", 1000), b'hello')))


class WebSocketFormatExceptionTests(unittest.TestCase):
    def test_exc(self):
        e = WebSocketFormatException()
        self.assertIsNone(e.reason)
        e = WebSocketFormatException("Hello")
        self.assertEqual(e.reason, "Hello")


def feed_data_and_eof(reader, data):
    reader.feed_data(data)
    reader.feed_eof()


class WebSocketParserTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)

    def tearDown(self):
        test_utils.run_briefly(self.loop)

        self.loop.close()
        gc.collect()

    def test_binary_message(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)
        task = asyncio.Task(parser.get_message(), loop=self.loop)

        frame = FrameBuilder.binary(b'binary')
        self.loop.call_soon(lambda: reader.feed_data(frame))

        frame = self.loop.run_until_complete(task)
        self.assertEqual(frame.opcode, OpCode.binary)
        self.assertEqual(frame.payload, b'binary')

    def test_unmasking(self):
        data = b'\x81\x97\xea\x84N\xe4\xbf\xf7+\x96\xca\xa3*\x80\x8e\xa3n\x81\x84\xf0+\x96\x8f\xe0n\x87\x82\xe5:'
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)
        task = asyncio.Task(parser.parse_frame(reader), loop=self.loop)
        self.loop.call_soon(lambda: reader.feed_data(data))

        frame = self.loop.run_until_complete(task)
        self.assertEqual(frame.fin, 1)
        self.assertEqual(frame.opcode, OpCode.text)
        self.assertEqual(frame.payload, b"User 'ddd' entered chat")

    def test_close_frame_no_payload(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)
        task = asyncio.Task(parser.parse_frame(reader), loop=self.loop)

        self.loop.call_soon(lambda: reader.feed_data(FrameBuilder.close()))

        frame = self.loop.run_until_complete(task)
        self.assertEqual(frame.opcode, OpCode.close)

    def test_nonfin_control_frame(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)
        task = asyncio.Task(parser.parse_frame(reader), loop=self.loop)

        frame = FrameBuilder.build(fin=False, opcode=OpCode.close, payload=b'', masked=True)
        self.loop.call_soon(lambda: reader.feed_data(frame))

        self.assertRaises(WebSocketFormatException, self.loop.run_until_complete, task)

    def test_ping_frame_between_text_frames(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        first = FrameBuilder.text("Hello", fin=False)
        ping = FrameBuilder.ping()
        second = FrameBuilder.continuation(" world!", fin=True)

        frame = FrameBuilder.build(fin=False, opcode=OpCode.close, payload=b'', masked=True)
        self.loop.call_soon(lambda: reader.feed_data(b''.join((first, ping, second))))

        task = asyncio.Task(parser.get_message(), loop=self.loop)
        message = self.loop.run_until_complete(task)
        
        self.assertEqual(message.opcode, OpCode.ping)

        task = asyncio.Task(parser.get_message(), loop=self.loop)
        message = self.loop.run_until_complete(task)

        self.assertEqual(message.opcode, OpCode.text)
        self.assertEqual(message.payload, 'Hello world!')

    def test_raise_on_first_continuation(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame = FrameBuilder.continuation(" world!", fin=True)

        self.loop.call_soon(lambda: reader.feed_data(frame))

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        self.assertRaises(WebSocketFormatException, self.loop.run_until_complete, task)

    def test_raise_on_text_after_text(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame1 = FrameBuilder.text("Hello", fin=False)
        frame2 = FrameBuilder.text(" world!", fin=True)

        self.loop.call_soon(lambda: reader.feed_data(b''.join((frame1, frame2))))

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        self.assertRaises(WebSocketFormatException, self.loop.run_until_complete, task)

    def test_return_none_on_eof(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        self.loop.call_soon(lambda: reader.feed_eof())

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        msg = self.loop.run_until_complete(task)
        self.assertIsNone(msg)

    def test_two_byte_length(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame = FrameBuilder.text(" "*1000, fin=True)
        self.loop.call_soon(lambda: reader.feed_data(frame))

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        msg = self.loop.run_until_complete(task)
        self.assertEqual(len(msg.payload), 1000)

    def test_eight_byte_length(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame = FrameBuilder.text(" "*67000, fin=True)
        self.loop.call_soon(lambda: reader.feed_data(frame))

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        msg = self.loop.run_until_complete(task)
        self.assertEqual(len(msg.payload), 67000)

    def test_invalid_opcode(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame = FrameBuilder.close()
        frame = b'\xff' + frame[1:]
        self.loop.call_soon(lambda: reader.feed_data(frame))

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        self.assertRaises(WebSocketFormatException, self.loop.run_until_complete, task)

    def test_rsv_set(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame = FrameBuilder.close()
        frame = b'\x70' + frame[1:]
        self.loop.call_soon(lambda: reader.feed_data(frame))

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        self.assertRaises(WebSocketFormatException, self.loop.run_until_complete, task)

    def test_control_frame_too_long(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame = FrameBuilder.close(1000, payload=' '*126)
        self.loop.call_soon(lambda: reader.feed_data(frame))

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        self.assertRaises(WebSocketFormatException, self.loop.run_until_complete, task)

    def test_reject_unmasked_frames(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame = FrameBuilder.close(masked=False)
        self.loop.call_soon(lambda: reader.feed_data(frame))

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        self.assertRaises(WebSocketFormatException, self.loop.run_until_complete, task)

    def test_eof_when_reading_length(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame = FrameBuilder.text(' ' * 129)[:2]
        self.loop.call_soon(feed_data_and_eof, reader, frame)

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        self.assertIsNone(self.loop.run_until_complete(task))

        reader._eof = False

        frame = FrameBuilder.text(' ' * 67000)[:2]
        self.loop.call_soon(feed_data_and_eof, reader, frame)

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        self.assertIsNone(self.loop.run_until_complete(task))

    def test_eof_when_reading_mask(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame = FrameBuilder.text('hello')[:2]
        self.loop.call_soon(feed_data_and_eof, reader, frame)

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        self.assertIsNone(self.loop.run_until_complete(task))

    def test_eof_when_reading_payload(self):
        reader = asyncio.StreamReader(loop=self.loop)
        parser = WebSocketParser(reader)

        frame = FrameBuilder.text('hello')[:6]
        self.loop.call_soon(feed_data_and_eof, reader, frame)

        task = asyncio.Task(parser.get_message(), loop=self.loop)

        self.assertIsNone(self.loop.run_until_complete(task))


class WebsocketWriterTests(unittest.TestCase):
    def test_writer_creation(self):
        transport = BytesIO()
        ww = WebSocketWriter(transport)
        self.assertIs(transport, ww._transport)

    def test_writer_send(self):
        transport = BytesIO()
        ww = WebSocketWriter(transport)
        ww.send(b'Hello')
        transport.seek(0)
        self.assertEqual(transport.read(), b'\x82\x05Hello')

        transport = BytesIO()
        ww = WebSocketWriter(transport)
        ww.send('пы')
        transport.seek(0)
        self.assertEqual(transport.read(), b'\x81\x04\xd0\xbf\xd1\x8b')

    def test_writer_close(self):
        transport = BytesIO()
        ww = WebSocketWriter(transport)
        ww.close()
        transport.seek(0)
        self.assertEqual(transport.read(), FrameBuilder.close(masked=False))
