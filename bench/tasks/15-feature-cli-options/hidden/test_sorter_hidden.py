from sorter import main


def run(argv, capsys):
    code = main(argv)
    return code, capsys.readouterr().out.split()


def test_reverse(capsys):
    assert run(["b", "a", "c", "--reverse"], capsys) == (0, ["c", "b", "a"])


def test_unique_keeps_the_first(capsys):
    assert run(["b", "a", "b", "a", "--unique"], capsys) == (0, ["a", "b"])


def test_combined_with_numeric(capsys):
    code, out = run(["2", "10", "2", "--numeric", "--reverse", "--unique"], capsys)
    assert (code, out) == (0, ["10", "2"])


def test_errors_still_work(capsys):
    assert main(["x", "--numeric"]) == 2
