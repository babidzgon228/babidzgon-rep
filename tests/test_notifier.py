import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage

from bot.models import DayPlan, PlanItem
from bot.services import notifier as notifier_mod
from bot.services.notifier import Notifier
from bot.ui import keyboards, texts

UTC = timezone.utc
D = date(2026, 11, 9)       # понедельник


def msk(h, m=0, d=D) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC) - timedelta(hours=3)


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str, object]] = []
        self.error: Exception | None = None

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        if self.error is not None:
            raise self.error
        self.sent.append((chat_id, text, reply_markup))

    def texts(self, prefix=""):
        return [t for _, t, _ in self.sent if t.startswith(prefix)]

    def markups(self, prefix=""):
        return [m for _, t, m in self.sent if t.startswith(prefix)]


class FakeAI:
    def __init__(self, reply="Хороший день", fail=False):
        self.reply, self.fail, self.calls = reply, fail, 0

    @property
    def enabled(self):
        return True

    async def day_insight(self, user, stats, plan, activities):
        self.calls += 1
        if self.fail:
            raise RuntimeError("API down")
        return self.reply


@pytest.fixture(autouse=True)
def fake_ui(monkeypatch):
    """Функции ui.texts/keyboards пишет другой агент — подменяем простыми заглушками."""
    patches = {
        texts: {
            "morning_brief": lambda user, d, lessons, events, top, plan: f"MORNING {d} tasks={len(top)}",
            "day_report": lambda stats, ai_comment=None: f"REPORT {stats.date} ai={ai_comment}",
            "day_plan": lambda plan, header=None, now_local=None: f"PLAN {plan.date} {header}",
            "lesson_reminder": lambda lesson, minutes_left: f"LESSON {lesson.subject} {minutes_left}",
            "event_reminder": lambda event, minutes_left, tz_name: f"EVENT {event.title} {minutes_left}",
            "plan_item_reminder": lambda item: f"PLANITEM {item.title}",
            "deadline_reminder": lambda task, tz_name, hours_left: f"DEADLINE {task.title} {hours_left}",
            "checkin_prompt": lambda current, tz_name: f"CHECKIN {current.category if current else '-'}",
        },
        keyboards: {
            "main_menu": lambda: "KB-MAIN",
            "plan_actions": lambda d, status: f"KB-PLAN {d} {status}",
            "checkin_keyboard": lambda: "KB-CHECKIN",
            "plan_item_actions": lambda d, index, item: f"KB-ITEM {d} {index}",
            "event_reminder_actions": lambda event_id: f"KB-EVENT {event_id}",
            "deadline_actions": lambda task_id: f"KB-DL {task_id}",
        },
    }
    for module, funcs in patches.items():
        for name, fn in funcs.items():
            monkeypatch.setattr(module, name, fn)


@pytest.fixture
def bot():
    return FakeBot()


@pytest.fixture
def notifier(bot, db):
    return Notifier(bot, db)


@pytest.fixture
async def no_checkins(db, user):
    await db.update_settings(user.id, checkin_enabled=False)


# ---------------------------------------------------------------- сводки

async def test_morning_brief_once_with_plan(notifier, bot, db, user, no_checkins):
    await notifier.tick(msk(7, 44))
    assert bot.texts("MORNING") == []
    await notifier.tick(msk(7, 45))
    await notifier.tick(msk(7, 46))
    await notifier.tick(msk(8, 0))
    assert bot.texts("MORNING") == [f"MORNING {D} tasks=0"]
    # плана на сегодня не было — построен черновик и к сводке приложены кнопки плана
    assert bot.markups("MORNING") == [f"KB-PLAN {D} draft"]
    assert (await db.get_plan(user.id, D)).status == "draft"


async def test_morning_brief_skipped_after_long_downtime(notifier, bot, user, no_checkins):
    await notifier.tick(msk(9, 0))          # сводка была в 07:45 — больше часа назад
    assert bot.texts("MORNING") == []


