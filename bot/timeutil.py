"""Работа со временем и часовыми поясами."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Europe/Moscow")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime is not allowed")
    return dt.astimezone(timezone.utc)


def to_local(dt: datetime, tz_name: str) -> datetime:
    return dt.astimezone(tz(tz_name))


def local_now(tz_name: str) -> datetime:
    return now_utc().astimezone(tz(tz_name))


def local_today(tz_name: str) -> date:
    return local_now(tz_name).date()


def parse_hhmm(value: str) -> time:
    h, m = value.strip().replace(".", ":").split(":")
    return time(int(h), int(m))


def fmt_hhmm(t: time | datetime) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def combine_local(d: date, hhmm: str, tz_name: str) -> datetime:
    """Дата + "HH:MM" в часовом поясе пользователя -> aware datetime."""
    return datetime.combine(d, parse_hhmm(hhmm), tzinfo=tz(tz_name))


def minutes_of(hhmm: str) -> int:
    t = parse_hhmm(hhmm)
    return t.hour * 60 + t.minute


def hhmm_of(minutes: int) -> str:
    minutes = max(0, min(minutes, 24 * 60 - 1))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def day_bounds_utc(d: date, tz_name: str) -> tuple[datetime, datetime]:
    """Начало и конец локального дня в UTC: [start, end)."""
    start = datetime.combine(d, time(0, 0), tzinfo=tz(tz_name))
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso(dt: datetime | None) -> str | None:
    return to_utc(dt).isoformat() if dt else None


def human_duration(minutes: int) -> str:
    """125 -> '2 ч 5 мин'."""
    minutes = int(round(minutes))
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} ч {m} мин"
    if h:
        return f"{h} ч"
    return f"{m} мин"
