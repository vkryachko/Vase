from asyncio import coroutine


class LimitedReader:
    def __init__(self, reader, limit):
        self._reader = reader
        self._limit = limit
        self._read_count = 0

    @coroutine
    def read(self, n=-1):
        if not n or not self.bytes_left:
            return b''
        if n < 0 or n > self.bytes_left:
            n = self.bytes_left
        self._read_count += n
        return (yield from self._reader.read(n))

    @property
    def bytes_left(self):
        left = self._limit - self._read_count
        if left < 0:  # pragma: no cover
            left = 0
        return left
