from weather import api, service


def update_city(city, data):
    key = service._key(city)
    api.store(key, data)
    service.CACHE.invalidate(key)
