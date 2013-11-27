import asyncio
import sys
from .server import HttpProtocol
from urllib.parse import quote, unquote
import ssl

class WsgiProtocol(HttpProtocol):
    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self._app = app

    @asyncio.coroutine
    def handle_request(self, message, writer):
        wsgienv = self._build_environ(message, writer.transport)

        def start_response(status, headers, exc_info=None):
            writer.write_status(status)
            writer.write_headers(headers)

            return writer

        result = yield from self._app(wsgienv, start_response)
        assert writer.status_written, 'Wsgi app did not call start_response!'
        if(message.keep_alive):
            writer.write_header('Connection', 'Keep-Alive')
        writer.writelines(result)


    def _build_environ(self, message, transport):
        try:
            path, query = message.url.split('?')
        except ValueError:
            path = message.url
            query = ''

        ip, port = message.peername[0], message.peername[1]
        sslctx = transport.get_extra_info('sslcontext')

        headers = {}
        for name, value in message.headers:
            hname = 'HTTP_{}'.format(name.decode('ascii').replace('-', '_').upper())
            if hname not in headers:
                headers[hname] = value.decode('ascii')
            else:
                sep = ','
                if hname == 'HTTP_COOKIE':
                    sep = ';'
                headers[hname] += "{}{}".format(sep, value)

        environ = {
            'REQUEST_METHOD': message.method,
            'SCRIPT_NAME': '',
            'PATH_INFO': unquote(path),
            'QUERY_STRING': unquote(query),
            'REMOTE_ADDR': ip,
            'SERVER_PROTOCOL': message.version,
            'REMOTE_PORT': port,
            'wsgi.input': message.body,
            'wsgi.error': sys.stderr,
            'wsgi.version': (1, 0),
            'wsgi.multithread': False,
            'wsgi.multiprocess': False,
            'wsgi.run_once': False,
            'wsgi.url_scheme': 'http' if sslctx is None else 'https',
        }
        environ.update(headers)
        return environ


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    
    asyncio.async(loop.create_server(lambda: WsgiProtocol(loop=loop),
                        '10.66.10.109', 3000, ssl=None))
    loop.run_forever()
