import sys
import asyncio
from urllib.parse import unquote
from .protocol import (
    BaseHandler,
    BaseHttpProtocol,
)


def request_to_wsgi(request):
    ip, port = request.extra['peername']
    try:
        path, query = request.uri.split('?')
    except ValueError:
        path, query = request.uri, ''

    headers = {}
    for name, value in request.items():
        headers["HTTP_{}".format(name.upper().replace('-', '_'))] = value

    environ = {
        'REQUEST_METHOD': request.method,
        'SCRIPT_NAME': '',
        'PATH_INFO': unquote(path),
        'QUERY_STRING': unquote(query),
        'REMOTE_ADDR': ip,
        'SERVER_PROTOCOL': request.version,
        'REMOTE_PORT': port,
        'wsgi.input': request.body,
        'wsgi.error': sys.stderr,
        'wsgi.version': (1, 0),
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
        'wsgi.url_scheme': 'http' if request.extra.get('sslcontext') is None else 'https',
    }
    environ.update(headers)
    return environ


class WsgiHandler(BaseHandler):
    def __init__(self, transport, protocol, reader, writer, *, app):
        self._app = app
        super().__init__(transport, protocol, reader, writer)
    @asyncio.coroutine
    def handle_request(self, request):
        environ = request_to_wsgi(request)

        def start_response(status, headers):
            self._writer.write_status(status)
            self._writer.write_headers(headers)
            def write(data):
                self._writer.write(data)
            return write
        result = yield from self._app(environ, start_response)

        self._writer.writelines(result)


class WsgiProtocol(BaseHttpProtocol):
    handler_factory = WsgiHandler
    def __init__(self, app, keep_alive=None, loop=None):
        self._app = app
        super().__init__(keep_alive=keep_alive,
                        loop=loop)

    def get_handler_kwargs(self):
        return {'app': self._app}
