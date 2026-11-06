"""E2E-тесты хендлеров через настоящий Dispatcher и фейковую сессию бота (без сети)."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageCaption,
    EditMessageReplyMarkup,
    EditMessageText,
    GetFile,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    File,
    InlineKeyboardMarkup,
    Message,
    PhotoSize,
    Update,
)
from aiogram.types import User as TgUser

from bot.__main__ import build_dispatcher
from bot.ai.assistant import AIAssistant, AIReply
from bot.config import Config
from bot.handlers import BOT_COMMANDS, events as events_handlers, setup_routers
from bot.handlers.tracker import detect_category
from bot.services import timetable as tt
from bot.timeutil import combine_local, local_today, now_utc
from bot.ui import keyboards as kb
from bot.ui.callbacks import CheckinCb, EventCb

USER_ID = 4242
TIMETABLE = str(Path(__file__).resolve().parents[1] / "data" / "timetable.yaml")
BOT_USER = TgUser(id=123, is_bot=True, first_name="Planner")
UTC = timezone.utc


# ---------------------------------------------------------------- фейковая сессия

class FakeSession(BaseSession):
    """Записывает все вызовы Bot API и отвечает правдоподобными объектами."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[TelegramMethod, Any]] = []
        self._next_id = 1000

    def _message(self, bot: Bot, chat_id: Any, *, text: str | None = None, caption: str | None = None,
                 markup: Any = None, message_id: int | None = None, photo: bool = False) -> Message:
        if message_id is None:
            self._next_id += 1
            message_id = self._next_id
        extra: dict[str, Any] = {}
        if photo:
            extra["photo"] = [PhotoSize(file_id="sent", file_unique_id="sent", width=10, height=10)]
        return Message(message_id=message_id, date=datetime.now(UTC), chat=Chat(id=int(chat_id or USER_ID), type="private"),
                       from_user=BOT_USER, text=text, caption=caption,
                       reply_markup=markup if isinstance(markup, InlineKeyboardMarkup) else None, **extra).as_(bot)

    def _respond(self, bot: Bot, method: TelegramMethod) -> Any:
        markup = getattr(method, "reply_markup", None)
        if isinstance(markup, InlineKeyboardMarkup):
            for row in markup.inline_keyboard:
                for b in row:
                    if b.callback_data is not None:
                        assert len(b.callback_data.encode()) <= 64, b.callback_data
        if isinstance(method, SendMessage):
            assert len(method.text) <= 4096
            return self._message(bot, method.chat_id, text=method.text, markup=markup)
        if isinstance(method, EditMessageText):
            return self._message(bot, method.chat_id, text=method.text, markup=markup, message_id=method.message_id)
        if isinstance(method, SendPhoto):
            return self._message(bot, method.chat_id, caption=method.caption, markup=markup, photo=True)
        if isinstance(method, EditMessageCaption):
            return self._message(bot, method.chat_id, caption=method.caption, markup=markup,
                                 message_id=method.message_id, photo=True)
        if isinstance(method, EditMessageReplyMarkup):
            return True
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u-" + method.file_id, file_path="photos/p.jpg")
        return True  # AnswerCallbackQuery, SendChatAction, DeleteMessage, SetMyCommands, ...

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> Any:
        result = self._respond(bot, method)
        self.calls.append((method, result))
        return result

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30,
                             chunk_size: int = 65536, raise_for_status: bool = True):
        yield b"\xff\xd8\xff\xe0fake-jpeg"

    async def close(self) -> None:
        pass


def _text_of(method: TelegramMethod) -> str | None:
    if isinstance(method, (SendMessage, EditMessageText)):
        return method.text
    if isinstance(method, (SendPhoto, EditMessageCaption)):
        return method.caption
    return None


