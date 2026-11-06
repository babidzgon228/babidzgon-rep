"""Реестр модулей: какие разделы есть, какие включены у пользователя, из чего собирать меню.

Модуль описывается объектом Module. Встроенный каталог (CATALOG) перечисляет все разделы продукта —
даже те, чей код ещё в разработке (у них router=None): онбординг всё равно даёт их выбрать заранее.
Реализация модуля регистрирует себя через register(Module(...)) с теми же key, дополняя router/hooks.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from aiogram import Router

from bot.models import User

Hook = Callable[..., Awaitable[Any]]


@dataclass
class Module:
    key: str
    emoji: str
    title: dict[str, str]                       # {"ru", "en", "zh"}
    description: dict[str, str] = field(default_factory=dict)
    core: bool = False                          # нельзя выключить
    default_on: bool = True
    menu: bool = True                           # есть кнопка в главном меню
    order: int = 100                            # порядок в меню и онбординге
    router: Callable[[], Router] | None = None
    schema: str = ""                            # CREATE TABLE IF NOT EXISTS … своих таблиц
    digest_lines: Hook | None = None            # async (db, user, d, lang, *, evening: bool) -> list[str]
    today_lines: Hook | None = None             # async (db, user, d, lang) -> list[str]
    notifier_tick: Hook | None = None           # async (notifier, user, now) -> None

    def name(self, lang: str = "ru") -> str:
        return self.title.get(lang) or self.title["ru"]

    def label(self, lang: str = "ru") -> str:
        return f"{self.emoji} {self.name(lang)}"


def _t(ru: str, en: str, zh: str) -> dict[str, str]:
    return {"ru": ru, "en": en, "zh": zh}


CATALOG: list[Module] = [
    Module("today", "🏠", _t("Сегодня", "Today", "今天"), _t("План дня, сейчас и дальше, дайджесты",
           "Day plan, now & next, digests", "今日计划、提醒和日报"), core=True, order=0),
    Module("tasks", "✅", _t("Задачи", "Tasks", "任务"), _t("Задачи, приоритеты, матрица, канбан",
           "Tasks, priorities, matrix, kanban", "任务、优先级、矩阵、看板"), core=True, order=1),
    Module("study", "🎓", _t("Учёба", "Study", "学习"), _t("Расписание, домашки, экзамены, оценки, карточки",
           "Timetable, homework, exams, grades, flashcards", "课表、作业、考试、成绩、闪卡"), order=10),
    Module("habits", "🔥", _t("Привычки", "Habits", "习惯"), _t("Стрики, ритуалы, челленджи, цели, дневник",
           "Streaks, rituals, challenges, goals, journal", "连续打卡、仪式、挑战、目标、日记"), order=11),
    Module("money", "💰", _t("Деньги", "Money", "钱"), _t("Траты в ¥ и ₽, бюджет, подписки, долги",
           "Spending in ¥ and ₽, budget, subscriptions, debts", "人民币/卢布支出、预算、订阅、借款"), order=12),
    Module("focus", "⏱", _t("Фокус", "Focus", "专注"), _t("Трекер времени, помодоро, фокус-румы",
           "Time tracker, pomodoro, focus rooms", "时间记录、番茄钟、专注房间"), order=13),
    Module("health", "💊", _t("Здоровье", "Health", "健康"), _t("Вода, сон, настроение, таблетки, спорт",
           "Water, sleep, mood, pills, workouts", "喝水、睡眠、心情、药物、运动"), order=14),
    Module("progress", "📊", _t("Прогресс", "Progress", "进度"), _t("Статистика, XP, уровни, ачивки, монетки",
           "Stats, XP, levels, achievements, coins", "统计、经验、等级、成就、金币"), order=15),
    Module("friends", "👥", _t("Друзья", "Friends", "朋友"), _t("Лидерборд, фокус-румы, общие списки",
           "Leaderboard, focus rooms, shared lists", "排行榜、专注房间、共享清单"),
           default_on=False, menu=False, order=30),
    Module("cycle", "🌸", _t("Цикл", "Cycle", "周期"), _t("Женский календарь", "Menstrual cycle tracker", "经期记录"),
           default_on=False, menu=False, order=31),
    Module("more", "⚙️", _t("Ещё", "More", "更多"), _t("Настройки, модули, экспорт, интеграции",
           "Settings, modules, export, integrations", "设置、模块、导出、集成"), core=True, order=99),
]

_REGISTRY: dict[str, Module] = {m.key: m for m in CATALOG}


def register(module: Module) -> Module:
    """Регистрирует реализацию модуля (дополняет запись каталога с тем же key)."""
    base = _REGISTRY.get(module.key)
    if base is not None:
        updates = {k: v for k, v in module.__dict__.items()
                   if v not in (None, "", {}) and k not in ("key",)}
        module = replace(base, **updates)
    _REGISTRY[module.key] = module
    return module


def get(key: str) -> Module | None:
    return _REGISTRY.get(key)


def all_modules() -> list[Module]:
    return sorted(_REGISTRY.values(), key=lambda m: m.order)


def enabled(user: User, key: str) -> bool:
    m = _REGISTRY.get(key)
    if m is None:
        return False
    if m.core:
        return True
    prefs = getattr(user.settings, "modules", None) or {}
    return bool(prefs.get(key, m.default_on))


def enabled_modules(user: User) -> list[Module]:
    return [m for m in all_modules() if enabled(user, m.key)]


async def set_enabled(db, user: User, key: str, on: bool) -> None:
    m = _REGISTRY.get(key)
    if m is None or m.core:
        return
    prefs = dict(getattr(user.settings, "modules", None) or {})
    prefs[key] = bool(on)
    user.settings = await db.update_settings(user.id, modules=prefs)


def menu_layout(user: User | None, *, cols: int = 3) -> list[list[Module]]:
    """Модули для главного меню: Сегодня, Задачи, ➕ (слот add), затем включённые хабы, «Ещё» последним."""
    mods = [m for m in all_modules() if m.menu and (user is None and m.default_on or user and enabled(user, m.key))]
    head = [m for m in mods if m.key in ("today", "tasks")]
    tail = [m for m in mods if m.key == "more"]
    middle = [m for m in mods if m.key not in ("today", "tasks", "more")]
    add = Module("add", "➕", _t("", "", ""), core=True)  # кнопка быстрого добавления, только эмодзи
    flat = head + [add] + middle + tail
    return [flat[i:i + cols] for i in range(0, len(flat), cols)]


def schemas() -> list[str]:
    return [m.schema for m in all_modules() if m.schema]
