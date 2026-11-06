from datetime import date, datetime, timedelta, timezone

from bot.models import Event, Lesson, PlanItem, Task, UserSettings
from bot.services import planner
from bot.services.planner import build_plan_items
from bot.timeutil import minutes_of

UTC = timezone.utc
D = date(2026, 11, 9)                                   # понедельник
EVENING_BEFORE = datetime(2026, 11, 8, 18, 0, tzinfo=UTC)  # 21:00 МСК накануне
FIXED_KINDS = {"lesson", "event", "buffer"}


def lesson(lid, start, end, subject="Пара", kind="лекция", room="305") -> Lesson:
    return Lesson(id=lid, user_id=1, weekday=0, start_time=start, end_time=end,
                  subject=subject, kind=kind, room=room)


def task(tid, est=60, **kw) -> Task:
    kw.setdefault("created_at", EVENING_BEFORE)
    return Task(id=tid, user_id=1, title=kw.pop("title", f"Задача {tid}"), estimate_min=est, **kw)


def msk(h, m=0, d=D) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC) - timedelta(hours=3)


def span(item: PlanItem) -> tuple[int, int]:
    return minutes_of(item.start), minutes_of(item.end)


def assert_valid(items: list[PlanItem]) -> None:
    starts = [minutes_of(i.start) for i in items]
    assert starts == sorted(starts), "план должен быть отсортирован"
    for i in items:
        s, e = span(i)
        assert s < e, i
    for a_idx, a in enumerate(items):
        for b in items[a_idx + 1:]:
            if a.kind in FIXED_KINDS and b.kind in FIXED_KINDS:
                continue
            (s1, e1), (s2, e2) = span(a), span(b)
            assert e1 <= s2 or e2 <= s1, f"пересечение: {a} и {b}"


def tasks_of(items, tid=None):
    return [i for i in items if i.kind == "task" and (tid is None or i.ref_id == tid)]


def test_lessons_are_fixed_blocks():
    lessons = [lesson(2, "10:40", "12:10", "Физика", "практика", "Б-2"),
               lesson(1, "09:00", "10:30", "Матан", "лекция", "305")]
    items = build_plan_items(D, UserSettings(), lessons, [], [task(1, 120)], EVENING_BEFORE)
    assert_valid(items)
    got = [(i.start, i.end, i.title, i.ref_id, i.note) for i in items if i.kind == "lesson"]
    assert got == [("09:00", "10:30", "Матан", 1, "лекция · ауд. 305"),
                   ("10:40", "12:10", "Физика", 2, "практика · Б-2")]


def test_busy_day_has_no_overlaps_and_breaks_between_chunks():
    lessons = [lesson(1, "09:00", "10:30"), lesson(2, "10:40", "12:10"), lesson(3, "14:00", "15:30")]
    events = [Event(id=7, user_id=1, title="Встреча", start_at=msk(19), location="кафе")]
    tasks = [task(1, 240, importance=3, deadline=msk(12, d=D + timedelta(days=3)), energy="high"),
             task(2, 15, importance=1, energy="low"),
             task(3, 60, importance=2, deadline=msk(23), energy="medium"),
             task(4, 120, importance=2, energy="low")]
    items = build_plan_items(D, UserSettings(commute_min=40), lessons, events, tasks, EVENING_BEFORE)
    assert_valid(items)
    ev = [i for i in items if i.kind == "event"]
    assert [(i.start, i.end, i.ref_id) for i in ev] == [("19:00", "20:00", 7)]   # без end_at → 60 мин
    for i in tasks_of(items):
        s, e = span(i)
        assert e - s <= planner.MAX_CHUNK
        assert e <= minutes_of("23:00")             # последние 30 мин — подготовка ко сну
    # между соседними кусками задач всегда перерыв
    for a, b in zip(items, items[1:]):
        assert not (a.kind == "task" and b.kind == "task"), (a, b)
    assert any(i.kind == "routine" and i.title == "Подготовка ко сну" and i.start == "23:00"
               for i in items)


