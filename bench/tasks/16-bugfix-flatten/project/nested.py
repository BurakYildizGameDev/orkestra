from collections.abc import Iterable


def flatten(items, depth=None):
    out = []
    for item in items:
        if isinstance(item, Iterable):
            out.extend(flatten(item))
        else:
            out.append(item)
    return out
