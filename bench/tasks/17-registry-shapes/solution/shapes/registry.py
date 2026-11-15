_SHAPES = {}


def register(name):
    def store(fn):
        if name in _SHAPES:
            raise ValueError(f"shape {name!r} is already registered")
        _SHAPES[name] = fn
        return fn

    return store


def get(name):
    try:
        return _SHAPES[name]
    except KeyError:
        raise KeyError(f"unknown shape {name!r}; known: {', '.join(available())}") from None


def available():
    return sorted(_SHAPES)
