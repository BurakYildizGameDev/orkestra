class LRUCache:
    """A fixed-size cache that drops the least recently used key when full."""

    def __init__(self, capacity):
        """``capacity`` >= 1, otherwise ValueError."""
        raise NotImplementedError

    def get(self, key, default=None):
        """The value (and the key becomes the most recently used), or ``default``."""
        raise NotImplementedError

    def put(self, key, value):
        """Store or replace; both make the key the most recently used. When a new key does
        not fit, the least recently used one is dropped first."""
        raise NotImplementedError

    def __len__(self):
        raise NotImplementedError

    def __contains__(self, key):
        """Membership test; does not change the order."""
        raise NotImplementedError

    def keys(self):
        """Keys from least to most recently used."""
        raise NotImplementedError
