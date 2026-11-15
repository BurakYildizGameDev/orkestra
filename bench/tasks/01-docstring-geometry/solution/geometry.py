import math


def circle_area(radius):
    """Area of a circle.

    Args:
        radius: The circle's radius; must not be negative.

    Returns:
        The area as a float.
    """
    if radius < 0:
        raise ValueError("radius must not be negative")
    return math.pi * radius * radius


def rectangle_perimeter(width, height):
    """Perimeter of a rectangle.

    Args:
        width: The rectangle's width.
        height: The rectangle's height.

    Returns:
        The perimeter.
    """
    return 2 * (width + height)


def distance(x1, y1, x2, y2):
    """Straight-line distance between two points.

    Args:
        x1: X of the first point.
        y1: Y of the first point.
        x2: X of the second point.
        y2: Y of the second point.

    Returns:
        The distance as a float.
    """
    return math.hypot(x2 - x1, y2 - y1)


def triangle_area(a, b, c):
    """Area of a triangle from its side lengths (Heron's formula).

    Args:
        a: Length of the first side.
        b: Length of the second side.
        c: Length of the third side.

    Returns:
        The area as a float.
    """
    s = (a + b + c) / 2
    value = s * (s - a) * (s - b) * (s - c)
    if value < 0:
        raise ValueError("not a triangle")
    return math.sqrt(value)
