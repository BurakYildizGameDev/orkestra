import pytest
import signup


def setup_function():
    signup.USERS.clear()


def test_register_and_update():
    assert signup.register("Ada", " Ada@Example.org ") == "ada@example.org"
    assert signup.update_email("ada@example.org", "ADA@new.org") == "ada@new.org"
    assert signup.USERS == {"ada@new.org": "Ada"}


def test_invalid():
    with pytest.raises(ValueError):
        signup.register("x", "no-at-sign")
