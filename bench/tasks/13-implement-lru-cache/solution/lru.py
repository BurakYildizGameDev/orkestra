from collections import OrderedDict


class LRUCache:
    """A fixed-size cache that drops the least recently used key when full."""

    def __init__(self, capacity):
        """``capacity`` >= 1, otherwise ValueError."""
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._capacity = capacity
        self._data = OrderedDict()

    def get(self, key, default=None):
        """The value (and the key becomes the most recently used), or ``default``."""
        if key not in self._data:
            return default
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key, value):
        """Store or replace; both make the key the most recently used. When a new key does
        not fit, the least recently used one is dropped first."""
        if key in self._data:
            self._data.move_to_end(key)
        elif len(self._data) >= self._capacity:
            self._data.popitem(last=False)
        self._data[key] = value

    def __len__(self):
        return len(self._data)

    def __contains__(self, key):
        """Membership test; does not change the order."""
        return key in self._data

    def keys(self):
        """Keys from least to most recently used."""
        return list(self._data)
