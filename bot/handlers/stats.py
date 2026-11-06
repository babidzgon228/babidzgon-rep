"""«📊 Статистика» и /stats: день / неделя / месяц, листание назад."""
from __future__ import annotations

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.db import Database
from bot.handlers.common import MenuButton, ack, log, reply, show
from bot.models import User
from bot.services import stats as stats_service
from bot.timeutil import local_today
from bot.ui import keyboards as kb
from bot.ui import texts
from bot.ui.callbacks import NavCb, StatsCb

MAX_OFFSET = 60
MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
              "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
PERIOD_ARGS = {"d": "d", "day": "d", "день": "d", "сегодня": "d",
               "w": "w", "week": "w", "неделя": "w", "неделю": "w",
               "m": "m", "month": "m", "месяц": "m"}


def _month_start(d: date, back: int) -> date:
    y, m = d.year, d.month - back
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _month_end(first: date) -> date:
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _range_label(a: date, b: date) -> str:
    if a.month == b.month:
        return f"{a.day}{texts.DASH}{b.day} {texts.MONTHS_GEN[b.month - 1]}"
    return f"{a.day} {texts.MONTHS_SHORT[a.month - 1]} {texts.DASH} {b.day} {texts.MONTHS_SHORT[b.month - 1]}"


async def render_stats(db: Database, user: User, period: str = "d", offset: int = 0
                       ) -> tuple[str, InlineKeyboardMarkup]:
    period = period if period in ("d", "w", "m") else "d"
    offset = max(0, min(offset, MAX_OFFSET))
    today = local_today(user.settings.tz)
    markup = kb.stats_keyboard(period, offset)
    try:
        if period == "d":
            d = today - timedelta(days=offset)
            rel = texts.fmt_day_rel(d, today)
            heading = f"{rel.capitalize()} · {texts.fmt_date(d)}" if offset <= 1 else texts.fmt_date(d, year=d.year != today.year)
            return texts.stats_day(await stats_service.day_stats(db, user, d), heading), markup
        if period == "w":
            monday = today - timedelta(days=today.weekday() + 7 * offset)
            sunday = monday + timedelta(days=6)
            end = min(sunday, today)
            name = {0: "Эта неделя", 1: "Прошлая неделя"}.get(offset, f"{offset} нед. назад")
            heading = f"{name} · {_range_label(monday, sunday)}"
            return texts.stats_period(await stats_service.period_stats(db, user, monday, end), heading), markup
        first = _month_start(today, offset)
        end = min(_month_end(first), today)
        heading = MONTHS_NOM[first.month - 1] + (f" {first.year}" if first.year != today.year else "")
        if offset == 0:
            heading = f"Этот месяц · {heading}"
        return texts.stats_period(await stats_service.period_stats(db, user, first, end), heading), markup
    except Exception:  # noqa: BLE001
        log.exception("stats failed")
        return "⚠️ <b>Не получилось посчитать статистику.</b>\n<i>Попробуй чуть позже.</i>", markup


async def menu_stats(message: Message, db: Database, user: User, state: FSMContext,
                     command: CommandObject | None = None) -> None:
    await state.clear()
    arg = ((command.args or "") if command is not None else "").strip().lower()
    text, markup = await render_stats(db, user, PERIOD_ARGS.get(arg, "d"))
    await reply(message, text, markup)


async def nav_stats(cq: CallbackQuery, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    await ack(cq)
    text, markup = await render_stats(db, user)
    await show(cq, text, markup)


async def cb_stats(cq: CallbackQuery, callback_data: StatsCb, db: Database, user: User) -> None:
    await ack(cq)
    text, markup = await render_stats(db, user, callback_data.p, callback_data.o)
    await show(cq, text, markup)


def router() -> Router:
    r = Router(name="stats")
    r.message.register(menu_stats, MenuButton(kb.BTN_STATS))
    r.message.register(menu_stats, Command("stats"))
    r.callback_query.register(nav_stats, NavCb.filter(F.to == "stats"))
    r.callback_query.register(cb_stats, StatsCb.filter())
    return r
