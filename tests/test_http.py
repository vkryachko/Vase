import gc
import unittest
import unittest.mock
from vase.http import (
    HttpWriter,
    WsgiParser,
    BadRequestException,
)
import asyncio


class HttpWriterTests(unittest.TestCase):
    
    def test_write_status_raises_when_status_written(self):
        writer = HttpWriter(None, None, None, None)
        writer._status_written = True
        self.assertRaises(AssertionError, writer.write_status, b'200 OK')

    @unittest.mock.patch.object(HttpWriter, 'write')
    def test_write_status(self, write_method):
        writer = HttpWriter(None, None, None, None)

        writer.write_status(b'200 OK')
        write_method.assert_called_with(b'HTTP/1.1 200 OK\r\n')

    def test_write_header_raises_when_headers_sent(self):
        writer = HttpWriter(None, None, None, None)
        writer._headers_sent = True
        self.assertRaises(AssertionError, writer.write_header, b'foo', b'bar')

    @unittest.mock.patch.object(HttpWriter, 'write')
    def test_write_header(self, write_method):
        writer = HttpWriter(None, None, None, None)

        writer.write_header(b'foo', b'bar')
        write_method.assert_called_with(b'foo: bar\r\n')

        writer.write_header('foo', 'bar')
        write_method.assert_called_with(b'foo: bar\r\n')

    @unittest.mock.patch.object(HttpWriter, 'write_header')
    def test_write_headers(self, write_header_method):
        writer = HttpWriter(None, None, None, None)

        writer.write_headers(((b'foo', b'bar'),))
        write_header_method.assert_called_with(b'foo', b'bar')

    def test_status_written(self):
        writer = HttpWriter(None, None, None, None)
        self.assertFalse(writer.status_written)

        writer._status_written = True
        self.assertTrue(writer.status_written)

    def test_status_written(self):
        writer = HttpWriter(None, None, None, None)
        self.assertFalse(writer.status_written)
        self.assertFalse(writer._headers_sent)

        writer._status_written = self._headers_sent = True

        writer.restore()

        self.assertFalse(writer.status_written)
        self.assertFalse(writer._headers_sent)

    @unittest.mock.patch.object(HttpWriter, 'write')
    def test_maybe_finalize_headers(self, write_method):
        writer = HttpWriter(None, None, None, None)
        writer._maybe_finalize_headers()
        write_method.assert_called_with(b'\r\n')

        writer = HttpWriter(None, None, None, None)
        writer._headers_sent = True
        writer._maybe_finalize_headers()
        self.assertTrue(writer._headers_sent)

    @unittest.mock.patch.object(HttpWriter, 'write')
    def test_write_body(self, write_method):
        writer = HttpWriter(None, None, None, None)
        writer.write_body(b'hello')
        self.assertTrue(writer._headers_sent)
        write_method.assert_called_with(b'hello')

    def test_writelines(self):
        mtransport = unittest.mock.MagicMock()
        writer = HttpWriter(mtransport, None, None, None)
        writer.writelines((b'Hello',))
        self.assertTrue(writer._headers_sent)
        mtransport.writelines.assert_called_with((b'Hello',))


class HttpParserTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)

    def tearDown(self):
        asyncio.test_utils.run_briefly(self.loop)

        self.loop.close()
        gc.collect()

    def test_eof(self):
        stream = asyncio.StreamReader(loop=self.loop)
        task = asyncio.Task(WsgiParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_eof())
        environ = self.loop.run_until_complete(task)
        self.assertIs(environ, None)

    def test_parse_bad_version(self):
        stream = asyncio.StreamReader(loop=self.loop)
        task = asyncio.Task(WsgiParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(b'GET / HTTP/2.3\r\n'))
        self.assertRaises(BadRequestException, self.loop.run_until_complete, task)

    def test_parse_no_query(self):
        stream = asyncio.StreamReader(loop=self.loop)
        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream.set_transport(transport)
        task = asyncio.Task(WsgiParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(b'GET / HTTP/1.1\r\nContent-Length: 3\r\n\r\nfoo'))
        env =self.loop.run_until_complete(task)
        self.assertEqual(env['QUERY_STRING'], '')

    def test_parse_with_query(self):
        stream = asyncio.StreamReader(loop=self.loop)
        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream.set_transport(transport)
        task = asyncio.Task(WsgiParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(b'GET /?foo=bar HTTP/1.1\r\nContent-Length: 3\r\n\r\nfoo'))
        env =self.loop.run_until_complete(task)
        self.assertEqual(env['QUERY_STRING'], 'foo=bar')
        self.assertEqual(env['HTTP_CONTENT_LENGTH'], '3')

    def test_parse_invalid_header(self):
        stream = asyncio.StreamReader(loop=self.loop)
        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream.set_transport(transport)
        task = asyncio.Task(WsgiParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(b'GET /?foo=bar HTTP/1.1\r\nContent-Length 3\r\n\r\nfoo'))
        self.assertRaises(BadRequestException, self.loop.run_until_complete, task)

    def test_parse_multiple_same_name_headers(self):
        stream = asyncio.StreamReader(loop=self.loop)
        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream.set_transport(transport)
        task = asyncio.Task(WsgiParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(b'GET /?foo=bar HTTP/1.1\r\nContent-Type: foo\r\nContent-Type: bar\r\nCookie: foo\r\nCookie: bar\r\nContent-Length: boo\r\n\r\n'))
        env = self.loop.run_until_complete(task)
        self.assertEqual(env['HTTP_CONTENT_TYPE'], 'foo,bar')
        self.assertEqual(env['HTTP_COOKIE'], 'foo;bar')
