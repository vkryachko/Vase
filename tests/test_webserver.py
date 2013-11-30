import unittest
from vase.webserver import (
    should_close_conn_immediately,
    is_websocket_request,
    WebServer,
)


class ShouldCloseConnTests(unittest.TestCase):
    def test_http10(self):
        env = {
            'SERVER_PROTOCOL': 'HTTP/1.0',
        }
        self.assertTrue(should_close_conn_immediately(env))

    def test_http10_keep_alive(self):
        env = {
            'SERVER_PROTOCOL': 'HTTP/1.0',
            'HTTP_CONNECTION': 'keep-alive',
        }
        self.assertFalse(should_close_conn_immediately(env))

    def test_http10_close(self):
        env = {
            'SERVER_PROTOCOL': 'HTTP/1.0',
            'HTTP_CONNECTION': 'close',
        }
        self.assertTrue(should_close_conn_immediately(env))

    def test_http11(self):
        env = {
            'SERVER_PROTOCOL': 'HTTP/1.1',
        }
        self.assertFalse(should_close_conn_immediately(env))

    def test_http11_keep_alive(self):
        env = {
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'HTTP_CONNECTION': 'keep-alive',
        }
        self.assertFalse(should_close_conn_immediately(env))

    def test_http11_close(self):
        env = {
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'HTTP_CONNECTION': 'close',
        }
        self.assertTrue(should_close_conn_immediately(env))


WEBSOCKET_HEADERS = {
    'HTTP_UPGRADE': 'websocket',
    'HTTP_CONNECTION': 'upgrade',
    'HTTP_SEC_WEBSOCKET_KEY': 'foo',
    'HTTP_SEC_WEBSOCKET_VERSION': '13',
}


class IsWebSocketRequestTests(unittest.TestCase):
    def test_is_websocket_request(self):
        self.assertTrue(is_websocket_request(WEBSOCKET_HEADERS))

    def test_not_websocket_request(self):
        env = WEBSOCKET_HEADERS.copy()
        env.pop('HTTP_UPGRADE')
        self.assertFalse(is_websocket_request(env))
