from shapes.registry import register


@register("triangle")
def triangle_area(base, height):
    return base * height / 2