async def test_morning_with_accepted_plan_uses_main_menu(notifier, bot, db, user, no_checkins):
    await db.save_plan(DayPlan(user_id=user.id, date=D, status="accepted",
                               items=[PlanItem("10:00", "11:00", "task", "X")]))
    await notifier.send_morning(user, now=msk(7, 45))
    assert bot.markups("MORNING") == ["KB-MAIN"]


async def test_evening_report_and_tomorrow_plan(bot, db, user, no_checkins):
    ai = FakeAI()
    n = Notifier(bot, db, ai=ai)
    await db.add_task(user.id, "Курсач", estimate_min=60)
    await n.tick(msk(21, 30))
    await n.tick(msk(21, 31))
    tomorrow = D + timedelta(days=1)
    assert bot.texts("REPORT") == [f"REPORT {D} ai=Хороший день"]
    assert bot.texts("PLAN") == [f"PLAN {tomorrow} План на завтра"]
    assert bot.markups("PLAN") == [f"KB-PLAN {tomorrow} draft"]
    assert [t.split()[0] for t in bot.texts()] == ["REPORT", "PLAN"]
    plan = await db.get_plan(user.id, tomorrow)
    assert plan.status == "draft" and any(i.kind == "task" for i in plan.items)
    assert ai.calls == 1


async def test_evening_survives_ai_failure_and_respects_ai_setting(bot, db, user, no_checkins):
    ai = FakeAI(fail=True)
    n = Notifier(bot, db, ai=ai)
    await n.send_evening(user, now=msk(21, 30))
    assert bot.texts("REPORT") == [f"REPORT {D} ai=None"]
    assert len(bot.texts("PLAN")) == 1

    await db.update_settings(user.id, ai_enabled=False)
    off = await db.get_user(user.id)
    ai2 = FakeAI()
    await Notifier(bot, db, ai=ai2).send_evening(off, now=msk(21, 30))
    assert ai2.calls == 0


async def test_evening_keeps_accepted_tomorrow_plan(notifier, bot, db, user):
    tomorrow = D + timedelta(days=1)
    items = [PlanItem("10:00", "11:00", "task", "Моё", ref_id=None)]
    await db.save_plan(DayPlan(user_id=user.id, date=tomorrow, status="accepted", items=items))
    await notifier.send_evening(user, now=msk(21, 30))
    plan = await db.get_plan(user.id, tomorrow)
    assert plan.status == "accepted" and plan.items == items
    assert bot.markups("PLAN") == [f"KB-PLAN {tomorrow} accepted"]


# ---------------------------------------------------------------- напоминания

async def test_lesson_reminder_once_and_catchup_window(notifier, bot, db, user, no_checkins):
    await db.add_lesson(user.id, 0, "09:00", "10:30", "Матан")
    await db.add_lesson(user.id, 0, "13:00", "14:30", "Физика")
    await db.add_lesson(user.id, 1, "09:00", "10:30", "Вторник")
    await notifier.tick(msk(8, 49))
    assert bot.texts("LESSON") == []
    await notifier.tick(msk(8, 50))
    await notifier.tick(msk(8, 53))
    await notifier.tick(msk(8, 59))
    assert bot.texts("LESSON") == ["LESSON Матан 10"]
    # бот «лежал» с 12:00 до 13:05 — о начавшейся паре не напоминаем
    await notifier.tick(msk(13, 5))
    assert bot.texts("LESSON") == ["LESSON Матан 10"]


async def test_event_reminder_with_keyboard_and_catchup(notifier, bot, db, user, no_checkins):
    ev = await db.add_event(user.id, "Встреча", msk(15), remind_before_min=30)
    late = await db.add_event(user.id, "Поздняя", msk(18), remind_before_min=60)
    await db.add_event(user.id, "Без напоминания", msk(16), remind_before_min=0)
    await notifier.tick(msk(14, 29))
    await notifier.tick(msk(14, 30))
    await notifier.tick(msk(14, 35))
    assert bot.texts("EVENT") == ["EVENT Встреча 30"]
    assert bot.markups("EVENT") == [f"KB-EVENT {ev.id}"]
    await notifier.tick(msk(15, 50))       # не напомнили в 15:00–15:10 → уже поздно (окно 10 мин)
    await notifier.tick(msk(17, 15))
    assert bot.texts("EVENT") == ["EVENT Встреча 30"]
    assert late.id                          # «Поздняя» пропущена из-за окна догонялки


