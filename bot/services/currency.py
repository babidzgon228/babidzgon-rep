"""Курс юаня к рублю (официальный курс ЦБ РФ через cbr-xml-daily.ru: бесплатно, без ключа)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
CACHE_TTL = 3 * 60 * 60


@dataclass
class Rate:
    code: str          # "CNY"
    rub: float         # рублей за 1 единицу
    prev_rub: float
    date: str          # дата курса ЦБ (ISO)

    @property
    def change(self) -> float:
        return self.rub - self.prev_rub

    def line(self, lang: str = "ru") -> str:
        """«💴 ¥1 = 11.42 ₽ ▲0.05» — для утренней сводки."""
        arrow = "▲" if self.change > 0.0001 else "▼" if self.change < -0.0001 else "•"
        diff = f" {arrow}{abs(self.change):.2f}" if arrow != "•" else ""
        label = {"ru": "курс ЦБ", "en": "CBR rate", "zh": "央行汇率"}.get(lang, "")
        return f"💴 ¥1 = {self.rub:.2f} ₽{diff} · {label}"

    def convert(self, amount: float, frm: str = "CNY") -> float:
        """CNY→RUB или RUB→CNY."""
        return amount * self.rub if frm == "CNY" else amount / self.rub


def parse_cbr(data: dict[str, Any], code: str = "CNY") -> Rate | None:
    try:
        v = data["Valute"][code]
        nominal = float(v.get("Nominal") or 1)
        return Rate(code=code, rub=float(v["Value"]) / nominal, prev_rub=float(v["Previous"]) / nominal,
                    date=str(data.get("Date", ""))[:10])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        log.warning("currency: неожиданный ответ API")
        return None


_cache: dict[str, tuple[float, Rate]] = {}


async def get_rate(code: str = "CNY", session: aiohttp.ClientSession | None = None) -> Rate | None:
    hit = _cache.get(code)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    own = session is None
    session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    try:
        async with session.get(API_URL) as resp:
            if resp.status != 200:
                log.warning("currency: HTTP %s", resp.status)
                return None
            # сервер отдаёт application/javascript — content_type=None, чтобы aiohttp не ругался
            rate = parse_cbr(await resp.json(content_type=None), code)
    except (aiohttp.ClientError, TimeoutError, ValueError) as e:
        log.warning("currency: сеть недоступна: %s", e)
        return None
    finally:
        if own:
            await session.close()
    if rate:
        _cache[code] = (time.monotonic(), rate)
    return rate
