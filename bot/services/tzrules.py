"""Автоматическая смена часового пояса по датам (например: семестр в Шэньчжэне, каникулы в Москве)."""
from __future__ import annotations

from datetime import date, datetime

from bot.models import User, UserSettings
from bot.timeutil import now_utc, tz


def _md(value: str) -> tuple[int, int]:
    m, d = value.strip().split("-")
    return int(m), int(d)


def _in_range(d: date, start: str, end: str) -> bool:
    """Попадает ли дата в диапазон "MM-DD".."MM-DD" (включительно, с переходом через Новый год)."""
    cur, a, b = (d.month, d.day), _md(start), _md(end)
    if a <= b:
        return a <= cur <= b
    return cur >= a or cur <= b


def resolve_rule(settings: UserSettings, at: datetime | None = None) -> dict[str, str] | None:
    """Правило, действующее в момент at (дата считается по домашнему поясу)."""
    at = at or now_utc()
    d = at.astimezone(tz(settings.home_tz)).date()
    for rule in settings.tz_rules or []:
        try:
            if _in_range(d, rule["from"], rule["to"]):
                return rule
        except (KeyError, ValueError):
            continue
    return None


def resolve_tz(settings: UserSettings, at: datetime | None = None) -> str:
    rule = resolve_rule(settings, at)
    return rule["tz"] if rule else settings.home_tz


def location_label(settings: UserSettings, at: datetime | None = None) -> str:
    """Человекочитаемое место: «Шэньчжэнь» / «Москва» (или название пояса)."""
    rule = resolve_rule(settings, at)
    if rule:
        return rule.get("label") or rule["tz"]
    return settings.home_tz.split("/")[-1].replace("_", " ") if settings.home_tz != "Europe/Moscow" else "Москва"


async def sync_user_tz(db, user: User, at: datetime | None = None) -> bool:
    """Если включён tz_auto — выставляет settings.tz по правилам. True, если пояс поменялся.
    user.settings обновляется на месте."""
    s = user.settings
    if not s.tz_auto:
        return False
    target = resolve_tz(s, at)
    if target == s.tz:
        return False
    user.settings = await db.update_settings(user.id, tz=target)
    return True
