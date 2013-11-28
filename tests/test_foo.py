import unittest
import asyncio
from vase.websocket import WebSocketParser
from io import BytesIO


class ExampleTests(unittest.TestCase):

    def test_works(self):
        print("Works")


class BufferReader(BytesIO):
    @asyncio.coroutine
    def read(self, n):
        return super().read(n)


class WebSocketFormatTests(unittest.TestCase):
    def test_control_frame(self):
        stream = BufferReader("hello")
        print((yield from stream.read(2)))
        #WebSocketParser("Hello")
