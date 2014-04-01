import unittest
import unittest.mock

from vase.response import (
    status_line,
    HttpResponse,
)


class HttpResponseTests(unittest.TestCase):
    def test_status_line(self):
        self.assertEqual(status_line(404), b'404 Not Found')

    def test_http_response(self):
        resp = HttpResponse(b'foo')
        self.assertEqual(resp._status, 200)
        self.assertEqual(resp._body, b'foo')
        resp = HttpResponse('foo')
        self.assertEqual(resp._body, b'foo')
        resp._get_headers()

        start_response = unittest.mock.Mock()
        resp(start_response)

        start_response.assert_called_with(b'200 OK', [
            (b'Content-Encoding', b'UTF-8'),
            (b'Content-Type', b'text/html'),
            (b'Content-Length', str(len(b'foo')).encode('ascii')),
        ])

