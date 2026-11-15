from collections.abc import Iterable


def flatten(items, depth=None):
    out = []
    for item in items:
        openable = isinstance(item, Iterable) and not isinstance(item, (str, bytes, dict))
        if openable and (depth is None or depth > 0):
            out.extend(flatten(item, None if depth is None else depth - 1))
        else:
            out.append(item)
    return out
