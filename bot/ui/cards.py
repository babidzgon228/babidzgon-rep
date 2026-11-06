"""[Агент «Интерфейс»] PNG-карточка плана дня (Pillow). ЗАГЛУШКА — реализовать."""
from __future__ import annotations

from bot.models import DayPlan


def render_day_card(plan: DayPlan, *, title: str, subtitle: str | None = None) -> bytes:
    """PNG-картинка расписания/плана дня. Возвращает bytes PNG."""
    raise NotImplementedError
