import math


def circle_area(radius):
    if radius < 0:
        raise ValueError("radius must not be negative")
    return math.pi * radius * radius


def rectangle_perimeter(width, height):
    return 2 * (width + height)


def distance(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


def triangle_area(a, b, c):
    s = (a + b + c) / 2
    value = s * (s - a) * (s - b) * (s - c)
    if value < 0:
        raise ValueError("not a triangle")
    return math.sqrt(value)