def test_commute_buffers_and_pad_after_lessons():
    lessons = [lesson(1, "09:00", "10:30"), lesson(2, "10:40", "12:10")]
    items = build_plan_items(D, UserSettings(commute_min=30), lessons, [], [task(1, 300, energy="medium")],
                             EVENING_BEFORE)
    assert_valid(items)
    buffers = [(i.start, i.end, i.title) for i in items if i.kind == "buffer"]
    assert ("08:30", "09:00", "Дорога") in buffers
    assert ("12:10", "12:40", "Дорога домой") in buffers
    no_commute = build_plan_items(D, UserSettings(commute_min=0), lessons, [], [task(1, 300)], EVENING_BEFORE)
    assert not [i for i in no_commute if i.kind == "buffer"]
    # после пары — 10 минут без задач
    for i in tasks_of(no_commute):
        s, _ = span(i)
        assert not (minutes_of("10:30") <= s < minutes_of("10:40"))
        assert not (minutes_of("12:10") <= s < minutes_of("12:20"))


def test_tasks_today_never_in_the_past():
    now = msk(14, 3)                                   # 14:03 МСК → начинаем с 14:05
    lessons = [lesson(1, "09:00", "10:30")]
    tasks = [task(i, 60, importance=2) for i in range(1, 6)]
    items = build_plan_items(D, UserSettings(), lessons, [], tasks, now)
    assert_valid(items)
    assert any(i.kind == "lesson" for i in items)      # прошедшая пара остаётся в плане
    flexible = [i for i in items if i.kind not in FIXED_KINDS]
    assert flexible
    assert all(minutes_of(i.start) >= minutes_of("14:05") for i in flexible)
    assert min(minutes_of(i.start) for i in tasks_of(items)) == minutes_of("14:05")
    assert not any(i.title == "Завтрак" for i in items)


def test_past_day_has_no_flexible_blocks():
    items = build_plan_items(D, UserSettings(), [lesson(1, "09:00", "10:30")], [], [task(1)],
                             datetime(2026, 11, 10, 12, 0, tzinfo=UTC))
    assert [i.kind for i in items] == ["lesson"]


def test_long_task_is_split_into_parts():
    # горящая задача (дедлайн завтра) — ставится целиком: 240 = 80 + 80 + 80
    hot = task(1, 240, deadline=msk(12, d=D + timedelta(days=1)))
    items = build_plan_items(D, UserSettings(), [], [], [hot], EVENING_BEFORE)
    assert_valid(items)
    parts = tasks_of(items, 1)
    assert [i.note for i in parts] == ["часть 1/3", "часть 2/3", "часть 3/3"]
    assert sum(e - s for s, e in map(span, parts)) == 240
    assert all(e - s <= 90 for s, e in map(span, parts))
    for a, b in zip(parts, parts[1:]):
        gap = minutes_of(b.start) - minutes_of(a.end)
        assert gap >= 10
    assert any(i.kind == "break" for i in items)

    # не горящая — не больше 3 ч в день целыми частями, остальное — в другие дни
    calm = task(2, 240)
    parts = tasks_of(build_plan_items(D, UserSettings(), [], [], [calm], EVENING_BEFORE), 2)
    assert [i.note for i in parts] == ["часть 1/3", "часть 2/3"]
    assert sum(e - s for s, e in map(span, parts)) == 160


def test_energy_goes_to_peak_and_light_to_evening():
    tasks = [task(1, 60, energy="medium"), task(2, 60, energy="high"), task(3, 60, energy="low")]
    items = build_plan_items(D, UserSettings(focus_peak="morning"), [], [], tasks, EVENING_BEFORE)
    assert_valid(items)
    by_id = {i.ref_id: span(i) for i in tasks_of(items)}
    assert minutes_of("08:00") <= by_id[2][0] < minutes_of("12:00")     # сложная — в утренний пик
    assert by_id[3][0] >= minutes_of("20:00")                          # лёгкая — в конец дня
    assert not (minutes_of("08:00") <= by_id[1][0] < minutes_of("12:00"))  # средняя не занимает пик

    items = build_plan_items(D, UserSettings(focus_peak="evening"), [], [], [task(5, 60, energy="high")],
                             EVENING_BEFORE)
    (s, _), = [span(i) for i in tasks_of(items)]
    assert minutes_of("17:00") <= s < minutes_of("22:00")


