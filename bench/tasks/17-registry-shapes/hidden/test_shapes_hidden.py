import inspect

import pytest
import shapes
from shapes import registry


def test_triangle_and_available():
    assert shapes.area("triangle", base=4, height=3) == 6
    assert shapes.available() == ["circle", "square", "triangle"]


def test_a_new_shape_registers_itself():
    @registry.register("hexagon-test")
    def hexagon(side):
        return 2.598 * side * side

    assert shapes.area("hexagon-test", side=1) == 2.598
    assert "hexagon-test" in shapes.available()
    with pytest.raises(ValueError):
        registry.register("hexagon-test")(hexagon)


def test_unknown_shape_lists_the_known_ones():
    with pytest.raises(KeyError) as info:
        shapes.area("blob")
    assert "circle" in str(info.value) and "square" in str(info.value)


def test_no_if_chain():
    source = inspect.getsource(shapes.area)
    assert "elif" not in source and '"circle"' not in source
