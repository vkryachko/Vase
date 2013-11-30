import asyncio
import unittest

from vase.stream import LimitedReader
import io


class CoroReader:
    def __init__(self, bytes_io):
        self._bytes_io = bytes_io

    @asyncio.coroutine
    def read(self, n):
        self._bytes_io.read(n)


class LimitedReaderTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)

    def test_bytes_left(self):
        stream = asyncio.StreamReader(loop=self.loop)
        data = b"hello world"
        length = len(data)

        reader = LimitedReader(stream, length)
        self.assertEqual(reader.bytes_left, length)

        self.loop.call_soon(lambda: stream.feed_data(data))
        task = asyncio.Task(reader.read(), loop=self.loop)

        self.loop.run_until_complete(reader.read())

        self.assertEqual(reader.bytes_left, 0)

    def test_read(self):
        stream = asyncio.StreamReader(loop=self.loop)
        data = b"hello world"
        length = len(data) - 1
        reader = LimitedReader(stream, length)

        self.loop.call_soon(lambda: stream.feed_data(data))
        task = asyncio.Task(reader.read(), loop=self.loop)

        result = self.loop.run_until_complete(task)
        self.assertEqual(data[:-1], result)

        stream = asyncio.StreamReader(loop=self.loop)
        data = b"hello world"
        length = len(data) - 1
        reader = LimitedReader(stream, length)

        self.loop.call_soon(lambda: stream.feed_data(data))
        task = asyncio.Task(reader.read(3), loop=self.loop)

        result = self.loop.run_until_complete(task)
        self.assertEqual(data[:3], result)
