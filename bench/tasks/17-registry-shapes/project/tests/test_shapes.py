import math

import shapes


def test_area():
    assert shapes.area("circle", radius=1) == math.pi
    assert shapes.area("square", side=3) == 9
