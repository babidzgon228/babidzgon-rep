"""Фоновые уведомления.

Каждые `interval_sec` секунд `tick()` проходит по всем пользователям и в их часовом поясе
проверяет, не пора ли что-то отправить:

    утренняя сводка       morning_brief_time                 (окно догонялки 60 мин)
    вечерний отчёт + план evening_plan_time                  (окно догонялки 60 мин)
    пара                  за class_reminder_min до начала    (≤ 0 — выключено)
    событие               за remind_before_min до начала     (≤ 0 — выключено)
    блок принятого плана  в момент начала (только task; plan_reminders и не quiet)
    дедлайн задачи        за 24 ч и за 2 ч
    чек-ин «что делаешь?» checkin_enabled и не quiet; wake+30мин..sleep−30мин (через полночь,
                          если отбой после 00:00); не во время пары
                          или события; не чаще checkin_interval_min с последнего чек-ина
                          или старта/конца активности; не во время сна

Перед проверками для каждого пользователя вызывается tzrules.sync_user_tz (автосмена пояса).
Дедупликация — `db.mark_sent(key)` до отправки. Окно догонялки: напоминание уходит,
только если now ∈ [due, due + 10 мин], чтобы после простоя бота не заваливать старьём
(для утренней/вечерней сводки окно 60 мин — пропустить план на завтра обиднее).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from bot.db import Database
from bot.models import Lesson, User
from bot.services import planner, prioritizer, stats as stats_service, timetable, tzrules
from bot.timeutil import (combine_local, day_bounds_utc, iso, minutes_of, now_utc, parse_iso,
                          to_local)
from bot.ui import keyboards, texts

log = logging.getLogger(__name__)

CATCHUP = timedelta(minutes=10)
DIGEST_CATCHUP = timedelta(minutes=60)
DEADLINE_OFFSETS_H = (24, 2)
EVENT_LOOKAHEAD = timedelta(days=8)       # события с напоминанием до недели вперёд
DEFAULT_EVENT_DURATION = timedelta(minutes=60)
CLEANUP_OLDER_THAN = timedelta(days=14)
CHECKIN_MARGIN = timedelta(minutes=30)
CHECKIN_MIN_INTERVAL_MIN = 15
STATE_LAST_CHECKIN = "notifier:last_checkin"
TOP_TASKS = 5
TOMORROW_HEADER = "План на завтра"


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _in_window(now: datetime, due: datetime, width: timedelta = CATCHUP) -> bool:
    return due <= now <= due + width


def _stamp(dt: datetime) -> str:
    return _utc(dt).strftime("%Y%m%dT%H%M")


@dataclass
class _Ctx:
    user: User
    now: datetime          # aware UTC
    local: datetime        # now в поясе пользователя
    today: date
    lessons: list[Lesson]

    @property
    def tz(self) -> str:
        return self.user.settings.tz


class Notifier:
    def __init__(self, bot: Bot, db: Database, ai=None, interval_sec: int = 30) -> None:
        self.bot, self.db, self.ai, self.interval_sec = bot, db, ai, interval_sec
        self._stopping = False
        self._wakeup = asyncio.Event()
        self._last_cleanup: date | None = None

    # ------------------------------------------------------------ цикл
    async def run(self) -> None:
        """Бесконечный цикл: tick() каждые interval_sec, пока не вызван stop()."""
        log.info("Notifier запущен (интервал %s с)", self.interval_sec)
        while not self._stopping:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("notifier: tick упал")
            if self._stopping:
                break
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=self.interval_sec)
            except asyncio.TimeoutError:
                pass
        log.info("Notifier остановлен")

    def stop(self) -> None:
        self._stopping = True
        self._wakeup.set()

    async def tick(self, now: datetime | None = None) -> None:
        """Один проход по всем пользователям (now — aware UTC; для тестов)."""
        now = _utc(now) if now else now_utc()
        await self._maybe_cleanup(now)
        for user in await self.db.list_users():
            try:
                await self._tick_user(user, now)
            except Exception:
                log.exception("notifier: ошибка для пользователя %s", user.id)

    async def _maybe_cleanup(self, now: datetime) -> None:
        if self._last_cleanup == now.date():
            return
        self._last_cleanup = now.date()
        try:
            await self.db.cleanup_sent(now - CLEANUP_OLDER_THAN)
        except Exception:
            log.exception("notifier: cleanup_sent упал")

    async def _tick_user(self, user: User, now: datetime) -> None:
        try:   # автосмена пояса (Шэньчжэнь ↔ Москва) — до любых расчётов времени
            await tzrules.sync_user_tz(self.db, user, now)
        except Exception:
            log.exception("notifier: sync_user_tz упал (пользователь %s)", user.id)
        local = to_local(now, user.settings.tz)
        lessons = await timetable.lessons_for_date(self.db, user, local.date())
        ctx = _Ctx(user=user, now=now, local=local, today=local.date(), lessons=lessons)
        for check in (self._check_morning, self._check_evening, self._check_lessons,
                      self._check_events, self._check_plan_items, self._check_deadlines,
                      self._check_checkin):
            try:
                await check(ctx)
            except Exception:
                log.exception("notifier: %s упал (пользователь %s)", check.__name__, user.id)

    # ------------------------------------------------------------ проверки
    async def _check_morning(self, ctx: _Ctx) -> None:
        due = combine_local(ctx.today, ctx.user.settings.morning_brief_time, ctx.tz)
        if _in_window(ctx.now, due, DIGEST_CATCHUP) and \
                await self.db.mark_sent(f"morning:{ctx.user.id}:{ctx.today}"):
            await self.send_morning(ctx.user, now=ctx.now)

    async def _check_evening(self, ctx: _Ctx) -> None:
        due = combine_local(ctx.today, ctx.user.settings.evening_plan_time, ctx.tz)
        if _in_window(ctx.now, due, DIGEST_CATCHUP) and \
                await self.db.mark_sent(f"evening:{ctx.user.id}:{ctx.today}"):
            await self.send_evening(ctx.user, now=ctx.now)

    async def _check_lessons(self, ctx: _Ctx) -> None:
        lead = int(ctx.user.settings.class_reminder_min or 0)
        if lead <= 0:
            return
        for lesson in ctx.lessons:
            start = combine_local(ctx.today, lesson.start_time, ctx.tz)
            if ctx.now >= start or not _in_window(ctx.now, start - timedelta(minutes=lead)):
                continue
            left = max(0, round((start - ctx.now).total_seconds() / 60))
            await self._emit(ctx.user, f"lesson:{ctx.user.id}:{ctx.today}:{lesson.id}",
                             lambda: texts.lesson_reminder(lesson, left))

    async def _check_events(self, ctx: _Ctx) -> None:
        events = await self.db.list_events(ctx.user.id, ctx.now, ctx.now + EVENT_LOOKAHEAD)
        for ev in events:
            lead = int(ev.remind_before_min or 0)
            if lead <= 0 or not _in_window(ctx.now, ev.start_at - timedelta(minutes=lead)):
                continue
            left = max(0, round((ev.start_at - ctx.now).total_seconds() / 60))
            await self._emit(ctx.user, f"event:{ctx.user.id}:{ev.id}:{_stamp(ev.start_at)}",
                             lambda: texts.event_reminder(ev, left, ctx.tz),
                             lambda: keyboards.event_reminder_actions(ev.id))

    async def _check_plan_items(self, ctx: _Ctx) -> None:
        s = ctx.user.settings
        if not s.plan_reminders or s.quiet:
            return
        plan = await self.db.get_plan(ctx.user.id, ctx.today)
        if not plan or plan.status != "accepted":
            return
        for index, item in enumerate(plan.items):
            if item.kind != "task" or item.done:
                continue
            start = combine_local(ctx.today, item.start, ctx.tz)
            if not _in_window(ctx.now, start):
                continue
            if item.ref_id is not None:
                task = await self.db.get_task(item.ref_id)
                if task is not None and task.status != "todo":
                    continue
            await self._emit(
                ctx.user, f"plan:{ctx.user.id}:{ctx.today}:{index}:{item.start}:{item.ref_id}",
                lambda: texts.plan_item_reminder(item),
                lambda: keyboards.plan_item_actions(ctx.today, index, item))

    async def _check_deadlines(self, ctx: _Ctx) -> None:
        for task in await self.db.list_tasks(ctx.user.id, status="todo"):
            if task.deadline is None or ctx.now >= task.deadline:
                continue
            for hours in DEADLINE_OFFSETS_H:
                if not _in_window(ctx.now, task.deadline - timedelta(hours=hours)):
                    continue
                hours_left = round((task.deadline - ctx.now).total_seconds() / 3600, 1)
                await self._emit(
                    ctx.user, f"deadline:{ctx.user.id}:{task.id}:{hours}h:{_stamp(task.deadline)}",
                    lambda: texts.deadline_reminder(task, ctx.tz, hours_left),
                    lambda: keyboards.deadline_actions(task.id))

    async def _check_checkin(self, ctx: _Ctx) -> None:
        s = ctx.user.settings
        if not s.checkin_enabled or s.quiet:
            return
        if not self._awake_window(ctx):
            return
        for lesson in ctx.lessons:
            if combine_local(ctx.today, lesson.start_time, ctx.tz) <= ctx.now \
                    < combine_local(ctx.today, lesson.end_time, ctx.tz):
                return
        day_start, day_end = day_bounds_utc(ctx.today, ctx.tz)
        for ev in await self.db.list_events(ctx.user.id, day_start - timedelta(hours=12), day_end):
            ev_end = ev.end_at if ev.end_at and ev.end_at > ev.start_at \
                else ev.start_at + DEFAULT_EVENT_DURATION
            if ev.start_at <= ctx.now < ev_end:
                return

        interval = timedelta(minutes=max(CHECKIN_MIN_INTERVAL_MIN, int(s.checkin_interval_min or 0)))
        last = parse_iso(await self.db.get_state(ctx.user.id, STATE_LAST_CHECKIN))
        if last and ctx.now - last < interval:
            return
        # недавно начатая или закончившаяся активность — не дёргаем
        for act in await self.db.list_activities(ctx.user.id, ctx.now - interval, ctx.now):
            if act.ended_at is not None or act.started_at > ctx.now - interval:
                return
        current = await self.db.current_activity(ctx.user.id)
        if current is not None and current.category == "sleep":
            return
        text = texts.checkin_prompt(current, ctx.tz)
        markup = self._markup(keyboards.checkin_keyboard)
        await self.db.set_state(ctx.user.id, STATE_LAST_CHECKIN, iso(ctx.now))
        await self._send(ctx.user, text, markup)

    @staticmethod
    def _awake_window(ctx: _Ctx) -> bool:
        """now ∈ [wake+30 мин, sleep−30 мин) — с учётом отбоя после полуночи
        (тогда окно «вчерашнего» дня продолжается после 00:00)."""
        s = ctx.user.settings
        for base in (ctx.today - timedelta(days=1), ctx.today):
            wake = combine_local(base, s.wake_time, ctx.tz)
            sleep = combine_local(base, s.sleep_time, ctx.tz)
            if sleep <= wake:
                sleep += timedelta(days=1)
            if wake + CHECKIN_MARGIN <= ctx.now < sleep - CHECKIN_MARGIN:
                return True
        return False

    @staticmethod
    def _logical_day(user: User, local: datetime) -> date:
        """«Текущий» день пользователя: до подъёма ещё идёт вчерашний (для отбоя после полуночи)."""
        try:
            before_wake = local.hour * 60 + local.minute < minutes_of(user.settings.wake_time)
        except Exception:
            before_wake = False
        return local.date() - timedelta(days=1) if before_wake else local.date()

    # ------------------------------------------------------------ сводки
    async def send_morning(self, user: User, *, now: datetime | None = None) -> None:
        """Утренняя сводка прямо сейчас."""
        now = _utc(now) if now else now_utc()
        tz_name = user.settings.tz
        local = to_local(now, tz_name)
        d = local.date()
        lessons = await timetable.lessons_for_date(self.db, user, d)
        start, end = day_bounds_utc(d, tz_name)
        events = await self.db.list_events(user.id, start, end)
        top = prioritizer.prioritize(await self.db.list_tasks(user.id, status="todo"), local)[:TOP_TASKS]
        plan = await self.db.get_plan(user.id, d)
        if plan is None:
            try:
                plan = await planner.build_plan(self.db, user, d, now=now)
            except Exception:
                log.exception("notifier: не удалось построить план на сегодня (%s)", user.id)
        text = texts.morning_brief(user, d, lessons, events, top, plan)
        if plan is not None and plan.status != "accepted" and plan.items:
            markup = self._markup(lambda: keyboards.plan_actions(d, plan.status))
        else:
            markup = self._markup(keyboards.main_menu)
        await self._send(user, text, markup)

    async def send_evening(self, user: User, *, now: datetime | None = None) -> None:
        """Вечерний отчёт за сегодня + черновик плана на завтра прямо сейчас."""
        now = _utc(now) if now else now_utc()
        tz_name = user.settings.tz
        d = self._logical_day(user, to_local(now, tz_name))   # в 00:40 отчёт ещё за «вчера»
        try:
            day = await stats_service.day_stats(self.db, user, d, now=now)
            comment = await self._ai_insight(user, d, day)
            await self._send(user, texts.day_report(day, comment))
        except Exception:
            log.exception("notifier: вечерний отчёт не удался (%s)", user.id)

        tomorrow = d + timedelta(days=1)
        try:
            plan = await self.db.get_plan(user.id, tomorrow)
            if plan is None or plan.status != "accepted":   # принятый план не затираем
                plan = await planner.build_plan(self.db, user, tomorrow, now=now)
            text = texts.day_plan(plan, header=TOMORROW_HEADER)
            await self._send(user, text, self._markup(lambda: keyboards.plan_actions(tomorrow, plan.status)))
        except Exception:
            log.exception("notifier: план на завтра не удался (%s)", user.id)

    async def _ai_insight(self, user: User, d: date, day) -> str | None:
        if self.ai is None or not getattr(self.ai, "enabled", False) or not user.settings.ai_enabled:
            return None
        try:
            plan = await self.db.get_plan(user.id, d)
            activities = await self.db.list_activities(user.id, *day_bounds_utc(d, user.settings.tz))
            return await self.ai.day_insight(user, day, plan, activities)
        except Exception:
            log.exception("notifier: ИИ-инсайт не удался (%s)", user.id)
            return None

    # ------------------------------------------------------------ отправка
    async def _emit(self, user: User, key: str, make_text: Callable[[], str],
                    make_markup: Callable[[], Any] | None = None) -> bool:
        """Отправить один раз по ключу: текст собирается до пометки, пометка — до отправки."""
        if await self.db.was_sent(key):
            return False
        text = make_text()
        markup = self._markup(make_markup)
        if not await self.db.mark_sent(key):
            return False
        return await self._send(user, text, markup)

    @staticmethod
    def _markup(make: Callable[[], Any] | None) -> Any:
        if make is None:
            return None
        try:
            return make()
        except Exception:
            log.warning("notifier: клавиатура не собралась, шлю без неё", exc_info=True)
            return None

    async def _send(self, user: User, text: str, markup: Any = None) -> bool:
        if not text:
            return False
        for attempt in range(2):
            try:
                await self.bot.send_message(user.chat_id, text, reply_markup=markup)
                return True
            except TelegramRetryAfter as e:
                if attempt:
                    log.warning("notifier: flood control для %s, сообщение пропущено", user.id)
                    return False
                await asyncio.sleep(min(float(e.retry_after), 30.0))
            except TelegramForbiddenError:
                log.warning("notifier: пользователь %s заблокировал бота", user.id)
                return False
            except TelegramBadRequest as e:
                log.warning("notifier: Telegram отклонил сообщение для %s: %s", user.id, e)
                return False
            except Exception:
                log.exception("notifier: не удалось отправить сообщение %s", user.id)
                return False
        return False
