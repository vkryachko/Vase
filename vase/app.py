import asyncio
import functools
import collections
from routes import Mapper
from .webserver import WebServer
from .request import HttpRequest
from .response import HttpResponse

__all__ = ["Vase"]


_HANDLER_ATTR = '_vase__handler'
_BAG_ATTR = '_vase__bag'


class CallableDict(dict):
    "Dirty hack, so that routes does not stringify the dict"
    def __call__(self):
        pass


class Vase:
    def __init__(self, name):
        self._name = name
        self._routes = Mapper(register=False)
        self._endpoints = Mapper(register=False)

    @asyncio.coroutine
    def __call__(self, environ, start_response):
        match = self._routes.match(environ=environ)
        if match is None:
            return (yield from self._handle_404(environ, start_response))

        handler = match.pop(_HANDLER_ATTR)
        request = HttpRequest(environ)
        yield from request._maybe_init_post()

        data = yield from asyncio.coroutine(handler)(request)
        if isinstance(data, HttpResponse):
            response = data
        else:
            response = HttpResponse(data)
        
        return response(environ, start_response)

    def initialize_endpoint(self, environ):
        match = self._endpoints.match(environ=environ)
        if match is None:
            return None
        handler = match.pop(_HANDLER_ATTR)
        bag = match.pop(_BAG_ATTR)
        instance = handler()
        instance.bag = bag

        return instance

    @asyncio.coroutine
    def _handle_404(self, environ, start_response):
        data = 'Not found'.encode('utf-8')
        headers = (
            ('Content-Type', 'text/plain'),
            ('Content-Length', str(len(data)))
        )
        start_response(b'404 Not Found', headers)
        return [data]

    def route(self, *, path, methods=('get', 'post')):
        def wrap(func):
            self._routes.connect(path, **{_HANDLER_ATTR: func})
            return func

        return wrap

    def endpoint(self, *, path):
        def wrap(cls):
            self._endpoints.connect(path, **{_HANDLER_ATTR: cls, _BAG_ATTR: CallableDict()})
            return cls

        return wrap

    def run(self, *, host='0.0.0.0', port=3000, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()
        asyncio.async(loop.create_server(lambda: WebServer(loop=loop, app=self),
                    host, port))
        loop.run_forever()
