"""[Агент «Планировщик»] Фоновые уведомления. ЗАГЛУШКА — реализовать."""
from __future__ import annotations

from datetime import datetime

from aiogram import Bot

from bot.db import Database
from bot.models import User


class Notifier:
    def __init__(self, bot: Bot, db: Database, ai=None, interval_sec: int = 30) -> None:
        self.bot, self.db, self.ai, self.interval_sec = bot, db, ai, interval_sec

    async def run(self) -> None:
        """Бесконечный цикл: tick() каждые interval_sec, пока не вызван stop()."""
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    async def tick(self, now: datetime | None = None) -> None:
        """Один проход по всем пользователям (now — aware UTC; для тестов)."""
        raise NotImplementedError

    async def send_morning(self, user: User) -> None:
        """Утренняя сводка прямо сейчас."""
        raise NotImplementedError

    async def send_evening(self, user: User) -> None:
        """Вечерний отчёт за сегодня + черновик плана на завтра прямо сейчас."""
        raise NotImplementedError
