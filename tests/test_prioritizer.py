from datetime import date, datetime, timedelta, timezone

from bot.models import Task
from bot.services import prioritizer as pr

UTC = timezone.utc
NOW = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)


def task(tid=1, **kw) -> Task:
    kw.setdefault("created_at", NOW)
    kw.setdefault("title", f"t{tid}")
    return Task(id=tid, user_id=1, **kw)


def test_urgency_bounds_and_monotonic():
    assert pr.urgency(task(), NOW) == 0.0
    assert pr.urgency(task(deadline=NOW - timedelta(hours=1)), NOW) == 1.0
    far = pr.urgency(task(deadline=NOW + timedelta(days=7)), NOW)
    day = pr.urgency(task(deadline=NOW + timedelta(days=1)), NOW)
    soon = pr.urgency(task(deadline=NOW + timedelta(hours=6)), NOW)
    assert 0 < far < day < soon <= 1


def test_task_that_does_not_fit_gets_max_urgency():
    # 10 ч до дедлайна ≈ 4 ч рабочего времени, а нужно 5 ч → не влезает
    t = task(deadline=NOW + timedelta(hours=10), estimate_min=300)
    assert not pr.fits_in_time(t, NOW)
    assert pr.urgency(t, NOW) == 1.0
    # та же задача на 30 мин — влезает, срочность заметно ниже
    assert pr.urgency(task(deadline=NOW + timedelta(hours=10), estimate_min=30), NOW) < 0.8


def test_score_range_and_overdue_is_top():
    overdue = task(1, importance=2, deadline=NOW - timedelta(hours=3), estimate_min=60)
    important = task(2, importance=3, estimate_min=60)
    low = task(3, importance=1, estimate_min=120)
    for t in (overdue, important, low):
        assert 0 <= pr.score_task(t, NOW) <= 100
    assert pr.score_task(overdue, NOW) > pr.score_task(important, NOW) > pr.score_task(low, NOW)
    # максимум не превышается даже при всех бонусах
    maxed = task(4, importance=3, deadline=NOW - timedelta(days=1), estimate_min=10,
                 created_at=NOW - timedelta(days=30), planned_date=NOW.date())
    assert pr.score_task(maxed, NOW) == 100


def test_bonuses_quick_win_stale_planned():
    base = task(1, importance=2, estimate_min=120)
    assert pr.score_task(task(2, importance=2, estimate_min=15), NOW) > pr.score_task(base, NOW)
    stale = task(3, importance=2, estimate_min=120, created_at=NOW - timedelta(days=10))
    assert pr.score_task(stale, NOW) > pr.score_task(base, NOW)
    today = task(4, importance=2, estimate_min=120, planned_date=NOW.date())
    tomorrow = task(5, importance=2, estimate_min=120, planned_date=NOW.date() + timedelta(days=1))
    assert pr.score_task(today, NOW) > pr.score_task(tomorrow, NOW) > pr.score_task(base, NOW)


def test_prioritize_order_filters_and_is_stable():
    a = task(1, importance=1, estimate_min=120)
    b = task(2, importance=3, deadline=NOW + timedelta(hours=20), estimate_min=240)
    c = task(3, importance=3, estimate_min=120)
    done = task(4, importance=3, deadline=NOW, status="done")
    twin1 = task(5, importance=2, estimate_min=120)
    twin2 = task(6, importance=2, estimate_min=120)
    result = pr.prioritize([a, twin1, b, done, c, twin2], NOW)
    assert [t.id for t in result] == [2, 3, 5, 6, 1]


def test_quadrants():
    assert pr.quadrant(task(importance=3, deadline=NOW + timedelta(hours=10)), NOW) == "do"
    assert pr.quadrant(task(importance=3), NOW) == "plan"
    assert pr.quadrant(task(importance=3, deadline=NOW + timedelta(days=5)), NOW) == "plan"
    assert pr.quadrant(task(importance=1, deadline=NOW + timedelta(hours=5)), NOW) == "quick"
    assert pr.quadrant(task(importance=1), NOW) == "later"
    # дедлайн через 5 дней, но работы на 60 ч — не влезает → срочно
    huge = task(importance=1, deadline=NOW + timedelta(days=5), estimate_min=3600)
    assert pr.quadrant(huge, NOW) == "quick"
    # средняя важность становится важной при высоком score (просрочена)
    assert pr.quadrant(task(importance=2, deadline=NOW - timedelta(hours=1)), NOW) == "do"
    assert pr.quadrant(task(importance=2), NOW) == "later"
    assert set(pr.QUADRANT_LABELS) == {"do", "plan", "quick", "later"}


def test_explain_score_texts():
    text = pr.explain_score(task(importance=3, deadline=NOW + timedelta(hours=20), estimate_min=240), NOW)
    first = text.splitlines()[0]
    assert first == "Высокая важность · дедлайн через 20 ч · нужно ~4 ч"
    assert len(text.splitlines()) <= 2
    tight = pr.explain_score(task(importance=3, deadline=NOW + timedelta(hours=12), estimate_min=240), NOW)
    assert "впритык" in tight

    overdue = pr.explain_score(task(importance=1, deadline=NOW - timedelta(hours=5)), NOW)
    assert overdue.startswith("Низкая важность · просрочено на 5 ч")

    quick = pr.explain_score(task(importance=2, estimate_min=15, planned_date=NOW.date()), NOW)
    assert "без дедлайна" in quick and "быстрая победа" in quick and "на сегодня" in quick

    late = pr.explain_score(task(importance=2, deadline=NOW + timedelta(hours=3), estimate_min=180), NOW)
    assert "не успеваешь" in late


def test_planned_for():
    d = date(2026, 11, 9)
    assert pr.planned_for(task(), d)
    assert pr.planned_for(task(planned_date=d), d)
    assert pr.planned_for(task(planned_date=d - timedelta(days=1)), d)      # перенос
    assert not pr.planned_for(task(planned_date=d + timedelta(days=1)), d)
