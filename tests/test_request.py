import asyncio
import unittest
from vase.request import (
    HttpRequest,
    MultiDict,
    _FORM_URLENCODED,
)


ENVIRON = {
    "REQUEST_METHOD": "GET",
    "PATH_INFO": "/hello",
    "QUERY_STRING": "foo=bar&baz",
    "HTTP_COOKIE": "foo=bar;baz=far",
    "HTTP_CONTENT_TYPE": _FORM_URLENCODED,
}

class RequestTests(unittest.TestCase):
    def test_request(self):
        req = HttpRequest(ENVIRON)
        self.assertEqual(req.GET, MultiDict(foo=['bar'], baz=['']))
        self.assertEqual(req.GET, MultiDict(foo=['bar'], baz=['']))

    def test_has_form(self):
        req = HttpRequest(ENVIRON)
        self.assertTrue(req._has_form())

        env = ENVIRON.copy()
        env['HTTP_CONTENT_TYPE'] = "application/json"

        req = HttpRequest(env)
        self.assertFalse(req._has_form())

    def test_cookies(self):
        req = HttpRequest(ENVIRON)
        self.assertEqual(req.COOKIES, {'foo': 'bar', 'baz': 'far'})
        self.assertEqual(req.COOKIES, {'foo': 'bar', 'baz': 'far'})

        env = ENVIRON.copy()
        env['COOKIES'] = "application/json"

        req = HttpRequest(env)

    def test_maybe_init_post(self):
        req = HttpRequest(ENVIRON)
        env = ENVIRON.copy()
        loop = asyncio.new_event_loop()
        stream = asyncio.StreamReader(loop=loop)
        env['wsgi.input'] = stream
        req = HttpRequest(env)

        task = asyncio.Task(req._maybe_init_post(), loop=loop)
        def feed():
            stream.feed_data(b'foo=bar&baz=far')
            stream.feed_eof()
        loop.call_soon(feed)

        loop.run_until_complete(task)
        self.assertEqual(req.POST, MultiDict(foo=['bar'], baz=['far']))

        task = asyncio.Task(req._maybe_init_post(), loop=loop)
        def feed():
            stream.feed_data(b'foo=bar&baz=far')
            stream.feed_eof()
        loop.call_soon(feed)

        loop.run_until_complete(task)

        env['HTTP_CONTENT_TYPE'] = 'application/json'

        req = HttpRequest(env)

        task = asyncio.Task(req._maybe_init_post(), loop=loop)
        loop.call_soon(feed)

        loop.run_until_complete(task)
        self.assertEqual(req.POST, MultiDict())

