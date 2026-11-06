"""Оценка эффективности/приоритета задач («что делать в первую очередь»).

Формула приоритета score (0..100) — сумма понятных слагаемых:

    важность          1 → 10, 2 → 25, 3 → 40 баллов
    срочность         до 45 баллов = 45 × urgency(task)            (см. ниже)
    просрочено        +5
    быстрая победа    оценка ≤ 15 мин → +8, ≤ 30 мин → +5, ≤ 60 мин → +2
    залежалость       +1 за каждые 2 дня с момента создания, максимум +5
    привязка к дню    planned_date сегодня (или раньше) → +10, завтра → +4
    итог обрезается до 0..100

urgency (0..1) = max(срочность по времени, срочность по объёму):
    по времени   = 24 / (24 + часов_до_дедлайна)   сутки → 0.5, двое → 0.33, неделя → 0.13
    по объёму    = нужно / доступно, где «доступно» = 40 % оставшегося времени
                   (≈ 9–10 ч в сутки реально можно потратить на дела);
                   если задача не влезает (нужно ≥ доступно) → 1
    просрочено → 1, нет дедлайна → 0

Квадрант Эйзенхауэра:
    важная  = важность 3, или важность 2 и score ≥ 55
    срочная = дедлайн ≤ 48 ч (в т.ч. просрочено) или задача не влезает в оставшееся время

Про `now`: дедлайны сравниваются как aware datetime (пояс не важен), а planned_date —
с `now.date()`, поэтому для точности передавай локальное время пользователя
(`bot.timeutil.local_now(tz)`); UTC тоже работает, но около полуночи может ошибиться на день.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from bot.models import IMPORTANCE_LABELS, Task
from bot.timeutil import human_duration

# Квадранты Эйзенхауэра
QUADRANT_LABELS: dict[str, str] = {
    "do": "🔥 Срочно и важно",
    "plan": "📅 Важно, не срочно",
    "quick": "⚡ Срочно, не важно",
    "later": "💤 Можно потом",
}

# ---------------------------------------------------------------- параметры формулы
IMPORTANCE_POINTS = {1: 10.0, 2: 25.0, 3: 40.0}
URGENCY_POINTS = 45.0
OVERDUE_BONUS = 5.0
QUICK_WIN_BONUS = ((15, 8.0), (30, 5.0), (60, 2.0))   # (оценка ≤ мин, баллы)
STALE_DAYS_PER_POINT = 2
STALE_MAX = 5.0
PLANNED_TODAY_BONUS = 10.0
PLANNED_TOMORROW_BONUS = 4.0

WORK_SHARE = 0.4            # доля оставшегося до дедлайна времени, которую реально можно работать
URGENT_HOURS = 48           # дедлайн ближе — задача «срочная»
IMPORTANT_SCORE = 55        # порог score, при котором задача средней важности считается важной
TIGHT_RATIO = 1.5           # доступно / нужно < 1.5 — «впритык»


# ---------------------------------------------------------------- вспомогательное

def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _importance(task: Task) -> int:
    try:
        return max(1, min(3, int(task.importance)))
    except (TypeError, ValueError):
        return 2


def _need_min(task: Task) -> int:
    try:
        return max(5, int(task.estimate_min or 0))
    except (TypeError, ValueError):
        return 30


def minutes_left(task: Task, now: datetime) -> float | None:
    """Минут до дедлайна (отрицательно — просрочено), None — дедлайна нет."""
    if task.deadline is None:
        return None
    return (_aware(task.deadline) - _aware(now)).total_seconds() / 60


def available_minutes(task: Task, now: datetime) -> float | None:
    """Сколько рабочего времени реально есть до дедлайна (None — дедлайна нет)."""
    left = minutes_left(task, now)
    if left is None:
        return None
    return max(0.0, left) * WORK_SHARE


def fits_in_time(task: Task, now: datetime) -> bool:
    """Успевает ли задача в оставшееся рабочее время (без дедлайна — всегда да)."""
    avail = available_minutes(task, now)
    return avail is None or avail > _need_min(task)


def _quick_bonus(task: Task) -> float:
    need = _need_min(task)
    for limit, points in QUICK_WIN_BONUS:
        if need <= limit:
            return points
    return 0.0


def _age_days(task: Task, now: datetime) -> float:
    if not task.created_at:
        return 0.0
    return max(0.0, (_aware(now) - _aware(task.created_at)).total_seconds() / 86400)


def _stale_bonus(task: Task, now: datetime) -> float:
    return min(STALE_MAX, _age_days(task, now) / STALE_DAYS_PER_POINT)


def _planned_bonus(task: Task, now: datetime) -> float:
    if not task.planned_date:
        return 0.0
    today = now.date()
    if task.planned_date <= today:
        return PLANNED_TODAY_BONUS
    if task.planned_date == today + timedelta(days=1):
        return PLANNED_TOMORROW_BONUS
    return 0.0


def _fmt_span(minutes: float) -> str:
    """Человекочитаемый промежуток: «40 мин», «2 ч 30 мин», «20 ч», «3 дн»."""
    minutes = abs(minutes)
    if minutes < 60:
        return f"{max(1, int(round(minutes)))} мин"
    if minutes < 6 * 60:
        return human_duration(int(round(minutes / 10)) * 10)
    hours = minutes / 60
    if hours < 48:
        return f"{int(hours + 0.5)} ч"
    return f"{int(hours / 24 + 0.5)} дн"


# ---------------------------------------------------------------- публичный API

def urgency(task: Task, now: datetime) -> float:
    """0..1 — насколько горит дедлайн (1 = просрочено/не успеваешь, 0 = нет дедлайна)."""
    left = minutes_left(task, now)
    if left is None:
        return 0.0
    if left <= 0:
        return 1.0
    by_time = 24 / (24 + left / 60)
    avail = left * WORK_SHARE
    need = _need_min(task)
    by_load = 1.0 if need >= avail else need / avail
    return round(min(1.0, max(by_time, by_load)), 4)


def score_task(task: Task, now: datetime) -> float:
    """0..100 — итоговый приоритет (чем больше, тем раньше делать)."""
    score = IMPORTANCE_POINTS[_importance(task)]
    score += URGENCY_POINTS * urgency(task, now)
    left = minutes_left(task, now)
    if left is not None and left <= 0:
        score += OVERDUE_BONUS
    score += _quick_bonus(task)
    score += _stale_bonus(task, now)
    score += _planned_bonus(task, now)
    return round(max(0.0, min(100.0, score)), 1)


def is_urgent(task: Task, now: datetime) -> bool:
    left = minutes_left(task, now)
    if left is None:
        return False
    return left <= URGENT_HOURS * 60 or not fits_in_time(task, now)


def is_important(task: Task, now: datetime) -> bool:
    imp = _importance(task)
    return imp >= 3 or (imp == 2 and score_task(task, now) >= IMPORTANT_SCORE)


def quadrant(task: Task, now: datetime) -> str:
    """Ключ из QUADRANT_LABELS."""
    important, urgent = is_important(task, now), is_urgent(task, now)
    if important and urgent:
        return "do"
    if important:
        return "plan"
    if urgent:
        return "quick"
    return "later"


def prioritize(tasks: list[Task], now: datetime) -> list[Task]:
    """Только задачи status=='todo', отсортированные по score_task по убыванию.

    Сортировка стабильная: при равном score сохраняется исходный порядок.
    """
    todo = [t for t in tasks if t.status == "todo"]
    return sorted(todo, key=lambda t: -score_task(t, now))


def explain_score(task: Task, now: datetime) -> str:
    """Короткое объяснение по-русски (1–2 строки), почему у задачи такой приоритет.

    Пример: «Высокая важность · дедлайн через 20 ч · нужно ~4 ч\\n⏳ впритык»
    """
    parts = [f"{IMPORTANCE_LABELS[_importance(task)].capitalize()} важность"]
    left = minutes_left(task, now)
    if left is None:
        parts.append("без дедлайна")
    elif left <= 0:
        parts.append(f"просрочено на {_fmt_span(left)}")
    else:
        parts.append(f"дедлайн через {_fmt_span(left)}")
    parts.append(f"нужно ~{human_duration(_need_min(task))}")

    extras: list[str] = []
    if left is not None and left > 0:
        avail = left * WORK_SHARE
        need = _need_min(task)
        if avail <= need:
            extras.append("⚠️ не успеваешь в обычном темпе")
        elif avail / need < TIGHT_RATIO:
            extras.append("⏳ впритык")
    if _quick_bonus(task) >= 5:
        extras.append("⚡ быстрая победа")
    planned = _planned_bonus(task, now)
    if planned == PLANNED_TODAY_BONUS:
        extras.append("📌 запланирована на сегодня")
    elif planned == PLANNED_TOMORROW_BONUS:
        extras.append("📌 запланирована на завтра")
    age = _age_days(task, now)
    if age >= 7:
        extras.append(f"🕸 висит {int(age)} дн")

    text = " · ".join(parts)
    if extras:
        text += "\n" + " · ".join(extras)
    return text


def planned_for(task: Task, d: date) -> bool:
    """Задача может попасть в план дня d: не привязана к дню, привязана к d или к прошедшему
    дню и всё ещё не сделана (переносится). Привязанные к более поздним дням — нет."""
    return task.planned_date is None or task.planned_date <= d


__all__ = [
    "QUADRANT_LABELS", "urgency", "score_task", "quadrant", "prioritize", "explain_score",
    "minutes_left", "available_minutes", "fits_in_time", "is_urgent", "is_important", "planned_for",
]
