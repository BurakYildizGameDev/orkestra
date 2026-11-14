import inspect

import pytest
import signup


def setup_function():
    signup.USERS.clear()


def test_one_helper_used_by_both():
    assert hasattr(signup, "_normalize_email")
    for fn in (signup.register, signup.update_email):
        source = inspect.getsource(fn)
        assert "_normalize_email(" in source
        assert ".count(" not in source and "split(" not in source


@pytest.mark.parametrize("bad", ["a@b", "@b.com", "a@.com", "a@com.", "a@@b.com", "ab.com", " "])
def test_the_helper_rejects(bad):
    with pytest.raises(ValueError):
        signup._normalize_email(bad)


def test_the_helper_cleans():
    assert signup._normalize_email("  Ada@Example.ORG ") == "ada@example.org"


def test_behaviour_is_unchanged():
    signup.register("Ada", "ada@example.org")
    with pytest.raises(ValueError):
        signup.register("Ada", "ADA@example.org")
    with pytest.raises(ValueError):
        signup.update_email("ada@example.org", "bad")
    assert signup.update_email("ada@example.org", "ada@x.io") == "ada@x.io"
