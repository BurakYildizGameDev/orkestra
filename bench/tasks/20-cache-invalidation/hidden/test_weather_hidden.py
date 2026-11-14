import pytest
from weather import admin, api, service
from weather.cache import TTLCache


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(service, "CACHE", TTLCache(60, clock=fake))
    api.CALLS["count"] = 0
    api.store("paris", {"temp": 18})
    return fake


def test_second_call_is_cached_and_case_insensitive(clock):
    assert service.get_forecast("Paris")["temp"] == 18
    assert service.get_forecast("  paris ")["temp"] == 18
    assert api.CALLS["count"] == 1


def test_entries_expire(clock):
    service.get_forecast("oslo")
    clock.now += 61
    service.get_forecast("oslo")
    assert api.CALLS["count"] == 2


def test_update_invalidates(clock):
    service.get_forecast("paris")
    admin.update_city("PARIS", {"temp": 25})
    assert service.get_forecast("paris")["temp"] == 25
    assert api.CALLS["count"] == 2


def test_cache_unit():
    fake = Clock()
    cache = TTLCache(10, clock=fake)
    assert cache.get("k") is None
    cache.set("k", 1)
    assert cache.get("k") == 1
    fake.now += 11
    assert cache.get("k") is None
    cache.set("a", 1)
    cache.set("b", 2)
    cache.invalidate("a")
    assert cache.get("a") is None and cache.get("b") == 2
    cache.clear()
    assert cache.get("b") is None