def test_planned_date_and_deadline_today_go_first():
    # свободно только одно окно 10:10–11:10 (10:00–10:10 — буфер после пары)
    lessons = [lesson(1, "07:30", "10:00"), lesson(2, "11:10", "23:30")]
    important = task(1, 50, importance=3)
    pinned = task(2, 50, importance=1, planned_date=D)
    other_day = task(3, 20, importance=3, planned_date=D + timedelta(days=1))
    items = build_plan_items(D, UserSettings(), lessons, [], [important, pinned, other_day], EVENING_BEFORE)
    assert_valid(items)
    assert [i.ref_id for i in tasks_of(items)] == [2]

    # не сделанная задача, привязанная ко вчерашнему дню, переносится и идёт первой
    carried = task(5, 50, importance=1, planned_date=D - timedelta(days=1))
    items = build_plan_items(D, UserSettings(), lessons, [], [important, carried], EVENING_BEFORE)
    assert [i.ref_id for i in tasks_of(items)] == [5]

    due_today = task(4, 50, importance=1, deadline=msk(18))
    items = build_plan_items(D, UserSettings(), lessons, [], [important, due_today], EVENING_BEFORE)
    placed = tasks_of(items)
    assert [i.ref_id for i in placed] == [4]
    assert placed[0].note == "⏰ дедлайн в 18:00"


def test_empty_day_has_only_routine():
    items = build_plan_items(D, UserSettings(), [], [], [], EVENING_BEFORE)
    assert_valid(items)
    got = [(i.start, i.end, i.kind) for i in items]
    assert got == [("07:30", "07:50", "meal"), ("12:30", "13:05", "meal"),
                   ("18:30", "19:00", "meal"), ("23:00", "23:30", "routine")]


def test_day_without_free_windows():
    lessons = [lesson(1, "07:00", "12:30"), lesson(2, "12:40", "18:00"), lesson(3, "18:20", "23:40")]
    items = build_plan_items(D, UserSettings(), lessons, [], [task(1, 30), task(2, 15)], EVENING_BEFORE)
    assert_valid(items)
    assert [i.kind for i in items] == ["lesson", "lesson", "lesson"]


def test_small_gaps_are_not_used_for_tasks():
    # окна по 20 мин между парами (с учётом буфера 10 мин — по 10) — задачи не ставим
    lessons = [lesson(1, "07:30", "10:00"), lesson(2, "10:20", "12:00"), lesson(3, "12:20", "23:30")]
    items = build_plan_items(D, UserSettings(), lessons, [], [task(1, 15)], EVENING_BEFORE)
    assert not tasks_of(items)


def test_events_outside_window_and_overlapping_fixed_blocks_are_kept():
    lessons = [lesson(1, "09:00", "10:30")]
    events = [Event(id=1, user_id=1, title="Пробежка", start_at=msk(6), end_at=msk(6, 45)),
              Event(id=2, user_id=1, title="Созвон", start_at=msk(10), end_at=msk(11), kind="meeting")]
    items = build_plan_items(D, UserSettings(), lessons, events, [task(1, 60)], EVENING_BEFORE)
    assert_valid(items)
    ev = {i.ref_id: (i.start, i.end, i.note) for i in items if i.kind == "event"}
    assert ev[1] == ("06:00", "06:45", None)
    assert ev[2] == ("10:00", "11:00", "🤝 Встреча")
    assert any(i.kind == "lesson" and i.start == "09:00" for i in items)


def test_lunch_fits_into_long_break_between_lessons():
    lessons = [lesson(1, "10:40", "12:30"), lesson(2, "13:10", "14:40")]
    items = build_plan_items(D, UserSettings(), lessons, [], [], EVENING_BEFORE)
    lunch = [i for i in items if i.title == "Обед"]
    assert [(i.start, i.end) for i in lunch] == [("12:30", "13:05")]


