from weather.service import get_forecast


def test_forecast():
    assert get_forecast("Paris")["temp"] == 18
