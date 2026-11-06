"""[Агент «ИИ»] Claude-ассистент. ЗАГЛУШКА — реализовать."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bot.models import Activity, DayPlan, DayStats, Event, Lesson, Task, User


@dataclass
class AIReply:
    text: str                                         # Telegram-HTML-safe
    actions: list[str] = field(default_factory=list)  # что сделано: ["➕ Задача «Курсач» добавлена"]
    changed: bool = False                             # менял ли данные (задачи/события/трекер/...)


class AIAssistant:
    def __init__(self, db, api_key: str | None, model: str = "claude-opus-5-5") -> None:
        self.db, self.api_key, self.model = db, api_key, model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def chat(self, user: User, text: str) -> AIReply:
        raise NotImplementedError

    async def improve_plan(self, user: User, plan: DayPlan, *, lessons: list[Lesson],
                           events: list[Event], tasks: list[Task]) -> DayPlan:
        raise NotImplementedError

    async def day_insight(self, user: User, stats: DayStats, plan: DayPlan | None,
                          activities: list[Activity]) -> str | None:
        raise NotImplementedError

    async def parse_timetable(self, *, text: str | None = None, image: bytes | None = None,
                              mime: str = "image/jpeg") -> list[dict[str, Any]]:
        raise NotImplementedError

    async def suggest_task_fields(self, user: User, title: str) -> dict[str, Any]:
        raise NotImplementedError