def test_build_plan_items_is_deterministic():
    tasks = [task(i, 30 + 15 * i, importance=1 + i % 3) for i in range(1, 8)]
    a = build_plan_items(D, UserSettings(), [lesson(1, "09:00", "10:30")], [], tasks, EVENING_BEFORE)
    b = build_plan_items(D, UserSettings(), [lesson(1, "09:00", "10:30")], [], list(tasks), EVENING_BEFORE)
    assert a == b


async def test_build_plan_saves_draft(db, user):
    await db.add_lesson(user.id, 0, "09:00", "10:30", "Матан", kind="лекция", room="305")
    t = await db.add_task(user.id, "Курсач", estimate_min=60, importance=3)
    await db.add_event(user.id, "Встреча", msk(16), end_at=msk(17))
    await db.add_event(user.id, "Завтрашнее", msk(16, d=D + timedelta(days=1)))

    plan = await planner.build_plan(db, user, D, now=EVENING_BEFORE)
    assert plan.status == "draft"
    kinds = {i.kind for i in plan.items}
    assert {"lesson", "event", "task"} <= kinds
    assert [i.title for i in plan.items if i.kind == "event"] == ["Встреча"]
    assert [i.ref_id for i in plan.items if i.kind == "task"] == [t.id]
    saved = await db.get_plan(user.id, D)
    assert saved is not None and saved.items == plan.items

    # отметка о паре переживает перестройку, а статус снова draft
    lesson_idx = next(i for i, it in enumerate(saved.items) if it.kind == "lesson")
    await db.mark_plan_item_done(user.id, D, lesson_idx)
    await db.set_plan_status(user.id, D, "accepted")
    rebuilt = await planner.build_plan(db, user, D, now=EVENING_BEFORE)
    assert rebuilt.status == "draft"
    assert [i.done for i in rebuilt.items if i.kind == "lesson"] == [True]
    assert (await db.get_plan(user.id, D)).status == "draft"

    other = await planner.build_plan(db, user, D + timedelta(days=2), save=False, now=EVENING_BEFORE)
    assert await db.get_plan(user.id, D + timedelta(days=2)) is None
    assert other.items


# ---------------------------------------------------------------- отбой после полуночи и реальное расписание

def assert_hhmm(items):
    for i in items:
        for value in (i.start, i.end):
            h, m = map(int, value.split(":"))
            assert 0 <= h <= 23 and 0 <= m <= 59, i


def test_sleep_after_midnight():
    settings = UserSettings(wake_time="08:30", sleep_time="00:30")
    tasks = [task(1, 60, energy="low"), task(2, 90, energy="high"), task(3, 600, importance=3,
                                                                          deadline=msk(12, d=D + timedelta(days=1)))]
    items = build_plan_items(D, settings, [], [], tasks, EVENING_BEFORE)
    assert_valid(items)
    assert_hhmm(items)
    assert items[0].start == "08:30" and items[0].title == "Завтрак"
    assert items[-1].title == "Подготовка ко сну"
    assert (items[-1].start, items[-1].end) == ("23:30", "23:59")
    assert max(minutes_of(i.end) for i in tasks_of(items)) <= minutes_of("23:30")
    # вечер после 23:00 тоже рабочий (у обычного режима там уже подготовка ко сну)
    assert any(minutes_of(i.end) > minutes_of("23:00") for i in tasks_of(items))


def test_today_late_evening_for_night_owl():
    settings = UserSettings(wake_time="08:30", sleep_time="00:30")
    items = build_plan_items(D, settings, [], [], [task(1, 30), task(2, 60)], msk(23, 1))
    assert_hhmm(items)
    # окно 23:05–23:30: 30-минутная задача ужимается до 25 мин без «огрызка», часовая не влезает
    assert [(i.start, i.end, i.kind, i.ref_id, i.note) for i in items] == [
        ("23:05", "23:30", "task", 1, None), ("23:30", "23:59", "routine", None, None)]


