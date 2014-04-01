import re

class RequestSpec:
    def __init__(self, pattern, methods="*"):
        self.pattern = pattern
        if isinstance(methods, str):
            method = (methods, )
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
    if ":" not in name: name = "%s:[^/]+" % name
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