async def test_plan_item_reminders(notifier, bot, db, user, no_checkins):
    task = await db.add_task(user.id, "Курсач")
    done_task = await db.add_task(user.id, "Готово")
    await db.complete_task(done_task.id)
    items = [PlanItem("09:00", "10:30", "lesson", "Матан", ref_id=1),
             PlanItem("11:00", "12:00", "task", "Курсач", ref_id=task.id),
             PlanItem("12:30", "13:00", "meal", "Обед"),
             PlanItem("14:00", "15:00", "task", "Готово", ref_id=done_task.id),
             PlanItem("16:00", "17:00", "task", "Отмечено", done=True)]
    await db.save_plan(DayPlan(user_id=user.id, date=D, status="draft", items=items))
    await notifier.tick(msk(11, 0))
    assert bot.texts("PLANITEM") == []       # черновик — не напоминаем

    await db.set_plan_status(user.id, D, "accepted")
    for t in (msk(11, 0), msk(11, 2), msk(12, 30), msk(14, 0), msk(16, 0), msk(9, 0)):
        await notifier.tick(t)
    assert bot.texts("PLANITEM") == ["PLANITEM Курсач"]
    assert bot.markups("PLANITEM") == [f"KB-ITEM {D} 1"]


async def test_plan_reminders_respect_quiet_and_setting(notifier, bot, db, user, no_checkins):
    items = [PlanItem("11:00", "12:00", "task", "A"), PlanItem("13:00", "14:00", "task", "B")]
    await db.save_plan(DayPlan(user_id=user.id, date=D, status="accepted", items=items))
    await db.update_settings(user.id, quiet=True)
    await notifier.tick(msk(11, 0))
    await db.update_settings(user.id, quiet=False, plan_reminders=False)
    await notifier.tick(msk(13, 0))
    assert bot.texts("PLANITEM") == []


async def test_deadline_reminders_24h_and_2h(notifier, bot, db, user, no_checkins):
    deadline = msk(18)
    task = await db.add_task(user.id, "Реферат", deadline=deadline)
    await db.add_task(user.id, "Без дедлайна")
    for t in (deadline - timedelta(hours=24, minutes=1), deadline - timedelta(hours=24),
              deadline - timedelta(hours=23, minutes=55), deadline - timedelta(hours=2),
              deadline - timedelta(hours=1, minutes=58), deadline - timedelta(minutes=30)):
        await notifier.tick(t)
    assert bot.texts("DEADLINE") == ["DEADLINE Реферат 24.0", "DEADLINE Реферат 2.0"]
    assert bot.markups("DEADLINE") == [f"KB-DL {task.id}"] * 2


async def test_deadline_reminder_not_for_done_task(notifier, bot, db, user, no_checkins):
    task = await db.add_task(user.id, "Сделано", deadline=msk(18))
    await db.complete_task(task.id)
    await notifier.tick(msk(16))
    assert bot.texts("DEADLINE") == []


# ---------------------------------------------------------------- чек-ины

async def test_checkin_interval(notifier, bot, user):
    await notifier.tick(msk(12, 0))
    await notifier.tick(msk(12, 30))
    await notifier.tick(msk(13, 59))
    assert bot.texts("CHECKIN") == ["CHECKIN -"]
    assert bot.markups("CHECKIN") == ["KB-CHECKIN"]
    await notifier.tick(msk(14, 0))
    assert bot.texts("CHECKIN") == ["CHECKIN -", "CHECKIN -"]


