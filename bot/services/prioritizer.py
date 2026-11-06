"""[Агент «Планировщик»] Оценка эффективности/приоритета задач. ЗАГЛУШКА — реализовать."""
from __future__ import annotations

from datetime import datetime

from bot.models import Task

# Квадранты Эйзенхауэра
QUADRANT_LABELS: dict[str, str] = {
    "do": "🔥 Срочно и важно",
    "plan": "📅 Важно, не срочно",
    "quick": "⚡ Срочно, не важно",
    "later": "💤 Можно потом",
}


def urgency(task: Task, now: datetime) -> float:
    """0..1 — насколько горит дедлайн (1 = просрочено/сегодня, 0 = нет дедлайна/далеко)."""
    raise NotImplementedError


def score_task(task: Task, now: datetime) -> float:
    """0..100 — итоговый приоритет (чем больше, тем раньше делать)."""
    raise NotImplementedError


def quadrant(task: Task, now: datetime) -> str:
    """Ключ из QUADRANT_LABELS."""
    raise NotImplementedError


def prioritize(tasks: list[Task], now: datetime) -> list[Task]:
    """Только задачи status=='todo', отсортированные по score_task по убыванию."""
    raise NotImplementedError


def explain_score(task: Task, now: datetime) -> str:
    """Короткое объяснение по-русски, почему у задачи такой приоритет."""
    raise NotImplementedError
