from dataclasses import dataclass, field


@dataclass(frozen=True)
class Product:
    name: str
    price: float
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.price < 0:
            raise ValueError("price must not be negative")

    def price_with_vat(self, rate: float = 0.2) -> float:
        return round(self.price * (1 + rate), 2)
