"""[Агент «Интерфейс»] Тексты и форматирование (Telegram HTML). ЗАГЛУШКА — реализовать.
Ниже — функции, которые ОБЯЗАН предоставить модуль (их вызывает notifier). Остальные — на усмотрение."""
from __future__ import annotations

from datetime import date, datetime

from bot.models import Activity, DayPlan, DayStats, Event, Lesson, PlanItem, Task, User


def day_plan(plan: DayPlan, *, header: str | None = None, now_local: datetime | None = None) -> str:
    raise NotImplementedError


def morning_brief(user: User, d: date, lessons: list[Lesson], events: list[Event],
                  top_tasks: list[Task], plan: DayPlan | None) -> str:
    raise NotImplementedError


def lesson_reminder(lesson: Lesson, minutes_left: int) -> str:
    raise NotImplementedError


def event_reminder(event: Event, minutes_left: int, tz_name: str) -> str:
    raise NotImplementedError


def plan_item_reminder(item: PlanItem) -> str:
    raise NotImplementedError


def deadline_reminder(task: Task, tz_name: str, hours_left: float) -> str:
    raise NotImplementedError


def checkin_prompt(current: Activity | None, tz_name: str) -> str:
    raise NotImplementedError


def day_report(stats: DayStats, ai_comment: str | None = None) -> str:
    raise NotImplementedError
