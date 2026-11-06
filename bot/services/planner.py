"""Составление плана дня.

Алгоритм `build_plan_items` (чистая детерминированная функция, время — минуты от полуночи):

1. Окно дня: wake_time..sleep_time (отбой после полуночи, например "00:30", — окно до 24:00,
   «Подготовка ко сну» тогда 23:30–23:59). Если день d — сегодня (по поясу settings.tz), гибкие
   блоки ставятся не раньше `now`, округлённого вверх до 5 минут; прошедший день — без гибких блоков.
2. Фиксированные блоки (показываются всегда, даже вне окна): пары, события (без end_at — 60 мин),
   «Дорога» перед первой парой и «Дорога домой» после последней (если commute_min > 0).
3. Рутина в свободных местах: завтрак 20 мин сразу после подъёма, обед 30–35 мин в 12:30–14:30
   (подойдёт и длинный перерыв между парами), ужин 30 мин в 18:30–20:00, «Подготовка ко сну»
   в последние 30 минут перед сном. Нет места — блок пропускается.
4. Задачи по порядку: сначала привязанные к дню d и с дедлайном до конца d, затем остальные —
   по убыванию приоритета (prioritizer). Задачи, привязанные к более позднему дню, пропускаются;
   привязанные к прошедшему дню и не сделанные — переносятся (идут в первую группу).
   Каждая задача режется на куски ≤ 90 мин (поровну: 240 → 80+80+80), куски ставятся только в
   окна ≥ 25 мин, после пар — буфер 10 мин, между кусками задач — перерыв 10 мин (15 после куска
   ≥ 60 мин). Нетерпящая отлагательств задача (дедлайн/привязка к d или дедлайн до конца d+1)
   ставится целиком, остальные — не больше 3 ч в день («часть 1/3», продолжение — в другие дни).
   Куда ставить: дедлайн в этот день → как можно раньше; high → в пик продуктивности
   (focus_peak: morning 08–12, afternoon 12–17, evening 17–22); low → в последние 3 ч перед
   подготовкой ко сну; medium/low не занимают пик, пока в очереди есть сложные задачи.
5. Перерывы показываются между соседними кусками задач. Выход отсортирован; гибкие блоки
   не пересекаются ни с чем (фиксированные между собой могут пересекаться — как в исходных данных).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from bot.models import EVENT_KINDS, DayPlan, Event, Lesson, PlanItem, Task, User, UserSettings
from bot.services import prioritizer, timetable
from bot.timeutil import combine_local, day_bounds_utc, hhmm_of, minutes_of, now_utc, to_local

DAY_MIN = 24 * 60

MIN_WINDOW = 25              # в окна короче задачи не ставим
MAX_CHUNK = 90               # максимум работы подряд над одной задачей
BREAK_SHORT = 10             # перерыв после куска < 60 мин
BREAK_LONG = 15              # перерыв после куска ≥ 60 мин
LONG_CHUNK = 60
POST_LESSON_PAD = 10         # после пары не сразу садимся за задачи
BEDTIME_PREP = 30            # последние 30 мин перед сном — без задач
DEFAULT_EVENT_MIN = 60
MAX_TASK_MIN_PER_DAY = 180   # не горящая задача занимает не больше 3 ч в день
LOW_ENERGY_ZONE = 180        # «конец дня» для лёгких задач: последние 3 ч перед подготовкой ко сну
MERGE_TAIL = 15              # хвост короче 15 мин доклеиваем к куску (если не выйдет > 90)

BREAKFAST = ("Завтрак", 20, 20, 90)                  # title, min, max, окно поиска от подъёма
LUNCH = ("Обед", 30, 35, (12 * 60 + 30, 14 * 60 + 30))
DINNER = ("Ужин", 30, 30, (18 * 60 + 30, 20 * 60))
BEDTIME_TITLE = "Подготовка ко сну"
# Заголовки рутины — без эмодзи: ui.texts сам ставит значок по kind (🍽 ☕ 🚌 ✨)
BREAK_TITLE = "Перерыв"
COMMUTE_TITLE = "Дорога"
COMMUTE_BACK_TITLE = "Дорога домой"

PEAK_ZONES: dict[str, tuple[int, int]] = {
    "morning": (8 * 60, 12 * 60),
    "afternoon": (12 * 60, 17 * 60),
    "evening": (17 * 60, 22 * 60),
}

Interval = tuple[int, int]


@dataclass
class _Block:
    start: int
    end: int
    kind: str
    title: str
    ref_id: int | None = None
    note: str | None = None
    seq: int = 0

    def to_item(self) -> PlanItem:
        return PlanItem(start=hhmm_of(self.start), end=hhmm_of(self.end), kind=self.kind,
                        title=self.title, ref_id=self.ref_id, note=self.note)


# ---------------------------------------------------------------- интервалы

def _free(lo: int, hi: int, busy: list[Interval]) -> list[Interval]:
    """Свободные отрезки [lo, hi) за вычетом занятых."""
    if hi <= lo:
        return []
    result: list[Interval] = []
    cur = lo
    for s, e in sorted(busy):
        if e <= cur:
            continue
        if s >= hi:
            break
        if s > cur:
            result.append((cur, s))
        cur = max(cur, e)
        if cur >= hi:
            break
    if cur < hi:
        result.append((cur, hi))
    return result


def _ceil5(value: float) -> int:
    return int(math.ceil(value / 5 - 1e-9)) * 5


def _parse_min(value: str | None) -> int | None:
    try:
        return minutes_of(value)  # type: ignore[arg-type]
    except Exception:
        return None


def _minute_in_day(dt_local: datetime, d: date) -> int:
    if dt_local.date() < d:
        return 0
    if dt_local.date() > d:
        return DAY_MIN
    return dt_local.hour * 60 + dt_local.minute


def _floor_minute(d: date, now_local: datetime) -> int:
    """С какой минуты дня d можно ставить гибкие блоки."""
    if now_local.date() < d:
        return 0
    if now_local.date() > d:
        return DAY_MIN
    m = now_local.hour * 60 + now_local.minute
    if now_local.second or now_local.microsecond:
        m += 1
    return min(DAY_MIN, _ceil5(m))


def _lesson_note(lesson: Lesson) -> str | None:
    room = (lesson.room or "").strip()
    if room and room[0].isdigit():
        room = f"ауд. {room}"
    parts = [p for p in ((lesson.kind or "").strip(), room) if p]
    return " · ".join(parts) or None


def _event_note(event: Event) -> str | None:
    parts = []
    if event.kind and event.kind != "event" and event.kind in EVENT_KINDS:
        parts.append(EVENT_KINDS[event.kind])
    if event.location:
        parts.append(event.location)
    return " · ".join(parts) or None


def _choose_slot(free: list[Interval], want: int, prefer: Interval | None,
                 avoid: Interval | None) -> Interval | None:
    """Выбор окна для куска задачи. Возвращает (начало, предел) или None.

    Ярусы: окна в предпочтительной зоне → окна вне «запретной» зоны → любые.
    Внутри яруса — самое раннее окно, где кусок помещается целиком, иначе просто самое раннее.
    """
    tiers: list[list[Interval]] = []
    if prefer:
        zs, ze = prefer
        tier = []
        for a, b in free:
            s = max(a, zs)
            if s < ze and b - s >= MIN_WINDOW:
                tier.append((s, b))
        tiers.append(tier)
    if avoid:
        zs, ze = avoid
        tier = []
        for a, b in free:
            for x, y in ((a, min(b, zs)), (max(a, ze), b)):
                if y - x >= MIN_WINDOW:
                    tier.append((x, y))
        tiers.append(sorted(tier))
    tiers.append(free)
    for tier in tiers:
        if not tier:
            continue
        for s, limit in tier:
            if limit - s >= want:
                return s, limit
        return tier[0]
    return None


# ---------------------------------------------------------------- основной алгоритм

def build_plan_items(d: date, settings: UserSettings, lessons: list[Lesson], events: list[Event],
                     tasks: list[Task], now: datetime) -> list[PlanItem]:
    """ЧИСТАЯ функция (без БД): план дня d. Пары и события — фиксированные блоки,
    задачи раскладываются в свободные окна по приоритету. Отсортировано по start."""
    tz_name = settings.tz
    now_local = to_local(now, tz_name)
    floor = _floor_minute(d, now_local)

    wake = _parse_min(settings.wake_time)
    sleep = _parse_min(settings.sleep_time)
    wake = minutes_of("07:30") if wake is None else wake
    sleep = minutes_of("23:30") if sleep is None else sleep
    if sleep <= wake:
        # отбой после полуночи ("00:30") — это ещё тот же день: окно до 24:00,
        # подготовка ко сну показывается последним блоком 23:30–23:59
        day_end = DAY_MIN
        bedtime: Interval = (max(wake, DAY_MIN - BEDTIME_PREP), DAY_MIN)
    else:
        day_end = sleep
        bedtime = (max(wake, sleep - BEDTIME_PREP), sleep)
    tasks_hi = bedtime[0]
    lo = max(wake, floor)

    seq = iter(range(1_000_000))
    fixed: list[_Block] = []

    # --- пары
    lesson_blocks: list[_Block] = []
    for lesson in sorted(lessons, key=lambda x: (x.start_time, x.end_time)):
        s, e = _parse_min(lesson.start_time), _parse_min(lesson.end_time)
        if s is None or e is None:
            continue
        e = max(e, s + 5)
        block = _Block(s, e, "lesson", lesson.subject, lesson.id, _lesson_note(lesson), next(seq))
        lesson_blocks.append(block)
        fixed.append(block)

    # --- события
    event_busy: list[Interval] = []
    for ev in sorted(events, key=lambda x: x.start_at):
        st = to_local(ev.start_at, tz_name)
        if ev.end_at and ev.end_at > ev.start_at:
            en = to_local(ev.end_at, tz_name)
        else:
            en = st + timedelta(minutes=DEFAULT_EVENT_MIN)
        s, e = _minute_in_day(st, d), _minute_in_day(en, d)
        if s >= DAY_MIN or e <= 0:
            continue
        e = max(e, s + 5)
        fixed.append(_Block(s, e, "event", ev.title, ev.id, _event_note(ev), next(seq)))
        event_busy.append((s, e))

    # --- дорога до универа и обратно
    commute = max(0, int(settings.commute_min or 0))
    if lesson_blocks and commute:
        lesson_busy = [(b.start, b.end) for b in lesson_blocks]
        first = min(b.start for b in lesson_blocks)
        segs = _free(max(0, first - commute), first, event_busy)
        if segs and segs[-1][1] == first:
            fixed.append(_Block(segs[-1][0], first, "buffer", COMMUTE_TITLE, seq=next(seq)))
        last = max(b.end for b in lesson_blocks)
        segs = _free(last, min(DAY_MIN, last + commute), event_busy + lesson_busy)
        if segs and segs[0][0] == last:
            fixed.append(_Block(last, segs[0][1], "buffer", COMMUTE_BACK_TITLE, seq=next(seq)))

    fixed_busy = [(b.start, b.end) for b in fixed]
    flex: list[_Block] = []

    def busy_now() -> list[Interval]:
        return fixed_busy + [(b.start, b.end) for b in flex]

    # --- рутина
    def place_meal(title: str, min_len: int, max_len: int, win: Interval) -> None:
        for a, b in _free(max(lo, win[0]), min(win[1], day_end), busy_now()):
            if b - a >= min_len:
                flex.append(_Block(a, a + min(max_len, b - a), "meal", title, seq=next(seq)))
                return

    place_meal(BREAKFAST[0], BREAKFAST[1], BREAKFAST[2], (wake, wake + BREAKFAST[3]))
    place_meal(LUNCH[0], LUNCH[1], LUNCH[2], LUNCH[3])
    place_meal(DINNER[0], DINNER[1], DINNER[2], DINNER[3])
    segs = [x for x in _free(max(bedtime[0], floor), bedtime[1], busy_now()) if x[1] - x[0] >= 10]
    if segs:
        a, b = max(segs, key=lambda x: x[1] - x[0])
        flex.append(_Block(a, b, "routine", BEDTIME_TITLE, seq=next(seq)))

    # --- задачи
    _, end_of_d = day_bounds_utc(d, tz_name)
    _, end_of_next = day_bounds_utc(d + timedelta(days=1), tz_name)
    score_now = max(now_local, combine_local(d, hhmm_of(wake), tz_name))

    def pinned(t: Task) -> bool:     # привязана к d (или перенесена с прошлого дня) / горит в d
        return (t.planned_date is not None and t.planned_date <= d) or \
            (t.deadline is not None and t.deadline < end_of_d)

    queue = [t for t in prioritizer.prioritize(tasks, score_now) if prioritizer.planned_for(t, d)]
    queue.sort(key=lambda t: 0 if pinned(t) else 1)   # стабильно: внутри групп — по приоритету

    peak = PEAK_ZONES.get(settings.focus_peak, PEAK_ZONES["morning"])
    low_zone = (max(lo, tasks_hi - LOW_ENERGY_ZONE), tasks_hi)
    pad_busy = [(b.end, b.end + POST_LESSON_PAD) for b in lesson_blocks]
    reserved: list[Interval] = []      # куски задач вместе с перерывами вокруг
    task_blocks: list[_Block] = []

    for idx, task in enumerate(queue):
        need = max(5, int(task.estimate_min or 30))
        due_on_d = task.deadline is not None and task.deadline < end_of_d
        hot = pinned(task) or (task.deadline is not None and task.deadline < end_of_next)
        n_parts = max(1, math.ceil(need / MAX_CHUNK))
        part_len = min(MAX_CHUNK, _ceil5(need / n_parts))
        # не горящая задача — не больше 3 ч в день, причём целыми частями (без огрызков)
        cap = need if hot else min(need, max(part_len, MAX_TASK_MIN_PER_DAY // part_len * part_len))
        high_pending = any(t.energy == "high" for t in queue[idx + 1:])

        if due_on_d:
            prefer, avoid = None, None
        elif task.energy == "high":
            prefer, avoid = peak, None
        elif task.energy == "low":
            prefer, avoid = low_zone, (peak if high_pending else None)
        else:
            prefer, avoid = None, (peak if high_pending else None)

        chunks: list[Interval] = []
        remaining, planned = need, 0
        while remaining > 0 and planned < cap:
            want = min(part_len, remaining, cap - planned)
            if want < MIN_WINDOW and remaining > want:
                break
            tail = remaining - want
            if 0 < tail < MERGE_TAIL and want + tail <= MAX_CHUNK:
                want += tail
            free = [x for x in _free(lo, tasks_hi, busy_now() + pad_busy + reserved)
                    if x[1] - x[0] >= MIN_WINDOW]
            slot = _choose_slot(free, want, prefer, avoid)
            if slot is None:
                break
            s, limit = slot
            length = min(want, limit - s)
            chunks.append((s, s + length))
            rest = BREAK_LONG if length >= LONG_CHUNK else BREAK_SHORT
            reserved.append((s - BREAK_LONG, s + length + rest))
            if want == remaining and want - length < MERGE_TAIL:
                length = remaining     # не хватает < 15 мин на последний кусок — ужимаем, без огрызка
            remaining -= length
            planned += length

        if not chunks:
            continue
        total = len(chunks) + (math.ceil(remaining / part_len) if remaining > 0 else 0)
        deadline_note = None
        if task.deadline is not None and task.deadline < end_of_d:
            dl_local = to_local(task.deadline, tz_name)
            deadline_note = ("⏰ просрочено" if dl_local.date() < d or task.deadline <= now
                             else f"⏰ дедлайн в {hhmm_of(dl_local.hour * 60 + dl_local.minute)}")
        for i, (s, e) in enumerate(sorted(chunks), 1):
            notes = []
            if total > 1:
                notes.append(f"часть {i}/{total}")
            if deadline_note:
                notes.append(deadline_note)
            task_blocks.append(_Block(s, e, "task", task.title, task.id,
                                      " · ".join(notes) or None, next(seq)))

    # --- сборка + перерывы между соседними кусками задач
    blocks = sorted(fixed + flex + task_blocks, key=lambda b: (b.start, b.end, b.seq))
    breaks: list[_Block] = []
    for cur, nxt in zip(blocks, blocks[1:]):
        if cur.kind == "task" and nxt.kind == "task" and 0 < nxt.start - cur.end <= 20:
            breaks.append(_Block(cur.end, nxt.start, "break", BREAK_TITLE, seq=next(seq)))
    blocks = sorted(blocks + breaks, key=lambda b: (b.start, b.end, b.seq))
    return [b.to_item() for b in blocks]


async def build_plan(db, user: User, d: date, *, save: bool = True,
                     now: datetime | None = None) -> DayPlan:
    """Собирает данные из БД, строит план (status='draft'), по умолчанию сохраняет.

    Перестроенный план всегда снова 'draft'. Отметки «выполнено» у пар и событий из прежнего
    плана на этот день сохраняются (они не зависят от раскладки задач).
    """
    now = now or now_utc()
    lessons = await timetable.lessons_for_date(db, user, d)
    start, end = day_bounds_utc(d, user.settings.tz)
    events = await db.list_events(user.id, start, end)
    tasks = await db.list_tasks(user.id, status="todo")
    items = build_plan_items(d, user.settings, lessons, events, tasks, now)

    old = await db.get_plan(user.id, d)
    if old:
        done_fixed = {(i.kind, i.ref_id, i.start) for i in old.items
                      if i.done and i.kind in ("lesson", "event")}
        for item in items:
            if (item.kind, item.ref_id, item.start) in done_fixed:
                item.done = True

    plan = DayPlan(user_id=user.id, date=d, items=items, status="draft")
    if save:
        await db.save_plan(plan)
    return plan
