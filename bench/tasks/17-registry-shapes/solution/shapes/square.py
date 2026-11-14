from shapes.registry import register


@register("square")
def square_area(side):
    return side * side
