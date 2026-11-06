"""FSM-состояния мастеров."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class TaskWizard(StatesGroup):
    title = State()      # ждём название новой задачи
    card = State()       # карточка черновика с переключателями (текст = переименовать)
    deadline = State()   # ввод своего дедлайна «12.11 18:00»


class TaskEdit(StatesGroup):
    title = State()
    deadline = State()


class EventWizard(StatesGroup):
    title = State()
    date = State()
    time = State()
    choose = State()     # шаги, где ждём только кнопки (напоминание, тип)


class LessonWizard(StatesGroup):
    time = State()
    subject = State()
    room = State()
    choose = State()


class TimetableUpload(StatesGroup):
    waiting = State()    # ждём фото или текст расписания
    preview = State()    # показали распознанное, ждём «Заменить / Добавить»


class SettingsInput(StatesGroup):
    value = State()      # свой ввод для поля настроек (data["field"])


class SetupInput(StatesGroup):
    tz = State()         # свой часовой пояс в быстрой настройке
