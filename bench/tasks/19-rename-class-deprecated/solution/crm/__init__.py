import warnings

from crm.models import Customer

__all__ = ["Customer"]


def __getattr__(name):
    if name == "UserRecord":
        warnings.warn(
            "crm.UserRecord is deprecated; use crm.Customer", DeprecationWarning, stacklevel=2
        )
        return Customer
    raise AttributeError(f"module 'crm' has no attribute {name!r}")
