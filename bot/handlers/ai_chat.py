"""/ai и «запасной» обработчик: любой текст без мастера -> ИИ-ассистент (или предложение сделать задачу),
фото без мастера -> предложение распознать расписание. Роутер подключается ПОСЛЕДНИМ."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from bot.db import Database
from bot.handlers.common import ack, ai_active, drop_markup, log, reply, show
from bot.models import User
from bot.ui import keyboards as kb
from bot.ui import texts
from bot.ui.callbacks import AiCb, NavCb

PENDING_TEXT = "pending_text"
PENDING_PHOTO = "pending_photo"
AI_ERROR = ("⚠️ <b>ИИ сейчас не отвечает.</b>\n"
            "<i>Попробуй ещё раз чуть позже — или сделай из сообщения задачу/событие кнопкой ниже.</i>")


def _ai_screen(ai, user: User) -> tuple[str, object]:
    available = bool(ai is not None and getattr(ai, "enabled", False))
    enabled = bool(user.settings.ai_enabled)
    return (texts.ai_help(available=available, enabled=enabled),
            kb.ai_help_keyboard(available=available, enabled=enabled))


async def cmd_ai(message: Message, user: User, state: FSMContext, ai=None) -> None:
    await state.clear()
    text, markup = _ai_screen(ai, user)
    await reply(message, text, markup)  # type: ignore[arg-type]


async def nav_ai(cq: CallbackQuery, user: User, state: FSMContext, ai=None) -> None:
    await state.clear()
    await ack(cq)
    text, markup = _ai_screen(ai, user)
    await show(cq, text, markup)  # type: ignore[arg-type]


def _text_from_offer(cq: CallbackQuery) -> str | None:
    """Запасной путь: текст из «Записать? «…»», если FSM-данные уже очищены."""
    msg = cq.message
    body = getattr(msg, "text", None) or ""
    if "«" in body and "»" in body:
        inner = body[body.index("«") + 1:body.rindex("»")].strip()
        if inner and not inner.endswith("…"):
            return inner
    return None


async def cb_ai(cq: CallbackQuery, callback_data: AiCb, db: Database, user: User, state: FSMContext,
                bot: Bot, ai=None) -> None:
    a = callback_data.a
    if a == "clear":
        await db.clear_ai_history(user.id)
        await ack(cq, "🧹 Контекст очищен — начнём с чистого листа")
        return
    if a in ("on", "off"):
        user.settings = await db.update_settings(user.id, ai_enabled=a == "on")
        await ack(cq, "🤖 ИИ включён" if a == "on" else "⏸ ИИ выключен")
        text, markup = _ai_screen(ai, user)
        await show(cq, text, markup)  # type: ignore[arg-type]
        return
    if a in ("task", "event"):
        data = await state.get_data()
        text = data.get(PENDING_TEXT) or _text_from_offer(cq)
        if not text:
            await ack(cq, "Не нашёл текст — пришли его ещё раз", alert=True)
            return
        await ack(cq)
        if a == "task":
            from bot.handlers.tasks import start_draft
            await state.clear()
            await start_draft(cq, state, user, text, ai=ai, bot=bot)
        else:
            from bot.handlers.events import start_event_wizard
            await start_event_wizard(cq, state, user, title=text)
        return
    if a == "photo":
        data = await state.get_data()
        file_id = data.get(PENDING_PHOTO)
        if not file_id:
            await ack(cq, "Фото потерялось — пришли его ещё раз", alert=True)
            return
        from bot.handlers.timetable import download_file, recognize_timetable
        await ack(cq, "🔎 Распознаю…")
        await drop_markup(cq)
        try:
            image = await download_file(bot, file_id)
        except Exception:  # noqa: BLE001
            log.warning("photo download failed", exc_info=True)
            await show(cq, "⚠️ Не получилось скачать фото. Пришли его ещё раз.", new=True)
            return
        await state.clear()
        await recognize_timetable(cq, state, user, ai, bot, image=image)
        return
    # no / nophoto / неизвестное
    await state.update_data({PENDING_TEXT: None, PENDING_PHOTO: None})
    await ack(cq, "👌")
    await drop_markup(cq)


# ---------------------------------------------------------------- fallback

async def unknown_command(message: Message) -> None:
    await reply(message, "🤔 Не знаю такую команду. Все команды — в /help, главное — в меню внизу.", kb.main_menu())


async def text_in_wizard(message: Message) -> None:
    await reply(message, "👆 Сейчас жду выбор кнопкой выше. /cancel — выйти из мастера.")


async def free_text(message: Message, user: User, state: FSMContext, bot: Bot, ai=None) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    if not ai_active(ai, user):
        await state.update_data({PENDING_TEXT: text[:500]})
        await reply(message, texts.free_text_offer(text), kb.free_text_keyboard())
        return
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            answer = await ai.chat(user, text)
    except Exception:  # noqa: BLE001
        log.exception("ai.chat failed")
        await state.update_data({PENDING_TEXT: text[:500]})
        await reply(message, AI_ERROR, kb.free_text_keyboard())
        return
    body = texts.ai_reply(getattr(answer, "text", "") or "", getattr(answer, "actions", None) or ())
    markup = kb.ai_changed_keyboard() if getattr(answer, "changed", False) else None
    await reply(message, body, markup)


async def photo_offer(message: Message, user: User, state: FSMContext, ai=None) -> None:
    if not message.photo:
        return
    if not ai_active(ai, user):
        await reply(message, "📷 Фото получил, но распознавать расписание я умею только с ИИ "
                             "(он сейчас недоступен). Пары можно добавить в «🎓 Расписание» → «➕ Пара».")
        return
    await state.update_data({PENDING_PHOTO: message.photo[-1].file_id})
    await reply(message, "📷 <b>Это расписание?</b>\nМогу распознать пары и добавить их в бота.",
                kb.photo_offer_keyboard())


async def other_message(message: Message) -> None:
    await reply(message, "Я понимаю текст и фото 🙂 Главное — в меню внизу.", kb.main_menu())


def router() -> Router:
    r = Router(name="ai_chat")
    r.message.register(cmd_ai, Command("ai"))
    r.callback_query.register(nav_ai, NavCb.filter(F.to == "ai"))
    r.callback_query.register(cb_ai, AiCb.filter())
    r.message.register(unknown_command, F.text.startswith("/"))
    r.message.register(free_text, StateFilter(None), F.text)
    r.message.register(text_in_wizard, F.text)
    r.message.register(photo_offer, F.photo)
    r.message.register(other_message)
    return r
