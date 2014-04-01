

class MultiDict(dict):
    def __getitem__(self, key):
        value = super().__getitem__(key)
        return value[0]

    def __setitem__(self, key, value):
        super().__setitem__(key, [value])

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def getlist(self, key, default=[]):
        return super().get(key, default)

    def items(self):
        for key in self:
            yield key, self[key]

    def values(self):
        for key in self:
            yield self[key]

    def lists(self):
        return super().items()

    def __repr__(self):  # pragma: no cover
        return "<MultiDict {}>".format(super().__repr__())
