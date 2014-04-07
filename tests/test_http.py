import gc
import unittest
import unittest.mock
import asyncio
import asyncio.test_utils

from vase.http import (
    HttpRequest,
    HttpParser,
    HttpWriter,
    BadRequestException,
    _FORM_URLENCODED,
)
from vase.util import MultiDict


class RequestTests(unittest.TestCase):
    def _get_request(self):
        request = HttpRequest(
            method="GET",
            uri="/hello?foo=bar&baz",
            version="1.1",
            extra={'peername': ('127.0.0.1', '80')}
        )
        request.add_header("Cookie", "foo=bar;baz=far")
        request.add_header('content-type', _FORM_URLENCODED)
        return request

    def test_request(self):
        req = self._get_request()
        self.assertEqual(req.GET, MultiDict(foo=['bar'], baz=['']))
        self.assertEqual(req.GET, MultiDict(foo=['bar'], baz=['']))

    def test_has_form(self):
        req = self._get_request()
        self.assertTrue(req._has_form())

        req.replace_header('content-type', 'application/json')
        self.assertFalse(req._has_form())

    def test_cookies(self):
        req = self._get_request()
        self.assertEqual(req.COOKIES, {'foo': 'bar', 'baz': 'far'})
        self.assertEqual(req.COOKIES, {'foo': 'bar', 'baz': 'far'})

    def test_maybe_init_post(self):
        req = self._get_request()
        loop = asyncio.new_event_loop()
        stream = asyncio.StreamReader(loop=loop)
        data = b'foo=bar&baz=far'
        req.add_header('content-length', str(len(data)))
        req.body = stream

        task = asyncio.Task(req._maybe_init_post(), loop=loop)
        def feed():
            stream.feed_data(b'foo=bar&baz=far')
            stream.feed_eof()
        loop.call_soon(feed)

        loop.run_until_complete(task)
        self.assertEqual(req.POST, MultiDict(foo=['bar'], baz=['far']))

        req = self._get_request()
        stream._eof = False
        task = asyncio.Task(req._maybe_init_post(), loop=loop)
        def feed():
            stream.feed_data(b'foo=bar&baz=far')
            stream.feed_eof()
        loop.call_soon(feed)

        loop.run_until_complete(task)

        req.replace_header('content-type', 'application/json')
        req.body = stream
        stream._eof = False
        task = asyncio.Task(req._maybe_init_post(), loop=loop)
        loop.call_soon(feed)

        loop.run_until_complete(task)
        self.assertEqual(req.POST, MultiDict())



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
        task = asyncio.Task(HttpParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_eof())
        req = self.loop.run_until_complete(task)
        self.assertIs(req, None)
        req = self.loop.run_until_complete(task)

        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream = asyncio.StreamReader(loop=self.loop)
        stream.set_transport(transport)
        task = asyncio.Task(HttpParser.parse(stream), loop=self.loop)
        def feed():
            stream.feed_data(b'GET / HTTP/1.1\r\n')
            stream.feed_eof()
        self.loop.call_soon(feed)
        req = self.loop.run_until_complete(task)
        self.assertIs(req, None)

    def test_bad_version(self):
        stream = asyncio.StreamReader(loop=self.loop)
        task = asyncio.Task(HttpParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(b'GET / HTTP/2.3\r\n'))
        self.assertRaises(BadRequestException, self.loop.run_until_complete, task)

    def test_headers(self):
        req = b'GET / HTTP/1.1\r\nHello: world\r\n\r\n'
        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream = asyncio.StreamReader(loop=self.loop)
        stream.set_transport(transport)
        task = asyncio.Task(HttpParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(req))
        result = self.loop.run_until_complete(task)

        self.assertEqual(result.method, 'GET')
        self.assertEqual(result.path, '/')
        self.assertEqual(result.version, 'HTTP/1.1')
        self.assertEqual(result.get('Hello'), 'world')

    def test_multiline_headers(self):
        req = b'GET / HTTP/1.1\r\nHello: world\r\n foo\r\nContent-Type: text/html\r\n\r\n'
        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream = asyncio.StreamReader(loop=self.loop)
        stream.set_transport(transport)
        task = asyncio.Task(HttpParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(req))
        result = self.loop.run_until_complete(task)

        self.assertEqual(result.get('Hello'), 'world foo')
        self.assertEqual(result.get('Content-Type'), 'text/html')

    def test_invalid_headers(self):
        req = b'GET / HTTP/1.1\r\nContent-Type text/html\r\n\r\n'
        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream = asyncio.StreamReader(loop=self.loop)
        stream.set_transport(transport)
        task = asyncio.Task(HttpParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(req))
        self.assertRaises(BadRequestException, self.loop.run_until_complete, task)

    def test_no_body(self):
        req = b'GET / HTTP/1.1\r\nContent-Type: text/html\r\n\r\n'
        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream = asyncio.StreamReader(loop=self.loop)
        stream.set_transport(transport)
        task = asyncio.Task(HttpParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(req))
        result = self.loop.run_until_complete(task)

        body = self.loop.run_until_complete(asyncio.Task(result.body.read(), loop=self.loop))
        self.assertEqual(body, b'')

    def test_with_body(self):
        req = b'GET / HTTP/1.1\r\nContent-Type: text/html\r\nContent-Length: 5\r\n\r\nHello'
        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream = asyncio.StreamReader(loop=self.loop)
        stream.set_transport(transport)
        task = asyncio.Task(HttpParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(req))
        result = self.loop.run_until_complete(task)

        body = self.loop.run_until_complete(asyncio.Task(result.body.read(), loop=self.loop))
        self.assertEqual(body, b'Hello')

    def test_with_invalid_content_length(self):
        req = b'GET / HTTP/1.1\r\nContent-Type: text/html\r\nContent-Length: foo\r\n\r\nHello'
        transport = unittest.mock.Mock()
        transport.get_extra_info.return_value = ('127.0.0.1', 1)
        stream = asyncio.StreamReader(loop=self.loop)
        stream.set_transport(transport)
        task = asyncio.Task(HttpParser.parse(stream), loop=self.loop)
        self.loop.call_soon(lambda: stream.feed_data(req))
        result = self.loop.run_until_complete(task)

        body = self.loop.run_until_complete(asyncio.Task(result.body.read(), loop=self.loop))
        self.assertEqual(body, b'')


