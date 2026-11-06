"""«⏱ Трекер»: старт/стоп по категориям, оценка продуктивности, «записать прошедшее», /track, /stop,
ответы на чек-ины «Что делаешь?»."""
from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.db import Database
from bot.handlers.common import MenuButton, ack, drop_markup, reply, show
from bot.models import ACTIVITY_CATEGORIES, Activity, User
from bot.timeutil import day_bounds_utc, human_duration, local_today, now_utc
from bot.ui import keyboards as kb
from bot.ui import texts
from bot.ui.callbacks import CheckinCb, NavCb, PastCb, RateCb, TrackCb
from bot.ui.parsing import match_category

MAX_PAST_MIN = 24 * 60


# ---------------------------------------------------------------- разбор категории

def detect_category(text: str | None) -> tuple[str, str | None]:
    """/track <категория или текст> -> (ключ, описание).

    Понимает ключ («study»), название («Учёба»), эмодзи («📚»), синонимы («домашка»).
    Если категория не найдена — "other" с описанием = весь текст.
    """
    s = (text or "").strip()
    if not s:
        return "other", None
    for key, (emoji, name) in ACTIVITY_CATEGORIES.items():
        for variant in (emoji, emoji.replace("️", "")):
            if variant and s.startswith(variant):
                rest = s[len(variant):].lstrip("️").strip()
                if rest.lower().startswith(name.lower()):
                    rest = rest[len(name):].strip()
                return key, rest or None
    key, desc = match_category(s)
    if key != "other" and desc is not None and desc != s:
        # первое слово — синоним («домашка по физике»), а не сама категория: описание — весь текст
        first = s.split()[0].lower().strip(".,!?:")
        _emoji, name = ACTIVITY_CATEGORIES[key]
        if first not in (key, name.lower(), name.lower().replace("ё", "е")):
            desc = s
    return key, desc


# ---------------------------------------------------------------- рендер

def _minutes_today(acts: list[Activity], start: datetime, end: datetime, now: datetime) -> dict[str, int]:
    by_cat: dict[str, float] = {}
    for a in acts:
        s = max(a.started_at, start)
        e = min(a.ended_at or now, end, now)
        mins = (e - s).total_seconds() / 60
        if mins > 0:
            by_cat[a.category] = by_cat.get(a.category, 0.0) + mins
    return {k: int(round(v)) for k, v in by_cat.items() if round(v) > 0}


async def render_tracker(db: Database, user: User, note: str = "") -> tuple[str, InlineKeyboardMarkup]:
    tz_name = user.settings.tz
    now = now_utc()
    current = await db.current_activity(user.id)
    start, end = day_bounds_utc(local_today(tz_name), tz_name)
    by_cat = _minutes_today(await db.list_activities(user.id, start, end), start, end, now)
    text = texts.tracker_screen(current, sum(by_cat.values()), tz_name, by_cat, now=now)
    return note + text, kb.tracker_keyboard(running=current is not None)


async def _show_tracker(target: Message | CallbackQuery, db: Database, user: User, note: str = "") -> None:
    text, markup = await render_tracker(db, user, note)
    await show(target, text, markup)


async def _stop(target: Message | CallbackQuery, db: Database, user: User) -> None:
    act = await db.stop_activity(user.id)
    if act is None:
        await _show_tracker(target, db, user, "⏸ <i>Таймер и так не запущен.</i>\n\n")
        return
    await show(target, texts.tracker_stopped(act, user.settings.tz), kb.rating_keyboard(act.id))


async def _own_activity(db: Database, user: User, activity_id: int) -> Activity | None:
    act = await db.get_activity(activity_id)
    return act if act and act.user_id == user.id else None


# ---------------------------------------------------------------- меню и команды

