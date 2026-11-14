from weather import api


def get_forecast(city):
    return api.fetch(city.strip().lower())