class HttpWriterTests(unittest.TestCase):

    @unittest.mock.patch.object(HttpWriter, 'write')
    def test_write_status(self, write_method):
        writer = HttpWriter(None, None, None, None)

        writer.status = 200
        self.assertFalse(writer._headers_sent)
        writer.flush()
        self.assertTrue(writer._headers_sent)
        write_method.assert_called_with(b'HTTP/1.1 200 OK\r\n\r\n')

    def test_write_header_raises_when_headers_sent(self):
        writer = HttpWriter(None, None, None, None)
        writer._headers_sent = True
        self.assertRaises(AssertionError, writer.__setitem__, 'foo', 'bar')

    @unittest.mock.patch.object(HttpWriter, 'write')
    def test_write_header(self, write_method):
        writer = HttpWriter(None, None, None, None)
        writer.status = 200
        writer['foo'] = 'bar'
        writer.flush()

        write_method.assert_called_with(b'HTTP/1.1 200 OK\r\nfoo: bar\r\n\r\n')

    @unittest.mock.patch.object(HttpWriter, '__setitem__')
    def test_write_headers(self, write_header_method):
        writer = HttpWriter(None, None, None, None)

        writer.add_headers(('foo', 'bar'))
        write_header_method.assert_called_with('foo', 'bar')

    def test_status_written(self):
        writer = HttpWriter(None, None, None, None)
        self.assertFalse(writer._headers_sent)

        writer._status_written = self._headers_sent = True

        writer.restore()

        self.assertFalse(writer._headers_sent)

    @unittest.mock.patch.object(HttpWriter, 'write')
    def test_maybe_finalize_headers(self, write_method):
        writer = HttpWriter(None, None, None, None)
        writer._maybe_send_headers()
        write_method.assert_called_with(b'HTTP/1.1 200 OK\r\n\r\n')

        writer = HttpWriter(None, None, None, None)
        writer._headers_sent = True
        writer._maybe_send_headers()
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
