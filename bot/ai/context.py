"""Краткий снимок состояния пользователя для user-части запроса к Claude.

Сюда идёт всё изменчивое (текущее время, чётность недели, пары, задачи, трекер), чтобы system+tools
оставались байт-в-байт стабильными и кешировались.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from bot.ai.tools import PARITY_LABELS, safe_prioritize
from bot.models import ACTIVITY_CATEGORIES, WEEKDAYS_FULL, WEEKDAYS_SHORT, Lesson, User
from bot.services.timetable import lessons_for_date, week_number, week_parity
from bot.services.tzrules import location_label
from bot.timeutil import human_duration, local_now, now_utc, to_local

log = logging.getLogger(__name__)

FOCUS_PEAK_LABELS = {"morning": "утро", "afternoon": "день", "evening": "вечер"}


def _lessons_line(lessons: list[Lesson]) -> str:
    if not lessons:
        return "нет"
    parts = []
    for l in lessons:
        extra = ", ".join(x for x in (l.kind, f"ауд. {l.room}" if l.room else "") if x)
        parts.append(f"{l.start_time}–{l.end_time} {l.subject}" + (f" ({extra})" if extra else ""))
    return "; ".join(parts)


def week_line(d: date, user: User) -> str:
    parity = week_parity(d, user.settings)
    n = week_number(d, user.settings)
    num = f"{n}-я учебная неделя, " if n else ""
    return f"{num}{PARITY_LABELS[parity]} ({'нечётная' if parity == 'odd' else 'чётная'}, {parity})"


def place_line(user: User) -> str:
    """«Шэньчжэнь, пояс Asia/Shanghai (UTC+08:00)»."""
    tzn = user.settings.tz
    try:
        city = location_label(user.settings)
    except Exception:  # noqa: BLE001
        city = ""
    offset = local_now(tzn).strftime("%z")
    utc = f"UTC{offset[:3]}:{offset[3:]}" if offset else ""
    return f"{city + ', ' if city else ''}пояс {tzn}" + (f" ({utc})" if utc else "")


def now_line(user: User, now_local: datetime | None = None) -> str:
    now_local = now_local or local_now(user.settings.tz)
    d = now_local.date()
    return (f"Сейчас: {WEEKDAYS_FULL[d.weekday()].lower()}, {d.isoformat()} {now_local:%H:%M} "
            f"(место: {place_line(user)}). Неделя: {week_line(d, user)}.")


def next_days_line(today: date, n: int = 8) -> str:
    days = [today + timedelta(days=i) for i in range(1, n + 1)]
    return "Ближайшие дни: " + ", ".join(f"{WEEKDAYS_SHORT[d.weekday()]} {d.isoformat()}" for d in days)


async def build_context(db, user: User) -> str:
    """Текст блока <context> (не падает: каждая часть в своём try)."""
    s = user.settings
    tzn = s.tz
    now_local = local_now(tzn)
    today = now_local.date()
    tomorrow = today + timedelta(days=1)
    lines = ["<context>", now_line(user, now_local), next_days_line(today)]

    try:
        lines.append(f"Пары сегодня: {_lessons_line(await lessons_for_date(db, user, today))}")
        lines.append(f"Пары завтра ({WEEKDAYS_SHORT[tomorrow.weekday()]}): "
                     f"{_lessons_line(await lessons_for_date(db, user, tomorrow))}")
    except Exception:  # noqa: BLE001
        log.exception("context: пары")

    try:
        now = now_utc()
        events = await db.list_events(user.id, now - timedelta(hours=1), now + timedelta(days=7))
        if events:
            ev = "; ".join(
                f"[id {e.id}] {WEEKDAYS_SHORT[to_local(e.start_at, tzn).weekday()]} "
                f"{to_local(e.start_at, tzn):%d.%m %H:%M} {e.title}" for e in events[:6])
            lines.append(f"События на 7 дней: {ev}" + (f" (и ещё {len(events) - 6})" if len(events) > 6 else ""))
        else:
            lines.append("События на 7 дней: нет")
    except Exception:  # noqa: BLE001
        log.exception("context: события")

    try:
        tasks = await db.list_tasks(user.id, "todo")
        ranked = safe_prioritize(tasks, now_utc())
        if ranked:
            items = []
            for t, score, _q in ranked[:5]:
                dl = ""
                if t.deadline:
                    ld = to_local(t.deadline, tzn)
                    dl = f", до {WEEKDAYS_SHORT[ld.weekday()]} {ld.isoformat(timespec='minutes')[:16]}"
                sc = f", score {round(score)}" if score is not None else ""
                items.append(f"[id {t.id}] {t.title} (важн. {t.importance}, ~{t.estimate_min} мин, "
                             f"{t.energy}{dl}{sc})")
            lines.append(f"Топ задач (всего активных {len(ranked)}): " + "; ".join(items))
        else:
            lines.append("Активных задач нет")
    except Exception:  # noqa: BLE001
        log.exception("context: задачи")

    try:
        cur = await db.current_activity(user.id)
        if cur:
            emoji, label = ACTIVITY_CATEGORIES.get(cur.category, ("", cur.category))
            mins = int((now_utc() - cur.started_at).total_seconds() // 60)
            desc = f" «{cur.description}»" if cur.description else ""
            lines.append(f"Трекер: сейчас {emoji} {label}{desc} с {to_local(cur.started_at, tzn):%H:%M} "
                         f"({human_duration(mins)})")
        else:
            lines.append("Трекер: не запущен")
    except Exception:  # noqa: BLE001
        log.exception("context: трекер")

    lines.append(f"Настройки: подъём {s.wake_time}, отбой {s.sleep_time}, пик продуктивности — "
                 f"{FOCUS_PEAK_LABELS.get(s.focus_peak, s.focus_peak)}, дорога до вуза {s.commute_min} мин.")
    lines.append("</context>")
    return "\n".join(lines)
