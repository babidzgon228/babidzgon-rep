"""Погода для утренней сводки (Open-Meteo: бесплатно, без ключа).

Город выбирается по текущему часовому поясу пользователя (Шэньчжэнь ↔ Москва меняются сами).
Ошибки сети не роняют бота: функции возвращают None.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from bot.models import UserSettings

log = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_TTL = 30 * 60

# часовой пояс -> (ключ города, широта, долгота)
CITIES: dict[str, tuple[str, float, float]] = {
    "Asia/Shanghai": ("shenzhen", 22.5431, 114.0579),
    "Asia/Hong_Kong": ("shenzhen", 22.5431, 114.0579),
    "Europe/Moscow": ("moscow", 55.7558, 37.6173),
}
CITY_NAMES = {
    "shenzhen": {"ru": "Шэньчжэнь", "en": "Shenzhen", "zh": "深圳"},
    "moscow": {"ru": "Москва", "en": "Moscow", "zh": "莫斯科"},
}

# WMO weather codes -> (emoji, {ru, en, zh})
_WMO: list[tuple[tuple[int, ...], str, dict[str, str]]] = [
    ((0,), "☀️", {"ru": "ясно", "en": "clear", "zh": "晴"}),
    ((1, 2), "🌤", {"ru": "переменная облачность", "en": "partly cloudy", "zh": "多云"}),
    ((3,), "☁️", {"ru": "пасмурно", "en": "overcast", "zh": "阴"}),
    ((45, 48), "🌫", {"ru": "туман", "en": "fog", "zh": "雾"}),
    ((51, 53, 55, 56, 57), "🌦", {"ru": "морось", "en": "drizzle", "zh": "毛毛雨"}),
    ((61, 63, 80, 81), "🌧", {"ru": "дождь", "en": "rain", "zh": "雨"}),
    ((65, 82), "🌧", {"ru": "ливень", "en": "heavy rain", "zh": "大雨"}),
    ((66, 67), "🌧", {"ru": "ледяной дождь", "en": "freezing rain", "zh": "冻雨"}),
    ((71, 73, 75, 77, 85, 86), "🌨", {"ru": "снег", "en": "snow", "zh": "雪"}),
    ((95, 96, 99), "⛈", {"ru": "гроза", "en": "thunderstorm", "zh": "雷雨"}),
]

ALERTS = {
    "umbrella": {"ru": "☂️ Возьми зонт", "en": "☂️ Take an umbrella", "zh": "☂️ 记得带伞"},
    "storm": {"ru": "⚠️ Гроза — по возможности сиди в помещении",
              "en": "⚠️ Thunderstorm — stay indoors if you can", "zh": "⚠️ 有雷雨，尽量待在室内"},
    "wind": {"ru": "🌀 Сильный ветер — следи за предупреждениями о тайфуне",
             "en": "🌀 Strong wind — watch for typhoon warnings", "zh": "🌀 大风，注意台风预警"},
    "heat": {"ru": "🥵 Жара — пей воду", "en": "🥵 Heat — drink water", "zh": "🥵 高温，多喝水"},
    "cold": {"ru": "🧣 Холодно — одевайся теплее", "en": "🧣 Cold — dress warmly", "zh": "🧣 天冷，多穿点"},
}


@dataclass
class Weather:
    city: str                      # ключ из CITY_NAMES
    now_temp: float | None
    now_code: int | None
    t_min: float
    t_max: float
    code: int
    precip_prob: int | None
    wind_max: float | None         # км/ч

    def emoji(self) -> str:
        return describe(self.code)[0]

    def text(self, lang: str = "ru") -> str:
        return describe(self.code)[1].get(lang) or describe(self.code)[1]["ru"]

    def city_name(self, lang: str = "ru") -> str:
        names = CITY_NAMES.get(self.city, {})
        return names.get(lang) or names.get("ru") or self.city

    def alerts(self) -> list[str]:
        """Ключи ALERTS, актуальные на сегодня."""
        out: list[str] = []
        if self.code in (95, 96, 99):
            out.append("storm")
        if (self.precip_prob or 0) >= 60 or self.code in (61, 63, 65, 80, 81, 82):
            out.append("umbrella")
        if (self.wind_max or 0) >= 50:
            out.append("wind")
        if self.t_max >= 33:
            out.append("heat")
        if self.t_min <= -10:
            out.append("cold")
        return out

    def line(self, lang: str = "ru") -> str:
        """Одна строка для сводки: «🌧 Шэньчжэнь: дождь, +21…+26°, сейчас +23° · ☂️ Возьми зонт»."""
        def t(v: float) -> str:
            return f"{'+' if v > 0 else ''}{round(v)}°"
        parts = [f"{self.emoji()} {self.city_name(lang)}: {self.text(lang)}, {t(self.t_min)}…{t(self.t_max)}"]
        if self.now_temp is not None:
            parts[0] += {"ru": f", сейчас {t(self.now_temp)}", "en": f", now {t(self.now_temp)}",
                         "zh": f"，现在 {t(self.now_temp)}"}.get(lang, f", {t(self.now_temp)}")
        alerts = [ALERTS[a].get(lang) or ALERTS[a]["ru"] for a in self.alerts()]
        return " · ".join(parts + alerts)


def describe(code: int | None) -> tuple[str, dict[str, str]]:
    for codes, emoji, names in _WMO:
        if code in codes:
            return emoji, names
    return "🌡", {"ru": "погода", "en": "weather", "zh": "天气"}


def city_for(settings: UserSettings) -> tuple[str, float, float] | None:
    return CITIES.get(settings.tz)


def parse_forecast(city: str, data: dict[str, Any]) -> Weather | None:
    """Разбор ответа Open-Meteo (берём первый день daily)."""
    try:
        daily = data["daily"]
        cur = data.get("current") or {}
        prob = (daily.get("precipitation_probability_max") or [None])[0]
        wind = (daily.get("wind_speed_10m_max") or [None])[0]
        return Weather(
            city=city,
            now_temp=cur.get("temperature_2m"),
            now_code=cur.get("weather_code"),
            t_min=float(daily["temperature_2m_min"][0]),
            t_max=float(daily["temperature_2m_max"][0]),
            code=int(daily["weather_code"][0]),
            precip_prob=int(prob) if prob is not None else None,
            wind_max=float(wind) if wind is not None else None,
        )
    except (KeyError, IndexError, TypeError, ValueError):
        log.warning("weather: неожиданный ответ API")
        return None


_cache: dict[str, tuple[float, Weather]] = {}


async def get_weather(settings: UserSettings, session: aiohttp.ClientSession | None = None) -> Weather | None:
    """Погода на сегодня для города пользователя. None — если город неизвестен или API недоступно."""
    city = city_for(settings)
    if not city:
        return None
    key, lat, lon = city
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    params = {
        "latitude": lat, "longitude": lon, "timezone": settings.tz, "forecast_days": 1,
        "current": "temperature_2m,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,wind_speed_10m_max",
    }
    own = session is None
    session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    try:
        async with session.get(API_URL, params=params) as resp:
            if resp.status != 200:
                log.warning("weather: HTTP %s", resp.status)
                return None
            weather = parse_forecast(key, await resp.json())
    except (aiohttp.ClientError, TimeoutError) as e:
        log.warning("weather: сеть недоступна: %s", e)
        return None
    finally:
        if own:
            await session.close()
    if weather:
        _cache[key] = (time.monotonic(), weather)
    return weather
