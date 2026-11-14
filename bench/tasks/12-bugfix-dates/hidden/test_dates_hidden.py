from datetime import date

import pytest
from dates import add_months, business_days_between


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 15), 1, date(2026, 2, 15)),
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 12, 5), 1, date(2027, 1, 5)),
        (date(2026, 3, 31), -1, date(2026, 2, 28)),
        (date(2026, 1, 10), -13, date(2024, 12, 10)),
        (date(2026, 5, 20), 0, date(2026, 5, 20)),
    ],
)
def test_add_months(start, months, expected):
    assert add_months(start, months) == expected


def test_business_days():
    assert business_days_between(date(2026, 11, 16), date(2026, 11, 23)) == 5  # Mon..Mon
    assert business_days_between(date(2026, 11, 21), date(2026, 11, 23)) == 0  # weekend
    assert business_days_between(date(2026, 11, 20), date(2026, 11, 20)) == 0
    assert business_days_between(date(2026, 11, 23), date(2026, 11, 16)) == -5
