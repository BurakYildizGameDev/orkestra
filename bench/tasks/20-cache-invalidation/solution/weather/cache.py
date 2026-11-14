import time


class TTLCache:
    def __init__(self, ttl_s, clock=time.monotonic):
        self._ttl_s = ttl_s
        self._clock = clock
        self._items = {}

    def get(self, key):
        found = self._items.get(key)
        if found is None:
            return None
        stored_at, value = found
        if self._clock() - stored_at > self._ttl_s:
            del self._items[key]
            return None
        return value

    def set(self, key, value):
        self._items[key] = (self._clock(), value)

    def invalidate(self, key):
        self._items.pop(key, None)

    def clear(self):
        self._items.clear()
