class EmptyStackError(Exception):
    """Raised by pop() and peek() on an empty stack."""


class Stack:
    """Last in, first out, with an optional size limit."""

    def __init__(self, limit=None):
        """``limit``: the most items it may hold (None: no limit); below 1 is a ValueError."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")
        self._items = []
        self._limit = limit

    def push(self, item):
        """Add on top; OverflowError when the stack is full."""
        if self._limit is not None and len(self._items) >= self._limit:
            raise OverflowError("stack is full")
        self._items.append(item)

    def pop(self):
        """Remove and return the top item; EmptyStackError when empty."""
        if not self._items:
            raise EmptyStackError("pop from an empty stack")
        return self._items.pop()

    def peek(self):
        """Return the top item without removing it; EmptyStackError when empty."""
        if not self._items:
            raise EmptyStackError("peek at an empty stack")
        return self._items[-1]

    def __len__(self):
        return len(self._items)

    def is_empty(self):
        return not self._items
