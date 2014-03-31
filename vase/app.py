import asyncio
from .protocol import BaseHttpProtocol
from .request import HttpRequest
from .response import HttpResponse
from .handlers import (
    CallbackRoute,
    RoutingProcessor,
    CallbackRouteHandler,
    WebSocketHandler
)

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
        self._routes = []

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
            (b'Content-Type', b'text/plain'),
            (b'Content-Length', str(len(data)).encode('utf-8'))
        )
        start_response(b'404 Not Found', headers)
        return [data]

    def route(self, *, path, methods=('get', 'post')):
        def wrap(func):
            self._routes.append(CallbackRoute(CallbackRouteHandler, "^%s$" % path, self._decorate_callback(func)))
            return func

        return wrap

    def endpoint(self, *, path):
        def wrap(cls):
            self._routes.append(CallbackRoute(WebSocketHandler, "^%s$" % path, cls))
            return cls

        return wrap

    def run(self, *, host='0.0.0.0', port=3000, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        def processor_factory(transport, protocol, reader, writer):
            return RoutingProcessor(transport, protocol, reader, writer, routes=self._routes)

        asyncio.async(loop.create_server(lambda: BaseHttpProtocol(processor_factory, loop=loop),
                    host, port))
        loop.run_forever()

    @staticmethod
    def _decorate_callback(callback):
        @asyncio.coroutine
        def handle_normal(environ, start_response):
            request = HttpRequest(environ)
            yield from request._maybe_init_post()

            data = yield from asyncio.coroutine(callback)(request)
            if isinstance(data, HttpResponse):
                response = data
            else:
                response = HttpResponse(data)

            return response(environ, start_response)
        return handle_normal
