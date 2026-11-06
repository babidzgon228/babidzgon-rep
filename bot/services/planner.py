"""[Агент «Планировщик»] Составление плана дня. ЗАГЛУШКА — реализовать."""
from __future__ import annotations

from datetime import date, datetime

from bot.models import DayPlan, Event, Lesson, PlanItem, Task, User, UserSettings


def build_plan_items(d: date, settings: UserSettings, lessons: list[Lesson], events: list[Event],
                     tasks: list[Task], now: datetime) -> list[PlanItem]:
    """ЧИСТАЯ функция (без БД): план дня d. Пары и события — фиксированные блоки,
    задачи раскладываются в свободные окна по приоритету. Отсортировано по start."""
    raise NotImplementedError


async def build_plan(db, user: User, d: date, *, save: bool = True) -> DayPlan:
    """Собирает данные из БД, строит план (status='draft'), по умолчанию сохраняет."""
    raise NotImplementedError
