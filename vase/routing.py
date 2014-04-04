import asyncio
import re
from .protocol import BaseProcessor


class RoutingHttpProcessor(BaseProcessor):
    def __init__(self, transport, protocol, reader, writer, *, routes=None):
        if not routes:
            routes = []
        self._routes = routes
        self._handler = None
        super().__init__(transport, protocol, reader, writer)

    @asyncio.coroutine
    def handle_request(self, request):
        current_route = None
        matchdict = {}
        for route in self._routes:
            matchdict = route.matches(request)
            if matchdict is not None:
                current_route = route
                break
        if current_route is None:
            return (yield from super().handle_request(request))
        self._handler = current_route.handler_factory(request, self._reader, self._writer)

        return (yield from self._handler.handle(**matchdict))

    def on_timeout(self):
        self._handler.on_timeout()
        if self._handler.persistent_connection():
            return
        super().on_timeout()

    def connection_lost(self, exc):
        if self._handler is not None:
            self._handler.connection_lost(exc)


class RequestSpec:
    def __init__(self, pattern, methods="*"):
        self.pattern = pattern
        if isinstance(methods, str):
            methods = (methods, )
        self.methods = tuple(m.lower() for m in methods)

    def __str__(self):
        return "<{} pattern='{}' methods='{}'>".format(
            self.__class__.__name__,
            self.pattern,
            self.methods
        )


_R = re.compile("{((\w+:)?[^{}]+)}")


def _regex_substituter(m):
    name = m.groups()[0]
    if ":" not in name:
        name = "%s:[^/]+" % name
    n, t = name.split(":")
    return "(?P<%s>%s)" % (n, t)


def pattern_to_regex(pattern):
    regex = "^%s$" % _R.sub(_regex_substituter, pattern)
    return re.compile(regex)


class RequestMatcher:

    def match(self, request):
        raise NotImplementedError


class PatternRequestMatcher(RequestMatcher):

    def __init__(self, spec):
        self._spec = spec
        self._regex = pattern_to_regex(spec.pattern)

    def match(self, request):
        if "*" not in self._spec.methods:
            if request.method.lower() not in self._spec.methods:
                return None


        match = self._regex.match(request.path)
        if match is None:
            return None
        return match.groupdict()


class Route:
    def matches(self, request):
        return True

    def handler_factory(self, request, reader, writer):
        raise NotImplementedError


class UrlRoute(Route):
    matcher_class = PatternRequestMatcher

    def __init__(self, spec):
        self._matcher = self.matcher_class(spec)

    def matches(self, request):
        return self._matcher.match(request)


class CallbackRoute(UrlRoute):
    def __init__(self, handler_factory, spec, callback):
        super().__init__(spec)
        self._handler_factory = handler_factory
        self._callback = callback

    def handler_factory(self, request, reader, writer):
        return self._handler_factory(request, reader, writer, self._callback)


class ContextHandlingCallbackRoute(CallbackRoute):
    def __init__(self, handler_factory, spec, callback):
        super().__init__(handler_factory, spec, callback)
        self._context_map = {}

    def handler_factory(self, request, reader, writer):
        return self._handler_factory(request, reader, writer, self._callback, self._context_map)