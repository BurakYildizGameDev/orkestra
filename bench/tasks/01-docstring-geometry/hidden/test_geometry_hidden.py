import inspect
import math

import geometry
import pytest

PUBLIC = ["circle_area", "rectangle_perimeter", "distance", "triangle_area"]


@pytest.mark.parametrize("name", PUBLIC)
def test_every_public_function_has_a_full_docstring(name):
    fn = getattr(geometry, name)
    doc = inspect.getdoc(fn)
    assert doc, f"{name} has no docstring"
    summary = doc.splitlines()[0].strip()
    assert summary and not summary.startswith(("Args", "Returns"))
    assert "Args:" in doc and "Returns:" in doc
    for param in inspect.signature(fn).parameters:
        assert param in doc.split("Args:", 1)[1], f"{name}: {param} is not described"


def test_behaviour_is_unchanged():
    assert geometry.circle_area(2) == pytest.approx(4 * math.pi)
    assert geometry.rectangle_perimeter(3, 4) == 14
    assert geometry.distance(0, 0, 3, 4) == 5
    assert geometry.triangle_area(3, 4, 5) == pytest.approx(6)
    with pytest.raises(ValueError):
        geometry.circle_area(-1)
    with pytest.raises(ValueError):
        geometry.triangle_area(1, 1, 5)
