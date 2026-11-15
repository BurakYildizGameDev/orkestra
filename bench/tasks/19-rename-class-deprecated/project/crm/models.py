from dataclasses import dataclass


@dataclass
class UserRecord:
    id: int
    name: str
    email: str

    def display(self):
        return f"{self.name} <{self.email}>"
