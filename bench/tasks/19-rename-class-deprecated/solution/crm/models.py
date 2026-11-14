import warnings
from dataclasses import dataclass


@dataclass
class Customer:
    id: int
    name: str
    email: str

    def display(self):
        return f"{self.name} <{self.email}>"


def __getattr__(name):
    if name == "UserRecord":
        warnings.warn(
            "crm.models.UserRecord is deprecated; use Customer", DeprecationWarning, stacklevel=2
        )
        return Customer
    raise AttributeError(f"module 'crm.models' has no attribute {name!r}")
