CALLS = {"count": 0}
_DATA = {"paris": {"temp": 18}, "oslo": {"temp": 4}}


def fetch(city):
    CALLS["count"] += 1
    return dict(_DATA[city])


def store(city, data):
    _DATA[city] = dict(data)