def _real_profile():
    from pathlib import Path

    from bot.services import timetable

    path = Path(__file__).resolve().parent.parent / "data" / "timetable.yaml"
    meta, raw = timetable.load_timetable_file(path)
    if not raw:
        import pytest
        pytest.skip("нет data/timetable.yaml")
    settings = UserSettings.from_dict({**meta.get("settings", {}),
                                       "semester_start": str(meta.get("semester_start")),
                                       "semester_end": str(meta.get("semester_end"))})
    lessons = [Lesson(id=n, user_id=1, **x) for n, x in enumerate(raw, 1)]
    return settings, lessons


SHANGHAI_FRI = date(2026, 11, 13)
SHANGHAI_THU = date(2026, 11, 12)


def cst(h, m=0, d=SHANGHAI_FRI) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC) - timedelta(hours=8)


def test_real_timetable_friday_long_block():
    settings, all_lessons = _real_profile()
    lessons = [x for x in all_lessons if x.weekday == SHANGHAI_FRI.weekday()]
    tasks = [task(1, 120, importance=3, energy="high"), task(2, 45), task(3, 30, energy="low"),
             task(4, 60, importance=2, deadline=cst(23))]
    items = build_plan_items(SHANGHAI_FRI, settings, lessons, [], tasks, cst(21, d=SHANGHAI_THU))
    assert_valid(items)
    assert_hhmm(items)
    assert [(i.start, i.end) for i in items if i.kind == "lesson"] == [("09:00", "15:30"), ("15:45", "17:15")]
    assert not any(i.title == "Обед" for i in items)            # в пятницу обед не влезает — норм
    assert all(minutes_of(i.start) >= minutes_of("17:25") for i in tasks_of(items))
    assert {i.ref_id for i in tasks_of(items)} == {1, 2, 3, 4}
    assert any(i.title == "Ужин" for i in items)
    assert items[-1].title == "Подготовка ко сну" and items[-1].end == "23:59"


def test_real_timetable_thursday_gap_is_used():
    settings, all_lessons = _real_profile()
    lessons = [x for x in all_lessons if x.weekday == SHANGHAI_THU.weekday()]
    tasks = [task(1, 90, importance=3, energy="high"), task(2, 60)]
    items = build_plan_items(SHANGHAI_THU, settings, lessons, [], tasks, cst(21, d=SHANGHAI_THU - timedelta(days=1)))
    assert_valid(items)
    assert_hhmm(items)
    assert [i.start for i in items if i.kind == "lesson"] == ["09:00", "14:00", "18:00"]
    lunch = [i for i in items if i.title == "Обед"]
    assert len(lunch) == 1 and minutes_of("12:30") <= minutes_of(lunch[0].start) < minutes_of("14:00")
    first = tasks_of(items, 1)[0]                  # сложная — в утренний пик, после пары и буфера
    assert minutes_of("10:40") <= minutes_of(first.start) < minutes_of("12:00")


async def test_build_plan_with_real_profile_and_holidays(db, user):
    from bot.services import timetable

    settings, _ = _real_profile()
    meta, raw = timetable.load_timetable_file(
        __import__("pathlib").Path(__file__).resolve().parent.parent / "data" / "timetable.yaml")
    await timetable.apply_profile_settings(db, user, meta)
    await timetable.import_lessons(db, user.id, raw)
    user = await db.get_user(user.id)
    assert user.settings.sleep_time == settings.sleep_time

    plan = await planner.build_plan(db, user, SHANGHAI_FRI, now=cst(21, d=SHANGHAI_THU))
    assert [i.title for i in plan.items if i.kind == "lesson"] == ["Иванченко", "Чтение"]
    holiday = date(2027, 2, 5)                       # пятница после semester_end — каникулы
    plan = await planner.build_plan(db, user, holiday, save=False, now=cst(21, d=holiday - timedelta(days=1)))
    assert not [i for i in plan.items if i.kind == "lesson"]
