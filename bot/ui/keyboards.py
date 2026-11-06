"""[Агент «Интерфейс»] Клавиатуры. ЗАГЛУШКА — реализовать.
Ниже — функции, которые ОБЯЗАН предоставить модуль (их вызывает notifier). Остальные — на усмотрение."""
from __future__ import annotations

from datetime import date

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.models import PlanItem


def main_menu() -> ReplyKeyboardMarkup:
    raise NotImplementedError


def plan_actions(d: date, status: str) -> InlineKeyboardMarkup:
    raise NotImplementedError


def checkin_keyboard() -> InlineKeyboardMarkup:
    raise NotImplementedError


def plan_item_actions(d: date, index: int, item: PlanItem) -> InlineKeyboardMarkup:
    raise NotImplementedError


def event_reminder_actions(event_id: int) -> InlineKeyboardMarkup:
    raise NotImplementedError


def deadline_actions(task_id: int) -> InlineKeyboardMarkup:
    raise NotImplementedError


def rating_keyboard(activity_id: int) -> InlineKeyboardMarkup:
    raise NotImplementedError
