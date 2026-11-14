from nested import flatten


def test_strings_are_single_items():
    assert flatten(["ab", ["cd", ["ef"]]]) == ["ab", "cd", "ef"]
    assert flatten([b"xy", [b"z"]]) == [b"xy", b"z"]


def test_all_levels():
    assert flatten([1, [2, [3, (4, 5)], 6]]) == [1, 2, 3, 4, 5, 6]


def test_depth():
    data = [1, [2, [3, [4]]]]
    assert flatten(data, depth=0) == [1, [2, [3, [4]]]]
    assert flatten(data, depth=1) == [1, 2, [3, [4]]]
    assert flatten(data, depth=2) == [1, 2, 3, [4]]


def test_generators_and_dicts():
    assert flatten([(x for x in range(2)), {"k": 1}]) == [0, 1, {"k": 1}]
