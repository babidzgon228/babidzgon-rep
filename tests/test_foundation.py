"""Тесты фундамента: БД, расписание, часовые пояса."""
from datetime import date, datetime, timedelta, timezone

import pytest

from bot.models import DayPlan, PlanItem, UserSettings
from bot.services.timetable import (
    in_semester,
    lessons_for_date,
    load_timetable_file,
    normalize_lesson_dict,
    seed_from_file_if_empty,
    week_parity,
)
from bot.services.tzrules import location_label, resolve_tz, sync_user_tz
from bot.timeutil import day_bounds_utc, now_utc


async def test_tasks_crud(db, user):
    t = await db.add_task(user.id, "  Курсач ", importance=5, estimate_min=1,
                          deadline=now_utc() + timedelta(days=2))
    assert t.title == "Курсач" and t.importance == 3 and t.estimate_min == 5
    t = await db.update_task(t.id, planned_date=date(2026, 11, 7), energy="high")
    assert t.planned_date == date(2026, 11, 7) and t.energy == "high"
    await db.complete_task(t.id)
    assert (await db.get_task(t.id)).status == "done"
    assert await db.list_tasks(user.id) == []
    with pytest.raises(KeyError):
        await db.update_task(t.id, user_id=5)


async def test_activity_tracker(db, user):
    a = await db.start_activity(user.id, "study")
    b = await db.start_activity(user.id, "rest")  # автостоп предыдущей
    assert (await db.get_activity(a.id)).ended_at is not None
    assert (await db.current_activity(user.id)).id == b.id
    stopped = await db.stop_activity(user.id)
    assert stopped.id == b.id and await db.current_activity(user.id) is None
    start, end = day_bounds_utc(date.today(), "UTC")
    assert len(await db.list_activities(user.id, start - timedelta(days=1), end + timedelta(days=1))) == 2


async def test_plan_and_dedupe(db, user):
    d = date(2026, 11, 9)
    await db.save_plan(DayPlan(user.id, d, [PlanItem("10:00", "11:00", "task", "X", ref_id=1)]))
    plan = await db.mark_plan_item_done(user.id, d, 0)
    assert plan.items[0].done
    await db.set_plan_status(user.id, d, "accepted")
    assert (await db.get_plan(user.id, d)).status == "accepted"
    assert await db.mark_sent("k1") is True
    assert await db.mark_sent("k1") is False


def test_normalize_lesson():
    l = normalize_lesson_dict({"day": "Пн.", "time": "9.00–10.30", "subject": "Английский",
                               "room": "1-301", "weeks": "знаменатель"})
    assert l["weekday"] == 0 and l["start_time"] == "09:00" and l["end_time"] == "10:30"
    assert l["parity"] == "even" and l["room"] == "1-301"
    with pytest.raises(ValueError):
        normalize_lesson_dict({"day": "xx", "time": "9:00-10:00", "subject": "A"})


def test_week_parity_and_semester():
    s = UserSettings(semester_start="2026-09-01", semester_end="2027-01-31")
    assert week_parity(date(2026, 9, 1), s) == "odd"
    assert week_parity(date(2026, 9, 7), s) == "even"
    assert in_semester(date(2026, 11, 9), s)
    assert not in_semester(date(2026, 8, 31), s)
    assert not in_semester(date(2027, 2, 1), s)


async def test_real_timetable_file(db):
    meta, lessons = load_timetable_file("data/timetable.yaml")
    assert len(lessons) == 16
    u, _ = await db.get_or_create_user(7, 7, "T")
    assert await seed_from_file_if_empty(db, u, "data/timetable.yaml") == 16
    u = await db.get_user(7)
    assert u.settings.wake_time == "08:30" and u.settings.sleep_time == "00:30"
    assert u.settings.tz_auto and u.settings.semester_end == "2027-01-31"
    wed = await lessons_for_date(db, u, date(2026, 11, 11))
    assert [l.start_time for l in wed] == ["09:00", "10:45", "14:00", "15:45", "18:00"]
    assert await lessons_for_date(db, u, date(2026, 11, 14)) == []   # суббота
    assert await lessons_for_date(db, u, date(2027, 2, 8)) == []     # каникулы
    # повторный сид не дублирует
    assert await seed_from_file_if_empty(db, u, "data/timetable.yaml") == 0


@pytest.mark.parametrize("day,expected", [
    ("2026-11-06", "Asia/Shanghai"), ("2027-01-31", "Asia/Shanghai"), ("2027-02-01", "Europe/Moscow"),
    ("2027-03-01", "Asia/Shanghai"), ("2027-07-15", "Asia/Shanghai"), ("2027-07-16", "Europe/Moscow"),
])
def test_tz_rules(day, expected):
    s = UserSettings(tz_auto=True, home_tz="Europe/Moscow", tz_rules=[
        {"from": "09-01", "to": "01-31", "tz": "Asia/Shanghai", "label": "Шэньчжэнь"},
        {"from": "03-01", "to": "07-15", "tz": "Asia/Shanghai", "label": "Шэньчжэнь"}])
    at = datetime.fromisoformat(day + "T12:00:00+00:00")
    assert resolve_tz(s, at) == expected
    assert location_label(s, at) == ("Шэньчжэнь" if expected == "Asia/Shanghai" else "Москва")


async def test_sync_user_tz(db):
    u, _ = await db.get_or_create_user(8, 8, "T", default_settings=UserSettings(
        tz="Asia/Shanghai", tz_auto=True, tz_rules=[{"from": "09-01", "to": "01-31", "tz": "Asia/Shanghai"}]))
    assert await sync_user_tz(db, u, datetime(2026, 11, 6, tzinfo=timezone.utc)) is False
    assert await sync_user_tz(db, u, datetime(2027, 2, 10, tzinfo=timezone.utc)) is True
    assert (await db.get_user(8)).settings.tz == "Europe/Moscow"
