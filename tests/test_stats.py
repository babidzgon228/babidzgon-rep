from datetime import date, datetime, timedelta, timezone

from bot.models import DayPlan, DayStats, PlanItem
from bot.services import stats

UTC = timezone.utc
D = date(2026, 11, 9)


def msk(h, m=0, d=D) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC) - timedelta(hours=3)


AFTER = msk(12, d=D + timedelta(days=1))     # день D уже закончился


async def test_activities_are_clipped_to_day_bounds(db, user):
    await db.add_activity(user.id, "sleep", msk(23, d=D - timedelta(days=1)), msk(7))
    await db.add_activity(user.id, "study", msk(22), msk(2, d=D + timedelta(days=1)))
    await db.add_activity(user.id, "rest", msk(10, d=D - timedelta(days=1)), msk(11, d=D - timedelta(days=1)))
    s = await stats.day_stats(db, user, D, now=AFTER)
    assert s.minutes_by_category == {"sleep": 420, "study": 120}
    assert s.tracked_min == 540
    assert s.productive_min == 120


async def test_running_activity_counts_until_now(db, user):
    await db.add_activity(user.id, "study", msk(8), msk(9), rating=5)
    await db.start_activity(user.id, "work", started_at=msk(10))
    s = await stats.day_stats(db, user, D, now=msk(10, 45))
    assert s.minutes_by_category == {"study": 60, "work": 45}
    assert s.tracked_min == 105
    # если день уже прошёл, текущая активность обрезается концом дня
    s2 = await stats.day_stats(db, user, D, now=AFTER)
    assert s2.minutes_by_category["work"] == 14 * 60


async def test_productive_rules_and_rating(db, user):
    await db.add_activity(user.id, "study", msk(9), msk(10), rating=2)     # продуктивная, но 50 %
    await db.add_activity(user.id, "rest", msk(10), msk(11), rating=5)     # отдых с оценкой 5 — продуктивно
    await db.add_activity(user.id, "sport", msk(11), msk(11, 30))          # спорт без оценки — 100 %
    await db.add_activity(user.id, "social", msk(12), msk(13), rating=3)   # не продуктивно
    s = await stats.day_stats(db, user, D, now=AFTER)
    assert s.productive_min == 30 + 60 + 30
    assert s.tracked_min == 210
    assert s.avg_rating == round((2 * 60 + 5 * 60 + 3 * 60) / 180, 2)


async def test_tasks_plan_and_lessons(db, user):
    t1 = await db.add_task(user.id, "a")
    t2 = await db.add_task(user.id, "b")
    t3 = await db.add_task(user.id, "c")
    await db.update_task(t1.id, status="done", done_at=msk(12))
    await db.update_task(t2.id, status="done", done_at=msk(23, d=D - timedelta(days=1)))  # вчера
    await db.add_lesson(user.id, 0, "09:00", "10:30", "Матан")
    await db.add_lesson(user.id, 0, "10:40", "12:10", "Физика")
    await db.add_lesson(user.id, 1, "09:00", "10:30", "Вторник")
    await db.save_plan(DayPlan(user_id=user.id, date=D, status="accepted", items=[
        PlanItem("07:30", "07:50", "meal", "Завтрак", done=True),
        PlanItem("09:00", "10:30", "lesson", "Матан", ref_id=1, done=True),
        PlanItem("11:00", "12:00", "task", "a", ref_id=t1.id, note="часть 1/2"),
        PlanItem("12:30", "13:30", "task", "a", ref_id=t1.id, note="часть 2/2", done=True),
        PlanItem("14:00", "15:00", "task", "c", ref_id=t3.id),
        PlanItem("15:00", "15:10", "break", "Перерыв", done=True),
    ]))
    s = await stats.day_stats(db, user, D, now=AFTER)
    assert s.tasks_done == 1
    assert s.plan_items_total == 4 and s.plan_items_done == 2
    assert s.tasks_planned == 2
    assert s.lessons_count == 2
    assert 0 <= s.focus_score <= 100


def test_focus_score_formula():
    full = DayStats(date=D, plan_items_total=4, plan_items_done=2, tracked_min=300, productive_min=240,
                    avg_rating=4.0, tasks_done=3)
    # план 0.5·40 + продуктивность (240/480)·30 + оценка 0.75·15 + задачи 1·15 = 61.25
    assert stats.compute_focus_score(full, 960) == 61
    assert stats.compute_focus_score(DayStats(date=D), 960) == 0
    # без плана и оценок вес делится между остальными компонентами
    only_tracker = DayStats(date=D, tracked_min=600, productive_min=480)
    assert stats.compute_focus_score(only_tracker, 960) == 100
    perfect = DayStats(date=D, plan_items_total=3, plan_items_done=3, tracked_min=600, productive_min=600,
                       avg_rating=5, tasks_done=5, tasks_planned=3)
    assert stats.compute_focus_score(perfect, 960) == 100


async def test_empty_day(db, user):
    s = await stats.day_stats(db, user, D, now=AFTER)
    assert s.tracked_min == 0 and s.minutes_by_category == {} and s.avg_rating is None
    assert s.focus_score == 0


async def test_period_stats(db, user):
    d1, d2, d3 = D, D + timedelta(days=1), D + timedelta(days=2)
    await db.add_activity(user.id, "study", msk(9, d=d1), msk(10, d=d1), rating=4)
    await db.add_activity(user.id, "study", msk(9, d=d2), msk(15, d=d2), rating=5)
    await db.add_activity(user.id, "rest", msk(16, d=d2), msk(17, d=d2), rating=2)
    now = msk(12, d=d3 + timedelta(days=1))
    p = await stats.period_stats(db, user, d1, d3, now=now)
    assert [s.date for s in p.days] == [d1, d2, d3]
    assert p.minutes_by_category == {"study": 420, "rest": 60}
    assert p.tracked_min == 480
    assert p.productive_min == 420
    assert p.best_day == d2
    day_scores = [s.focus_score for s in p.days[:2]]
    assert p.avg_focus_score == round(sum(day_scores) / 2)      # пустой d3 не тянет среднее вниз
    assert p.avg_rating is not None
    # перевёрнутый интервал тоже работает
    assert (await stats.period_stats(db, user, d3, d1, now=now)).tracked_min == 480


def test_awake_minutes_with_sleep_after_midnight():
    from bot.models import UserSettings

    night_owl = UserSettings(wake_time="08:30", sleep_time="00:30")
    assert stats.awake_minutes(night_owl, D, AFTER) == 16 * 60
    assert stats.awake_minutes(night_owl, D, msk(10, 30)) == 120          # сегодня — сколько прошло
    assert stats.awake_minutes(night_owl, D + timedelta(days=3), AFTER) == 0  # будущий день
    assert stats.awake_minutes(UserSettings(), D, AFTER) == 16 * 60
