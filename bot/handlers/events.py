"""«📌 События»: список ближайших, карточка, удаление, мастер добавления (/event) и кнопки напоминаний."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.db import Database
from bot.handlers.common import FreeText, ack, chat_id_of, drop_markup, log, reply, show
from bot.handlers.states import EventWizard
from bot.models import EVENT_KINDS, Event, User
from bot.timeutil import combine_local, fmt_hhmm, local_now, local_today, now_utc
from bot.ui import keyboards as kb
from bot.ui import texts
from bot.ui.callbacks import EventCb, EventWizCb, NavCb, s2t
from bot.ui.parsing import parse_date, parse_datetime, parse_time, parse_time_range

UPCOMING_LIMIT = 10
SNOOZE_MIN = 10
SNOOZE_UNIT_SEC = 60          # секунд в «минуте» отложенного напоминания (в тестах подменяется)

TITLE_PROMPT = ("✍️ Как назовём событие?\n"
                "<i>Например: «Встреча с научруком», «Экзамен по матану», «ДР Маши».</i>")
DATE_PROMPT = "📅 Когда? Выбери кнопкой или напиши дату: <i>12.11</i>, <i>12.11.2026</i>, <i>пт</i>"
TIME_PROMPT = ("🕐 Во сколько? Выбери или напиши: <i>18:30</i>, <i>18.30</i>\n"
               "<i>Можно с концом: «18:00-19:30».</i>")
REMIND_PROMPT = "🔔 Когда напомнить?"
KIND_PROMPT = "🏷 Что это за событие?"

_background: set[asyncio.Task] = set()


# ---------------------------------------------------------------- черновик

def _draft(data: dict[str, Any]) -> dict[str, Any] | None:
    draft = data.get("ev")
    return draft if isinstance(draft, dict) else None


def _event_start(draft: dict[str, Any], tz_name: str) -> datetime:
    return combine_local(date.fromisoformat(draft["date"]), draft["time"], tz_name).astimezone(timezone.utc)


def _is_past(d: date, hhmm: str, tz_name: str) -> bool:
    return combine_local(d, hhmm, tz_name) <= local_now(tz_name)


async def start_event_wizard(target: Message | CallbackQuery, state: FSMContext, user: User,
                             title: str | None = None) -> None:
    """Запускает мастер события. С названием — сразу к выбору даты."""
    await state.clear()
    draft: dict[str, Any] = {"title": (title or "").strip()[:200] or None, "date": None, "time": None,
                             "end": None, "remind": None,
                             "remind_default": int(user.settings.event_reminder_min or 30)}
    await state.update_data(ev=draft)
    if draft["title"]:
        await _ask_date(target, state, draft)
        return
    await state.set_state(EventWizard.title)
    await show(target, texts.event_draft(draft, TITLE_PROMPT), kb.wizard_cancel_keyboard(EventWizCb(f="cancel")))


async def _ask_date(target: Message | CallbackQuery, state: FSMContext, draft: dict[str, Any],
                    note: str = "") -> None:
    await state.set_state(EventWizard.date)
    await state.update_data(ev=draft)
    await show(target, note + texts.event_draft(draft, DATE_PROMPT), kb.event_date_keyboard())


async def _ask_time(target: Message | CallbackQuery, state: FSMContext, draft: dict[str, Any],
                    note: str = "") -> None:
    await state.set_state(EventWizard.time)
    await state.update_data(ev=draft)
    await show(target, note + texts.event_draft(draft, TIME_PROMPT), kb.event_time_keyboard())


async def _ask_remind(target: Message | CallbackQuery, state: FSMContext, draft: dict[str, Any]) -> None:
    await state.set_state(EventWizard.choose)
    await state.update_data(ev=draft)
    default = int(draft.get("remind_default") or 30)
    await show(target, texts.event_draft(draft, REMIND_PROMPT), kb.event_remind_keyboard(default))


async def _ask_kind(target: Message | CallbackQuery, state: FSMContext, draft: dict[str, Any]) -> None:
    await state.set_state(EventWizard.choose)
    await state.update_data(ev=draft)
    await show(target, texts.event_draft(draft, KIND_PROMPT), kb.event_kind_keyboard())


async def _save(target: Message | CallbackQuery, state: FSMContext, db: Database, user: User,
                draft: dict[str, Any], kind: str) -> None:
    tz_name = user.settings.tz
    start_at = _event_start(draft, tz_name)
    end_at = None
    if draft.get("end"):
        end_at = combine_local(date.fromisoformat(draft["date"]), draft["end"], tz_name).astimezone(timezone.utc)
    remind = draft.get("remind")
    if remind is None:
        remind = int(draft.get("remind_default") or 30)
    event = await db.add_event(user.id, draft.get("title") or "Событие", start_at, end_at=end_at,
                               remind_before_min=int(remind), kind=kind if kind in EVENT_KINDS else "event")
    await state.clear()
    await show(target, "✅ <b>Событие добавлено</b>\n\n" + texts.event_card(event, tz_name),
               kb.event_saved_keyboard(event.id))


# ---------------------------------------------------------------- список и карточка

async def render_events(db: Database, user: User) -> tuple[str, InlineKeyboardMarkup]:
    events = await db.upcoming_events(user.id, limit=UPCOMING_LIMIT)
    text = texts.event_list(events, user.settings.tz)
    return text, kb.event_list_keyboard([(n, e.id) for n, e in enumerate(events, 1)])


async def _own_event(db: Database, user: User, event_id: int) -> Event | None:
    event = await db.get_event(event_id)
    return event if event and event.user_id == user.id else None


# ---------------------------------------------------------------- команды и навигация

async def cmd_event(message: Message, command: CommandObject, user: User, state: FSMContext) -> None:
    await start_event_wizard(message, state, user, title=(command.args or "").strip() or None)


async def cmd_events(message: Message, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    text, markup = await render_events(db, user)
    await reply(message, text, markup)


async def nav_events(cq: CallbackQuery, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    await ack(cq)
    text, markup = await render_events(db, user)
    await show(cq, text, markup)


# ---------------------------------------------------------------- ввод текста в мастере

async def wizard_title(message: Message, user: User, state: FSMContext) -> None:
    draft = _draft(await state.get_data())
    if draft is None:
        await start_event_wizard(message, state, user, title=message.text)
        return
    draft["title"] = (message.text or "").strip()[:200]
    await _ask_date(message, state, draft)


async def wizard_date(message: Message, user: User, state: FSMContext) -> None:
    draft = _draft(await state.get_data())
    if draft is None:
        await state.clear()
        await reply(message, "Мастер устарел — начни заново: /event")
        return
    tz_name = user.settings.tz
    now_l = local_now(tz_name)
    today = now_l.date()
    text = message.text or ""
    d = parse_date(text, today)
    if d is not None:
        if d < today:
            await reply(message, "⏪ Эта дата уже прошла. Выбери другую.", kb.event_date_keyboard())
            return
        draft["date"] = d.isoformat()
        await _ask_time(message, state, draft)
        return
    # «12.11 18:00», «завтра 10:00» — дата и время сразу
    parsed = parse_datetime(text, today, fmt_hhmm(now_l)) if len(text.split()) >= 2 else None
    if parsed and parse_time(text.split()[-1]):
        d, hhmm = parsed
        if _is_past(d, hhmm, tz_name):
            await reply(message, "⏪ Это время уже прошло. Выбери другую дату.", kb.event_date_keyboard())
            return
        draft["date"], draft["time"] = d.isoformat(), hhmm
        await _ask_remind(message, state, draft)
        return
    await reply(message, "🤔 Не понял дату.\n" + DATE_PROMPT, kb.event_date_keyboard())


async def wizard_time(message: Message, user: User, state: FSMContext) -> None:
    draft = _draft(await state.get_data())
    if draft is None or not draft.get("date"):
        await state.clear()
        await reply(message, "Мастер устарел — начни заново: /event")
        return
    text = message.text or ""
    rng = parse_time_range(text)
    start, end = rng if rng else (parse_time(text), None)
    if not start:
        await reply(message, "🤔 Не понял время.\n" + TIME_PROMPT, kb.event_time_keyboard())
        return
    if _is_past(date.fromisoformat(draft["date"]), start, user.settings.tz):
        await reply(message, "⏪ Это время сегодня уже прошло. Напиши другое или вернись к дате.",
                    kb.event_time_keyboard())
        return
    draft["time"], draft["end"] = start, end
    await _ask_remind(message, state, draft)


# ---------------------------------------------------------------- колбэки мастера

async def cb_wizard(cq: CallbackQuery, callback_data: EventWizCb, db: Database, user: User,
                    state: FSMContext) -> None:
    f, v = callback_data.f, callback_data.v
    if f == "cancel":
        await state.clear()
        await ack(cq, "Отменено")
        await show(cq, "✖️ <i>Событие не добавлено.</i>")
        return
    draft = _draft(await state.get_data())
    if draft is None:
        await ack(cq, "Мастер устарел — начни заново: /event", alert=True)
        return
    tz_name = user.settings.tz
    today = local_today(tz_name)

    if f == "date":
        try:
            d = today + timedelta(days=int(v))
        except ValueError:
            await ack(cq)
            return
        draft["date"] = d.isoformat()
        await ack(cq)
        await _ask_time(cq, state, draft)
        return
    if f == "time":
        if not draft.get("date"):
            await ack(cq)
            await _ask_date(cq, state, draft)
            return
        hhmm = parse_time(s2t(v)) if v else None
        if not hhmm:
            await ack(cq)
            return
        if _is_past(date.fromisoformat(draft["date"]), hhmm, tz_name):
            await ack(cq, "⏪ Это время сегодня уже прошло — выбери другое", alert=True)
            return
        draft["time"], draft["end"] = hhmm, None
        await ack(cq)
        await _ask_remind(cq, state, draft)
        return
    if f == "back":
        await ack(cq)
        if v == "time" and draft.get("date"):
            await _ask_time(cq, state, draft)
        else:
            await _ask_date(cq, state, draft)
        return
    if f == "rem":
        if not (draft.get("date") and draft.get("time")):
            await ack(cq)
            await _ask_date(cq, state, draft)
            return
        try:
            draft["remind"] = max(0, int(v))
        except ValueError:
            await ack(cq)
            return
        await ack(cq)
        await _ask_kind(cq, state, draft)
        return
    if f == "kind":
        if not (draft.get("date") and draft.get("time")):
            await ack(cq)
            await _ask_date(cq, state, draft)
            return
        await ack(cq, "💾 Сохранено")
        await _save(cq, state, db, user, draft, v)
        return
    await ack(cq)


# ---------------------------------------------------------------- колбэки событий и напоминаний

async def _remind_again(bot: Bot, db: Database, user_id: int, chat_id: int, event_id: int, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        event = await db.get_event(event_id)
        user = await db.get_user(user_id)
        if not event or not user:
            return
        left = round((event.start_at - now_utc()).total_seconds() / 60)
        if left < -15:
            return
        await bot.send_message(chat_id, texts.event_reminder(event, max(0, left), user.settings.tz),
                               reply_markup=kb.event_reminder_actions(event.id))
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — фоновая задача не должна ронять бота
        log.warning("snoozed event reminder failed", exc_info=True)


async def cb_event(cq: CallbackQuery, callback_data: EventCb, db: Database, user: User, state: FSMContext,
                   bot: Bot) -> None:
    a = callback_data.a
    if a == "list":
        await nav_events(cq, db, user, state)
        return
    if a == "add":
        await ack(cq)
        await start_event_wizard(cq, state, user)
        return

    event = await _own_event(db, user, callback_data.id)
    if a in ("snooze", "ok"):
        if a == "ok" or event is None:
            await ack(cq, "👌")
            await drop_markup(cq, "👌 <i>Принято</i>" if event else None)
            return
        left = (event.start_at - now_utc()).total_seconds() / 60
        if left <= 1:
            await ack(cq, "Событие уже начинается!")
            await drop_markup(cq, "▶️ <i>Уже начинается</i>")
            return
        delay_min = SNOOZE_MIN if left > SNOOZE_MIN else max(1, int(left))
        task = asyncio.create_task(_remind_again(bot, db, user.id, chat_id_of(cq), event.id,
                                                 delay_min * SNOOZE_UNIT_SEC))
        _background.add(task)
        task.add_done_callback(_background.discard)
        await ack(cq, f"⏰ Напомню через {delay_min} мин")
        await drop_markup(cq, f"⏰ <i>Напомню ещё раз через {delay_min} мин</i>")
        return

    if event is None:
        await ack(cq, "Событие не найдено — возможно, уже удалено", alert=True)
        text, markup = await render_events(db, user)
        await show(cq, text, markup)
        return
    tz_name = user.settings.tz
    if a == "view":
        await ack(cq)
        await show(cq, texts.event_card(event, tz_name), kb.event_card_keyboard(event.id))
    elif a == "del":
        await ack(cq)
        await show(cq, texts.event_card(event, tz_name) + "\n\n🗑 <b>Удалить событие?</b>",
                   kb.event_delete_confirm(event.id))
    elif a == "delok":
        await db.delete_event(event.id)
        await ack(cq, "🗑 Удалено")
        text, markup = await render_events(db, user)
        await show(cq, text, markup)
    else:
        await ack(cq)


def router() -> Router:
    r = Router(name="events")
    r.message.register(cmd_event, Command("event"))
    r.message.register(cmd_events, Command("events"))
    r.callback_query.register(nav_events, NavCb.filter(F.to == "events"))
    r.callback_query.register(cb_event, EventCb.filter())
    r.callback_query.register(cb_wizard, EventWizCb.filter())
    r.message.register(wizard_title, EventWizard.title, FreeText())
    r.message.register(wizard_date, EventWizard.date, FreeText())
    r.message.register(wizard_time, EventWizard.time, FreeText())
    return r