class Harness:
    def __init__(self, db, ai) -> None:
        self.db = db
        self.ai = ai
        self.session = FakeSession()
        self.bot = Bot("123:abc", session=self.session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.config = Config(bot_token="123:abc", timetable_path=TIMETABLE)
        self.dp = build_dispatcher(db, ai, self.config, notifier=None)
        self.tg_user = TgUser(id=USER_ID, is_bot=False, first_name="Тест")
        self.chat = Chat(id=USER_ID, type="private")
        self._update_id = 0
        self._msg_id = 0

    def _ids(self) -> tuple[int, int]:
        self._update_id += 1
        self._msg_id += 1
        return self._update_id, self._msg_id

    async def _feed(self, **update: Any) -> list[tuple[TelegramMethod, Any]]:
        start = len(self.session.calls)
        update_id, _ = self._ids()
        await self.dp.feed_update(self.bot, Update(update_id=update_id, **update))
        return self.session.calls[start:]

    async def send(self, text: str) -> list[tuple[TelegramMethod, Any]]:
        _, mid = self._ids()
        msg = Message(message_id=mid, date=datetime.now(UTC), chat=self.chat, from_user=self.tg_user, text=text)
        return await self._feed(message=msg)

    async def send_photo(self, file_id: str = "photo-1") -> list[tuple[TelegramMethod, Any]]:
        _, mid = self._ids()
        msg = Message(message_id=mid, date=datetime.now(UTC), chat=self.chat, from_user=self.tg_user,
                      photo=[PhotoSize(file_id=file_id + "-s", file_unique_id="s", width=90, height=90),
                             PhotoSize(file_id=file_id, file_unique_id="b", width=900, height=900)])
        return await self._feed(message=msg)

    async def press(self, data: str, *, text: str = "…", message_id: int = 1) -> list[tuple[TelegramMethod, Any]]:
        msg = Message(message_id=message_id, date=datetime.now(UTC), chat=self.chat, from_user=BOT_USER, text=text)
        self._update_id += 1
        cq = CallbackQuery(id=f"cq{self._update_id}", from_user=self.tg_user, chat_instance="ci", data=data,
                           message=msg)
        start = len(self.session.calls)
        await self.dp.feed_update(self.bot, Update(update_id=self._update_id, callback_query=cq))
        return self.session.calls[start:]

    # ---- поиск кнопок/текстов
    def last_screen(self) -> tuple[TelegramMethod, Any]:
        for method, result in reversed(self.session.calls):
            if isinstance(getattr(method, "reply_markup", None), InlineKeyboardMarkup):
                return method, result
        raise AssertionError("нет сообщений с инлайн-кнопками")

    def find_button(self, label: str):
        method, result = self.last_screen()
        buttons = [b for row in method.reply_markup.inline_keyboard for b in row]
        for b in buttons:
            if b.text in (label, f"✓ {label}"):
                return b, method, result
        for b in buttons:
            if label in b.text:
                return b, method, result
        raise AssertionError(f"кнопка {label!r} не найдена среди {[b.text for b in buttons]}")

    async def click(self, label: str) -> list[tuple[TelegramMethod, Any]]:
        button, method, result = self.find_button(label)
        mid = result.message_id if isinstance(result, Message) else 1
        return await self.press(button.callback_data, text=_text_of(method) or "…", message_id=mid)

    @staticmethod
    def texts(calls: list[tuple[TelegramMethod, Any]]) -> list[str]:
        return [t for t in (_text_of(m) for m, _ in calls) if t]

    @staticmethod
    def alerts(calls: list[tuple[TelegramMethod, Any]]) -> list[str]:
        return [m.text or "" for m, _ in calls if isinstance(m, AnswerCallbackQuery)]

    @staticmethod
    def joined(calls: list[tuple[TelegramMethod, Any]]) -> str:
        return "\n".join(Harness.texts(calls))

    async def user(self):
        return await self.db.get_user(USER_ID)


class FakeAI:
    """ИИ с предсказуемыми ответами."""
    enabled = True

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.chats: list[str] = []
        self.parsed: list[tuple[str | None, bytes | None]] = []

    async def chat(self, user, text: str) -> AIReply:
        self.chats.append(text)
        if self.fail:
            raise RuntimeError("API down")
        return AIReply(text="Готово, записал <b>курсач</b> 👍", actions=["➕ Задача «Курсач»"], changed=True)

    async def suggest_task_fields(self, user, title: str) -> dict[str, Any]:
        return {"importance": 3, "estimate_min": 120, "energy": "high"}

    async def parse_timetable(self, *, text: str | None = None, image: bytes | None = None,
                              mime: str = "image/jpeg") -> list[dict[str, Any]]:
        self.parsed.append((text, image))
        return [{"day": "пн", "time": "09:00-10:30", "subject": "Матанализ", "room": "1-301"},
                {"day": "ср", "time": "10:45-12:15", "subject": "Физика", "weeks": "odd"},
                {"day": "xx", "time": "??", "subject": ""}]

    async def improve_plan(self, user, plan, **kwargs):
        return plan


@pytest.fixture(autouse=True)
def no_error_logs(caplog):
    caplog.set_level(logging.WARNING)
    yield
    records = caplog.get_records("setup") + caplog.get_records("call")
    errors = [f"{r.name}: {r.getMessage()}" for r in records if r.levelno >= logging.ERROR]
    assert not errors, errors


@pytest.fixture
async def h(db):
    harness = Harness(db, AIAssistant(db, None))
    yield harness
    await harness.bot.session.close()


@pytest.fixture
async def h_ai(db):
    harness = Harness(db, FakeAI())
    yield harness


# ---------------------------------------------------------------- сборка

def test_commands_and_routers():
    names = [c.command for c in BOT_COMMANDS]
    assert names == ["start", "today", "tomorrow", "plan", "tasks", "add", "event", "track", "stop", "stats",
                     "week", "settings", "ai", "help", "cancel"]
    assert all(c.description for c in BOT_COMMANDS)
    root = setup_routers()
    assert [r.name for r in root.sub_routers][-1] == "ai_chat"


def test_detect_category():
    assert detect_category("учёба матан") == ("study", "матан")
    assert detect_category("📚 конспект") == ("study", "конспект")
    assert detect_category("🏃") == ("sport", None)
    assert detect_category("домашка по физике") == ("study", "домашка по физике")
    assert detect_category("rest") == ("rest", None)
    assert detect_category("чиню велосипед") == ("other", "чиню велосипед")


def test_callback_data_fits_for_extreme_values():
    from bot.models import DayPlan, PlanItem, UserSettings
    from bot.ui.callbacks import LessonWizCb, PastCb, TtCb
    big = 2_000_000_000
    s = UserSettings(tz_rules=[{"from": "09-01", "to": "01-31", "tz": "Asia/Shanghai"}])
    plan = DayPlan(user_id=1, date=date(2026, 12, 31),
                   items=[PlanItem(start="09:00", end="10:00", kind="task", title="x" * 80)] * 3)
    markups = [
        kb.event_list_keyboard([(n, big) for n in range(1, 11)]), kb.event_card_keyboard(big),
        kb.event_delete_confirm(big), kb.event_saved_keyboard(big), kb.event_reminder_actions(big),
        kb.event_date_keyboard(), kb.event_time_keyboard(), kb.event_remind_keyboard(1440), kb.event_kind_keyboard(),
        kb.tracker_keyboard(True), kb.past_category_keyboard(), kb.past_ago_keyboard("chores"),
        kb.past_dur_keyboard("social", 240), kb.rating_keyboard(big), kb.checkin_keyboard(), kb.after_stop_keyboard(),
        kb.stats_keyboard("m", 60), kb.week_keyboard(52),
        kb.lesson_day_keyboard({0: 3, 6: 9}, lambda wd: TtCb(a="dday", o=52, day=wd), back=TtCb(a="w", o=52)),
        kb.lesson_time_keyboard(kb.DEFAULT_SLOTS), kb.lesson_subject_keyboard(["Очень длинный предмет " * 4] * 10),
        kb.lesson_kind_keyboard(), kb.lesson_room_keyboard(["1-301"] * 8), kb.lesson_parity_keyboard(),
        kb.lesson_delete_confirm(big, 6, 52), kb.timetable_import_keyboard(), kb.lesson_saved_keyboard(52),
        kb.timetable_upload_keyboard(52), kb.timetable_no_ai_keyboard(52), kb.settings_keyboard(s),
        kb.setting_input_keyboard("se"), kb.ai_help_keyboard(available=True, enabled=True),
        kb.free_text_keyboard(), kb.photo_offer_keyboard(), kb.ai_changed_keyboard(), kb.checkin_done_keyboard(),
        kb.plan_checklist(plan), kb.task_fields_keyboard(big, {}, draft=False), kb.task_card_keyboard(big, 99),
        kb.kb([kb.btn("x", PastCb(cat="chores", ago=1440, dur=1440)), kb.btn("y", LessonWizCb(f="time", v="2330-2359"))]),
    ]
    for field in ("tz", "wake", "sleep", "mb", "ep", "ci", "cr", "er", "fp", "cm", "ss", "se"):
        markups.append(kb.setting_options_keyboard(field, s))
    for markup in markups:
        for button in kb.iter_buttons(markup):
            assert button.callback_data and len(button.callback_data.encode()) <= 64, button.callback_data


# ---------------------------------------------------------------- старт и главное меню

async def test_start_imports_timetable_and_menu_screens(h, db):
    calls = await h.send("/start")
    assert len(await db.list_lessons(USER_ID)) == 16
    assert any(isinstance(m, SendMessage) and m.reply_markup is not None for m, _ in calls)
    assert "16" in h.joined(calls) or "пар" in h.joined(calls)

    today = h.joined(await h.send("📅 Сегодня"))
    assert "Сегодня" in today
    tomorrow = h.joined(await h.send("🗓 Завтра"))
    assert "завтра" in tomorrow.lower()
    tasks = h.joined(await h.send("✅ Задачи"))
    assert "задач" in tasks.lower()
    help_text = h.joined(await h.send("/help"))
    assert "/track" in help_text
    # кнопка меню с потерянным U+FE0F всё равно ловится
    settings = h.joined(await h.send("⚙ Настройки"))
    assert "Настройки" in settings


async def test_unknown_command_and_ai_help(h):
    await h.send("/start")
    assert "Не знаю такую команду" in h.joined(await h.send("/foo"))
    assert "ANTHROPIC_API_KEY" in h.joined(await h.send("/ai"))


# ---------------------------------------------------------------- задачи

async def test_add_task_wizard_saves_task(h, db):
    await h.send("/start")
    calls = await h.send("➕ Добавить")
    assert "Что добавим" in h.joined(calls)
    calls = await h.send("Курсовая по экономике")
    assert "Курсовая по экономике" in h.joined(calls)
    await h.click("⭐⭐⭐")
    await h.click("Завтра")
    calls = await h.click("💾 Сохранить")
    assert "Задача добавлена" in h.joined(calls)
    tasks = await db.list_tasks(USER_ID)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.title == "Курсовая по экономике" and task.importance == 3 and task.deadline is not None
    tz_name = (await h.user()).settings.tz
    assert task.deadline == combine_local(local_today(tz_name) + timedelta(days=1), "23:59", tz_name)


# ---------------------------------------------------------------- события

async def test_event_wizard_saves_event_in_utc(h, db):
    await h.send("/start")
    calls = await h.send("/event Встреча с научруком")
    assert "Когда" in h.joined(calls)
    await h.click("Завтра")
    calls = await h.send("18.30")
    assert "напомнить" in h.joined(calls)
    await h.click("за 1 ч")
    calls = await h.click("🤝 Встреча")
    assert "Событие добавлено" in h.joined(calls)
    tz_name = (await h.user()).settings.tz
    events = await db.upcoming_events(USER_ID)
    assert len(events) == 1
    ev = events[0]
    expected = combine_local(local_today(tz_name) + timedelta(days=1), "18:30", tz_name).astimezone(UTC)
    assert ev.start_at == expected and ev.start_at.utcoffset() == timedelta(0)
    assert ev.title == "Встреча с научруком" and ev.remind_before_min == 60 and ev.kind == "meeting"


async def test_event_wizard_typed_date_list_and_delete(h, db):
    await h.send("/start")
    await h.send("/event")
    await h.send("Экзамен по матану")
    future = local_today("UTC") + timedelta(days=40)
    await h.send(future.strftime("%d.%m.%Y"))
    calls = await h.send("10:00-12:00")
    assert "напомнить" in h.joined(calls)
    await h.click("за день")
    await h.click("🎓 Экзамен")
    ev = (await db.upcoming_events(USER_ID))[0]
    tz_name = (await h.user()).settings.tz
    assert ev.start_at == combine_local(future, "10:00", tz_name)
    assert ev.end_at == combine_local(future, "12:00", tz_name)
    assert ev.kind == "exam" and ev.remind_before_min == 1440

    calls = await h.press(EventCb(a="list").pack())
    assert "Экзамен по матану" in h.joined(calls)
    await h.click("1")
    calls = await h.click("🗑 Удалить")
    assert "Удалить событие?" in h.joined(calls)
    await h.click("🗑 Да, удалить")
    assert await db.upcoming_events(USER_ID) == []


async def test_event_wizard_rejects_bad_input(h, db):
    await h.send("/start")
    await h.send("/event Тест")
    assert "Не понял дату" in h.joined(await h.send("когда-нибудь"))
    await h.click("Завтра")
    assert "Не понял время" in h.joined(await h.send("25:99"))
    assert await db.upcoming_events(USER_ID) == []


async def test_add_choice_event_and_snooze(h, db, monkeypatch):
    await h.send("/start")
    await h.send("➕ Добавить")
    calls = await h.click("📌 Событие")
    assert "Как назовём событие" in h.joined(calls)
    await h.send("Созвон")
    await h.click("Завтра")
    await h.click("18:00")
    await h.click("за 30 мин")
    await h.click("📌 Событие")
    ev = (await db.upcoming_events(USER_ID))[0]

    monkeypatch.setattr(events_handlers, "SNOOZE_UNIT_SEC", 0)
    calls = await h.press(EventCb(a="snooze", id=ev.id).pack(), text="📌 Скоро событие")
    assert any("Напомню" in a for a in h.alerts(calls))
    for _ in range(20):
        await asyncio.sleep(0)
        if not events_handlers._background:
            break
    reminders = [m for m, _ in h.session.calls if isinstance(m, SendMessage) and "Созвон" in m.text]
    assert reminders and isinstance(reminders[-1].reply_markup, InlineKeyboardMarkup)
    calls = await h.press(EventCb(a="ok", id=ev.id).pack(), text="📌 Скоро событие")
    assert any(isinstance(m, (EditMessageText, EditMessageReplyMarkup)) for m, _ in calls)


# ---------------------------------------------------------------- трекер

async def test_tracker_start_stop_rate_and_past(h, db):
    await h.send("/start")
    calls = await h.send("⏱ Трекер")
    assert "Трекер" in h.joined(calls)
    await h.click("📚 Учёба")
    current = await db.current_activity(USER_ID)
    assert current and current.category == "study" and current.source == "timer"
    calls = await h.click("⏹ Стоп")
    assert "Насколько продуктивно" in h.joined(calls)
    assert await db.current_activity(USER_ID) is None
    calls = await h.click("🤩 5")
    assert "5/5" in h.joined(calls)
    assert (await db.get_activity(current.id)).rating == 5

    await h.send("/track домашка по физике")
    current = await db.current_activity(USER_ID)
    assert current.category == "study" and current.description == "домашка по физике"
    await h.send("/track 🏃 пробежка")
    current = await db.current_activity(USER_ID)
    assert current.category == "sport" and current.description == "пробежка"
    calls = await h.send("/stop")
    assert "Записал" in h.joined(calls)
    await h.click("Пропустить")
    assert (await db.get_activity(current.id)).rating is None

    await h.send("⏱ Трекер")
    await h.click("➕ Прошедшее")
    await h.click("🍽 Еда")
    calls = await h.click("30м назад")
    assert "Сколько длилось" in h.joined(calls)
    await h.click("15м")
    start, end = now_utc() - timedelta(days=1), now_utc() + timedelta(minutes=1)
    manual = [a for a in await db.list_activities(USER_ID, start, end) if a.source == "manual"]
    assert len(manual) == 1 and manual[0].category == "food"
    assert round((manual[0].ended_at - manual[0].started_at).total_seconds() / 60) == 15


async def test_checkin_callbacks(h, db):
    await h.send("/start")
    calls = await h.press(CheckinCb(cat="study").pack(), text="👋 Что делаешь сейчас?")
    act = await db.current_activity(USER_ID)
    assert act and act.category == "study" and act.source == "checkin"
    assert any("Записываю" in t for t in h.texts(calls))
    calls = await h.press(CheckinCb(cat="same").pack(), text="👋 Что делаешь сейчас?")
    assert (await db.current_activity(USER_ID)).id == act.id
    assert any("Продолжа" in a for a in h.alerts(calls))
    await h.press(CheckinCb(cat="rest").pack(), text="👋 Что делаешь сейчас?")
    assert (await db.current_activity(USER_ID)).category == "rest"


# ---------------------------------------------------------------- статистика

async def test_stats_day_week_month(h, db):
    await h.send("/start")
    await h.send("/track учёба")
    calls = await h.send("/stats")
    assert "Статистика" in h.joined(calls) and "Сегодня" in h.joined(calls)
    calls = await h.click("Неделя")
    assert "Эта неделя" in h.joined(calls)
    calls = await h.click("◀️ Раньше")
    assert "Прошлая неделя" in h.joined(calls)
    calls = await h.click("Месяц")
    assert "Статистика" in h.joined(calls)
    calls = await h.send("📊 Статистика")
    assert "Статистика" in h.joined(calls)


# ---------------------------------------------------------------- расписание

async def test_week_and_lesson_wizard_and_delete(h, db):
    await h.send("/start")
    calls = await h.send("/week")
    assert "Расписание" in h.joined(calls)
    calls = await h.click("Следующая неделя ▶️")
    assert "Расписание" in h.joined(calls)
    await h.click("◀️ Эта неделя")

    await h.click("➕ Пара")
    calls = await h.click("Ср")
    assert "Время пары" in h.joined(calls)
    assert "Не понял время" in h.joined(await h.send("12:00"))
    calls = await h.send("12:00-13:30")
    assert "предмет" in h.joined(calls)
    await h.send("Физика")
    await h.click("лекция")
    await h.click("Пропустить →")
    calls = await h.click("Числитель (нечёт)")
    assert "Пара добавлена" in h.joined(calls)
    lessons = await db.list_lessons(USER_ID, weekday=2)
    phys = [l for l in lessons if l.subject == "Физика"]
    assert len(phys) == 1
    assert (phys[0].start_time, phys[0].end_time, phys[0].kind, phys[0].room, phys[0].parity) == \
        ("12:00", "13:30", "лекция", None, "odd")
    assert len(await db.list_lessons(USER_ID)) == 17

    # пара из существующих предметов кнопкой
    await h.click("➕ Ещё пара")
    await h.click("Сб")
    await h.click("09:00–10:30")   # слоты из существующих пар
    await h.click("Английский язык")
    await h.click("—")
    await h.click("1-301")
    await h.click("Каждую неделю")
    sat = await db.list_lessons(USER_ID, weekday=5)
    assert any(l.subject == "Английский язык" and l.room == "1-301" and l.kind == ""
               and (l.start_time, l.end_time) == ("09:00", "10:30") for l in sat)

    await h.click("🎓 Расписание")
    await h.click("🗑 Удалить пару")
    await h.click("Ср")
    await h.click("🗑 12:00 Физика")
    calls = await h.click("🗑 Да, удалить")
    assert not [l for l in await db.list_lessons(USER_ID) if l.subject == "Физика"]
    assert len(await db.list_lessons(USER_ID)) == 17


async def test_timetable_upload_needs_ai(h, db):
    await h.send("/start")
    await h.send("/week")
    calls = await h.click("📷 Загрузить")
    assert "ИИ" in h.joined(calls)
    calls = await h.send_photo()
    assert "только с ИИ" in h.joined(calls)


async def test_timetable_upload_photo_and_text_with_ai(h_ai, db):
    h = h_ai
    await h.send("/start")
    calls = await h.send_photo("ph-big")
    assert "Это расписание" in h.joined(calls)
    calls = await h.click("📷 Да, распознать расписание")
    assert h.ai.parsed and h.ai.parsed[-1][1].startswith(b"\xff\xd8")
    assert any(isinstance(m, GetFile) and m.file_id == "ph-big" for m, _ in calls)
    assert "Распознал расписание" in h.joined(calls) and "Матанализ" in h.joined(calls)
    await h.click("♻️ Заменить всё")
    lessons = await db.list_lessons(USER_ID)
    assert sorted(l.subject for l in lessons) == ["Матанализ", "Физика"]

    await h.send("/week")
    calls = await h.click("📷 Загрузить")
    assert "Загрузка расписания" in h.joined(calls)
    calls = await h.send("пн 09:00-10:30 Матанализ")
    assert h.ai.parsed[-1][0] == "пн 09:00-10:30 Матанализ"
    await h.click("➕ Добавить")
    assert len(await db.list_lessons(USER_ID)) == 4


# ---------------------------------------------------------------- настройки

async def test_settings_wake_time_and_timezone(h, db):
    await h.send("/start")
    assert (await h.user()).settings.tz_auto is True
    calls = await h.send("⚙️ Настройки")
    assert "Настройки" in h.joined(calls)
    await h.click("⏰ Подъём")
    await h.click("07:00")
    assert (await h.user()).settings.wake_time == "07:00"

    await h.click("⏰ Подъём")
    await h.click("✍️ Своё")
    assert "Не понял время" in h.joined(await h.send("25:99"))
    calls = await h.send("6:45")
    assert "Сохранено" in h.joined(calls)
    assert (await h.user()).settings.wake_time == "06:45"

    await h.click("🌍 Пояс")
    await h.click("Москва")
    s = (await h.user()).settings
    assert s.tz == "Europe/Moscow" and s.tz_auto is False

    await h.click("🌍 Пояс")
    await h.click("✍️ Другой пояс")
    await h.send("Europe/Berlin")
    s = (await h.user()).settings
    assert s.tz == "Europe/Berlin" and s.tz_auto is False

    await h.click("🔄 Автопояс")
    s = (await h.user()).settings
    assert s.tz_auto is True and s.tz in ("Asia/Shanghai", "Europe/Moscow")


async def test_settings_toggles_semester_and_now(h, db):
    await h.send("/start")
    await h.send("/settings")
    await h.click("Тихий:")
    assert (await h.user()).settings.quiet is True
    await h.click("Напоминания плана")
    assert (await h.user()).settings.plan_reminders is False
    await h.click("👋 Чек-ины")
    await h.click("3 ч")
    s = (await h.user()).settings
    assert s.checkin_enabled and s.checkin_interval_min == 180
    await h.click("🚌 Дорога")
    await h.click("45 мин")
    assert (await h.user()).settings.commute_min == 45
    await h.click("⚡ Пик")
    await h.click("🌙 Вечер")
    assert (await h.user()).settings.focus_peak == "evening"

    await h.click("📆 Начало сем.")
    await h.click("Эта неделя — чётная")
    s = (await h.user()).settings
    assert tt.week_parity(local_today(s.tz), s) == "even"
    await h.click("🏁 Конец сем.")
    await h.click("✍️ Ввести дату")
    calls = await h.send("01.01.2020")
    assert "раньше начала" in h.joined(calls)
    await h.send("30.06.2027")
    assert (await h.user()).settings.semester_end == "2027-06-30"

    calls = await h.click("☀️ Сводка сейчас")
    assert any("не запущены" in a for a in h.alerts(calls))
    await h.click("🤖 ИИ")
    assert (await h.user()).settings.ai_enabled is False


# ---------------------------------------------------------------- свободный текст и ИИ

async def test_fallback_text_without_ai_offers_task(h, db):
    await h.send("/start")
    calls = await h.send("купить молоко")
    assert "Записать?" in h.joined(calls) and "купить молоко" in h.joined(calls)
    calls = await h.click("➕ Сделать задачей")
    assert "купить молоко" in h.joined(calls)
    await h.click("💾 Сохранить")
    assert [t.title for t in await db.list_tasks(USER_ID)] == ["купить молоко"]

    await h.send("сходить в банк")
    await h.click("📌 Событием")
    await h.click("Послезавтра")
    await h.click("10:00")
    await h.click("за 10 мин")
    await h.click("📌 Событие")
    assert [e.title for e in await db.upcoming_events(USER_ID)] == ["сходить в банк"]


async def test_fallback_text_with_fake_ai(h_ai, db):
    h = h_ai
    await h.send("/start")
    calls = await h.send("курсач до пятницы")
    assert h.ai.chats == ["курсач до пятницы"]
    out = h.joined(calls)
    assert "записал <b>курсач</b>" in out and "<blockquote>" in out
    method, _ = h.last_screen()
    assert any("Сегодня" in b.text for b in kb.iter_buttons(method.reply_markup))

    h.ai.fail = True
    calls = await h.send("ещё вопрос")
    assert "ИИ сейчас не отвечает" in h.joined(calls)


async def test_ai_settings_buttons(h_ai, db):
    h = h_ai
    await h.send("/start")
    await db.add_ai_message(USER_ID, "user", "привет")
    await h.send("/ai")
    calls = await h.click("🧹 Очистить контекст")
    assert any("очищен" in a for a in h.alerts(calls))
    assert await db.get_ai_history(USER_ID) == []
    await h.click("⏸ Выключить ИИ")
    assert (await h.user()).settings.ai_enabled is False
    # с выключенным ИИ текст не уходит в ИИ
    await h.send("просто текст")
    assert h.ai.chats == []
    await h.send("/ai")
    await h.click("🤖 Включить ИИ")
    assert (await h.user()).settings.ai_enabled is True


async def test_wizard_states_beat_fallback_and_menu_beats_wizard(h_ai, db):
    h = h_ai
    await h.send("/start")
    await h.send("/event Тест")
    await h.click("Завтра")
    await h.click("18:00")
    # ждём кнопку напоминания: текст — подсказка, а не ИИ
    calls = await h.send("что-то")
    assert "жду выбор кнопкой" in h.joined(calls) and h.ai.chats == []
    # кнопка меню выходит из мастера
    calls = await h.send("✅ Задачи")
    assert "задач" in h.joined(calls).lower()
    await h.send("привет")
    assert h.ai.chats == ["привет"]
    # /cancel из мастера
    await h.send("➕ Добавить")
    calls = await h.send("/cancel")
    assert "Отменил" in h.joined(calls)
