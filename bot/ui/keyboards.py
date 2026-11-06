"""Клавиатуры: постоянное меню (reply) и все инлайн-клавиатуры.

Обязательные функции (их вызывает notifier): main_menu, plan_actions, checkin_keyboard,
plan_item_actions, event_reminder_actions, deadline_actions, rating_keyboard.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.models import (
    ACTIVITY_CATEGORIES,
    EVENT_KINDS,
    TASK_CATEGORIES,
    WEEKDAYS_SHORT,
    DayPlan,
    PlanItem,
    UserSettings,
)
from bot.ui.callbacks import (
    AddCb,
    AiCb,
    CheckinCb,
    DeadlineCb,
    EventCb,
    EventWizCb,
    LessonWizCb,
    NavCb,
    PastCb,
    PlanCb,
    PlanItemCb,
    RateCb,
    SetCb,
    StartCb,
    StatsCb,
    TaskCb,
    TaskFieldCb,
    TaskListCb,
    TrackCb,
    TtCb,
    d2s,
    t2s,
)
from bot.ui.parsing import TIMEZONES, utc_offset_label
from bot.ui.texts import MINOR_KINDS, PLAN_KIND_EMOJI, RATING_EMOJI, truncate

# ================================================================ главное меню

BTN_TODAY = "📅 Сегодня"
BTN_TOMORROW = "🗓 Завтра"
BTN_TASKS = "✅ Задачи"
BTN_ADD = "➕ Добавить"
BTN_TRACK = "⏱ Трекер"
BTN_STATS = "📊 Статистика"
BTN_WEEK = "🎓 Расписание"
BTN_SETTINGS = "⚙️ Настройки"
MENU_BUTTONS = (BTN_TODAY, BTN_TOMORROW, BTN_TASKS, BTN_ADD, BTN_TRACK, BTN_STATS, BTN_WEEK, BTN_SETTINGS)


def norm_button(text: str | None) -> str:
    """Нормализует текст кнопки (клиенты иногда теряют/добавляют U+FE0F)."""
    return (text or "").replace("️", "").strip()


_MENU_NORM = {norm_button(b) for b in MENU_BUTTONS}


def is_menu_text(text: str | None) -> bool:
    return norm_button(text) in _MENU_NORM


def main_menu() -> ReplyKeyboardMarkup:
    """Постоянное меню: 3 + 3 + 2 — короткие частые кнопки сверху, настройки внизу."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_TOMORROW), KeyboardButton(text=BTN_TASKS)],
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_TRACK), KeyboardButton(text=BTN_STATS)],
            [KeyboardButton(text=BTN_WEEK), KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Задача, вопрос или /команда…",
    )


# ================================================================ хелперы

def btn(text: str, cb: CallbackData | str) -> InlineKeyboardButton:
    data = cb.pack() if isinstance(cb, CallbackData) else cb
    return InlineKeyboardButton(text=text, callback_data=data)


