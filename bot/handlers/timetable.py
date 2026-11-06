"""«🎓 Расписание» и /week: неделя с чётностью, листание, мастер пары, удаление пары,
загрузка расписания фото/текстом через ИИ."""
from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.chat_action import ChatActionSender

from bot.db import Database
from bot.handlers.common import FreeText, MenuButton, ack, ai_active, chat_id_of, log, reply, show
from bot.handlers.states import LessonWizard, TimetableUpload
from bot.models import WEEKDAYS_FULL, Lesson, User
from bot.services import timetable as tt
from bot.timeutil import local_today
from bot.ui import keyboards as kb
from bot.ui import texts
from bot.ui.callbacks import LessonWizCb, NavCb, TtCb, s2t
from bot.ui.parsing import parse_time_range

MAX_WEEK_OFFSET = 52
MAX_SUBJECTS = 10
MAX_ROOMS = 8
KIND_LABELS = dict(kb.LESSON_KINDS)
TIME_HINT = "🕘 Время пары? Выбери или напиши: <i>08:30-10:00</i>"
SUBJECT_HINT = "📚 Какой предмет? Выбери или напиши название."
ROOM_HINT = "📍 Аудитория? Выбери, напиши или пропусти."
UPLOAD_PROMPT = "\n".join([
    texts.title("📷", "Загрузка расписания"), texts.SEP,
    "Пришли <b>фото</b> или скриншот расписания — или вставь его <b>текстом</b>.",
    "<i>Например: «пн 09:00-10:30 Матанализ, ауд. 1-301, числитель».</i>",
    "",
    "Покажу, что распознал, и спрошу, заменить ли текущее расписание.",
])
NO_AI_TEXT = "\n".join([
    texts.title("📷", "Загрузка расписания"), texts.SEP,
    "🤖 Распознавание фото и текста работает через ИИ, а он сейчас недоступен "
    "(нет ключа ANTHROPIC_API_KEY или ИИ выключен в настройках).",
    "Пары можно добавить вручную — кнопкой «➕ Добавить пару».",
])


# ---------------------------------------------------------------- неделя

