from tests.util import BaseLoopTestCase
from vase.http import (
    HttpRequest,
)
from vase.protocol import BaseHttpProtocol

class BaseHttpProtocolTests(BaseLoopTestCase):
    def test_should_close_conn(self):
        proto = BaseHttpProtocol(loop=self.loop)
        req = HttpRequest('GET', '/', 'HTTP/1.0')
        self.assertTrue(proto._should_close_conn_immediately(req))

        req = HttpRequest('GET', '/', 'HTTP/1.0')
        req.add_header('connection', 'keep-alive')
        self.assertFalse(proto._should_close_conn_immediately(req))

        req = HttpRequest('GET', '/', 'HTTP/1.0')
        req.add_header('connection', 'boo')
        self.assertTrue(proto._should_close_conn_immediately(req))

        req = HttpRequest('GET', '/', 'HTTP/1.1')
        self.assertFalse(proto._should_close_conn_immediately(req))

        req = HttpRequest('GET', '/', 'HTTP/1.1')
        req.add_header('connection', 'close')
        self.assertTrue(proto._should_close_conn_immediately(req))

        proto1 = BaseHttpProtocol(keep_alive=0, loop=self.loop)
        self.assertTrue(proto1._should_close_conn_immediately(req))


