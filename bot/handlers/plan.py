"""«📅 Сегодня», «🗓 Завтра», /plan: таймлайн, принятие плана, ИИ-улучшение, карточка-картинка,
отметки выполненного и кнопки напоминаний о блоках плана (▶️ Начать / ✅ Готово / ⏭ Пропустить)."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.chat_action import ChatActionSender

from bot.db import Database
from bot.handlers.common import (
    MenuButton,
    ack,
    ai_active,
    chat_id_of,
    drop_markup,
    log,
    reply,
    safe_prioritize,
    show,
)
from bot.models import DayPlan, User
from bot.services import planner
from bot.services import timetable as tt
from bot.timeutil import day_bounds_utc, local_now, local_today, now_utc
from bot.ui import cards
from bot.ui import keyboards as kb
from bot.ui import texts
from bot.ui.callbacks import NavCb, PlanCb, PlanItemCb, s2d

# категория трекера для блока плана
TASK_TO_ACTIVITY = {"study": "study", "work": "work", "personal": "chores", "health": "sport", "other": "other"}
KIND_TO_ACTIVITY = {"lesson": "study", "event": "social", "meal": "food", "break": "rest",
                    "buffer": "road", "routine": "other", "task": "study"}


# ---------------------------------------------------------------- рендер экранов

def _plan_header(d: date, today: date, user: User) -> str:
    rel = texts.fmt_day_rel(d, today)
    if rel == "сегодня":
        head = f"Сегодня · {texts.fmt_date(d)}"
        emoji = "📅"
    elif rel == "завтра":
        head = f"План на завтра · {texts.fmt_date(d)}"
        emoji = "🗓"
    else:
        head = f"План · {texts.fmt_date(d)}"
        emoji = "🗓"
    sub = []
    if not texts.in_semester(d, user.settings):
        sub.append("🏖 каникулы")
    else:
        wl = texts.week_label(d, user.settings)
        if wl:
            sub.append(wl)
    if user.settings.tz_auto:
        sub.append(f"📍 {texts.esc(texts.location(user.settings))}")
    return texts.title(emoji, head, " · ".join(sub) or None)


async def _tracker_line(db: Database, user: User) -> str:
    current = await db.current_activity(user.id)
    status = texts.activity_status(current, user.settings.tz)
    return f"\n\n<b>⏱ Трекер:</b> {status}" if status else ""


async def render_today(db: Database, user: User) -> tuple[str, InlineKeyboardMarkup]:
    tz_name = user.settings.tz
    today = local_today(tz_name)
    plan = await db.get_plan(user.id, today)
    header = _plan_header(today, today, user)
    if plan and plan.items:
        text = texts.day_plan(plan, header=header, now_local=local_now(tz_name))
    else:
        lessons = await tt.lessons_for_date(db, user, today)
        start, end = day_bounds_utc(today, tz_name)
        events = await db.list_events(user.id, start, end)
        top = safe_prioritize(await db.list_tasks(user.id), now_utc())[:3]
        text = texts.today_overview(today, lessons, events, top, tz_name, header=header,
                                    vacation=not texts.in_semester(today, user.settings))
    text += await _tracker_line(db, user)
    return text, kb.today_actions(today, plan)


def _should_rebuild(plan: DayPlan | None) -> bool:
    """Черновик без ИИ-правок дёшево перестроить (подтянет новые задачи); принятый — не трогаем."""
    return plan is None or (plan.status != "accepted" and not plan.ai_comment)


async def render_plan(db: Database, user: User, d: date, *, rebuild: bool | None = None
                      ) -> tuple[str, InlineKeyboardMarkup | None]:
    """Экран плана на день d (для сегодняшнего дня — экран «Сегодня»)."""
    today = local_today(user.settings.tz)
    plan = await db.get_plan(user.id, d)
    need = _should_rebuild(plan) if rebuild is None else rebuild
    if need:
        try:
            plan = await planner.build_plan(db, user, d)
        except Exception:  # noqa: BLE001
            log.exception("build_plan failed")
            if plan is None:
                return ("⚠️ <b>Не получилось составить план.</b>\n"
                        "<i>Попробуй ещё раз чуть позже.</i>"), kb.kb([kb.btn("🔄 Ещё раз", PlanCb(a="re", d=_ds(d)))])
    if d == today:
        return await render_today(db, user)
    assert plan is not None
    text = texts.day_plan(plan, header=_plan_header(d, today, user))
    return text, kb.plan_actions(d, plan.status)


def _ds(d: date) -> str:
    return d.strftime("%Y%m%d")


async def _get_or_build(db: Database, user: User, d: date) -> DayPlan | None:
    plan = await db.get_plan(user.id, d)
    if plan is None:
        try:
            plan = await planner.build_plan(db, user, d)
        except Exception:  # noqa: BLE001
            log.exception("build_plan failed")
            return None
    return plan


# ---------------------------------------------------------------- меню и команды

async def menu_today(message: Message, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    text, markup = await render_today(db, user)
    await reply(message, text, markup)


async def menu_tomorrow(message: Message, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    tomorrow = local_today(user.settings.tz) + timedelta(days=1)
    text, markup = await render_plan(db, user, tomorrow)
    await reply(message, text, markup)


async def cmd_plan(message: Message, command: CommandObject, db: Database, user: User,
                   state: FSMContext) -> None:
    await state.clear()
    today = local_today(user.settings.tz)
    arg = (command.args or "").strip().lower()
    d = today if arg in ("сегодня", "today", "0") else today + timedelta(days=1)
    text, markup = await render_plan(db, user, d)
    await reply(message, text, markup)


async def nav_day(cq: CallbackQuery, callback_data: NavCb, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    await ack(cq)
    if callback_data.to == "today":
        text, markup = await render_today(db, user)
    else:
        text, markup = await render_plan(db, user, local_today(user.settings.tz) + timedelta(days=1))
    await show(cq, text, markup)


# ---------------------------------------------------------------- кнопки плана

async def _send_card(cq: CallbackQuery, bot: Bot, user: User, plan: DayPlan) -> None:
    today = local_today(user.settings.tz)
    rel = texts.fmt_day_rel(plan.date, today)
    title = {"сегодня": "План на сегодня", "завтра": "План на завтра"}.get(rel, "План дня")
    subtitle = f"{texts.WEEKDAYS_FULL[plan.date.weekday()]}, {plan.date.day} {texts.MONTHS_GEN[plan.date.month - 1]}"
    if texts.in_semester(plan.date, user.settings):
        wl = texts.week_label(plan.date, user.settings)
        if wl:
            subtitle += f" · {wl}"
    else:
        subtitle += " · каникулы"
    chat_id = chat_id_of(cq)
    async with ChatActionSender.upload_photo(bot=bot, chat_id=chat_id):
        png = await asyncio.to_thread(cards.render_day_card, plan, title=title, subtitle=subtitle)
    caption = f"🖼 <b>{title}</b> · {texts.fmt_date(plan.date)}\n{texts.plan_summary(plan)}".rstrip()
    await bot.send_photo(chat_id, BufferedInputFile(png, filename=f"plan-{plan.date.isoformat()}.png"),
                         caption=caption, reply_markup=kb.after_card_keyboard(plan.date))


async def cb_plan(cq: CallbackQuery, callback_data: PlanCb, db: Database, user: User, bot: Bot,
                  ai=None) -> None:
    a = callback_data.a
    try:
        d = s2d(callback_data.d)
    except (ValueError, IndexError):
        await ack(cq, "Кнопка устарела", alert=True)
        return

    if a in ("show", "ref"):
        await ack(cq, "🔄 Обновлено" if a == "ref" else None)
        text, markup = await render_plan(db, user, d, rebuild=False)
        await show(cq, text, markup)
        return

    if a in ("re", "mk"):
        await ack(cq, "🧩 Составляю план…")
        text, markup = await render_plan(db, user, d, rebuild=True)
        await show(cq, text, markup)
        return

    if a == "acc":
        plan = await db.get_plan(user.id, d)
        if not plan:
            await ack(cq, "План не найден — нажми «Перестроить»", alert=True)
            return
        await db.set_plan_status(user.id, d, "accepted")
        reminders = "напомню о каждом блоке" if user.settings.plan_reminders and not user.settings.quiet \
            else "напоминания плана выключены в настройках"
        await ack(cq, f"✅ План принят — {reminders}")
        text, markup = await render_plan(db, user, d, rebuild=False)
        await show(cq, text, markup)
        return

    if a == "chk":
        plan = await db.get_plan(user.id, d)
        if not plan or not plan.items:
            await ack(cq, "Плана нет — сначала составь его", alert=True)
            return
        await ack(cq)
        text = texts.day_plan(plan, header=_plan_header(d, local_today(user.settings.tz), user))
        await show(cq, text + "\n\n<i>Отметь выполненное ⬇️</i>", kb.plan_checklist(plan))
        return

    if a == "img":
        await ack(cq, "🖼 Рисую карточку…")
        plan = await _get_or_build(db, user, d)
        if plan is None:
            await show(cq, "⚠️ Не получилось собрать план для картинки.", new=True)
            return
        try:
            await _send_card(cq, bot, user, plan)
        except Exception:  # noqa: BLE001
            log.exception("render_day_card failed")
            await show(cq, "⚠️ Не получилось нарисовать карточку. Попробуй позже.", new=True)
        return

    if a == "ai":
        if not ai_active(ai, user):
            reason = "в настройках выключен ИИ" if getattr(ai, "enabled", False) else "не задан ANTHROPIC_API_KEY"
            await ack(cq, f"🤖 ИИ недоступен: {reason}", alert=True)
            return
        await ack(cq, "🤖 Улучшаю план…")
        plan = await _get_or_build(db, user, d)
        if plan is None:
            await show(cq, "⚠️ Не получилось собрать план.", new=True)
            return
        try:
            lessons = await tt.lessons_for_date(db, user, d)
            start, end = day_bounds_utc(d, user.settings.tz)
            events = await db.list_events(user.id, start, end)
            tasks = await db.list_tasks(user.id)
            async with ChatActionSender.typing(bot=bot, chat_id=chat_id_of(cq)):
                improved = await ai.improve_plan(user, plan, lessons=lessons, events=events, tasks=tasks)
            if improved is not None and improved.items:
                await db.save_plan(improved)
        except Exception:  # noqa: BLE001
            log.exception("improve_plan failed")
            await show(cq, "⚠️ ИИ не смог улучшить план — оставил как было.", new=True)
            return
        text, markup = await render_plan(db, user, d, rebuild=False)
        await show(cq, text, markup)
        return

    await ack(cq)


# ---------------------------------------------------------------- блоки плана

async def _activity_for_item(db: Database, item) -> str:
    if item.kind == "task" and item.ref_id:
        task = await db.get_task(item.ref_id)
        if task:
            return TASK_TO_ACTIVITY.get(task.category, "other")
    return KIND_TO_ACTIVITY.get(item.kind, "other")


async def _set_item_done(db: Database, user: User, d: date, index: int, done: bool) -> DayPlan | None:
    plan = await db.mark_plan_item_done(user.id, d, index, done)
    if plan and 0 <= index < len(plan.items):
        item = plan.items[index]
        if item.kind == "task" and item.ref_id:
            task = await db.get_task(item.ref_id)
            if task and task.user_id == user.id:
                if done and task.status != "done":
                    await db.complete_task(task.id)
                elif not done and task.status == "done":
                    await db.update_task(task.id, status="todo", done_at=None)
    return plan


async def cb_plan_item(cq: CallbackQuery, callback_data: PlanItemCb, db: Database, user: User) -> None:
    try:
        d = s2d(callback_data.d)
    except (ValueError, IndexError):
        await ack(cq, "Кнопка устарела", alert=True)
        return
    i = callback_data.i
    plan = await db.get_plan(user.id, d)
    if not plan or not 0 <= i < len(plan.items):
        await ack(cq, "Этого блока уже нет в плане", alert=True)
        await drop_markup(cq)
        return
    item = plan.items[i]
    a = callback_data.a

    if a == "t":  # переключатель в чек-листе
        plan = await _set_item_done(db, user, d, i, not item.done)
        await ack(cq, "✅ Отмечено" if not item.done else "↩️ Снял отметку")
        if plan:
            text = texts.day_plan(plan, header=_plan_header(d, local_today(user.settings.tz), user))
            await show(cq, text + "\n\n<i>Отметь выполненное ⬇️</i>", kb.plan_checklist(plan))
        return

    if a == "start":
        cat = await _activity_for_item(db, item)
        await db.start_activity(user.id, cat, description=item.title, source="timer")
        label = texts.activity_label(cat)
        await ack(cq, f"▶️ Трекер: {label}")
        await drop_markup(cq, f"▶️ <i>Трекер запущен: {label}</i>")
        return

    if a == "done":
        await _set_item_done(db, user, d, i, True)
        await ack(cq, "✅ Готово!")
        await drop_markup(cq, "✅ <i>Готово! Так держать 💪</i>")
        return

    if a == "skip":
        await ack(cq, "⏭ Пропущено")
        await drop_markup(cq, "⏭ <i>Пропущено</i>")
        return

    await ack(cq)


def router() -> Router:
    r = Router(name="plan")
    r.message.register(menu_today, MenuButton(kb.BTN_TODAY))
    r.message.register(menu_today, Command("today"))
    r.message.register(menu_tomorrow, MenuButton(kb.BTN_TOMORROW))
    r.message.register(menu_tomorrow, Command("tomorrow"))
    r.message.register(cmd_plan, Command("plan"))
    r.callback_query.register(nav_day, NavCb.filter(F.to.in_({"today", "tomorrow"})))
    r.callback_query.register(cb_plan, PlanCb.filter())
    r.callback_query.register(cb_plan_item, PlanItemCb.filter())
    return r
