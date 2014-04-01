import unittest
import unittest.mock

from vase.routing import (
    RequestSpec,
    pattern_to_regex,
    PatternRequestMatcher,
)


class RequestSpecTests(unittest.TestCase):
    def test_request_spec(self):
        spec = RequestSpec("/")
        self.assertEqual(spec.pattern, "/")
        self.assertEqual(spec.methods, ("*",))

        self.assertEqual(str(spec), "<RequestSpec pattern='/' methods='('*',)'>")


class PatternToRequestTests(unittest.TestCase):
    def test_basic(self):
        result = pattern_to_regex("/{user_id}")
        self.assertEqual(result.pattern, "^/(?P<user_id>[^/]+)$")

        result = pattern_to_regex("/{user_id}/{hello:\d+}")
        self.assertEqual(result.pattern, '^/(?P<user_id>[^/]+)/(?P<hello>\d+)$')


class PatternRequestMatcherTests(unittest.TestCase):
    def test(self):
        req = RequestSpec(pattern="/{foo}/{bar}")
        matcher = PatternRequestMatcher(req)
        request = unittest.mock.Mock()
        request.path = "/bar/baz"
        self.assertEqual(matcher.match(request), {
            'foo': 'bar',
            'bar': 'baz'
        })
