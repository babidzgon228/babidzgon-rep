"""Сборка роутеров и список команд бота."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import BotCommand

from bot.handlers import ai_chat, events, plan, settings, start, stats, tasks, timetable, tracker

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="🚀 Запуск и быстрая настройка"),
    BotCommand(command="today", description="📅 План и дела на сегодня"),
    BotCommand(command="tomorrow", description="🗓 План на завтра"),
    BotCommand(command="plan", description="🧩 Составить план на завтра"),
    BotCommand(command="tasks", description="✅ Задачи по приоритету"),
    BotCommand(command="add", description="➕ Новая задача"),
    BotCommand(command="event", description="📌 Новое событие"),
    BotCommand(command="track", description="⏱ Запустить трекер"),
    BotCommand(command="stop", description="⏹ Остановить трекер"),
    BotCommand(command="stats", description="📊 Статистика"),
    BotCommand(command="week", description="🎓 Расписание на неделю"),
    BotCommand(command="settings", description="⚙️ Настройки"),
    BotCommand(command="ai", description="🤖 ИИ-помощник"),
    BotCommand(command="help", description="❓ Помощь"),
    BotCommand(command="cancel", description="✖️ Отменить текущее действие"),
]

# Порядок важен: команды и кнопки меню — раньше, мастера ловят только свои состояния,
# ai_chat — последним (fallback на любой текст/фото).
ROUTER_MODULES = (start, plan, tasks, events, tracker, stats, timetable, settings, ai_chat)


def setup_routers() -> Router:
    root = Router(name="root")
    for module in ROUTER_MODULES:
        root.include_router(module.router())
    return root