def kb(*rows: Sequence[InlineKeyboardButton] | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def chunk(items: Sequence[Any], size: int) -> list[list[Any]]:
    return [list(items[i:i + size]) for i in range(0, len(items), size)]


def mark(text: str, selected: bool) -> str:
    return f"✓ {text}" if selected else text


def nav_row(*targets: tuple[str, str]) -> list[InlineKeyboardButton]:
    return [btn(text, NavCb(to=to)) for text, to in targets]


# ================================================================ ОБЯЗАТЕЛЬНЫЕ

def plan_actions(d: date, status: str) -> InlineKeyboardMarkup:
    ds = d2s(d)
    if status == "accepted":
        return kb(
            [btn("🔄 Перестроить", PlanCb(a="re", d=ds)), btn("🤖 Улучшить с ИИ", PlanCb(a="ai", d=ds))],
            [btn("🖼 Картинкой", PlanCb(a="img", d=ds)), btn("✔️ Отметить", PlanCb(a="chk", d=ds))],
        )
    return kb(
        [btn("✅ Принять", PlanCb(a="acc", d=ds)), btn("🔄 Перестроить", PlanCb(a="re", d=ds))],
        [btn("🤖 Улучшить с ИИ", PlanCb(a="ai", d=ds)), btn("🖼 Картинкой", PlanCb(a="img", d=ds))],
    )


def _category_buttons(make_cb, *, cols: int = 3) -> list[list[InlineKeyboardButton]]:
    buttons = [btn(f"{emoji} {name}", make_cb(key)) for key, (emoji, name) in ACTIVITY_CATEGORIES.items()]
    return chunk(buttons, cols)


def checkin_keyboard() -> InlineKeyboardMarkup:
    rows = _category_buttons(lambda key: CheckinCb(cat=key))
    # последний ряд: «Другое» + «То же самое»
    if rows and len(rows[-1]) < 3:
        rows[-1].append(btn("🔁 То же самое", CheckinCb(cat="same")))
    else:
        rows.append([btn("🔁 То же самое", CheckinCb(cat="same"))])
    return kb(*rows)


def plan_item_actions(d: date, index: int, item: PlanItem) -> InlineKeyboardMarkup:
    ds = d2s(d)
    start_label = "▶️ Начать" if item.kind != "lesson" else "▶️ Иду на пару"
    return kb([
        btn(start_label, PlanItemCb(a="start", d=ds, i=index)),
        btn("✅ Готово", PlanItemCb(a="done", d=ds, i=index)),
        btn("⏭ Пропустить", PlanItemCb(a="skip", d=ds, i=index)),
    ])


def event_reminder_actions(event_id: int) -> InlineKeyboardMarkup:
    return kb([
        btn("⏰ Отложить на 10 мин", EventCb(a="snooze", id=event_id)),
        btn("👌 Ок", EventCb(a="ok", id=event_id)),
    ])


def deadline_actions(task_id: int) -> InlineKeyboardMarkup:
    return kb(
        [btn("✅ Готово", DeadlineCb(a="done", id=task_id)),
         btn("📅 Перенести на завтра", DeadlineCb(a="tom", id=task_id))],
        [btn("📝 Открыть задачу", TaskCb(a="view", id=task_id))],
    )


def rating_keyboard(activity_id: int) -> InlineKeyboardMarkup:
    return kb(
        [btn(f"{RATING_EMOJI[r]} {r}", RateCb(aid=activity_id, r=r)) for r in range(1, 6)],
        [btn("Пропустить", RateCb(aid=activity_id, r=0)), btn("⏱ Трекер", TrackCb(a="menu"))],
    )


# ================================================================ старт и настройка

def tz_buttons(make_cb, *, cols: int = 3, other_cb=None) -> list[list[InlineKeyboardButton]]:
    buttons = [btn(f"{label} {utc_offset_label(name).replace('UTC', '')}", make_cb(key))
               for key, (label, name) in TIMEZONES.items()]
    rows = chunk(buttons, cols)
    if other_cb is not None:
        rows.append([btn("✍️ Другой пояс", other_cb)])
    return rows


WAKE_OPTIONS = ("06:00", "06:30", "07:00", "07:30", "08:00", "08:30", "09:00", "09:30")
SLEEP_OPTIONS = ("22:00", "22:30", "23:00", "23:30", "00:00", "00:30", "01:00", "01:30")  # отбой бывает после полуночи
MORNING_OPTIONS = ("07:00", "07:30", "07:45", "08:00", "08:30", "08:45", "09:00", "09:30")
EVENING_OPTIONS = ("20:00", "20:30", "21:00", "21:30", "22:00", "22:30", "23:00", "23:30")


def time_buttons(options: Iterable[str], current: str | None, make_cb, cols: int = 4) -> list[list[InlineKeyboardButton]]:
    return chunk([btn(mark(t, t == current), make_cb(t2s(t))) for t in options], cols)


def setup_keyboard(step: str, settings: UserSettings) -> InlineKeyboardMarkup | None:
    if step == "tz":
        rows = tz_buttons(lambda key: StartCb(step="tz", v=key), other_cb=StartCb(step="tzother"))
        if settings.tz_auto and settings.tz_rules:
            rows.insert(0, [btn("✅ Оставить автосмену пояса", StartCb(step="tz", v="auto"))])
        rows.append([btn("Пропустить →", StartCb(step="done"))])
        return kb(*rows)
    if step == "wake":
        rows = time_buttons(WAKE_OPTIONS, settings.wake_time, lambda v: StartCb(step="wake", v=v))
        rows.append([btn("Пропустить →", StartCb(step="done"))])
        return kb(*rows)
    if step == "sleep":
        rows = time_buttons(SLEEP_OPTIONS, settings.sleep_time, lambda v: StartCb(step="sleep", v=v))
        rows.append([btn("Пропустить →", StartCb(step="done"))])
        return kb(*rows)
    return kb(nav_row(("📅 Сегодня", "today"), ("➕ Задача", "add")),
              nav_row(("🎓 Расписание", "week"), ("⚙️ Все настройки", "settings")))


# ================================================================ сегодня / план

def today_actions(d: date, plan: DayPlan | None) -> InlineKeyboardMarkup:
    ds = d2s(d)
    if not plan or not plan.items:
        return kb(
            [btn("🧩 Составить план", PlanCb(a="mk", d=ds))],
            [btn("🔄 Обновить", PlanCb(a="ref", d=ds)), btn("⏱ Трекер", TrackCb(a="menu"))],
        )
    rows = [
        [btn("✔️ Отметить выполненное", PlanCb(a="chk", d=ds)), btn("🖼 Картинкой", PlanCb(a="img", d=ds))],
        [btn("🔄 Обновить", PlanCb(a="ref", d=ds)), btn("🧩 Перестроить", PlanCb(a="re", d=ds))],
    ]
    if plan.status != "accepted":
        rows.insert(0, [btn("✅ Принять план", PlanCb(a="acc", d=ds))])
    return kb(*rows)


def plan_checklist(plan: DayPlan) -> InlineKeyboardMarkup:
    ds = d2s(plan.date)
    rows = []
    for idx, it in enumerate(plan.items):
        if it.kind in MINOR_KINDS:
            continue
        icon = "✅" if it.done else "⬜"
        rows.append([btn(f"{icon} {it.start} {PLAN_KIND_EMOJI.get(it.kind, '')} {truncate(it.title, 26)}",
                         PlanItemCb(a="t", d=ds, i=idx))])
    rows.append([btn("◀️ Назад к плану", PlanCb(a="show", d=ds))])
    return kb(*rows)


def after_card_keyboard(d: date) -> InlineKeyboardMarkup:
    return kb([btn("◀️ К плану", PlanCb(a="show", d=d2s(d)))])


# ================================================================ задачи

def add_choice_keyboard() -> InlineKeyboardMarkup:
    return kb(
        [btn("📝 Задача ✓", AddCb(kind="task")), btn("📌 Событие", AddCb(kind="event")),
         btn("🎓 Пара", AddCb(kind="lesson"))],
        [btn("✖️ Отмена", TaskFieldCb(id=0, f="cancel"))],
    )


def task_list_keyboard(task_ids: Sequence[tuple[int, int]], page: int, pages: int) -> InlineKeyboardMarkup:
    """task_ids: [(номер на экране, id задачи)]."""
    nums = [btn(str(n), TaskCb(a="view", id=tid, page=page)) for n, tid in task_ids]
    rows: list[list[InlineKeyboardButton]] = chunk(nums, 5)
    if pages > 1:
        nav = []
        nav.append(btn("◀️", TaskListCb(page=page - 1)) if page > 0 else btn("·", TaskListCb(page=page)))
        nav.append(btn(f"{page + 1}/{pages}", TaskListCb(page=page)))
        nav.append(btn("▶️", TaskListCb(page=page + 1)) if page < pages - 1 else btn("·", TaskListCb(page=page)))
        rows.append(nav)
    rows.append([btn("➕ Задача", NavCb(to="add")), btn("📌 События", EventCb(a="list"))])
    return kb(*rows)


def task_card_keyboard(task_id: int, page: int = 0, *, done: bool = False) -> InlineKeyboardMarkup:
    if done:
        return kb(
            [btn("↩️ Вернуть в работу", TaskCb(a="undo", id=task_id, page=page)),
             btn("🗑 Удалить", TaskCb(a="del", id=task_id, page=page))],
            [btn("◀️ К списку", TaskListCb(page=page))],
        )
    return kb(
        [btn("✅ Готово", TaskCb(a="done", id=task_id, page=page)),
         btn("✏️ Изменить", TaskCb(a="edit", id=task_id, page=page))],
        [btn("📅 На завтра", TaskCb(a="tom", id=task_id, page=page)),
         btn("🗑 Удалить", TaskCb(a="del", id=task_id, page=page))],
        [btn("❓ Почему такой приоритет", TaskCb(a="why", id=task_id, page=page))],
        [btn("◀️ К списку", TaskListCb(page=page))],
    )


def task_delete_confirm(task_id: int, page: int = 0) -> InlineKeyboardMarkup:
    return kb([btn("🗑 Да, удалить", TaskCb(a="delok", id=task_id, page=page)),
               btn("Отмена", TaskCb(a="view", id=task_id, page=page))])


DEADLINE_PRESETS = (("today", "Сегодня"), ("tom", "Завтра"), ("3d", "Через 3 дня"),
                    ("week", "Неделя"), ("custom", "✍️ Своя дата"), ("none", "Без срока"))
ESTIMATE_PRESETS = ((15, "15м"), (30, "30м"), (60, "1ч"), (120, "2ч"), (240, "4ч"))
ENERGY_PRESETS = (("low", "🟢 Легко"), ("medium", "🟡 Средне"), ("high", "🔴 Сложно"))


def task_fields_keyboard(task_id: int, values: dict[str, Any], *, deadline_key: str | None = None,
                         draft: bool) -> InlineKeyboardMarkup:
    """Кнопки-переключатели полей задачи. task_id=0 — черновик мастера."""
    imp = int(values.get("importance") or 2)
    est = int(values.get("estimate_min") or 30)
    energy = values.get("energy") or "medium"
    cat = values.get("category") or "study"
    has_dl = bool(values.get("deadline"))

    def f(field: str, v: Any = "") -> TaskFieldCb:
        return TaskFieldCb(id=task_id, f=field, v=str(v))

    rows: list[list[InlineKeyboardButton]] = [
        [btn(mark(label, imp == i), f("imp", i)) for i, label in ((1, "⭐"), (2, "⭐⭐"), (3, "⭐⭐⭐"))],
    ]
    dl_buttons = []
    for key, label in DEADLINE_PRESETS:
        selected = (deadline_key == key) if deadline_key else (key == "none" and not has_dl)
        dl_buttons.append(btn(mark(label, selected), f("dl", key)))
    rows.extend(chunk(dl_buttons, 3))
    rows.append([btn(mark(label, est == m), f("est", m)) for m, label in ESTIMATE_PRESETS])
    rows.append([btn(mark(label, energy == key), f("en", key)) for key, label in ENERGY_PRESETS])
    rows.append([btn(("✓" if key == cat else "") + emoji, f("cat", key))
                 for key, (emoji, _name) in TASK_CATEGORIES.items()])
    if draft:
        rows.append([btn("💾 Сохранить", f("save")), btn("📌 Это событие", f("event"))])
        rows.append([btn("✏️ Название", f("title")), btn("✖️ Отмена", f("cancel"))])
    else:
        rows.append([btn("✏️ Название", f("title")), btn("◀️ Готово", f("back"))])
    return kb(*rows)


def task_saved_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return kb([btn("📝 Открыть", TaskCb(a="view", id=task_id)), btn("➕ Ещё задачу", NavCb(to="add"))],
              [btn("✅ Все задачи", TaskListCb(page=0)), btn("📅 Сегодня", NavCb(to="today"))])


# ================================================================ события

def event_list_keyboard(event_ids: Sequence[tuple[int, int]]) -> InlineKeyboardMarkup:
    nums = [btn(str(n), EventCb(a="view", id=eid)) for n, eid in event_ids]
    rows = chunk(nums, 5)
    rows.append([btn("➕ Новое событие", EventCb(a="add")), btn("✅ Задачи", TaskListCb(page=0))])
    return kb(*rows)


def event_card_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return kb([btn("🗑 Удалить", EventCb(a="del", id=event_id)), btn("◀️ К событиям", EventCb(a="list"))])


def event_delete_confirm(event_id: int) -> InlineKeyboardMarkup:
    return kb([btn("🗑 Да, удалить", EventCb(a="delok", id=event_id)),
               btn("Отмена", EventCb(a="view", id=event_id))])


def event_date_keyboard() -> InlineKeyboardMarkup:
    return kb([btn("Сегодня", EventWizCb(f="date", v="0")), btn("Завтра", EventWizCb(f="date", v="1")),
               btn("Послезавтра", EventWizCb(f="date", v="2"))],
              [btn("✖️ Отмена", EventWizCb(f="cancel"))])


EVENT_TIME_PRESETS = ("09:00", "10:00", "12:00", "14:00", "16:00", "18:00", "19:00", "20:00")


def event_time_keyboard() -> InlineKeyboardMarkup:
    rows = chunk([btn(t, EventWizCb(f="time", v=t2s(t))) for t in EVENT_TIME_PRESETS], 4)
    rows.append([btn("◀️ Дата", EventWizCb(f="back", v="date")), btn("✖️ Отмена", EventWizCb(f="cancel"))])
    return kb(*rows)


REMIND_PRESETS = ((10, "за 10 мин"), (30, "за 30 мин"), (60, "за 1 ч"), (1440, "за день"))


def event_remind_keyboard(default: int) -> InlineKeyboardMarkup:
    rows = chunk([btn(mark(label, m == default), EventWizCb(f="rem", v=str(m))) for m, label in REMIND_PRESETS], 2)
    rows.append([btn("◀️ Время", EventWizCb(f="back", v="time")), btn("✖️ Отмена", EventWizCb(f="cancel"))])
    return kb(*rows)


def event_kind_keyboard() -> InlineKeyboardMarkup:
    rows = chunk([btn(label, EventWizCb(f="kind", v=key)) for key, label in EVENT_KINDS.items()], 2)
    rows.append([btn("✖️ Отмена", EventWizCb(f="cancel"))])
    return kb(*rows)


def event_saved_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return kb([btn("📌 Все события", EventCb(a="list")), btn("➕ Ещё", EventCb(a="add"))],
              [btn("🗑 Удалить", EventCb(a="del", id=event_id))])


def wizard_cancel_keyboard(cb: CallbackData) -> InlineKeyboardMarkup:
    return kb([btn("✖️ Отмена", cb)])


# ================================================================ трекер

def tracker_keyboard(running: bool) -> InlineKeyboardMarkup:
    rows = _category_buttons(lambda key: TrackCb(a="start", cat=key))
    if running:
        rows.insert(0, [btn("⏹ Стоп", TrackCb(a="stop"))])
    extra = btn("➕ Прошедшее", TrackCb(a="past"))
    if rows and len(rows[-1]) < 3:
        rows[-1].append(extra)
    else:
        rows.append([extra])
    rows.append([btn("🔄 Обновить", TrackCb(a="menu")), btn("📊 Статистика", StatsCb(p="d", o=0))])
    return kb(*rows)


def past_category_keyboard() -> InlineKeyboardMarkup:
    rows = _category_buttons(lambda key: PastCb(cat=key))
    rows.append([btn("◀️ Назад", TrackCb(a="menu"))])
    return kb(*rows)


PAST_AGO = (15, 30, 45, 60, 90, 120, 180, 240)
PAST_DUR = (15, 30, 45, 60, 90, 120, 180)


def _short_dur(m: int) -> str:
    if m < 60:
        return f"{m}м"
    h, r = divmod(m, 60)
    if not r:
        return f"{h}ч"
    return f"{h}.5ч" if r == 30 else f"{h}ч{r}м"


def past_ago_keyboard(cat: str) -> InlineKeyboardMarkup:
    rows = chunk([btn(f"{_short_dur(m)} назад", PastCb(cat=cat, ago=m)) for m in PAST_AGO], 4)
    rows.append([btn("◀️ Категория", TrackCb(a="past"))])
    return kb(*rows)


def past_dur_keyboard(cat: str, ago: int) -> InlineKeyboardMarkup:
    options = [m for m in PAST_DUR if m < ago]
    buttons = [btn(_short_dur(m), PastCb(cat=cat, ago=ago, dur=m)) for m in options]
    buttons.append(btn("⏱ До сейчас", PastCb(cat=cat, ago=ago, dur=ago)))
    rows = chunk(buttons, 4)
    rows.append([btn("◀️ Назад", PastCb(cat=cat))])
    return kb(*rows)


def after_stop_keyboard() -> InlineKeyboardMarkup:
    return kb([btn("⏱ Трекер", TrackCb(a="menu")), btn("📊 Статистика", StatsCb(p="d", o=0))])


# ================================================================ статистика

def stats_keyboard(period: str, offset: int) -> InlineKeyboardMarkup:
    tabs = [btn(mark(label, period == key), StatsCb(p=key, o=0))
            for key, label in (("d", "День"), ("w", "Неделя"), ("m", "Месяц"))]
    nav = [btn("◀️ Раньше", StatsCb(p=period, o=offset + 1))]
    if offset > 0:
        nav.append(btn("Позже ▶️", StatsCb(p=period, o=offset - 1)))
    return kb(tabs, nav)


# ================================================================ расписание

def week_keyboard(offset: int) -> InlineKeyboardMarkup:
    if offset == 0:
        switch = [btn("Следующая неделя ▶️", TtCb(a="w", o=1))]
    elif offset == 1:
        switch = [btn("◀️ Эта неделя", TtCb(a="w", o=0)), btn("Через неделю ▶️", TtCb(a="w", o=2))]
    else:
        switch = [btn("◀️ Назад", TtCb(a="w", o=offset - 1)), btn("Эта неделя", TtCb(a="w", o=0))]
    return kb(switch,
              [btn("➕ Пара", TtCb(a="add", o=offset)), btn("🗑 Удалить пару", TtCb(a="del", o=offset))],
              [btn("📷 Загрузить фото/текст расписания", TtCb(a="up", o=offset))])


def lesson_day_keyboard(counts: dict[int, int] | None, cb_factory, *, back: CallbackData) -> InlineKeyboardMarkup:
    buttons = []
    for wd in range(7):
        label = WEEKDAYS_SHORT[wd].capitalize()
        if counts is not None:
            if not counts.get(wd):
                continue
            label += f" · {counts[wd]}"
        buttons.append(btn(label, cb_factory(wd)))
    rows = chunk(buttons, 4)
    rows.append([btn("◀️ Назад", back)])
    return kb(*rows)


DEFAULT_SLOTS = ("08:30-10:00", "10:10-11:40", "11:50-13:20", "13:50-15:20", "15:30-17:00", "17:10-18:40")


def lesson_time_keyboard(slots: Sequence[str]) -> InlineKeyboardMarkup:
    buttons = [btn(s.replace("-", "–"), LessonWizCb(f="time", v=s.replace(":", ""))) for s in slots]
    rows = chunk(buttons, 2)
    rows.append([btn("✖️ Отмена", LessonWizCb(f="cancel"))])
    return kb(*rows)


def lesson_subject_keyboard(subjects: Sequence[str]) -> InlineKeyboardMarkup:
    rows = chunk([btn(truncate(s, 28), LessonWizCb(f="subj", v=str(i))) for i, s in enumerate(subjects)], 2)
    rows.append([btn("✖️ Отмена", LessonWizCb(f="cancel"))])
    return kb(*rows)


LESSON_KINDS = (("lec", "лекция"), ("pr", "практика"), ("lab", "лаба"), ("sem", "семинар"), ("none", "—"))


def lesson_kind_keyboard() -> InlineKeyboardMarkup:
    rows = chunk([btn(label, LessonWizCb(f="kind", v=key)) for key, label in LESSON_KINDS], 3)
    rows.append([btn("✖️ Отмена", LessonWizCb(f="cancel"))])
    return kb(*rows)


def lesson_room_keyboard(rooms: Sequence[str]) -> InlineKeyboardMarkup:
    rows = chunk([btn(truncate(r, 14), LessonWizCb(f="room", v=str(i))) for i, r in enumerate(rooms)], 4)
    rows.append([btn("Пропустить →", LessonWizCb(f="room", v="-")), btn("✖️ Отмена", LessonWizCb(f="cancel"))])
    return kb(*rows)


def lesson_parity_keyboard() -> InlineKeyboardMarkup:
    return kb([btn("Каждую неделю", LessonWizCb(f="par", v="all"))],
              [btn("Числитель (нечёт)", LessonWizCb(f="par", v="odd")),
               btn("Знаменатель (чёт)", LessonWizCb(f="par", v="even"))],
              [btn("✖️ Отмена", LessonWizCb(f="cancel"))])


def lesson_delete_keyboard(lessons, day: int, offset: int) -> InlineKeyboardMarkup:
    rows = [[btn(f"🗑 {l.start_time} {truncate(l.subject, 24)}", TtCb(a="dl", o=offset, day=day, id=l.id))]
            for l in lessons]
    rows.append([btn("◀️ Дни", TtCb(a="del", o=offset)), btn("Готово", TtCb(a="w", o=offset))])
    return kb(*rows)


def lesson_delete_confirm(lesson_id: int, day: int, offset: int) -> InlineKeyboardMarkup:
    return kb([btn("🗑 Да, удалить", TtCb(a="dlok", o=offset, day=day, id=lesson_id)),
               btn("Отмена", TtCb(a="dday", o=offset, day=day))])


def timetable_import_keyboard() -> InlineKeyboardMarkup:
    return kb([btn("♻️ Заменить всё", TtCb(a="imp", id=1)), btn("➕ Добавить", TtCb(a="imp", id=0))],
              [btn("✖️ Отмена", TtCb(a="impno"))])


def lesson_saved_keyboard(offset: int = 0) -> InlineKeyboardMarkup:
    return kb([btn("➕ Ещё пара", TtCb(a="add", o=offset)), btn("🎓 Расписание", TtCb(a="w", o=offset))])


# ================================================================ настройки

def settings_keyboard(s: UserSettings) -> InlineKeyboardMarkup:
    def f(field: str) -> SetCb:
        return SetCb(f=field)

    return kb(
        [btn("🌍 Пояс", f("tz")), btn(("🔄 Автопояс: вкл" if s.tz_auto else "🔄 Автопояс: выкл"),
                                       SetCb(f="ta", v="t"))],
        [btn("⏰ Подъём", f("wake")), btn("🌙 Отбой", f("sleep"))],
        [btn("☀️ Сводка", f("mb")), btn("🌆 План на завтра", f("ep"))],
        [btn("👋 Чек-ины", f("ci")), btn("🎓 О паре", f("cr")), btn("📌 О событии", f("er"))],
        [btn(("🔔" if s.plan_reminders else "🔕") + " Напоминания плана", SetCb(f="pr", v="t")),
         btn("⚡ Пик", f("fp"))],
        [btn("🚌 Дорога", f("cm")), btn("📆 Начало сем.", f("ss")), btn("🏁 Конец сем.", f("se"))],
        [btn(("🤫 Тихий: вкл" if s.quiet else "🔊 Тихий: выкл"), SetCb(f="q", v="t")),
         btn(("🤖 ИИ: вкл" if s.ai_enabled else "🤖 ИИ: выкл"), SetCb(f="ai", v="t"))],
        [btn("☀️ Сводка сейчас", SetCb(f="now", v="m")), btn("🌆 Отчёт сейчас", SetCb(f="now", v="e"))],
    )


def _back_settings() -> list[InlineKeyboardButton]:
    return [btn("◀️ Назад", SetCb(f="main"))]


def setting_options_keyboard(field: str, s: UserSettings) -> InlineKeyboardMarkup:
    def cb(v: Any) -> SetCb:
        return SetCb(f=field, v=str(v))

    custom = btn("✍️ Своё", SetCb(f=field, v="custom"))
    rows: list[list[InlineKeyboardButton]]
    if field == "tz":
        rows = tz_buttons(cb, other_cb=SetCb(f="tz", v="custom"))
        if s.tz_rules:
            rows.insert(0, [btn(mark("🔄 Авто по датам", s.tz_auto), SetCb(f="ta", v="on"))])
    elif field in ("wake", "sleep", "mb", "ep"):
        options = {"wake": WAKE_OPTIONS, "sleep": SLEEP_OPTIONS, "mb": MORNING_OPTIONS, "ep": EVENING_OPTIONS}[field]
        current = {"wake": s.wake_time, "sleep": s.sleep_time, "mb": s.morning_brief_time,
                   "ep": s.evening_plan_time}[field]
        rows = time_buttons(options, current, cb)
        rows.append([custom])
    elif field == "ci":
        rows = [[btn(mark("Выключить", not s.checkin_enabled), cb("off"))]]
        rows += chunk([btn(mark(label, s.checkin_enabled and s.checkin_interval_min == m), cb(m))
                       for m, label in ((60, "1 ч"), (90, "1.5 ч"), (120, "2 ч"), (180, "3 ч"), (240, "4 ч"))], 5)
    elif field == "cr":
        rows = [[btn(mark(f"{m} мин", s.class_reminder_min == m), cb(m)) for m in (5, 10, 15, 20, 30)]]
    elif field == "er":
        rows = chunk([btn(mark(label, s.event_reminder_min == m), cb(m))
                      for m, label in ((10, "10 мин"), (15, "15 мин"), (30, "30 мин"), (60, "1 ч"),
                                       (120, "2 ч"), (1440, "за день"))], 3)
    elif field == "fp":
        rows = [[btn(mark(label, s.focus_peak == key), cb(key))
                 for key, label in (("morning", "🌅 Утро"), ("afternoon", "☀️ День"), ("evening", "🌙 Вечер"))]]
    elif field == "cm":
        rows = chunk([btn(mark(label, s.commute_min == m), cb(m))
                      for m, label in ((0, "Нет"), (15, "15 мин"), (30, "30 мин"), (45, "45 мин"),
                                       (60, "1 ч"), (90, "1.5 ч"))], 3)
    elif field == "ss":
        rows = [[btn("Эта неделя — нечётная (числ.)", cb("odd"))],
                [btn("Эта неделя — чётная (знам.)", cb("even"))],
                [btn("1 сентября", cb("sep1")), btn("1 марта", cb("mar1"))],
                [btn("✍️ Ввести дату", cb("custom")), btn("Сбросить", cb("reset"))]]
    elif field == "se":
        rows = [[btn("31 января", cb("jan31")), btn("30 июня", cb("jun30")), btn("15 июля", cb("jul15"))],
                [btn("✍️ Ввести дату", cb("custom")), btn("Без конца", cb("reset"))]]
    else:
        rows = []
    rows.append(_back_settings())
    return kb(*rows)


# ================================================================ ИИ и свободный текст

def ai_help_keyboard(*, available: bool, enabled: bool) -> InlineKeyboardMarkup:
    if available and not enabled:
        return kb([btn("🤖 Включить ИИ", AiCb(a="on"))])
    if not available:
        return kb(nav_row(("➕ Добавить задачу", "add"), ("📅 Сегодня", "today")))
    return kb([btn("🧹 Очистить контекст", AiCb(a="clear"))])


def free_text_keyboard() -> InlineKeyboardMarkup:
    return kb([btn("➕ Сделать задачей", AiCb(a="task")), btn("📌 Событием", AiCb(a="event"))],
              [btn("✖️ Не надо", AiCb(a="no"))])


def ai_changed_keyboard() -> InlineKeyboardMarkup:
    return kb(nav_row(("📅 Сегодня", "today"), ("✅ Задачи", "tasks"), ("⏱ Трекер", "track")))


def photo_offer_keyboard() -> InlineKeyboardMarkup:
    return kb([btn("📷 Да, распознать расписание", AiCb(a="photo")), btn("✖️ Нет", AiCb(a="no"))])


# ================================================================ утилиты для тестов

def iter_buttons(markup: InlineKeyboardMarkup) -> Iterable[InlineKeyboardButton]:
    for row in markup.inline_keyboard:
        yield from row
