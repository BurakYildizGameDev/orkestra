from weather import api
from weather.cache import TTLCache

CACHE = TTLCache(60)


def _key(city):
    return city.strip().lower()


def get_forecast(city):
    key = _key(city)
    cached = CACHE.get(key)
    if cached is not None:
        return cached
    value = api.fetch(key)
    CACHE.set(key, value)
    return value
