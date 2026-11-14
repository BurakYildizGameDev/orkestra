from shapes import circle, registry, square, triangle  # noqa: F401  (they register themselves)


def area(name, **kwargs):
    return registry.get(name)(**kwargs)


def available():
    return registry.available()
