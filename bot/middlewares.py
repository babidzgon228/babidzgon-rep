"""Middleware: доступ только владельцу + загрузка пользователя в data["user"]."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Config
from bot.db import Database
from bot.models import UserSettings
from bot.services.timetable import seed_from_file_if_empty


class UserMiddleware(BaseMiddleware):
    """Для каждого апдейта кладёт в хендлер аргументы:
    user: bot.models.User, user_created: bool.
    db, ai, config прокидываются через dp workflow_data (см. bot/__main__.py).
    """

    def __init__(self, db: Database, config: Config) -> None:
        self.db = db
        self.config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        chat = data.get("event_chat")
        if tg_user is None:
            return await handler(event, data)

        if self.config.allowed_user_ids and tg_user.id not in self.config.allowed_user_ids:
            if isinstance(event, Message):
                await event.answer("🔒 Это личный бот. Доступ закрыт.")
            elif isinstance(event, CallbackQuery):
                await event.answer("🔒 Доступ закрыт", show_alert=True)
            return None

        user, created = await self.db.get_or_create_user(
            tg_user.id, chat.id if chat else tg_user.id, tg_user.first_name or "",
            default_settings=UserSettings(tz=self.config.default_tz),
        )
        if created:
            await seed_from_file_if_empty(self.db, user, self.config.timetable_path)
            user = await self.db.get_user(user.id)
        data["user"] = user
        data["user_created"] = created
        return await handler(event, data)
