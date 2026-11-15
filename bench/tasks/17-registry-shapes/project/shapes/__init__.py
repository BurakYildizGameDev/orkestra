from shapes.circle import circle_area
from shapes.square import square_area


def area(name, **kwargs):
    if name == "circle":
        return circle_area(**kwargs)
    elif name == "square":
        return square_area(**kwargs)
    raise KeyError(name)


def available():
    return ["circle", "square"]
