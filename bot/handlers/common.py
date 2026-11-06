"""Общие хелперы хендлеров: фильтры, показ экранов, безопасные ответы, «страховка» сервисов."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from bot.models import Task, User
from bot.services import prioritizer
from bot.ui.keyboards import is_menu_text, norm_button
from bot.ui.texts import split_message, strip_tags

log = logging.getLogger("bot.handlers")

Markup = InlineKeyboardMarkup | ReplyKeyboardMarkup | None


# ---------------------------------------------------------------- фильтры

class MenuButton(Filter):
    """Совпадение с кнопкой главного меню (без учёта U+FE0F)."""

    def __init__(self, *buttons: str) -> None:
        self.norm = {norm_button(b) for b in buttons}

    async def __call__(self, message: Message) -> bool:
        return norm_button(message.text) in self.norm


class FreeText(Filter):
    """Обычный текст: не команда и не кнопка меню (для ввода внутри мастеров и ИИ)."""

    async def __call__(self, message: Message) -> bool:
        text = message.text
        return bool(text) and not text.startswith("/") and not is_menu_text(text)


# ---------------------------------------------------------------- отправка/редактирование

def _is_parse_error(err: TelegramBadRequest) -> bool:
    msg = str(err).lower()
    return "can't parse entities" in msg or "unsupported start tag" in msg or "can't find end" in msg


async def ack(cq: CallbackQuery, text: str | None = None, *, alert: bool = False) -> None:
    """callback.answer(), который не падает, если на запрос уже ответили/он устарел."""
    try:
        await cq.answer(text, show_alert=alert)
    except TelegramBadRequest:
        pass
    except Exception:  # noqa: BLE001 — уведомление-«часики» не должно ронять хендлер
        log.debug("callback answer failed", exc_info=True)


async def reply(message: Message, text: str, markup: Markup = None, **kwargs: Any) -> Message | None:
    """message.answer с разбиением длинного текста и фолбэком на plain text при ошибке разметки."""
    chunks = split_message(text)
    sent: Message | None = None
    for n, chunk in enumerate(chunks):
        is_last = n == len(chunks) - 1
        try:
            sent = await message.answer(chunk, reply_markup=markup if is_last else None, **kwargs)
        except TelegramBadRequest as err:
            if not _is_parse_error(err):
                raise
            sent = await message.answer(strip_tags(chunk), reply_markup=markup if is_last else None,
                                        parse_mode=None, **kwargs)
    return sent


async def show(event: Message | CallbackQuery, text: str, markup: Markup = None, *, new: bool = False) -> Any:
    """Показывает экран: у колбэка редактирует сообщение (навигация без спама), иначе — новое сообщение.

    «message is not modified» игнорируется; если редактировать нельзя (фото, старое сообщение) —
    отправляется новое.
    """
    if isinstance(event, CallbackQuery):
        msg = event.message
        can_edit = isinstance(msg, Message) and msg.text is not None and not new \
            and not isinstance(markup, ReplyKeyboardMarkup)
        if can_edit and len(text) <= 4096:
            try:
                return await msg.edit_text(text, reply_markup=markup)  # type: ignore[union-attr]
            except TelegramBadRequest as err:
                low = str(err).lower()
                if "not modified" in low:
                    return msg
                if _is_parse_error(err):
                    return await msg.edit_text(strip_tags(text), reply_markup=markup,  # type: ignore[union-attr]
                                               parse_mode=None)
                log.debug("edit failed, sending new message: %s", err)
        if isinstance(msg, Message):
            return await reply(msg, text, markup)
        chat_id = msg.chat.id if msg is not None else event.from_user.id
        return await event.bot.send_message(chat_id, text, reply_markup=markup)  # type: ignore[union-attr]
    return await reply(event, text, markup)


async def drop_markup(cq: CallbackQuery, suffix: str | None = None) -> None:
    """Убирает кнопки у сообщения (например, у отработанного напоминания), опционально дописывает строку."""
    msg = cq.message
    if not isinstance(msg, Message):
        return
    try:
        if suffix and msg.text is not None:
            await msg.edit_text(f"{msg.html_text}\n\n{suffix}", reply_markup=None)
        elif suffix and msg.caption is not None:
            await msg.edit_caption(caption=f"{msg.html_text}\n\n{suffix}", reply_markup=None)
        else:
            await msg.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


def chat_id_of(event: Message | CallbackQuery) -> int:
    if isinstance(event, CallbackQuery):
        if event.message is not None:
            return event.message.chat.id
        return event.from_user.id
    return event.chat.id


async def clear_state(state: FSMContext | None) -> None:
    if state is not None:
        await state.clear()


def ai_active(ai: Any, user: User) -> bool:
    """ИИ доступен (есть ключ) и включён пользователем."""
    return bool(ai is not None and getattr(ai, "enabled", False) and user.settings.ai_enabled)


# ---------------------------------------------------------------- «страховка» сервисов планировщика

def _fallback_score(task: Task, now: datetime) -> float:
    score = task.importance * 25.0
    if task.deadline:
        hours = (task.deadline - now).total_seconds() / 3600
        score += 30 if hours <= 24 else 15 if hours <= 72 else 5
    return min(100.0, score)


def safe_prioritize(tasks: list[Task], now: datetime) -> list[Task]:
    try:
        return prioritizer.prioritize(tasks, now)
    except Exception:  # noqa: BLE001
        log.warning("prioritizer.prioritize failed, using fallback", exc_info=True)
        todo = [t for t in tasks if t.status == "todo"]
        return sorted(todo, key=lambda t: -_fallback_score(t, now))


def safe_score(task: Task, now: datetime) -> float | None:
    try:
        return float(prioritizer.score_task(task, now))
    except Exception:  # noqa: BLE001
        return _fallback_score(task, now)


def safe_quadrant(task: Task, now: datetime) -> str:
    try:
        q = prioritizer.quadrant(task, now)
        if q in prioritizer.QUADRANT_LABELS:
            return q
    except Exception:  # noqa: BLE001
        pass
    urgent = bool(task.deadline and (task.deadline - now).total_seconds() < 48 * 3600)
    important = task.importance >= 2
    return {(True, True): "do", (False, True): "plan", (True, False): "quick"}.get((urgent, important), "later")


def safe_explain(task: Task, now: datetime) -> str:
    try:
        return prioritizer.explain_score(task, now)
    except Exception:  # noqa: BLE001
        return "Приоритет считается из важности, близости дедлайна и объёма работы."
