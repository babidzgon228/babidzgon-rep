"""/start, /help, /cancel и быстрая настройка (часовой пояс → подъём → отбой)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import Database
from bot.handlers.common import FreeText, ack, ai_active, reply, show
from bot.handlers.states import SetupInput
from bot.models import User
from bot.ui import keyboards as kb
from bot.ui import texts
from bot.ui.callbacks import StartCb, s2t
from bot.ui.parsing import TIMEZONES, parse_tz

SETUP_DONE_KEY = "setup_done"


async def cmd_start(message: Message, db: Database, user: User, state: FSMContext,
                    ai=None, user_created: bool = False) -> None:
    await state.clear()
    lessons = await db.list_lessons(user.id)
    await reply(message, texts.welcome(user, len(lessons), created=user_created, ai_on=ai_active(ai, user)),
                kb.main_menu())
    if user_created or not await db.get_state(user.id, SETUP_DONE_KEY):
        await reply(message, texts.setup_prompt("tz", user.settings), kb.setup_keyboard("tz", user.settings))


async def cmd_help(message: Message, user: User, state: FSMContext, ai=None) -> None:
    await state.clear()
    await reply(message, texts.help_text(ai_active(ai, user)), kb.main_menu())


async def cmd_cancel(message: Message, state: FSMContext) -> None:
    had_state = await state.get_state() is not None
    await state.clear()
    text = "✖️ Отменил. Чем займёмся?" if had_state else "Нечего отменять 🙂 Меню внизу."
    await reply(message, text, kb.main_menu())


async def _setup_step(event: Message | CallbackQuery, step: str, user: User) -> None:
    await show(event, texts.setup_prompt(step, user.settings), kb.setup_keyboard(step, user.settings))


async def cb_setup(cq: CallbackQuery, callback_data: StartCb, db: Database, user: User,
                   state: FSMContext) -> None:
    step, v = callback_data.step, callback_data.v
    if step == "tz" and v == "auto":
        await ack(cq, "🔄 Пояс будет меняться автоматически")
        await _setup_step(cq, "wake", user)
        return
    if step == "tz" and v in TIMEZONES:
        # ручной выбор пояса выключает автосмену по датам
        user.settings = await db.update_settings(user.id, tz=TIMEZONES[v][1], tz_auto=False)
        await ack(cq, f"🌍 {TIMEZONES[v][0]}")
        await _setup_step(cq, "wake", user)
        return
    if step == "tzother":
        await state.set_state(SetupInput.tz)
        await ack(cq)
        await show(cq, texts.title("🌍", "Свой часовой пояс") + "\n" + texts.SEP + "\n"
                   "Напиши город или пояс: <i>Europe/Berlin</i>, <i>UTC+5</i>, <i>Казань</i>.",
                   kb.kb([kb.btn("◀️ Назад", StartCb(step="restart"))]))
        return
    if step == "restart":
        await state.clear()
        await ack(cq)
        await _setup_step(cq, "tz", user)
        return
    if step == "wake" and v:
        user.settings = await db.update_settings(user.id, wake_time=s2t(v))
        await ack(cq, f"⏰ {s2t(v)}")
        await _setup_step(cq, "sleep", user)
        return
    if step == "sleep" and v:
        user.settings = await db.update_settings(user.id, sleep_time=s2t(v))
        await ack(cq, f"🌙 {s2t(v)}")
    else:
        await ack(cq)
    await db.set_state(user.id, SETUP_DONE_KEY, "1")
    await state.clear()
    await _setup_step(cq, "done", user)


async def setup_tz_input(message: Message, db: Database, user: User, state: FSMContext) -> None:
    tz_name = parse_tz(message.text)
    if not tz_name:
        await reply(message, "🤔 Не понял пояс. Примеры: <i>Europe/Berlin</i>, <i>UTC+5</i>, <i>Москва</i>.",
                    kb.kb([kb.btn("◀️ Назад", StartCb(step="restart"))]))
        return
    user.settings = await db.update_settings(user.id, tz=tz_name, tz_auto=False)
    await state.clear()
    await _setup_step(message, "wake", user)


def router() -> Router:
    r = Router(name="start")
    r.message.register(cmd_start, CommandStart())
    r.message.register(cmd_help, Command("help"))
    r.message.register(cmd_cancel, Command("cancel"))
    r.message.register(cmd_cancel, F.text.lower().in_({"отмена", "отменить", "✖️ отмена"}))
    r.callback_query.register(cb_setup, StartCb.filter())
    r.message.register(setup_tz_input, SetupInput.tz, FreeText())
    return r