async def test_checkin_only_inside_waking_window(notifier, bot, user):
    await notifier.tick(msk(7, 50))      # подъём 07:30 → не раньше 08:00
    await notifier.tick(msk(23, 10))     # отбой 23:30 → не позже 23:00
    assert bot.texts("CHECKIN") == []
    await notifier.tick(msk(8, 0))
    assert bot.texts("CHECKIN") == ["CHECKIN -"]


async def test_checkin_not_during_lesson_or_event(notifier, bot, db, user):
    await db.add_lesson(user.id, 0, "12:00", "13:30", "Матан")
    await db.add_event(user.id, "Созвон", msk(15))                  # 15:00–16:00 (по умолчанию час)
    await db.update_settings(user.id, class_reminder_min=0)
    await notifier.tick(msk(12, 30))
    await notifier.tick(msk(15, 30))
    assert bot.texts("CHECKIN") == []
    await notifier.tick(msk(13, 30))
    assert bot.texts("CHECKIN") == ["CHECKIN -"]


async def test_checkin_quiet_and_disabled(notifier, bot, db, user):
    await db.update_settings(user.id, quiet=True)
    await notifier.tick(msk(12, 0))
    await db.update_settings(user.id, quiet=False, checkin_enabled=False)
    await notifier.tick(msk(13, 0))
    assert bot.texts("CHECKIN") == []


async def test_checkin_respects_activity(notifier, bot, db, user):
    await db.start_activity(user.id, "study", started_at=msk(11, 30))
    await notifier.tick(msk(12, 0))                 # активность началась 30 мин назад
    assert bot.texts("CHECKIN") == []
    await notifier.tick(msk(13, 31))                # идёт дольше интервала → «всё ещё …?»
    assert bot.texts("CHECKIN") == ["CHECKIN study"]

    await db.stop_activity(user.id, ended_at=msk(15))
    await notifier.tick(msk(15, 40))                # закончилась 40 мин назад
    assert bot.texts("CHECKIN") == ["CHECKIN study"]

    await db.start_activity(user.id, "sleep", started_at=msk(16))
    await notifier.tick(msk(19, 0))                 # спит — не будим
    assert bot.texts("CHECKIN") == ["CHECKIN study"]


# ---------------------------------------------------------------- надёжность

async def test_failing_builder_does_not_break_other_notifications(notifier, bot, db, user,
                                                                  no_checkins, monkeypatch):
    def boom(*args, **kwargs):
        raise NotImplementedError

    monkeypatch.setattr(texts, "lesson_reminder", boom)
    monkeypatch.setattr(keyboards, "event_reminder_actions", boom)
    await db.add_lesson(user.id, 0, "15:10", "16:40", "Матан")
    await db.add_event(user.id, "Встреча", msk(15, 30), remind_before_min=30)
    await notifier.tick(msk(15, 0))
    assert bot.texts("EVENT") == ["EVENT Встреча 30"]       # без клавиатуры, но отправлено
    assert bot.markups("EVENT") == [None]


async def test_telegram_errors_are_swallowed(notifier, bot, db, user, no_checkins):
    await db.add_event(user.id, "Встреча", msk(15), remind_before_min=30)
    bot.error = TelegramForbiddenError(method=SendMessage(chat_id=1, text="x"), message="blocked")
    await notifier.tick(msk(14, 30))
    bot.error = TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message="bad html")
    await notifier.send_morning(user, now=msk(7, 45))
    bot.error = RuntimeError("network")
    await notifier.send_evening(user, now=msk(21, 30))
    assert bot.sent == []


async def test_cleanup_once_per_day(notifier, db, user, no_checkins, monkeypatch):
    calls = []

    async def spy(older_than):
        calls.append(older_than)

    monkeypatch.setattr(db, "cleanup_sent", spy)
    await notifier.tick(msk(10))
    await notifier.tick(msk(11))
    await notifier.tick(msk(10, d=D + timedelta(days=1)))
    assert len(calls) == 2
    assert calls[0] == msk(10) - timedelta(days=14)


