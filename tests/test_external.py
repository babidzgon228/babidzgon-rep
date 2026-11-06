"""Погода и курс: разбор ответов API (сеть не нужна)."""
from bot.models import UserSettings
from bot.services.currency import parse_cbr
from bot.services.weather import city_for, parse_forecast

OPEN_METEO = {
    "current": {"temperature_2m": 23.4, "weather_code": 61},
    "daily": {"time": ["2026-11-06"], "weather_code": [63], "temperature_2m_max": [26.1],
              "temperature_2m_min": [20.6], "precipitation_probability_max": [80],
              "wind_speed_10m_max": [55.0]},
}


def test_weather_parse_and_alerts():
    w = parse_forecast("shenzhen", OPEN_METEO)
    assert w and w.t_max == 26.1 and w.precip_prob == 80
    assert set(w.alerts()) == {"umbrella", "wind"}
    line = w.line("ru")
    assert line.startswith("🌧 Шэньчжэнь: дождь, +21°…+26°, сейчас +23°") and "зонт" in line
    assert "深圳" in w.line("zh") and "Shenzhen" in w.line("en")
    assert parse_forecast("moscow", {"daily": {}}) is None


def test_city_follows_timezone():
    assert city_for(UserSettings(tz="Asia/Shanghai"))[0] == "shenzhen"
    assert city_for(UserSettings(tz="Europe/Moscow"))[0] == "moscow"
    assert city_for(UserSettings(tz="America/New_York")) is None


def test_cbr_parse():
    data = {"Date": "2026-11-06T11:30:00+03:00",
            "Valute": {"CNY": {"Nominal": 1, "Value": 11.4231, "Previous": 11.3712}}}
    r = parse_cbr(data)
    assert r and round(r.rub, 4) == 11.4231 and r.date == "2026-11-06"
    assert r.line("ru") == "💴 ¥1 = 11.42 ₽ ▲0.05 · курс ЦБ"
    assert round(r.convert(100), 2) == 1142.31 and round(r.convert(1142.31, "RUB"), 2) == 100.0
    # старый формат с номиналом 10
    r10 = parse_cbr({"Date": "x", "Valute": {"CNY": {"Nominal": 10, "Value": 114.0, "Previous": 114.0}}})
    assert r10.rub == 11.4 and "▲" not in r10.line()
    assert parse_cbr({"Valute": {}}) is None
