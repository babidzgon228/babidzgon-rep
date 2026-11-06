"""Запуск: python -m bot"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.ai.assistant import AIAssistant
from bot.config import load_config
from bot.db import Database
from bot.handlers import BOT_COMMANDS, setup_routers
from bot.middlewares import UserMiddleware
from bot.services.notifier import Notifier


def build_dispatcher(db: Database, ai: AIAssistant, config, notifier: Notifier | None) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    # Эти объекты попадают в хендлеры как именованные аргументы: db, ai, config, notifier
    dp["db"] = db
    dp["ai"] = ai
    dp["config"] = config
    dp["notifier"] = notifier
    mw = UserMiddleware(db, config)
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    dp.include_router(setup_routers())
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()

    db = Database(config.db_path)
    await db.connect()
    ai = AIAssistant(db, config.anthropic_api_key, config.anthropic_model)

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    notifier = Notifier(bot, db, ai)
    dp = build_dispatcher(db, ai, config, notifier)

    await bot.set_my_commands(BOT_COMMANDS)
    notifier_task = asyncio.create_task(notifier.run(), name="notifier")
    logging.info("Бот запущен. ИИ: %s", "включён" if ai.enabled else "выключен (нет ANTHROPIC_API_KEY)")
    try:
        await dp.start_polling(bot)
    finally:
        notifier.stop()
        notifier_task.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
