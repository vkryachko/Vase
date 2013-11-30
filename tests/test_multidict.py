import unittest
from vase.request import MultiDict


class MultiDictTests(unittest.TestCase):

    def test_setitem(self):
        md = MultiDict()
        key = 'hello'
        value = 'world'
        md[key] = value

        self.assertEqual(md[key], value)
        self.assertEqual(md.get(key), value)
        self.assertEqual(md.getlist(key), [value])

        self.assertRaises(KeyError, md.__getitem__, "vasya")

        self.assertEqual(md.get("vasya"), None)

        self.assertEqual(list(md.items()), [(key, value)])

        self.assertEqual(list(md.lists()), [(key, [value])])

        self.assertEqual(list(md.values()), [value])
