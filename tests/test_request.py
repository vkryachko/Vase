import asyncio
import unittest
import unittest.mock
from vase.request import (
    HttpRequest,
    MultiDict,
    _FORM_URLENCODED,
)
from vase.http import HttpMessage


ENVIRON = {
    "REQUEST_METHOD": "GET",
    "PATH_INFO": "/hello",
    "QUERY_STRING": "foo=bar&baz",
    "HTTP_COOKIE": "foo=bar;baz=far",
    "HTTP_CONTENT_TYPE": _FORM_URLENCODED,
}

class RequestTests(unittest.TestCase):
    def setUp(self):
        message = HttpMessage(
            method="GET",
            uri="/hello?foo=bar&baz",
            version="1.1",
            extra={'peername': ('127.0.0.1', '80')}
        )
        message.add_header("Cookie", "foo=bar;baz=far")
        message.add_header('content-type', _FORM_URLENCODED)
        self.req = message

    def test_request(self):
        req = HttpRequest(self.req)
        self.assertEqual(req.GET, MultiDict(foo=['bar'], baz=['']))
        self.assertEqual(req.GET, MultiDict(foo=['bar'], baz=['']))

    def test_has_form(self):
        req = HttpRequest(self.req)
        self.assertTrue(req._has_form())

        self.req.replace_header('content-type', 'application/json')
        req = HttpRequest(self.req)
        self.assertFalse(req._has_form())

    def test_cookies(self):
        req = HttpRequest(self.req)
        self.assertEqual(req.COOKIES, {'foo': 'bar', 'baz': 'far'})
        self.assertEqual(req.COOKIES, {'foo': 'bar', 'baz': 'far'})

    def test_maybe_init_post(self):
        env = ENVIRON.copy()
        loop = asyncio.new_event_loop()
        stream = asyncio.StreamReader(loop=loop)
        data = b'foo=bar&baz=far'
        self.req.add_header('content-length', str(len(data)))
        self.req.body = stream
        req = HttpRequest(self.req)

        task = asyncio.Task(req._maybe_init_post(), loop=loop)
        def feed():
            stream.feed_data(b'foo=bar&baz=far')
            stream.feed_eof()
        loop.call_soon(feed)

        loop.run_until_complete(task)
        self.assertEqual(req.POST, MultiDict(foo=['bar'], baz=['far']))

        stream._eof = False
        task = asyncio.Task(req._maybe_init_post(), loop=loop)
        def feed():
            stream.feed_data(b'foo=bar&baz=far')
            stream.feed_eof()
        loop.call_soon(feed)

        loop.run_until_complete(task)


        self.req.replace_header('content-type', 'application/json')
        self.req.body = stream
        req = HttpRequest(self.req)
        stream._eof = False
        task = asyncio.Task(req._maybe_init_post(), loop=loop)
        loop.call_soon(feed)

        loop.run_until_complete(task)
        self.assertEqual(req.POST, MultiDict())

