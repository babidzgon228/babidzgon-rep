"""[Агент «Планировщик»] Статистика трекера и эффективности. ЗАГЛУШКА — реализовать."""
from __future__ import annotations

from datetime import date

from bot.models import DayStats, PeriodStats, User


async def day_stats(db, user: User, d: date) -> DayStats:
    raise NotImplementedError


async def period_stats(db, user: User, start: date, end: date) -> PeriodStats:
    """Статистика за [start, end] включительно."""
    raise NotImplementedError