async def render_week(db: Database, user: User, offset: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    offset = max(0, min(offset, MAX_WEEK_OFFSET))
    s = user.settings
    today = local_today(s.tz)
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    lessons = await db.list_lessons(user.id)
    days: dict[int, list[Lesson]] = {}
    study_days: set[int] = set()
    for wd in range(7):
        d = monday + timedelta(days=wd)
        if tt.in_semester(d, s):
            study_days.add(wd)
        parity = tt.week_parity(d, s)
        day_lessons = [l for l in lessons if l.weekday == wd and l.parity in ("all", parity)]
        if day_lessons:
            days[wd] = sorted(day_lessons, key=lambda l: l.start_time)
    text = texts.week_timetable(monday, days, parity=tt.week_parity(monday, s), week_no=tt.week_number(monday, s),
                                today=today, study_days=study_days)
    return text, kb.week_keyboard(offset)


async def menu_week(message: Message, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    text, markup = await render_week(db, user)
    await reply(message, text, markup)


async def nav_week(cq: CallbackQuery, db: Database, user: User, state: FSMContext) -> None:
    await state.clear()
    await ack(cq)
    text, markup = await render_week(db, user)
    await show(cq, text, markup)


# ---------------------------------------------------------------- мастер пары

def _draft(data: dict[str, Any]) -> dict[str, Any] | None:
    draft = data.get("lw")
    return draft if isinstance(draft, dict) else None


def _time_slots(lessons: list[Lesson]) -> list[str]:
    slots = sorted({f"{l.start_time}-{l.end_time}" for l in lessons})
    return slots[:8] if len(slots) >= 2 else list(kb.DEFAULT_SLOTS)


def _subjects(lessons: list[Lesson]) -> list[str]:
    return sorted({l.subject for l in lessons if l.subject})[:MAX_SUBJECTS]


def _rooms(lessons: list[Lesson], subject: str) -> list[str]:
    first = [l.room for l in lessons if l.room and l.subject == subject]
    rest = sorted(l.room for l in lessons if l.room and l.subject != subject)
    out: list[str] = []
    for r in first + rest:
        if r not in out:
            out.append(r)
    return out[:MAX_ROOMS]


async def start_lesson_wizard(target: Message | CallbackQuery, state: FSMContext, db: Database, user: User,
                              offset: int = 0) -> None:
    await state.clear()
    await state.set_state(LessonWizard.choose)
    await state.update_data(lw={"offset": offset})
    await show(target, texts.lesson_draft({}, "📅 В какой день пара?"),
               kb.lesson_day_keyboard(None, lambda wd: LessonWizCb(f="day", v=str(wd)), back=TtCb(a="w", o=offset)))


async def _ask_time(target: Message | CallbackQuery, state: FSMContext, db: Database, user: User,
                    draft: dict[str, Any], note: str = "") -> None:
    await state.set_state(LessonWizard.time)
    await state.update_data(lw=draft)
    slots = _time_slots(await db.list_lessons(user.id))
    await show(target, note + texts.lesson_draft(draft, TIME_HINT), kb.lesson_time_keyboard(slots))


async def _ask_subject(target: Message | CallbackQuery, state: FSMContext, db: Database, user: User,
                       draft: dict[str, Any]) -> None:
    subjects = _subjects(await db.list_lessons(user.id))
    draft["subjects"] = subjects
    await state.set_state(LessonWizard.subject)
    await state.update_data(lw=draft)
    await show(target, texts.lesson_draft(draft, SUBJECT_HINT), kb.lesson_subject_keyboard(subjects))


async def _ask_kind(target: Message | CallbackQuery, state: FSMContext, draft: dict[str, Any]) -> None:
    await state.set_state(LessonWizard.choose)
    await state.update_data(lw=draft)
    await show(target, texts.lesson_draft(draft, "🏷 Тип занятия?"), kb.lesson_kind_keyboard())


async def _ask_room(target: Message | CallbackQuery, state: FSMContext, db: Database, user: User,
                    draft: dict[str, Any]) -> None:
    rooms = _rooms(await db.list_lessons(user.id), draft.get("subject") or "")
    draft["rooms"] = rooms
    await state.set_state(LessonWizard.room)
    await state.update_data(lw=draft)
    await show(target, texts.lesson_draft(draft, ROOM_HINT), kb.lesson_room_keyboard(rooms))


async def _ask_parity(target: Message | CallbackQuery, state: FSMContext, draft: dict[str, Any]) -> None:
    await state.set_state(LessonWizard.choose)
    await state.update_data(lw=draft)
    await show(target, texts.lesson_draft(draft, "🔁 По каким неделям?"), kb.lesson_parity_keyboard())


async def _save_lesson(target: Message | CallbackQuery, state: FSMContext, db: Database, user: User,
                       draft: dict[str, Any], parity: str) -> None:
    lesson = await db.add_lesson(user.id, int(draft["weekday"]), draft["start_time"], draft["end_time"],
                                 draft["subject"], kind=draft.get("kind") or "", room=draft.get("room"),
                                 parity=parity if parity in ("all", "odd", "even") else "all")
    await state.clear()
    text = "\n".join(["✅ <b>Пара добавлена</b>", texts.SEP,
                      f"📅 {WEEKDAYS_FULL[lesson.weekday]}",
                      texts.lesson_line(lesson, show_parity=True)])
    await show(target, text, kb.lesson_saved_keyboard(int(draft.get("offset") or 0)))


async def wizard_time_input(message: Message, db: Database, user: User, state: FSMContext) -> None:
    draft = _draft(await state.get_data())
    if draft is None or draft.get("weekday") is None:
        await state.clear()
        await reply(message, "Мастер устарел — открой «🎓 Расписание» → «➕ Пара».")
        return
    rng = parse_time_range(message.text)
    if not rng:
        await reply(message, "🤔 Не понял время. Нужно начало и конец: <i>08:30-10:00</i>",
                    kb.lesson_time_keyboard(_time_slots(await db.list_lessons(user.id))))
        return
    draft["start_time"], draft["end_time"] = rng
    await _ask_subject(message, state, db, user, draft)


async def wizard_subject_input(message: Message, state: FSMContext) -> None:
    draft = _draft(await state.get_data())
    if draft is None or not draft.get("start_time"):
        await state.clear()
        await reply(message, "Мастер устарел — открой «🎓 Расписание» → «➕ Пара».")
        return
    draft["subject"] = (message.text or "").strip()[:120]
    await _ask_kind(message, state, draft)


async def wizard_room_input(message: Message, state: FSMContext) -> None:
    draft = _draft(await state.get_data())
    if draft is None or not draft.get("subject"):
        await state.clear()
        await reply(message, "Мастер устарел — открой «🎓 Расписание» → «➕ Пара».")
        return
    room = (message.text or "").strip()[:40]
    draft["room"] = None if room in ("-", "—", "нет") else room
    await _ask_parity(message, state, draft)


async def cb_lesson_wizard(cq: CallbackQuery, callback_data: LessonWizCb, db: Database, user: User,
                           state: FSMContext) -> None:
    f, v = callback_data.f, callback_data.v
    draft = _draft(await state.get_data())
    if f == "cancel":
        await state.clear()
        await ack(cq, "Отменено")
        offset = int((draft or {}).get("offset") or 0)
        text, markup = await render_week(db, user, offset)
        await show(cq, text, markup)
        return
    if draft is None:
        await ack(cq, "Мастер устарел — начни заново: «➕ Пара»", alert=True)
        return
    if f == "day" and v.isdigit() and 0 <= int(v) <= 6:
        draft["weekday"] = int(v)
        await ack(cq)
        await _ask_time(cq, state, db, user, draft)
    elif f == "time" and draft.get("weekday") is not None:
        parts = v.split("-")
        rng = parse_time_range(f"{s2t(parts[0])}-{s2t(parts[1])}") if len(parts) == 2 else None
        if not rng:
            await ack(cq)
            return
        draft["start_time"], draft["end_time"] = rng
        await ack(cq)
        await _ask_subject(cq, state, db, user, draft)
    elif f == "subj" and draft.get("start_time"):
        subjects = draft.get("subjects") or []
        if not v.isdigit() or int(v) >= len(subjects):
            await ack(cq)
            return
        draft["subject"] = subjects[int(v)]
        await ack(cq)
        await _ask_kind(cq, state, draft)
    elif f == "kind" and draft.get("subject"):
        draft["kind"] = "" if v == "none" else KIND_LABELS.get(v, "")
        await ack(cq)
        await _ask_room(cq, state, db, user, draft)
    elif f == "room" and draft.get("subject"):
        rooms = draft.get("rooms") or []
        if v == "-":
            draft["room"] = None
        elif v.isdigit() and int(v) < len(rooms):
            draft["room"] = rooms[int(v)]
        else:
            await ack(cq)
            return
        await ack(cq)
        await _ask_parity(cq, state, draft)
    elif f == "par" and draft.get("subject") and draft.get("start_time"):
        await ack(cq, "💾 Сохранено")
        await _save_lesson(cq, state, db, user, draft, v)
    else:
        await ack(cq)


# ---------------------------------------------------------------- удаление пары

async def _day_delete_screen(cq: CallbackQuery, db: Database, user: User, day: int, offset: int) -> None:
    lessons = await db.list_lessons(user.id, weekday=day)
    if not lessons:
        await _delete_days_screen(cq, db, user, offset)
        return
    lines = [texts.title("🗑", f"Удалить пару · {WEEKDAYS_FULL[day]}"), texts.SEP]
    lines.extend(texts.lesson_line(l, show_parity=True) for l in lessons)
    lines.append("")
    lines.append("<i>Нажми на пару, которую удалить.</i>")
    await show(cq, "\n".join(lines), kb.lesson_delete_keyboard(lessons, day, offset))


async def _delete_days_screen(cq: CallbackQuery, db: Database, user: User, offset: int) -> None:
    counts: dict[int, int] = {}
    for l in await db.list_lessons(user.id):
        counts[l.weekday] = counts.get(l.weekday, 0) + 1
    if not counts:
        text, markup = await render_week(db, user, offset)
        await show(cq, "<i>Пар в расписании нет.</i>\n\n" + text, markup)
        return
    text = "\n".join([texts.title("🗑", "Удалить пару"), texts.SEP, "Из какого дня?"])
    await show(cq, text, kb.lesson_day_keyboard(counts, lambda wd: TtCb(a="dday", o=offset, day=wd),
                                                back=TtCb(a="w", o=offset)))


async def _own_lesson(db: Database, user: User, lesson_id: int) -> Lesson | None:
    return next((l for l in await db.list_lessons(user.id) if l.id == lesson_id), None)


# ---------------------------------------------------------------- загрузка расписания

async def download_file(bot: Bot, file_id: str) -> bytes:
    buf = BytesIO()
    await bot.download(file_id, destination=buf)
    return buf.getvalue()


async def recognize_timetable(target: Message | CallbackQuery, state: FSMContext, user: User, ai, bot: Bot, *,
                              text: str | None = None, image: bytes | None = None,
                              mime: str = "image/jpeg", offset: int = 0) -> None:
    """ИИ распознаёт расписание -> превью -> «Заменить всё / Добавить / Отмена»."""
    if not ai_active(ai, user):
        await state.clear()
        await show(target, NO_AI_TEXT, kb.timetable_no_ai_keyboard(offset))
        return
    raw: list[dict[str, Any]] = []
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id_of(target)):
            raw = await ai.parse_timetable(text=text, image=image, mime=mime) or []
    except Exception:  # noqa: BLE001
        log.warning("parse_timetable failed", exc_info=True)
    lessons: list[dict[str, Any]] = []
    skipped = 0
    for item in raw:
        try:
            lessons.append(tt.normalize_lesson_dict(item))
        except (ValueError, TypeError, AttributeError, KeyError):
            skipped += 1
    if not lessons:
        await state.set_state(TimetableUpload.waiting)
        await state.update_data(tt_offset=offset)
        await show(target, "🤔 <b>Не получилось разобрать расписание.</b>\n"
                           "Пришли фото почётче или текст: <i>«пн 09:00-10:30 Матанализ 1-301»</i>.",
                   kb.timetable_upload_keyboard(offset))
        return
    await state.set_state(TimetableUpload.preview)
    await state.update_data(tt_import=lessons, tt_offset=offset)
    await show(target, texts.timetable_preview(lessons, skipped), kb.timetable_import_keyboard())


async def upload_photo(message: Message, state: FSMContext, user: User, bot: Bot, ai=None) -> None:
    data = await state.get_data()
    offset = int(data.get("tt_offset") or 0)
    if message.photo:
        file_id, mime = message.photo[-1].file_id, "image/jpeg"
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        file_id, mime = message.document.file_id, message.document.mime_type or "image/jpeg"
    else:
        await reply(message, "Пришли фото или текст расписания 🙂", kb.timetable_upload_keyboard(offset))
        return
    try:
        image = await download_file(bot, file_id)
    except Exception:  # noqa: BLE001
        log.warning("photo download failed", exc_info=True)
        await reply(message, "⚠️ Не получилось скачать фото. Попробуй ещё раз.", kb.timetable_upload_keyboard(offset))
        return
    await recognize_timetable(message, state, user, ai, bot, image=image, mime=mime, offset=offset)


async def upload_text(message: Message, state: FSMContext, user: User, bot: Bot, ai=None) -> None:
    offset = int((await state.get_data()).get("tt_offset") or 0)
    await recognize_timetable(message, state, user, ai, bot, text=message.text, offset=offset)


# ---------------------------------------------------------------- колбэки расписания

async def cb_tt(cq: CallbackQuery, callback_data: TtCb, db: Database, user: User, state: FSMContext,
                ai=None) -> None:
    a, o, day = callback_data.a, max(0, callback_data.o), callback_data.day
    if a == "w":
        await state.clear()
        await ack(cq)
        text, markup = await render_week(db, user, o)
        await show(cq, text, markup)
    elif a == "add":
        await ack(cq)
        await start_lesson_wizard(cq, state, db, user, offset=o)
    elif a == "del":
        await state.clear()
        await ack(cq)
        await _delete_days_screen(cq, db, user, o)
    elif a == "dday" and 0 <= day <= 6:
        await ack(cq)
        await _day_delete_screen(cq, db, user, day, o)
    elif a in ("dl", "dlok"):
        lesson = await _own_lesson(db, user, callback_data.id)
        if lesson is None:
            await ack(cq, "Пара не найдена — возможно, уже удалена", alert=True)
            await _day_delete_screen(cq, db, user, day if 0 <= day <= 6 else 0, o)
            return
        if a == "dl":
            await ack(cq)
            text = "\n".join([texts.title("🗑", "Удалить пару?"), texts.SEP,
                              f"📅 {WEEKDAYS_FULL[lesson.weekday]}",
                              texts.lesson_line(lesson, show_parity=True)])
            await show(cq, text, kb.lesson_delete_confirm(lesson.id, lesson.weekday, o))
        else:
            await db.delete_lesson(lesson.id)
            await ack(cq, "🗑 Удалено")
            await _day_delete_screen(cq, db, user, lesson.weekday, o)
    elif a == "up":
        await ack(cq)
        if not ai_active(ai, user):
            await state.clear()
            await show(cq, NO_AI_TEXT, kb.timetable_no_ai_keyboard(o))
            return
        await state.clear()
        await state.set_state(TimetableUpload.waiting)
        await state.update_data(tt_offset=o)
        await show(cq, UPLOAD_PROMPT, kb.timetable_upload_keyboard(o))
    elif a == "imp":
        data = await state.get_data()
        lessons = data.get("tt_import")
        offset = int(data.get("tt_offset") or 0)
        if not lessons:
            await ack(cq, "Превью устарело — загрузи расписание заново", alert=True)
            return
        replace = callback_data.id == 1
        n = await tt.import_lessons(db, user.id, lessons, replace=replace)
        await state.clear()
        await ack(cq, "✅ Готово")
        text, markup = await render_week(db, user, offset)
        head = f"✅ <b>{'Заменил расписание' if replace else 'Добавил'}: {texts.count(n, texts.F_LESSON)}</b>\n\n"
        await show(cq, head + text, markup)
    elif a == "impno":
        offset = int((await state.get_data()).get("tt_offset") or o)
        await state.clear()
        await ack(cq, "Отменено")
        text, markup = await render_week(db, user, offset)
        await show(cq, text, markup)
    else:
        await ack(cq)


def router() -> Router:
    r = Router(name="timetable")
    r.message.register(menu_week, MenuButton(kb.BTN_WEEK))
    r.message.register(menu_week, Command("week"))
    r.callback_query.register(nav_week, NavCb.filter(F.to == "week"))
    r.callback_query.register(cb_tt, TtCb.filter())
    r.callback_query.register(cb_lesson_wizard, LessonWizCb.filter())
    r.message.register(wizard_time_input, LessonWizard.time, FreeText())
    r.message.register(wizard_subject_input, LessonWizard.subject, FreeText())
    r.message.register(wizard_room_input, LessonWizard.room, FreeText())
    uploading = StateFilter(TimetableUpload.waiting, TimetableUpload.preview)
    r.message.register(upload_photo, uploading, F.photo | F.document)
    r.message.register(upload_text, uploading, FreeText())
    return r
