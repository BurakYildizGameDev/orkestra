import pricing
import report


def test_the_new_name_exists_and_the_old_one_is_gone():
    assert hasattr(pricing, "format_price")
    assert not hasattr(pricing, "fmt")
    assert not hasattr(report, "fmt")


def test_behaviour():
    assert pricing.format_price(1234.5) == "1,234.50 EUR"
    assert pricing.format_price(3, currency="USD") == "3.00 USD"
    assert report.line("tea", 10) == "tea: 12.00 EUR"
    assert report.total([("a", 10), ("b", 5)]) == "18.00 EUR"