async def menu_tracker(message: Message, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    await _show_tracker(message, db, user)


async def cmd_track(message: Message, command: CommandObject, db: Database, user: User,
                    state: FSMContext) -> None:
    await state.clear()
    args = (command.args or "").strip()
    if not args:
        await _show_tracker(message, db, user)
        return
    cat, desc = detect_category(args)
    await db.start_activity(user.id, cat, description=desc, source="timer")
    label = texts.activity_label(cat)
    await _show_tracker(message, db, user, f"▶️ Запустил: <b>{label}</b>\n\n")


async def cmd_stop(message: Message, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    await _stop(message, db, user)


async def nav_tracker(cq: CallbackQuery, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    await ack(cq)
    await _show_tracker(cq, db, user)


# ---------------------------------------------------------------- колбэки

async def cb_track(cq: CallbackQuery, callback_data: TrackCb, db: Database, user: User, state: FSMContext) -> None:
    a = callback_data.a
    if a == "menu":
        await ack(cq)
        await _show_tracker(cq, db, user)
    elif a == "start":
        cat = callback_data.cat if callback_data.cat in ACTIVITY_CATEGORIES else "other"
        prev = await db.current_activity(user.id)
        await db.start_activity(user.id, cat, source="timer")
        label = texts.activity_label(cat)
        note = ""
        if prev is not None:
            mins = max(0, int((now_utc() - prev.started_at).total_seconds() // 60))
            note = f"⏹ {texts.activity_label(prev.category)} — {human_duration(mins)}\n"
        await ack(cq, f"▶️ {label}")
        await _show_tracker(cq, db, user, note + f"▶️ Запустил: <b>{label}</b>\n\n")
    elif a == "stop":
        await ack(cq)
        await _stop(cq, db, user)
    elif a == "past":
        await ack(cq)
        await show(cq, texts.past_intro(), kb.past_category_keyboard())
    else:
        await ack(cq)


async def cb_rate(cq: CallbackQuery, callback_data: RateCb, db: Database, user: User) -> None:
    act = await _own_activity(db, user, callback_data.aid)
    if act is None:
        await ack(cq, "Запись не найдена", alert=True)
        await drop_markup(cq)
        return
    r = callback_data.r
    if 1 <= r <= 5:
        await db.rate_activity(act.id, r)
        await ack(cq, f"{texts.RATING_EMOJI.get(r, '')} Оценка {r}/5")
    else:
        r = 0
        await ack(cq, "Ок, без оценки")
    await show(cq, texts.tracker_rated(act, user.settings.tz, r or None), kb.after_stop_keyboard())


async def cb_past(cq: CallbackQuery, callback_data: PastCb, db: Database, user: User) -> None:
    cat, ago, dur = callback_data.cat, callback_data.ago, callback_data.dur
    if cat not in ACTIVITY_CATEGORIES:
        await ack(cq)
        await show(cq, texts.past_intro(), kb.past_category_keyboard())
        return
    if ago <= 0:
        await ack(cq)
        await show(cq, texts.past_prompt(cat, "ago"), kb.past_ago_keyboard(cat))
        return
    ago = min(ago, MAX_PAST_MIN)
    if dur == -1:
        await ack(cq)
        await show(cq, texts.past_prompt(cat, "dur", ago), kb.past_dur_keyboard(cat, ago))
        return
    now = now_utc()
    started = now - timedelta(minutes=ago)
    ended = now if dur == -2 or dur <= 0 or dur >= ago else started + timedelta(minutes=dur)
    act = await db.add_activity(user.id, cat, started, ended, source="manual")
    await ack(cq, "✅ Записал")
    await show(cq, texts.tracker_stopped(act, user.settings.tz), kb.rating_keyboard(act.id))


async def cb_checkin(cq: CallbackQuery, callback_data: CheckinCb, db: Database, user: User) -> None:
    cat = callback_data.cat
    current = await db.current_activity(user.id)
    if cat == "same" or (current is not None and current.category == cat):
        if current is not None:
            label = texts.activity_label(current.category)
            await ack(cq, f"👍 Продолжаю: {label}")
            await drop_markup(cq, f"🔁 <i>Продолжаешь: {label}</i>")
        else:
            await ack(cq, "👌 Отметил")
            await drop_markup(cq, "👌 <i>Отметил. Таймер не запущен — включу, когда выберешь занятие.</i>")
        return
    if cat not in ACTIVITY_CATEGORIES:
        await ack(cq)
        return
    await db.start_activity(user.id, cat, source="checkin")
    label = texts.activity_label(cat)
    await ack(cq, f"▶️ {label}")
    msg = cq.message
    if isinstance(msg, Message) and msg.text is not None:
        await show(cq, f"{msg.html_text}\n\n▶️ <i>Записываю: {label}</i>", kb.checkin_done_keyboard())
    else:
        await drop_markup(cq, f"▶️ <i>Записываю: {label}</i>")


def router() -> Router:
    r = Router(name="tracker")
    r.message.register(menu_tracker, MenuButton(kb.BTN_TRACK))
    r.message.register(cmd_track, Command("track"))
    r.message.register(cmd_stop, Command("stop"))
    r.callback_query.register(nav_tracker, NavCb.filter(F.to == "track"))
    r.callback_query.register(cb_track, TrackCb.filter())
    r.callback_query.register(cb_rate, RateCb.filter())
    r.callback_query.register(cb_past, PastCb.filter())
    r.callback_query.register(cb_checkin, CheckinCb.filter())
    return r
