import math

from shapes.registry import register


@register("circle")
def circle_area(radius):
    return math.pi * radius**2
