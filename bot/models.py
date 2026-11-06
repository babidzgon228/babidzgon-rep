"""Модели данных бота. Общий контракт для всех модулей.

Правила времени:
- Все datetime в моделях — timezone-aware (обычно UTC, из БД приходят в UTC).
  Для показа пользователю переводим в его часовой пояс через bot.timeutil.to_local().
- Время внутри дня (PlanItem.start/end, Lesson.start_time/end_time) — строки "HH:MM"
  в ЛОКАЛЬНОМ часовом поясе пользователя.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

# ---------------------------------------------------------------- справочники

# Категории активностей для трекера: key -> (emoji, название)
ACTIVITY_CATEGORIES: dict[str, tuple[str, str]] = {
    "study": ("📚", "Учёба"),
    "work": ("💻", "Работа"),
    "sport": ("🏃", "Спорт"),
    "chores": ("🧹", "Дела"),
    "road": ("🚌", "Дорога"),
    "food": ("🍽", "Еда"),
    "social": ("👥", "Общение"),
    "rest": ("🎮", "Отдых"),
    "sleep": ("😴", "Сон"),
    "other": ("✍️", "Другое"),
}
# Категории, которые считаются продуктивными по умолчанию
PRODUCTIVE_CATEGORIES = frozenset({"study", "work", "sport", "chores"})

# Категории задач
TASK_CATEGORIES: dict[str, tuple[str, str]] = {
    "study": ("📚", "Учёба"),
    "work": ("💻", "Работа"),
    "personal": ("🏠", "Личное"),
    "health": ("💪", "Здоровье"),
    "other": ("📌", "Другое"),
}

# Важность задачи: 1..3
IMPORTANCE_LABELS = {1: "низкая", 2: "средняя", 3: "высокая"}
# Энергозатратность задачи (когнитивная нагрузка)
ENERGY_LEVELS = ("low", "medium", "high")
ENERGY_LABELS = {"low": "лёгкая", "medium": "средняя", "high": "сложная"}

TASK_STATUSES = ("todo", "done", "cancelled")
EVENT_KINDS = {"event": "📌 Событие", "meeting": "🤝 Встреча", "exam": "🎓 Экзамен/зачёт",
               "deadline": "⏰ Дедлайн", "birthday": "🎂 День рождения"}
LESSON_PARITY = ("all", "odd", "even")  # все недели / нечётные (числитель) / чётные (знаменатель)

# Типы элементов плана дня
PLAN_ITEM_KINDS = ("lesson", "event", "task", "break", "meal", "buffer", "routine")

WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WEEKDAYS_FULL = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


# ---------------------------------------------------------------- модели

@dataclass
class UserSettings:
    tz: str = "Europe/Moscow"           # ТЕКУЩИЙ часовой пояс (его используют все модули)
    # Автосмена пояса по датам: tz_rules = [{"from": "MM-DD", "to": "MM-DD", "tz": "Asia/Shanghai",
    # "label": "Шэньчжэнь"}], вне правил — home_tz. См. bot/services/tzrules.py
    tz_auto: bool = False
    home_tz: str = "Europe/Moscow"
    tz_rules: list[dict[str, str]] = field(default_factory=list)
    wake_time: str = "07:30"            # подъём
    sleep_time: str = "23:30"           # отбой; может быть после полуночи ("00:30") — это ещё «тот же» день
    morning_brief_time: str = "07:45"   # утренняя сводка
    evening_plan_time: str = "21:30"    # вечерний отчёт + план на завтра
    checkin_enabled: bool = True        # спрашивать «что делаешь?»
    checkin_interval_min: int = 120
    class_reminder_min: int = 10        # за сколько минут напоминать о паре
    event_reminder_min: int = 30        # дефолт для новых событий
    plan_reminders: bool = True         # напоминать о блоках принятого плана
    ai_enabled: bool = True
    semester_start: str | None = None   # "YYYY-MM-DD": неделя с этой датой — нечётная (1-я)
    semester_end: str | None = None     # "YYYY-MM-DD": после этой даты пары не показываются (каникулы)
    focus_peak: str = "morning"         # morning / afternoon / evening — пик продуктивности
    commute_min: int = 0                # дорога до универа (буфер перед первой парой)
    quiet: bool = False                 # тихий режим: без чек-инов и напоминаний плана
    lang: str = "ru"                    # язык интерфейса: ru / en / zh
    card_theme: str = "auto"            # тема PNG-карточки: auto (по времени суток) / light / dark
    modules: dict[str, bool] = field(default_factory=dict)  # вкл/выкл модулей (bot/modules/registry.py)
    dnd_start: str | None = None        # тихие часы: начало "HH:MM" (None — выключены)
    dnd_end: str | None = None          # тихие часы: конец "HH:MM"
    onboarded: bool = False             # прошёл ли онбординг с выбором модулей

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "UserSettings":
        data = data or {}
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class User:
    id: int                 # telegram user id
    chat_id: int
    first_name: str
    settings: UserSettings
    created_at: datetime


@dataclass
class Task:
    id: int
    user_id: int
    title: str
    notes: str | None = None
    importance: int = 2                  # 1..3
    deadline: datetime | None = None     # aware
    estimate_min: int = 30
    energy: str = "medium"               # low / medium / high
    category: str = "study"
    status: str = "todo"                 # todo / done / cancelled
    created_at: datetime | None = None
    done_at: datetime | None = None
    planned_date: date | None = None     # если задача вручную привязана к дню


@dataclass
class Event:
    id: int
    user_id: int
    title: str
    start_at: datetime                   # aware
    end_at: datetime | None = None
    location: str | None = None
    notes: str | None = None
    remind_before_min: int = 30
    kind: str = "event"


@dataclass
class Lesson:
    """Пара из недельного учебного расписания."""
    id: int
    user_id: int
    weekday: int          # 0 = понедельник
    start_time: str       # "HH:MM"
    end_time: str         # "HH:MM"
    subject: str
    kind: str = ""        # лекция / практика / лаба / семинар
    room: str | None = None
    teacher: str | None = None
    parity: str = "all"   # all / odd / even


@dataclass
class Activity:
    """Запись трекера: чем пользователь занимался."""
    id: int
    user_id: int
    category: str
    started_at: datetime
    ended_at: datetime | None = None
    description: str | None = None
    rating: int | None = None      # 1..5 — самооценка продуктивности
    source: str = "timer"          # timer / checkin / manual / ai

    @property
    def is_running(self) -> bool:
        return self.ended_at is None


@dataclass
class PlanItem:
    start: str                     # "HH:MM" локальное
    end: str                       # "HH:MM" локальное
    kind: str                      # см. PLAN_ITEM_KINDS
    title: str
    ref_id: int | None = None      # id задачи/события/пары
    note: str | None = None
    done: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PlanItem":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DayPlan:
    user_id: int
    date: date
    items: list[PlanItem] = field(default_factory=list)
    status: str = "draft"          # draft / accepted
    ai_comment: str | None = None
    created_at: datetime | None = None


@dataclass
class DayStats:
    """Статистика за день (или период — см. PeriodStats)."""
    date: date
    minutes_by_category: dict[str, int] = field(default_factory=dict)
    tracked_min: int = 0
    productive_min: int = 0
    avg_rating: float | None = None
    tasks_done: int = 0
    tasks_planned: int = 0          # задач в плане на день
    plan_items_done: int = 0
    plan_items_total: int = 0
    lessons_count: int = 0
    focus_score: int = 0            # 0..100 — итоговая «эффективность дня»


@dataclass
class PeriodStats:
    start: date
    end: date
    days: list[DayStats] = field(default_factory=list)
    minutes_by_category: dict[str, int] = field(default_factory=dict)
    tracked_min: int = 0
    productive_min: int = 0
    avg_rating: float | None = None
    tasks_done: int = 0
    avg_focus_score: int = 0
    best_day: date | None = None


# ================================================================ учёба, карточки, привычки
# (данные для bot/services/study.py, flashcards.py, habits.py, gamification.py, pomodoro.py;
#  тексты для пользователя — в самих сервисах, в словарях {"ru","en","zh"})

SUPPORTED_LANGS = ("ru", "en", "zh")
ATTENDANCE_STATUSES = ("present", "late", "absent", "excused")   # был / опоздал / пропустил / уважительная
FLASHCARD_GRADES = {0: "again", 1: "hard", 2: "good", 3: "easy"}
FLASHCARD_SOURCES = ("builtin", "user")
WELLBEING_SCALE = (1, 5)       # sleep_quality / energy / mood
ALL_DAYS_MASK = "1111111"      # пн..вс


@dataclass
class AttendanceRecord:
    """Отметка посещаемости пары за конкретную дату."""
    user_id: int
    lesson_id: int
    date: date
    status: str                          # см. ATTENDANCE_STATUSES
    subject: str = ""                    # снимок названия предмета на момент отметки
    marked_at: datetime | None = None


@dataclass
class Grade:
    id: int
    user_id: int
    subject: str
    value: float
    max_value: float = 5.0               # 5 — пятибалльная, 100 — стобалльная и т.п.
    weight: float = 1.0
    kind: str = ""                       # тест / экзамен / дз / ... (свободный ключ)
    note: str | None = None
    date: date | None = None             # локальная дата оценки
    created_at: datetime | None = None

    @property
    def percent(self) -> float:
        return 100.0 * self.value / self.max_value if self.max_value else 0.0


@dataclass
class Flashcard:
    """Карточка интервального повторения (SM-2, как в Anki)."""
    id: int
    user_id: int
    front: str                           # иероглифы / слово
    back: str                            # перевод
    pinyin: str | None = None
    example: str | None = None
    source: str = "user"                 # builtin / user
    ease: float = 2.5
    interval_days: int = 0
    reps: int = 0                        # успешных повторений подряд
    due: date | None = None              # когда показать (локальная дата)
    lapses: int = 0                      # сколько раз забыл
    created_at: datetime | None = None
    last_review: datetime | None = None


@dataclass
class Habit:
    id: int
    user_id: int
    title: str
    emoji: str = "✅"
    target_per_day: int = 1
    days_mask: str = ALL_DAYS_MASK       # 7 символов 0/1: пн..вс
    archived: bool = False
    created_at: datetime | None = None

    def scheduled_on(self, d: date) -> bool:
        mask = self.days_mask if len(self.days_mask) == 7 else ALL_DAYS_MASK
        return mask[d.weekday()] == "1"


@dataclass
class WellbeingEntry:
    """Сон и самочувствие за день."""
    user_id: int
    date: date
    sleep_hours: float | None = None
    sleep_quality: int | None = None     # 1..5
    energy: int | None = None            # 1..5
    mood: int | None = None              # 1..5
    note: str | None = None


@dataclass
class JournalEntry:
    user_id: int
    date: date
    answers: dict[str, str] = field(default_factory=dict)   # question_key -> текст
    created_at: datetime | None = None
    updated_at: datetime | None = None
