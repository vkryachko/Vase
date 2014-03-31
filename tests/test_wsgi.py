import unittest
from vase.http import HttpRequest
from vase.handlers import request_to_wsgi


class WsgiTests(unittest.TestCase):
    def test_request_to_wsgi(self):
        req = HttpRequest('GET', '/', 'HTTP/1.1', extra={
                'peername': ('127.0.0.1', 500),
                'sslcontext': None
            })
        req.add_header('Content-Type', 'text/html')
        environ = request_to_wsgi(req)
        self.assertEqual(environ.get('REQUEST_METHOD'), 'GET')
        self.assertEqual(environ.get('PATH_INFO'), '/')
        self.assertEqual(environ.get('HTTP_CONTENT_TYPE'), 'text/html')
        self.assertEqual(environ.get('wsgi.url_scheme'), 'http')

        req = HttpRequest('GET', '/', 'HTTP/1.1', extra={
                'peername': ('127.0.0.1', 500),
                'sslcontext': True,
            })
        environ = request_to_wsgi(req)
        self.assertEqual(environ.get('wsgi.url_scheme'), 'https')
