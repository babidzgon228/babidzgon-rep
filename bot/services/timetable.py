"""Учебное расписание: чётность недель, пары на дату, импорт из YAML."""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from bot.models import Lesson, User, UserSettings

_DAY_ALIASES = {
    "пн": 0, "понедельник": 0, "mon": 0, "monday": 0,
    "вт": 1, "вторник": 1, "tue": 1, "tuesday": 1,
    "ср": 2, "среда": 2, "wed": 2, "wednesday": 2,
    "чт": 3, "четверг": 3, "thu": 3, "thursday": 3,
    "пт": 4, "пятница": 4, "fri": 4, "friday": 4,
    "сб": 5, "суббота": 5, "sat": 5, "saturday": 5,
    "вс": 6, "воскресенье": 6, "sun": 6, "sunday": 6,
}
_PARITY_ALIASES = {
    "all": "all", "все": "all", "каждая": "all", "": "all", None: "all",
    "odd": "odd", "нечет": "odd", "нечётная": "odd", "нечетная": "odd", "числитель": "odd", "1": "odd",
    "even": "even", "чет": "even", "чётная": "even", "четная": "even", "знаменатель": "even", "2": "even",
}
_TIME_RANGE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})\s*$")


def week_number(d: date, settings: UserSettings) -> int | None:
    """Номер учебной недели (1, 2, ...) от semester_start, либо None если не задано."""
    if not settings.semester_start:
        return None
    start = date.fromisoformat(settings.semester_start)
    start_monday = start - timedelta(days=start.weekday())
    d_monday = d - timedelta(days=d.weekday())
    return (d_monday - start_monday).days // 7 + 1


def week_parity(d: date, settings: UserSettings) -> str:
    """'odd' (числитель, 1-я неделя) / 'even' (знаменатель).

    Если semester_start не задан — по ISO-номеру недели в году.
    """
    n = week_number(d, settings)
    if n is None:
        n = d.isocalendar().week
    return "odd" if n % 2 == 1 else "even"


def in_semester(d: date, settings: UserSettings) -> bool:
    """Идёт ли учёба в дату d (между semester_start и semester_end, если заданы)."""
    if settings.semester_start and d < date.fromisoformat(settings.semester_start):
        return False
    if settings.semester_end and d > date.fromisoformat(settings.semester_end):
        return False
    return True


def lesson_applies(lesson: Lesson, d: date, settings: UserSettings) -> bool:
    if lesson.weekday != d.weekday() or not in_semester(d, settings):
        return False
    return lesson.parity == "all" or lesson.parity == week_parity(d, settings)


async def lessons_for_date(db, user: User, d: date) -> list[Lesson]:
    """Пары пользователя на конкретную дату (с учётом чётности недели)."""
    lessons = await db.list_lessons(user.id, weekday=d.weekday())
    return sorted((l for l in lessons if lesson_applies(l, d, user.settings)),
                  key=lambda l: l.start_time)


# ---------------------------------------------------------------- YAML-импорт

def normalize_lesson_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Приводит словарь пары (из YAML/ИИ) к аргументам Database.add_lesson.

    Принимает: day|weekday ("пн"/0), time ("08:30-10:00") или start/end, subject,
    kind, room, teacher, weeks|parity.
    """
    day = raw.get("weekday", raw.get("day"))
    if isinstance(day, str):
        day = _DAY_ALIASES.get(day.strip().lower().rstrip("."))
    if not isinstance(day, int) or not 0 <= day <= 6:
        raise ValueError(f"не понял день недели: {raw.get('day', raw.get('weekday'))!r}")

    start, end = raw.get("start") or raw.get("start_time"), raw.get("end") or raw.get("end_time")
    if raw.get("time"):
        m = _TIME_RANGE.match(str(raw["time"]))
        if not m:
            raise ValueError(f"не понял время: {raw['time']!r} (нужно 08:30-10:00)")
        h1, m1, h2, m2 = m.groups()
        start, end = f"{int(h1):02d}:{m1}", f"{int(h2):02d}:{m2}"
    if not start or not end:
        raise ValueError("у пары нет времени")
    start = str(start).replace(".", ":").zfill(5)
    end = str(end).replace(".", ":").zfill(5)

    subject = str(raw.get("subject") or raw.get("name") or "").strip()
    if not subject:
        raise ValueError("у пары нет названия")
    parity_raw = raw.get("parity", raw.get("weeks"))
    parity = _PARITY_ALIASES.get(str(parity_raw).strip().lower() if parity_raw is not None else None, "all")
    room = raw.get("room")
    return {
        "weekday": day, "start_time": start, "end_time": end, "subject": subject,
        "kind": str(raw.get("kind") or "").strip(),
        "room": str(room).strip() if room not in (None, "") else None,
        "teacher": (str(raw["teacher"]).strip() or None) if raw.get("teacher") else None,
        "parity": parity,
    }


def load_timetable_file(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Читает YAML. Возвращает (meta, [нормализованные пары])."""
    p = Path(path)
    if not p.exists():
        return {}, []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    meta = {k: v for k, v in data.items() if k != "lessons"}
    lessons = [normalize_lesson_dict(x) for x in (data.get("lessons") or [])]
    return meta, lessons


async def import_lessons(db, user_id: int, lessons: list[dict[str, Any]], replace: bool = False) -> int:
    """Добавляет нормализованные пары в БД. Возвращает количество."""
    if replace:
        await db.clear_lessons(user_id)
    for l in lessons:
        await db.add_lesson(user_id, **l)
    return len(lessons)


async def apply_profile_settings(db, user: User, meta: dict[str, Any]) -> None:
    """Применяет блок `settings:` и даты семестра из YAML-профиля к пользователю."""
    changes: dict[str, Any] = {}
    for key in ("semester_start", "semester_end"):
        if meta.get(key):
            changes[key] = str(meta[key])
    known = UserSettings.__dataclass_fields__
    for key, value in (meta.get("settings") or {}).items():
        if key in known:
            changes[key] = value
    if changes:
        user.settings = await db.update_settings(user.id, **changes)


async def seed_from_file_if_empty(db, user: User, path: str | Path) -> int:
    """При первом запуске заливает профиль и расписание из data/timetable.yaml."""
    if await db.list_lessons(user.id):
        return 0
    meta, lessons = load_timetable_file(path)
    await apply_profile_settings(db, user, meta)
    return await import_lessons(db, user.id, lessons)
