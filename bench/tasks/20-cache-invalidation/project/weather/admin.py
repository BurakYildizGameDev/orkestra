from weather import api


def update_city(city, data):
    api.store(city.strip().lower(), data)