async def test_run_loop_survives_tick_errors_and_stops(db, monkeypatch):
    n = Notifier(FakeBot(), db, interval_sec=0.01)
    calls = 0

    async def flaky_tick(now=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        if calls >= 3:
            n.stop()

    monkeypatch.setattr(n, "tick", flaky_tick)
    await asyncio.wait_for(n.run(), timeout=2)
    assert calls == 3


async def test_tick_without_users_and_naive_now(notifier, bot):
    await notifier.tick(datetime(2026, 11, 9, 9, 0))          # naive → считается UTC
    await notifier.tick()
    assert bot.sent == []
    assert notifier_mod.CATCHUP == timedelta(minutes=10)


# ---------------------------------------------------------------- пояса и отбой после полуночи

async def test_tick_syncs_timezone_before_reminders(notifier, bot, db, user, no_checkins):
    await db.update_settings(user.id, tz_auto=True, home_tz="Europe/Moscow", tz="Europe/Moscow",
                             tz_rules=[{"from": "09-01", "to": "01-31", "tz": "Asia/Shanghai",
                                        "label": "Шэньчжэнь"}])
    await db.add_lesson(user.id, 0, "09:00", "10:30", "Английский язык")
    # 08:50 в Шэньчжэне = 00:50 UTC (в Москве в это время 03:50 — напоминать было бы не о чем)
    await notifier.tick(datetime(2026, 11, 9, 0, 50, tzinfo=UTC))
    assert (await db.get_user(user.id)).settings.tz == "Asia/Shanghai"
    assert bot.texts("LESSON") == ["LESSON Английский язык 10"]


async def test_checkin_window_crosses_midnight(notifier, bot, db, user):
    await db.update_settings(user.id, wake_time="08:30", sleep_time="00:30", checkin_interval_min=15)
    await notifier.tick(msk(23, 50))                        # окно до 00:00 — можно
    assert bot.texts("CHECKIN") == ["CHECKIN -"]
    await notifier.tick(msk(0, 5, d=D + timedelta(days=1)))   # после 00:00 — уже нет
    assert len(bot.texts("CHECKIN")) == 1

    await db.update_settings(user.id, sleep_time="01:30")   # отбой 01:30 → окно до 01:00
    await notifier.tick(msk(0, 25, d=D + timedelta(days=1)))
    assert len(bot.texts("CHECKIN")) == 2
    await notifier.tick(msk(1, 10, d=D + timedelta(days=1)))
    await notifier.tick(msk(8, 45, d=D + timedelta(days=1)))  # подъём 08:30 → с 09:00
    assert len(bot.texts("CHECKIN")) == 2
    await notifier.tick(msk(9, 0, d=D + timedelta(days=1)))
    assert len(bot.texts("CHECKIN")) == 3


async def test_evening_after_midnight_reports_previous_day(notifier, bot, db, user, no_checkins):
    await db.update_settings(user.id, wake_time="08:30", sleep_time="01:00", evening_plan_time="00:15")
    next_day = D + timedelta(days=1)
    await notifier.tick(msk(0, 15, d=next_day))
    assert bot.texts("REPORT") == [f"REPORT {D} ai=None"]
    assert bot.texts("PLAN") == [f"PLAN {next_day} План на завтра"]
    assert (await db.get_plan(user.id, next_day)).status == "draft"


async def test_real_profile_morning_and_evening_times(notifier, bot, db, user):
    await db.update_settings(user.id, tz="Asia/Shanghai", wake_time="08:30", sleep_time="00:30",
                             morning_brief_time="08:45", evening_plan_time="22:30", checkin_enabled=False)
    fri = date(2026, 11, 13)
    at = lambda h, m=0, d=fri: datetime(d.year, d.month, d.day, h, m, tzinfo=UTC) - timedelta(hours=8)  # noqa: E731
    await notifier.tick(at(8, 45))
    await notifier.tick(at(22, 30))
    assert bot.texts("MORNING") == [f"MORNING {fri} tasks=0"]
    assert bot.texts("PLAN") == [f"PLAN {fri + timedelta(days=1)} План на завтра"]
