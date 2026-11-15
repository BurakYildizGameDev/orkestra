from sorter import main


def test_sorts(capsys):
    assert main(["b", "a", "c"]) == 0
    assert capsys.readouterr().out.split() == ["a", "b", "c"]


def test_numeric(capsys):
    assert main(["10", "9", "--numeric"]) == 0
    assert capsys.readouterr().out.split() == ["9", "10"]
