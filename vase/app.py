import asyncio
from .protocol import BaseHttpProtocol
from .response import HttpResponse
from .handlers import (
    CallbackRouteHandler,
    WebSocketHandler,
)
from .routing import (
    CallbackRoute,
    RoutingHttpProcessor,
    WebSocketRoute,
)
from .sockjs import SockJsRoute
from .routing import RequestSpec

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
    def _handle_404(self, request, start_response):
        data = 'Not found'.encode('utf-8')
        headers = (
            (b'Content-Type', b'text/plain'),
            (b'Content-Length', str(len(data)).encode('utf-8'))
        )
        start_response(b'404 Not Found', headers)
        return [data]

    def route(self, *, path, methods=('get', 'post')):
        spec = RequestSpec(path, methods)
        def wrap(func):
            self._routes.append(CallbackRoute(CallbackRouteHandler, spec, self._decorate_callback(func)))
            return func

        return wrap

    def endpoint(self, *, path, with_sockjs=True):
        spec = RequestSpec(path)

        def wrap(cls):
            if with_sockjs:
                self._routes.append(SockJsRoute(spec, cls))
            else:
                self._routes.append(WebSocketRoute(spec, cls))
            return cls

        return wrap

    def run(self, *, host='0.0.0.0', port=3000, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        def processor_factory(transport, protocol, reader, writer):
            return RoutingHttpProcessor(transport, protocol, reader, writer, routes=self._routes)
        asyncio.async(loop.create_server(lambda: BaseHttpProtocol(processor_factory, loop=loop),
                    host, port))
        loop.run_forever()

    @staticmethod
    def _decorate_callback(callback):
        @asyncio.coroutine
        def handle_normal(request, start_response, **kwargs):
            yield from request._maybe_init_post()

            data = yield from asyncio.coroutine(callback)(request, **kwargs)
            if isinstance(data, HttpResponse):
                response = data
            else:
                response = HttpResponse(data)

            return response(start_response)
        return handle_normal
