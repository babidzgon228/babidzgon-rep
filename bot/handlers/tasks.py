"""«✅ Задачи», карточка задачи, редактирование кнопками, мастер «➕ Добавить», кнопки напоминаний о дедлайнах."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.chat_action import ChatActionSender

from bot.db import Database
from bot.handlers.common import (
    FreeText,
    MenuButton,
    ack,
    ai_active,
    chat_id_of,
    drop_markup,
    log,
    reply,
    safe_explain,
    safe_prioritize,
    safe_quadrant,
    safe_score,
)
from bot.handlers.common import show as show_screen
from bot.handlers.states import TaskEdit, TaskWizard
from bot.models import ENERGY_LEVELS, TASK_CATEGORIES, Task, User
from bot.services.prioritizer import QUADRANT_LABELS
from bot.timeutil import combine_local, day_bounds_utc, fmt_hhmm, local_now, local_today, now_utc, parse_iso, tz
from bot.ui import keyboards as kb
from bot.ui import texts
from bot.ui.callbacks import AddCb, DeadlineCb, NavCb, TaskCb, TaskFieldCb, TaskListCb
from bot.ui.parsing import match_category, parse_datetime

PAGE_SIZE = 8
QUADRANT_ORDER = ("do", "plan", "quick", "later")
ACTIVITY_TO_TASK_CATEGORY = {"study": "study", "work": "work", "sport": "health", "chores": "personal"}
DEADLINE_DAYS = {"today": 0, "tom": 1, "3d": 3, "week": 7}
DEADLINE_HINT = ("✍️ Напиши дедлайн: <i>12.11 18:00</i>, <i>завтра 10:00</i>, <i>пт</i>, <i>25.12</i>\n"
                 "<i>Без времени — до 23:59.</i>")


# ---------------------------------------------------------------- дедлайны

def preset_deadline(key: str, tz_name: str) -> datetime | None:
    if key not in DEADLINE_DAYS:
        return None
    d = local_today(tz_name) + timedelta(days=DEADLINE_DAYS[key])
    return combine_local(d, "23:59", tz_name).astimezone(timezone.utc)


def detect_deadline_key(deadline: datetime | None, tz_name: str) -> str | None:
    if deadline is None:
        return "none"
    for key in DEADLINE_DAYS:
        if preset_deadline(key, tz_name) == deadline.astimezone(timezone.utc):
            return key
    return "custom"


def _aware(dt: datetime, tz_name: str) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=tz(tz_name))


def _parse_ai_deadline(value: Any, tz_name: str) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value, tz_name)
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return _aware(dt, tz_name)
    return None


# ---------------------------------------------------------------- черновик

def new_draft(title: str) -> dict[str, Any]:
    draft: dict[str, Any] = {"title": title.strip()[:200], "importance": 2, "estimate_min": 30,
                             "energy": "medium", "category": "study", "deadline": None, "dl_key": "none"}
    cat, _ = match_category(title)
    if cat in ACTIVITY_TO_TASK_CATEGORY and cat != "other":
        draft["category"] = ACTIVITY_TO_TASK_CATEGORY[cat]
    return draft


def apply_suggestion(draft: dict[str, Any], sug: dict[str, Any] | None, tz_name: str) -> bool:
    """Применяет подсказку ИИ (с валидацией). True, если что-то поменялось."""
    if not sug:
        return False
    changed = False
    try:
        imp = int(sug.get("importance", 0))
        if 1 <= imp <= 3:
            draft["importance"], changed = imp, True
    except (TypeError, ValueError):
        pass
    try:
        est = int(sug.get("estimate_min", 0))
        if 5 <= est <= 24 * 60:
            draft["estimate_min"], changed = est, True
    except (TypeError, ValueError):
        pass
    if sug.get("energy") in ENERGY_LEVELS:
        draft["energy"], changed = sug["energy"], True
    if sug.get("category") in TASK_CATEGORIES:
        draft["category"], changed = sug["category"], True
    dl = _parse_ai_deadline(sug.get("deadline"), tz_name)
    if dl is not None:
        draft["deadline"] = dl.astimezone(timezone.utc).isoformat()
        draft["dl_key"] = detect_deadline_key(dl, tz_name)
        changed = True
    return changed


def draft_values(draft: dict[str, Any]) -> dict[str, Any]:
    """Черновик из FSM (JSON-friendly) -> значения для текстов/клавиатур."""
    values = dict(draft)
    values["deadline"] = parse_iso(draft.get("deadline")) if draft.get("deadline") else None
    return values


def draft_screen(draft: dict[str, Any], user: User, ai_used: bool) -> tuple[str, InlineKeyboardMarkup]:
    values = draft_values(draft)
    text = texts.task_draft(values, user.settings.tz, ai_used=ai_used)
    markup = kb.task_fields_keyboard(0, values, deadline_key=draft.get("dl_key"), draft=True)
    return text, markup


async def start_draft(target: Message | CallbackQuery, state: FSMContext, user: User, title: str,
                      ai=None, bot: Bot | None = None) -> None:
    """Создаёт черновик задачи и показывает карточку с переключателями (ИИ предзаполняет поля)."""
    draft = new_draft(title)
    ai_used = False
    if ai_active(ai, user):
        try:
            if bot is not None:
                async with ChatActionSender.typing(bot=bot, chat_id=chat_id_of(target)):
                    sug = await ai.suggest_task_fields(user, draft["title"])
            else:
                sug = await ai.suggest_task_fields(user, draft["title"])
            ai_used = apply_suggestion(draft, sug, user.settings.tz)
        except Exception:  # noqa: BLE001
            log.warning("suggest_task_fields failed", exc_info=True)
    await state.set_state(TaskWizard.card)
    await state.update_data(draft=draft, ai_used=ai_used)
    text, markup = draft_screen(draft, user, ai_used)
    await show_screen(target, text, markup)


def add_prompt() -> str:
    return "\n".join([texts.title("➕", "Что добавим?"), texts.SEP,
                      "✍️ Напиши <b>название задачи</b> — важность, срок и время настроим кнопками.",
                      "<i>Например: «Курсовая по экономике», «Сдать лабу по физике».</i>",
                      "",
                      "Или выбери событие / пару ⬇️"])


# ---------------------------------------------------------------- список задач

async def render_tasks(db: Database, user: User, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    now = now_utc()
    tz_name = user.settings.tz
    ordered = safe_prioritize(await db.list_tasks(user.id), now)
    entries = [(t, safe_score(t, now), safe_quadrant(t, now)) for t in ordered]
    entries.sort(key=lambda e: QUADRANT_ORDER.index(e[2]) if e[2] in QUADRANT_ORDER else 9)  # стабильно
    total = len(entries)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    chunk = entries[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    groups: list[tuple[str, list[tuple[int, Task, float | None]]]] = []
    ids: list[tuple[int, int]] = []
    for n, (task, score, quad) in enumerate(chunk, start=page * PAGE_SIZE + 1):
        label = QUADRANT_LABELS.get(quad, quad)
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append((n, task, score))
        ids.append((n, task.id))
    start, end = day_bounds_utc(local_today(tz_name), tz_name)
    done_today = len(await db.list_tasks_done_between(user.id, start, end))
    text = texts.task_list(groups, total=total, page=page, pages=pages, tz_name=tz_name, now=now,
                           done_today=done_today)
    return text, kb.task_list_keyboard(ids, page, pages)


async def _own_task(db: Database, user: User, task_id: int) -> Task | None:
    task = await db.get_task(task_id)
    return task if task and task.user_id == user.id else None


async def render_task(db: Database, user: User, task: Task, page: int = 0, *,
                      explain: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    now = now_utc()
    score = quad_label = None
    if task.status == "todo":
        score = safe_score(task, now)
        quad_label = QUADRANT_LABELS.get(safe_quadrant(task, now))
    explanation = safe_explain(task, now) if explain else None
    text = texts.task_card(task, user.settings.tz, now=now, score=score, quadrant_label=quad_label,
                           explanation=explanation)
    return text, kb.task_card_keyboard(task.id, page, done=task.status != "todo")


def render_edit(task: Task, user: User) -> tuple[str, InlineKeyboardMarkup]:
    values = dict(task.__dict__)
    text = texts.task_edit(task, user.settings.tz)
    markup = kb.task_fields_keyboard(task.id, values, deadline_key=detect_deadline_key(task.deadline, user.settings.tz),
                                     draft=False)
    return text, markup


# ---------------------------------------------------------------- хендлеры: меню/команды

async def menu_tasks(message: Message, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    text, markup = await render_tasks(db, user)
    await reply(message, text, markup)


async def menu_add(message: Message, user: User, state: FSMContext, ai=None, bot: Bot | None = None,
                   command: CommandObject | None = None) -> None:
    await state.clear()
    if command is not None and command.args and command.args.strip():
        await start_draft(message, state, user, command.args.strip(), ai=ai, bot=bot)
        return
    await state.set_state(TaskWizard.title)
    await reply(message, add_prompt(), kb.add_choice_keyboard())


async def nav_tasks(cq: CallbackQuery, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    await ack(cq)
    text, markup = await render_tasks(db, user)
    await show_screen(cq, text, markup)


async def nav_add(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(TaskWizard.title)
    await ack(cq)
    await show_screen(cq, add_prompt(), kb.add_choice_keyboard())


async def cb_add_choice(cq: CallbackQuery, callback_data: AddCb, db: Database, user: User,
                        state: FSMContext) -> None:
    kind = callback_data.kind
    if kind == "event":
        from bot.handlers.events import start_event_wizard
        await ack(cq)
        await start_event_wizard(cq, state, user)
        return
    if kind == "lesson":
        from bot.handlers.timetable import start_lesson_wizard
        await ack(cq)
        await start_lesson_wizard(cq, state, db, user)
        return
    await state.set_state(TaskWizard.title)
    await ack(cq, "✍️ Жду название задачи")


# ---------------------------------------------------------------- хендлеры: ввод текста в мастере

async def wizard_title(message: Message, user: User, state: FSMContext, ai=None, bot: Bot | None = None) -> None:
    await start_draft(message, state, user, message.text or "", ai=ai, bot=bot)


async def wizard_rename(message: Message, user: User, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("draft")
    if not draft:
        await state.clear()
        return
    draft["title"] = (message.text or "").strip()[:200]
    await state.update_data(draft=draft)
    text, markup = draft_screen(draft, user, bool(data.get("ai_used")))
    await reply(message, "✏️ Название обновил.\n\n" + text, markup)


async def wizard_deadline(message: Message, user: User, state: FSMContext) -> None:
    tz_name = user.settings.tz
    now_l = local_now(tz_name)
    parsed = parse_datetime(message.text, now_l.date(), fmt_hhmm(now_l))
    if not parsed:
        await reply(message, "🤔 Не понял дату.\n" + DEADLINE_HINT)
        return
    d, hhmm = parsed
    dl = combine_local(d, hhmm, tz_name).astimezone(timezone.utc)
    data = await state.get_data()
    draft = data.get("draft") or {}
    draft["deadline"], draft["dl_key"] = dl.isoformat(), "custom"
    await state.set_state(TaskWizard.card)
    await state.update_data(draft=draft)
    text, markup = draft_screen(draft, user, bool(data.get("ai_used")))
    await reply(message, text, markup)


async def edit_title_input(message: Message, db: Database, user: User, state: FSMContext) -> None:
    data = await state.get_data()
    task = await _own_task(db, user, int(data.get("edit_id") or 0))
    await state.clear()
    if not task:
        await reply(message, "Задача не найдена.")
        return
    task = await db.update_task(task.id, title=(message.text or "").strip()[:200])
    text, markup = render_edit(task, user)
    await reply(message, "✏️ Название обновил.\n\n" + text, markup)


async def edit_deadline_input(message: Message, db: Database, user: User, state: FSMContext) -> None:
    tz_name = user.settings.tz
    now_l = local_now(tz_name)
    parsed = parse_datetime(message.text, now_l.date(), fmt_hhmm(now_l))
    if not parsed:
        await reply(message, "🤔 Не понял дату.\n" + DEADLINE_HINT)
        return
    data = await state.get_data()
    task = await _own_task(db, user, int(data.get("edit_id") or 0))
    await state.clear()
    if not task:
        await reply(message, "Задача не найдена.")
        return
    d, hhmm = parsed
    task = await db.update_task(task.id, deadline=combine_local(d, hhmm, tz_name))
    text, markup = render_edit(task, user)
    await reply(message, text, markup)


# ---------------------------------------------------------------- хендлеры: колбэки задач

async def cb_task_list(cq: CallbackQuery, callback_data: TaskListCb, db: Database, user: User,
                       state: FSMContext) -> None:
    await state.clear()
    await ack(cq)
    text, markup = await render_tasks(db, user, callback_data.page)
    await show_screen(cq, text, markup)


async def cb_task(cq: CallbackQuery, callback_data: TaskCb, db: Database, user: User, state: FSMContext) -> None:
    a, page = callback_data.a, callback_data.page
    task = await _own_task(db, user, callback_data.id)
    if not task:
        await ack(cq, "Задача не найдена — возможно, уже удалена", alert=True)
        text, markup = await render_tasks(db, user, page)
        await show_screen(cq, text, markup)
        return

    if a == "view":
        await ack(cq)
        text, markup = await render_task(db, user, task, page)
        await show_screen(cq, text, markup)
    elif a == "why":
        await ack(cq)
        text, markup = await render_task(db, user, task, page, explain=True)
        await show_screen(cq, text, markup)
    elif a == "done":
        await db.complete_task(task.id)
        await ack(cq, "✅ Готово! Минус одна задача 💪")
        text, markup = await render_tasks(db, user, page)
        await show_screen(cq, text, markup)
    elif a == "undo":
        task = await db.update_task(task.id, status="todo", done_at=None)
        await ack(cq, "↩️ Вернул в работу")
        text, markup = await render_task(db, user, task, page)
        await show_screen(cq, text, markup)
    elif a == "tom":
        tomorrow = local_today(user.settings.tz) + timedelta(days=1)
        task = await db.update_task(task.id, planned_date=tomorrow)
        await ack(cq, "📅 Запланировал на завтра — попадёт в план")
        text, markup = await render_task(db, user, task, page)
        await show_screen(cq, text, markup)
    elif a == "edit":
        await state.clear()
        await ack(cq)
        text, markup = render_edit(task, user)
        await show_screen(cq, text, markup)
    elif a == "del":
        await ack(cq)
        text, _ = await render_task(db, user, task, page)
        await show_screen(cq, text + "\n\n🗑 <b>Удалить задачу?</b>", kb.task_delete_confirm(task.id, page))
    elif a == "delok":
        await db.delete_task(task.id)
        await ack(cq, "🗑 Удалено")
        text, markup = await render_tasks(db, user, page)
        await show_screen(cq, text, markup)
    else:
        await ack(cq)


async def cb_task_field(cq: CallbackQuery, callback_data: TaskFieldCb, db: Database, user: User,
                        state: FSMContext, ai=None) -> None:
    if callback_data.id == 0:
        await _draft_field(cq, callback_data, db, user, state)
    else:
        await _edit_field(cq, callback_data, db, user, state)


def _apply_field(values: dict[str, Any], f: str, v: str) -> bool:
    try:
        if f == "imp" and v in ("1", "2", "3"):
            values["importance"] = int(v)
        elif f == "est" and v.isdigit():
            values["estimate_min"] = int(v)
        elif f == "en" and v in ENERGY_LEVELS:
            values["energy"] = v
        elif f == "cat" and v in TASK_CATEGORIES:
            values["category"] = v
        else:
            return False
    except ValueError:
        return False
    return True


async def _draft_field(cq: CallbackQuery, cbd: TaskFieldCb, db: Database, user: User, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("draft")
    f, v = cbd.f, cbd.v
    if f == "cancel":
        await state.clear()
        await ack(cq, "Отменено")
        await show_screen(cq, "✖️ <i>Отменено.</i>")
        return
    if not draft:
        await ack(cq, "Черновик устарел — начни заново через «➕ Добавить»", alert=True)
        return
    tz_name = user.settings.tz
    if f == "save":
        deadline = parse_iso(draft.get("deadline")) if draft.get("deadline") else None
        task = await db.add_task(user.id, draft["title"] or "Без названия", importance=draft["importance"],
                                 deadline=deadline, estimate_min=draft["estimate_min"], energy=draft["energy"],
                                 category=draft["category"])
        await state.clear()
        await ack(cq, "💾 Сохранено")
        text, _ = await render_task(db, user, task)
        await show_screen(cq, "✅ <b>Задача добавлена</b>\n\n" + text, kb.task_saved_keyboard(task.id))
        return
    if f == "event":
        from bot.handlers.events import start_event_wizard
        await ack(cq)
        await start_event_wizard(cq, state, user, title=draft.get("title"))
        return
    if f == "title":
        await state.set_state(TaskWizard.card)
        await ack(cq, "✍️ Отправь новое название сообщением", alert=False)
        return
    if f == "dl":
        if v == "custom":
            await state.set_state(TaskWizard.deadline)
            await ack(cq)
            await show_screen(cq, f"📝 <b>{texts.esc(draft['title'])}</b>\n\n{DEADLINE_HINT}",
                              kb.kb([kb.btn("◀️ Назад", TaskFieldCb(id=0, f="back"))]))
            return
        dl = preset_deadline(v, tz_name)
        draft["deadline"] = dl.isoformat() if dl else None
        draft["dl_key"] = v if v in DEADLINE_DAYS else "none"
    elif f == "back":
        await state.set_state(TaskWizard.card)
    elif not _apply_field(draft, f, v):
        await ack(cq)
        return
    await state.update_data(draft=draft)
    await ack(cq)
    text, markup = draft_screen(draft, user, bool(data.get("ai_used")))
    await show_screen(cq, text, markup)


async def _edit_field(cq: CallbackQuery, cbd: TaskFieldCb, db: Database, user: User, state: FSMContext) -> None:
    task = await _own_task(db, user, cbd.id)
    if not task:
        await ack(cq, "Задача не найдена", alert=True)
        return
    f, v = cbd.f, cbd.v
    tz_name = user.settings.tz
    if f == "back":
        await state.clear()
        await ack(cq)
        text, markup = await render_task(db, user, task)
        await show_screen(cq, text, markup)
        return
    if f == "title":
        await state.set_state(TaskEdit.title)
        await state.update_data(edit_id=task.id)
        await ack(cq, "✍️ Отправь новое название сообщением")
        return
    if f == "dl":
        if v == "custom":
            await state.set_state(TaskEdit.deadline)
            await state.update_data(edit_id=task.id)
            await ack(cq)
            await show_screen(cq, f"📝 <b>{texts.esc(task.title)}</b>\n\n{DEADLINE_HINT}",
                              kb.kb([kb.btn("◀️ Назад", TaskCb(a="edit", id=task.id))]))
            return
        task = await db.update_task(task.id, deadline=preset_deadline(v, tz_name))
    else:
        values = dict(task.__dict__)
        if not _apply_field(values, f, v):
            await ack(cq)
            return
        field_name = {"imp": "importance", "est": "estimate_min", "en": "energy", "cat": "category"}[f]
        task = await db.update_task(task.id, **{field_name: values[field_name]})
    await ack(cq, "✓ Сохранено")
    text, markup = render_edit(task, user)
    await show_screen(cq, text, markup)


# ---------------------------------------------------------------- напоминания о дедлайнах

async def cb_deadline(cq: CallbackQuery, callback_data: DeadlineCb, db: Database, user: User) -> None:
    task = await _own_task(db, user, callback_data.id)
    if not task:
        await ack(cq, "Задача не найдена", alert=True)
        await drop_markup(cq)
        return
    if callback_data.a == "done":
        if task.status != "done":
            await db.complete_task(task.id)
        await ack(cq, "✅ Готово!")
        await drop_markup(cq, "✅ <i>Выполнено — отличная работа!</i>")
        return
    if callback_data.a == "tom":
        tz_name = user.settings.tz
        tomorrow = local_today(tz_name) + timedelta(days=1)
        changes: dict[str, Any] = {"planned_date": tomorrow}
        if task.deadline:
            new_dl = task.deadline + timedelta(days=1)
            changes["deadline"] = new_dl
        task = await db.update_task(task.id, **changes)
        when = texts.fmt_when(task.deadline, tz_name) if task.deadline else "завтра"
        await ack(cq, "📅 Перенёс на завтра")
        await drop_markup(cq, f"📅 <i>Перенёс: дедлайн {when}, задача в плане на завтра</i>")
        return
    await ack(cq)


def router() -> Router:
    r = Router(name="tasks")
    r.message.register(menu_tasks, MenuButton(kb.BTN_TASKS))
    r.message.register(menu_tasks, Command("tasks"))
    r.message.register(menu_add, MenuButton(kb.BTN_ADD))
    r.message.register(menu_add, Command("add"))
    r.callback_query.register(nav_tasks, NavCb.filter(F.to == "tasks"))
    r.callback_query.register(nav_add, NavCb.filter(F.to == "add"))
    r.callback_query.register(cb_add_choice, AddCb.filter())
    r.callback_query.register(cb_task_list, TaskListCb.filter())
    r.callback_query.register(cb_task, TaskCb.filter())
    r.callback_query.register(cb_task_field, TaskFieldCb.filter())
    r.callback_query.register(cb_deadline, DeadlineCb.filter())
    r.message.register(wizard_title, TaskWizard.title, FreeText())
    r.message.register(wizard_rename, TaskWizard.card, FreeText())
    r.message.register(wizard_deadline, TaskWizard.deadline, FreeText())
    r.message.register(edit_title_input, TaskEdit.title, FreeText())
    r.message.register(edit_deadline_input, TaskEdit.deadline, FreeText())
    return r
