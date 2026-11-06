"""[Агент «Интерфейс»] Сборка роутеров. ЗАГЛУШКА — реализовать."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import BotCommand

BOT_COMMANDS: list[BotCommand] = []


def setup_routers() -> Router:
    raise NotImplementedError
