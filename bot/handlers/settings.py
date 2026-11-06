"""«⚙️ Настройки» и /settings: варианты кнопками, свой ввод с валидацией, переключатели,
«утренняя сводка / вечерний отчёт сейчас»."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.db import Database
from bot.handlers.common import FreeText, MenuButton, ack, log, reply, show
from bot.handlers.states import SettingsInput
from bot.models import User, UserSettings
from bot.services import timetable as tt
from bot.services.tzrules import resolve_tz
from bot.timeutil import local_today
from bot.ui import keyboards as kb
from bot.ui import texts
from bot.ui.callbacks import NavCb, SetCb, s2t
from bot.ui.parsing import TIMEZONES, parse_date, parse_minutes, parse_time, parse_tz

TIME_FIELDS = {"wake": "wake_time", "sleep": "sleep_time", "mb": "morning_brief_time", "ep": "evening_plan_time"}
INT_FIELDS = {"cr": ("class_reminder_min", 0, 180), "er": ("event_reminder_min", 0, 7 * 24 * 60),
              "cm": ("commute_min", 0, 240)}
TOGGLES = {"pr": "plan_reminders", "q": "quiet", "ai": "ai_enabled"}
FOCUS_PEAKS = ("morning", "afternoon", "evening")
CUSTOM_FIELDS = {"tz", "wake", "sleep", "mb", "ep", "ci", "cr", "er", "cm", "ss", "se"}
OFF_WORDS = {"0", "нет", "выкл", "выключить", "off", "no", "-"}
FIXED_END_DATES = {"jan31": (1, 31), "jun30": (6, 30), "jul15": (7, 15)}


class SettingError(ValueError):
    """Непринятое значение настройки; текст — подсказка пользователю."""


# ---------------------------------------------------------------- экраны

def render_settings(s: UserSettings) -> tuple[str, InlineKeyboardMarkup]:
    return texts.settings_screen(s, local_today(s.tz)), kb.settings_keyboard(s)


async def _show_main(target: Message | CallbackQuery, user: User, note: str = "") -> None:
    text, markup = render_settings(user.settings)
    await show(target, note + text, markup)


async def _show_options(target: Message | CallbackQuery, field: str, user: User) -> None:
    await show(target, texts.setting_prompt(field, user.settings), kb.setting_options_keyboard(field, user.settings))


# ---------------------------------------------------------------- вычисление значений

def _next_date(today: date, month: int, day: int) -> date:
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)


def _semester_start_for(v: str, s: UserSettings, today: date) -> str | None:
    """Значение semester_start для кнопок «эта неделя — нечётная/чётная», «1 сентября», «1 марта»."""
    monday = today - timedelta(days=today.weekday())
    if v in ("odd", "even"):
        if s.semester_start:
            if tt.week_parity(today, s) == v:
                return s.semester_start
            # сдвигаем начало на неделю раньше: чётность меняется, текущая дата остаётся в семестре
            return (date.fromisoformat(s.semester_start) - timedelta(days=7)).isoformat()
        return (monday if v == "odd" else monday - timedelta(days=7)).isoformat()
    if v == "sep1":
        return date(today.year if today.month >= 8 else today.year - 1, 9, 1).isoformat()
    if v == "mar1":
        return date(today.year if today.month >= 2 else today.year - 1, 3, 1).isoformat()
    if v == "reset":
        return None
    raise SettingError("unknown")


def _check_semester(start: str | None, end: str | None) -> None:
    if start and end and date.fromisoformat(end) < date.fromisoformat(start):
        raise SettingError("🤔 Конец семестра получается раньше начала. Проверь даты.")


def option_changes(field: str, v: str, s: UserSettings, today: date) -> dict[str, Any]:
    """Значение с кнопки -> изменения настроек. SettingError, если значение непонятное."""
    if field == "tz":
        if v not in TIMEZONES:
            raise SettingError("unknown")
        return {"tz": TIMEZONES[v][1], "tz_auto": False}
    if field in TIME_FIELDS:
        hhmm = parse_time(s2t(v)) if v.isdigit() else None
        if not hhmm:
            raise SettingError("unknown")
        return {TIME_FIELDS[field]: hhmm}
    if field == "ci":
        if v == "off":
            return {"checkin_enabled": False}
        if v.isdigit() and 30 <= int(v) <= 720:
            return {"checkin_enabled": True, "checkin_interval_min": int(v)}
        raise SettingError("unknown")
    if field in INT_FIELDS:
        name, lo, hi = INT_FIELDS[field]
        if v.isdigit() and lo <= int(v) <= hi:
            return {name: int(v)}
        raise SettingError("unknown")
    if field == "fp":
        if v in FOCUS_PEAKS:
            return {"focus_peak": v}
        raise SettingError("unknown")
    if field == "ss":
        start = _semester_start_for(v, s, today)
        _check_semester(start, s.semester_end)
        return {"semester_start": start}
    if field == "se":
        if v == "reset":
            return {"semester_end": None}
        if v not in FIXED_END_DATES:
            raise SettingError("unknown")
        end = _next_date(today, *FIXED_END_DATES[v]).isoformat()
        _check_semester(s.semester_start, end)
        return {"semester_end": end}
    raise SettingError("unknown")


def _parse_semester_date(text: str, today: date, *, start: bool) -> date | None:
    d = parse_date(text, today)
    if d is None:
        return None
    # «01.09» без года: parse_date уводит прошедшие даты в следующий год — для начала семестра это не то
    if start and d > today + timedelta(days=200):
        try:
            d = d.replace(year=d.year - 1)
        except ValueError:
            return None
    return d


def input_changes(field: str, text: str, s: UserSettings, today: date) -> dict[str, Any]:
    """Свой ввод -> изменения настроек. SettingError с подсказкой, если не подходит."""
    raw = (text or "").strip()
    low = raw.lower()
    if field == "tz":
        tz_name = parse_tz(raw)
        if not tz_name:
            raise SettingError("🤔 Не понял пояс. Примеры: <i>Europe/Berlin</i>, <i>Asia/Shanghai</i>, "
                               "<i>UTC+5</i>, <i>Москва</i>.")
        return {"tz": tz_name, "tz_auto": False}
    if field in TIME_FIELDS:
        hhmm = parse_time(raw)
        if not hhmm:
            raise SettingError("🤔 Не понял время. Напиши как <i>07:30</i> или <i>7.30</i>.")
        return {TIME_FIELDS[field]: hhmm}
    if field == "ci":
        if low in OFF_WORDS:
            return {"checkin_enabled": False}
        mins = parse_minutes(raw)
        if mins is None or not 30 <= mins <= 720:
            raise SettingError("🤔 Нужен интервал от 30 минут до 12 часов: <i>90</i>, <i>2 ч</i> — или «выкл».")
        return {"checkin_enabled": True, "checkin_interval_min": mins}
    if field in INT_FIELDS:
        name, lo, hi = INT_FIELDS[field]
        mins = 0 if low in OFF_WORDS else parse_minutes(raw)
        if mins is None or not lo <= mins <= hi:
            raise SettingError(f"🤔 Нужно число минут от {lo} до {hi}: <i>15</i>, <i>1 ч</i>.")
        return {name: mins}
    if field in ("ss", "se"):
        if low in OFF_WORDS or low in ("сброс", "сбросить", "reset"):
            return {"semester_start" if field == "ss" else "semester_end": None}
        d = _parse_semester_date(raw, today, start=field == "ss")
        if d is None:
            raise SettingError("🤔 Не понял дату. Напиши как <i>01.09.2026</i> или <i>2026-09-01</i>.")
        if field == "ss":
            _check_semester(d.isoformat(), s.semester_end)
            return {"semester_start": d.isoformat()}
        _check_semester(s.semester_start, d.isoformat())
        return {"semester_end": d.isoformat()}
    raise SettingError("Эту настройку можно поменять только кнопками.")


# ---------------------------------------------------------------- хендлеры

async def menu_settings(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    await _show_main(message, user)


async def nav_settings(cq: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.clear()
    await ack(cq)
    await _show_main(cq, user)


async def _set_tz_auto(db: Database, user: User, on: bool) -> str:
    s = user.settings
    if on and not s.tz_rules:
        return "Правил автосмены пояса нет — выбери пояс вручную"
    if on:
        probe = UserSettings.from_dict({**s.to_dict(), "tz_auto": True})
        user.settings = await db.update_settings(user.id, tz_auto=True, tz=resolve_tz(probe))
        return f"🔄 Автосмена включена: {texts.location(user.settings)}"
    user.settings = await db.update_settings(user.id, tz_auto=False)
    return "Автосмена выключена"


async def cb_settings(cq: CallbackQuery, callback_data: SetCb, db: Database, user: User, state: FSMContext,
                      notifier=None) -> None:
    f, v = callback_data.f, callback_data.v
    s = user.settings

    if f == "main":
        await state.clear()
        await ack(cq)
        await _show_main(cq, user)
        return

    if f == "now":
        if notifier is None:
            await ack(cq, "Уведомления сейчас не запущены — попробуй позже", alert=True)
            return
        await ack(cq, "☀️ Отправляю сводку…" if v == "m" else "🌆 Готовлю отчёт…")
        try:
            if v == "m":
                await notifier.send_morning(user)
            else:
                await notifier.send_evening(user)
        except Exception:  # noqa: BLE001
            log.exception("send_morning/send_evening failed")
            await show(cq, "⚠️ Не получилось отправить. Попробуй чуть позже.", new=True)
        return

    if f == "ta":
        if v == "on":
            msg = await _set_tz_auto(db, user, True)
        else:
            msg = await _set_tz_auto(db, user, not s.tz_auto)
        await ack(cq, msg, alert=msg.startswith("Правил"))
        await _show_main(cq, user)
        return

    if f in TOGGLES:
        name = TOGGLES[f]
        new_value = not bool(getattr(s, name))
        user.settings = await db.update_settings(user.id, **{name: new_value})
        await ack(cq, f"{texts.SETTING_TITLES.get(f, '')}: {'вкл' if new_value else 'выкл'}".strip())
        await _show_main(cq, user)
        return

    if not v:
        await state.clear()
        await ack(cq)
        await _show_options(cq, f, user)
        return

    if v == "custom" and f in CUSTOM_FIELDS:
        await state.set_state(SettingsInput.value)
        await state.update_data(field=f)
        await ack(cq)
        await show(cq, texts.setting_prompt(f, s) + "\n\n✍️ <i>Напиши значение сообщением.</i>",
                   kb.setting_input_keyboard(f))
        return

    try:
        changes = option_changes(f, v, s, local_today(s.tz))
    except SettingError as err:
        hint = str(err)
        await ack(cq, hint if hint != "unknown" else "Кнопка устарела", alert=hint != "unknown")
        return
    user.settings = await db.update_settings(user.id, **changes)
    await state.clear()
    await ack(cq, "✓ Сохранено")
    await _show_main(cq, user)


async def settings_input(message: Message, db: Database, user: User, state: FSMContext) -> None:
    field = (await state.get_data()).get("field")
    if field not in CUSTOM_FIELDS:
        await state.clear()
        await _show_main(message, user)
        return
    s = user.settings
    try:
        changes = input_changes(field, message.text or "", s, local_today(s.tz))
    except SettingError as err:
        await reply(message, str(err), kb.setting_input_keyboard(field))
        return
    user.settings = await db.update_settings(user.id, **changes)
    await state.clear()
    await _show_main(message, user, "✓ <b>Сохранено</b>\n\n")


def router() -> Router:
    r = Router(name="settings")
    r.message.register(menu_settings, MenuButton(kb.BTN_SETTINGS))
    r.message.register(menu_settings, Command("settings"))
    r.callback_query.register(nav_settings, NavCb.filter(F.to == "settings"))
    r.callback_query.register(cb_settings, SetCb.filter())
    r.message.register(settings_input, SettingsInput.value, FreeText())
    return r
