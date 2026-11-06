"""Статистика трекера и эффективности.

Минуты по категориям: каждая активность обрезается границами локального дня, текущая
(незавершённая) считается до `now`.

Продуктивное время:
    категория из PRODUCTIVE_CATEGORIES (учёба, работа, спорт, дела) — 100 %,
    но если оценка ≤ 2 — только 50 %;
    любая другая активность (кроме сна) с оценкой ≥ 4 — тоже 100 % продуктивна.

focus_score (0..100) — взвешенное среднее доступных компонент (если компоненты нет —
её вес делится между остальными; нет ничего — 0):
    40  выполнение плана      = выполнено / всего блоков плана (пары, события, задачи)
    30  продуктивное время    = продуктивные минуты / (50 % бодрствования), максимум 1
                                (бодрствование = wake..sleep; для сегодняшнего дня — до now)
    15  средняя оценка        = (оценка − 1) / 4
    15  задачи                = закрытые задачи / 3, максимум 1 (если были задачи в плане или закрытые)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from bot.models import PRODUCTIVE_CATEGORIES, Activity, DayStats, PeriodStats, User, UserSettings
from bot.services import timetable
from bot.timeutil import day_bounds_utc, minutes_of, now_utc, to_local

PLAN_COUNTED_KINDS = frozenset({"task", "lesson", "event"})
FOCUS_WEIGHTS = {"plan": 40, "productive": 30, "rating": 15, "tasks": 15}
PRODUCTIVE_TARGET_SHARE = 0.5      # половина бодрствования продуктивно — это максимум
TASKS_TARGET = 3                   # 3 закрытые задачи за день — максимум по компоненте


def activity_minutes(activity: Activity, start: datetime, end: datetime, now: datetime) -> float:
    """Сколько минут активность заняла внутри [start, end); текущая — до now."""
    a_start = max(activity.started_at, start)
    a_end = min(activity.ended_at or now, end)
    return max(0.0, (a_end - a_start).total_seconds() / 60)


def productive_weight(activity: Activity) -> float:
    """Какая доля времени активности считается продуктивной (0, 0.5 или 1)."""
    if activity.category in PRODUCTIVE_CATEGORIES:
        return 0.5 if activity.rating is not None and activity.rating <= 2 else 1.0
    if activity.category != "sleep" and activity.rating is not None and activity.rating >= 4:
        return 1.0
    return 0.0


def awake_minutes(settings: UserSettings, d: date, now: datetime) -> int:
    """Минуты бодрствования дня d (для сегодняшнего — сколько уже прошло)."""
    try:
        wake, sleep = minutes_of(settings.wake_time), minutes_of(settings.sleep_time)
    except Exception:
        wake, sleep = 7 * 60 + 30, 23 * 60 + 30
    if sleep <= wake:
        sleep += 24 * 60
    total = sleep - wake
    local = to_local(now, settings.tz)
    if local.date() < d:
        return 0
    if local.date() == d:
        return max(0, min(total, local.hour * 60 + local.minute - wake))
    return total


def compute_focus_score(stats: DayStats, awake_min: int) -> int:
    """Итоговая «эффективность дня» 0..100 (формула — в докстринге модуля)."""
    parts: list[tuple[float, float]] = []
    if stats.plan_items_total:
        parts.append((FOCUS_WEIGHTS["plan"], stats.plan_items_done / stats.plan_items_total))
    if stats.tracked_min > 0 and awake_min > 0:
        target = awake_min * PRODUCTIVE_TARGET_SHARE
        parts.append((FOCUS_WEIGHTS["productive"], min(1.0, stats.productive_min / target)))
    if stats.avg_rating is not None:
        parts.append((FOCUS_WEIGHTS["rating"], max(0.0, min(1.0, (stats.avg_rating - 1) / 4))))
    if stats.tasks_done or stats.tasks_planned:
        parts.append((FOCUS_WEIGHTS["tasks"], min(1.0, stats.tasks_done / TASKS_TARGET)))
    total_w = sum(w for w, _ in parts)
    if not total_w:
        return 0
    return int(round(100 * sum(w * v for w, v in parts) / total_w))


async def day_stats(db, user: User, d: date, *, now: datetime | None = None) -> DayStats:
    now = now or now_utc()
    start, end = day_bounds_utc(d, user.settings.tz)

    by_cat: dict[str, float] = defaultdict(float)
    productive = 0.0
    rating_sum = rating_weight = 0.0
    for act in await db.list_activities(user.id, start, end):
        minutes = activity_minutes(act, start, end, now)
        if minutes <= 0:
            continue
        by_cat[act.category] += minutes
        productive += minutes * productive_weight(act)
        if act.rating is not None:
            rating_sum += act.rating * minutes
            rating_weight += minutes
    minutes_by_category = {k: int(round(v)) for k, v in sorted(by_cat.items(), key=lambda x: -x[1])
                           if round(v) > 0}

    stats = DayStats(date=d)
    stats.minutes_by_category = minutes_by_category
    stats.tracked_min = sum(minutes_by_category.values())
    stats.productive_min = min(stats.tracked_min, int(round(productive)))
    stats.avg_rating = round(rating_sum / rating_weight, 2) if rating_weight else None
    stats.tasks_done = len(await db.list_tasks_done_between(user.id, start, end))

    plan = await db.get_plan(user.id, d)
    if plan:
        counted = [i for i in plan.items if i.kind in PLAN_COUNTED_KINDS]
        stats.plan_items_total = len(counted)
        stats.plan_items_done = sum(1 for i in counted if i.done)
        stats.tasks_planned = len({i.ref_id if i.ref_id is not None else f"title:{i.title}"
                                   for i in plan.items if i.kind == "task"})
    stats.lessons_count = len(await timetable.lessons_for_date(db, user, d))
    stats.focus_score = compute_focus_score(stats, awake_minutes(user.settings, d, now))
    return stats


def _has_data(s: DayStats) -> bool:
    return bool(s.tracked_min or s.tasks_done or s.plan_items_total)


async def period_stats(db, user: User, start: date, end: date, *,
                       now: datetime | None = None) -> PeriodStats:
    """Статистика за [start, end] включительно."""
    if end < start:
        start, end = end, start
    now = now or now_utc()
    days: list[DayStats] = []
    d = start
    while d <= end:
        days.append(await day_stats(db, user, d, now=now))
        d += timedelta(days=1)

    result = PeriodStats(start=start, end=end, days=days)
    by_cat: dict[str, int] = defaultdict(int)
    for s in days:
        for k, v in s.minutes_by_category.items():
            by_cat[k] += v
    result.minutes_by_category = dict(sorted(by_cat.items(), key=lambda x: -x[1]))
    result.tracked_min = sum(s.tracked_min for s in days)
    result.productive_min = sum(s.productive_min for s in days)
    result.tasks_done = sum(s.tasks_done for s in days)

    rated = [s for s in days if s.avg_rating is not None]
    if rated:   # среднее дневных оценок
        result.avg_rating = round(sum(s.avg_rating for s in rated) / len(rated), 2)  # type: ignore[misc]
    active = [s for s in days if _has_data(s)]
    if active:
        result.avg_focus_score = int(round(sum(s.focus_score for s in active) / len(active)))
        result.best_day = max(active, key=lambda s: s.focus_score).date   # при равенстве — раньший
    return result
