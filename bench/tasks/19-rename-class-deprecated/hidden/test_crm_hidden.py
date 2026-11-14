import importlib
import pathlib
import warnings

import crm
import crm.models
import pytest
from crm.store import Store


def test_customer_is_the_class():
    assert crm.models.Customer.__name__ == "Customer"
    assert isinstance(Store().add(1, "Ada", "a@x.org"), crm.models.Customer)
    assert "Customer" in crm.__all__


@pytest.mark.parametrize("module", ["crm", "crm.models"])
def test_the_old_name_warns_and_is_the_new_class(module):
    mod = importlib.import_module(module)
    with pytest.warns(DeprecationWarning, match="Customer"):
        old = mod.UserRecord
    assert old is crm.models.Customer


def test_from_import_warns():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from crm import UserRecord  # noqa: F401
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_no_module_uses_the_old_name():
    root = pathlib.Path(crm.__file__).parent
    for name in ("store.py", "export.py"):
        assert "UserRecord" not in (root / name).read_text(encoding="utf-8"), name


def test_the_new_name_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        crm.models.Customer(1, "a", "b")
