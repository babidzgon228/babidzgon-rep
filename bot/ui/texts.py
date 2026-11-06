"""Тексты и форматирование (Telegram HTML) — дизайн-система сообщений бота.

Единый стиль:
- заголовок: жирный, с эмодзи слева — ``<b>📅 Сегодня · пт, 6 ноября</b>``;
- под заголовком — курсивный подзаголовок и тонкий разделитель ``SEP``;
- строки таймлайна: ``08:30–10:05  📚 <b>Матанализ</b> · лекция · ауд. 305``;
- текущий блок помечается ``▶`` и «сейчас», выполненный — ✅ и зачёркиванием;
- прогресс — полоски ``▰▰▰▱▱``, длительности — ``human_duration`` / ``fmt_span``.

Любой пользовательский текст проходит через ``esc`` (html.escape).
Функции здесь чистые: никаких обращений к БД и сервисам.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Sequence

from bot.models import (
    ACTIVITY_CATEGORIES,
    ENERGY_LABELS,
    EVENT_KINDS,
    IMPORTANCE_LABELS,
    TASK_CATEGORIES,
    WEEKDAYS_FULL,
    WEEKDAYS_SHORT,
    Activity,
    DayPlan,
    DayStats,
    Event,
    Lesson,
    PeriodStats,
    PlanItem,
    Task,
    User,
    UserSettings,
)
from bot.timeutil import human_duration, minutes_of, now_utc, to_local

# ================================================================ примитивы

SEP = "─" * 16
SEP_SOFT = "┄" * 16
DASH = "–"

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]

PLAN_KIND_EMOJI = {
    "lesson": "📚", "event": "📌", "task": "🎯", "break": "☕", "meal": "🍽",
    "buffer": "⏳", "routine": "✨",
}
PLAN_KIND_LABELS = {
    "lesson": "Пара", "event": "Событие", "task": "Задача", "break": "Перерыв", "meal": "Еда",
    "buffer": "Буфер", "routine": "Рутина",
}
# Второстепенные блоки — без жирного, чтобы глаз цеплялся за главное
MINOR_KINDS = frozenset({"break", "meal", "buffer", "routine"})

ENERGY_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴"}
IMPORTANCE_STARS = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐"}
PARITY_LABELS = {"all": "каждую неделю", "odd": "числитель", "even": "знаменатель"}
PARITY_SHORT = {"all": "", "odd": "числ.", "even": "знам."}
WEEK_PARITY_LABELS = {"odd": "нечётная · числитель", "even": "чётная · знаменатель"}
FOCUS_PEAK_LABELS = {"morning": "утро", "afternoon": "день", "evening": "вечер"}
RATING_EMOJI = {1: "😫", 2: "😕", 3: "😐", 4: "🙂", 5: "🤩"}


def esc(value: Any) -> str:
    """Экранирует пользовательский текст для Telegram HTML."""
    if value is None:
        return ""
    return html.escape(str(value), quote=False)


def truncate(value: str, limit: int) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: max(1, limit - 1)].rstrip() + "…"


def title(emoji: str, text: str, sub: str | None = None) -> str:
    """Заголовок экрана: жирный, с эмодзи, опционально курсивный подзаголовок.

    text и sub считаются уже безопасными (их собирает код), пользовательские части — через esc().
    """
    head = f"<b>{emoji} {text}</b>" if emoji else f"<b>{text}</b>"
    if sub:
        head += f"\n<i>{sub}</i>"
    return head


def bar(value: float, total: float = 1.0, width: int = 10) -> str:
    """Прогресс-бар ▰▰▰▱▱▱▱▱▱▱."""
    frac = 0.0 if not total else max(0.0, min(1.0, float(value) / float(total)))
    filled = int(round(frac * width))
    if value and filled == 0:
        filled = 1
    return "▰" * filled + "▱" * (width - filled)


_SPARK = "▁▂▃▄▅▆▇█"


def spark(values: Sequence[float], top: float | None = None) -> str:
    """Мини-график ▁▃▅█ по значениям."""
    if not values:
        return ""
    top = top or max(values) or 1
    out = []
    for v in values:
        if v <= 0:
            out.append("·")
        else:
            out.append(_SPARK[min(len(_SPARK) - 1, int(round(v / top * (len(_SPARK) - 1))))])
    return "".join(out)


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """plural(5, ("пара", "пары", "пар")) -> "пар"."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def count(n: int, forms: tuple[str, str, str]) -> str:
    return f"{n} {plural(n, forms)}"


F_LESSON = ("пара", "пары", "пар")
F_TASK = ("задача", "задачи", "задач")
F_EVENT = ("событие", "события", "событий")
F_DAY = ("день", "дня", "дней")
F_BLOCK = ("блок", "блока", "блоков")


def fmt_span(minutes: float) -> str:
    """Длительность с днями: 3000 -> "2 дня 2 ч", 125 -> "2 ч 5 мин"."""
    minutes = int(round(abs(minutes)))
    if minutes >= 24 * 60:
        days, rest = divmod(minutes, 24 * 60)
        hours = rest // 60
        out = count(days, F_DAY)
        return out + (f" {hours} ч" if hours else "")
    return human_duration(minutes)


def fmt_date(d: date, *, weekday: bool = True, year: bool = False) -> str:
    """"пт, 6 ноября" (+ " 2026")."""
    s = f"{d.day} {MONTHS_GEN[d.month - 1]}"
    if year:
        s += f" {d.year}"
    return f"{WEEKDAYS_SHORT[d.weekday()]}, {s}" if weekday else s


def fmt_day_rel(d: date, today: date) -> str:
    """"сегодня" / "завтра" / "вчера" / "пн, 9 ноября"."""
    delta = (d - today).days
    if delta == 0:
        return "сегодня"
    if delta == 1:
        return "завтра"
    if delta == 2:
        return "послезавтра"
    if delta == -1:
        return "вчера"
    return fmt_date(d, year=d.year != today.year)


def fmt_when(dt: datetime, tz_name: str, today: date | None = None) -> str:
    """aware datetime -> "сегодня, 18:00" / "пн, 9 ноября, 18:00" в поясе пользователя."""
    local = to_local(dt, tz_name)
    today = today or to_local(now_utc(), tz_name).date()
    return f"{fmt_day_rel(local.date(), today)}, {local:%H:%M}"


def fmt_left(minutes: float) -> str:
    """Сколько осталось: "через 2 ч 5 мин" / "уже началось"."""
    if minutes <= 0:
        return "прямо сейчас" if minutes > -1 else f"{fmt_span(-minutes)} назад"
    return f"через {fmt_span(minutes)}"


def fmt_range(start: str, end: str) -> str:
    return start if not end or end == start else f"{start}{DASH}{end}"


def item_minutes(start: str, end: str) -> int:
    try:
        return max(0, minutes_of(end) - minutes_of(start))
    except Exception:
        return 0


def room_label(room: str | None) -> str:
    if not room:
        return ""
    r = str(room).strip()
    if any(ch.isdigit() for ch in r) and "ауд" not in r.lower() and len(r) <= 12:
        return f"ауд. {r}"
    return r


def activity_label(key: str) -> str:
    emoji, name = ACTIVITY_CATEGORIES.get(key, ACTIVITY_CATEGORIES["other"])
    return f"{emoji} {name}"


def task_category_label(key: str) -> str:
    emoji, name = TASK_CATEGORIES.get(key, TASK_CATEGORIES["other"])
    return f"{emoji} {name}"


def focus_badge(score: int) -> str:
    if score >= 80:
        return "🔥"
    if score >= 60:
        return "💪"
    if score >= 40:
        return "🙂"
    return "🌱"


# ---------------------------------------------------------------- безопасный HTML от ИИ

_ALLOWED_SIMPLE_TAGS = ("b", "i", "u", "s", "code", "pre", "blockquote", "tg-spoiler", "em", "strong")
_RE_RESTORE_TAG = re.compile(r"&lt;(/?)(" + "|".join(_ALLOWED_SIMPLE_TAGS) + r")&gt;", re.I)
_RE_RESTORE_LINK = re.compile(r"&lt;a href=&quot;(https?://[^\s&]+?)&quot;&gt;(.*?)&lt;/a&gt;", re.I | re.S)


def sanitize_html(text: str | None) -> str:
    """Делает произвольный текст (например, ответ ИИ) безопасным Telegram-HTML.

    Экранирует всё, затем возвращает разрешённые простые теги и ссылки http(s).
    Идемпотентна для уже корректного HTML из разрешённых тегов.
    """
    if not text:
        return ""
    s = html.escape(html.unescape(str(text)), quote=True)
    s = _RE_RESTORE_TAG.sub(lambda m: f"<{m.group(1)}{m.group(2).lower()}>", s)
    s = _RE_RESTORE_LINK.sub(lambda m: f'<a href="{m.group(1)}">{m.group(2)}</a>', s)
    s = s.replace("<em>", "<i>").replace("</em>", "</i>")
    s = s.replace("<strong>", "<b>").replace("</strong>", "</b>")
    # Markdown-жирный, который ИИ любит вставлять: **текст** -> <b>текст</b>
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return s.replace("&quot;", '"').replace("&#x27;", "'")


def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Режет длинный текст по абзацам/строкам под лимит Telegram (4096)."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) > limit:
            parts.append(buf)
            buf = line
        else:
            buf = candidate
    if buf:
        parts.append(buf)
    return parts


# ================================================================ строки-компоненты

def lesson_meta(kind: str | None, room: str | None, teacher: str | None = None) -> list[str]:
    meta = []
    if kind:
        meta.append(esc(kind))
    if room:
        meta.append(esc(room_label(room)))
    if teacher:
        meta.append(esc(teacher))
    return meta


def lesson_line(lesson: Lesson, *, show_parity: bool = False, teacher: bool = False) -> str:
    """08:30–10:05  📚 <b>Матанализ</b> · лекция · ауд. 305"""
    meta = lesson_meta(lesson.kind, lesson.room, lesson.teacher if teacher else None)
    if show_parity and PARITY_SHORT.get(lesson.parity):
        meta.append(f"<i>{PARITY_SHORT[lesson.parity]}</i>")
    tail = "".join(f" · {m}" for m in meta)
    return f"{fmt_range(lesson.start_time, lesson.end_time)}  📚 <b>{esc(lesson.subject)}</b>{tail}"


def event_emoji(kind: str) -> str:
    label = EVENT_KINDS.get(kind, EVENT_KINDS["event"])
    return label.split(" ", 1)[0]


def event_kind_name(kind: str) -> str:
    label = EVENT_KINDS.get(kind, EVENT_KINDS["event"])
    return label.split(" ", 1)[1] if " " in label else label


def event_line(event: Event, tz_name: str, *, with_date: bool = False, today: date | None = None) -> str:
    """18:00–19:00  🤝 <b>Встреча</b> · Корпус 2"""
    start = to_local(event.start_at, tz_name)
    t = f"{start:%H:%M}"
    if event.end_at:
        t = fmt_range(t, f"{to_local(event.end_at, tz_name):%H:%M}")
    if with_date:
        today = today or to_local(now_utc(), tz_name).date()
        t = f"{fmt_day_rel(start.date(), today)}, {t}"
    tail = f" · {esc(event.location)}" if event.location else ""
    return f"{t}  {event_emoji(event.kind)} <b>{esc(event.title)}</b>{tail}"


def deadline_short(task: Task, tz_name: str, now: datetime | None = None) -> str:
    if not task.deadline:
        return ""
    now = now or now_utc()
    left = (task.deadline - now).total_seconds() / 60
    if left < 0:
        return f"🔥 просрочено на {fmt_span(-left)}"
    icon = "🔥" if left <= 24 * 60 else "⏰"
    return f"{icon} {fmt_when(task.deadline, tz_name, to_local(now, tz_name).date())}"


def task_line(n: int | None, task: Task, tz_name: str, *, score: float | None = None,
              now: datetime | None = None) -> str:
    """<b>1.</b> 📚 <b>Курсовая</b> · ⏰ завтра, 18:00 · 2 ч · <code>87</code>"""
    emoji = TASK_CATEGORIES.get(task.category, TASK_CATEGORIES["other"])[0]
    num = f"<b>{n}.</b> " if n is not None else ""
    parts = [f"{num}{emoji} <b>{esc(truncate(task.title, 60))}</b>"]
    dl = deadline_short(task, tz_name, now)
    if dl:
        parts.append(dl)
    parts.append(human_duration(task.estimate_min))
    if score is not None:
        parts.append(f"<code>{int(round(score))}</code>")
    return " · ".join(parts)


def plan_item_line(item: PlanItem, *, current: bool = False) -> str:
    """Строка таймлайна плана."""
    emoji = PLAN_KIND_EMOJI.get(item.kind, "•")
    if item.kind == "buffer" and "дорог" in (item.title or "").lower():
        emoji = "🚌"
    rng = fmt_range(item.start, item.end)
    name = esc(item.title)
    note = f" · {esc(item.note)}" if item.note else ""
    if item.done:
        return f"{rng}  ✅ <s>{name}</s>{note}"
    if item.kind in MINOR_KINDS:
        line = f"{rng}  {emoji} {name}{note}"
    else:
        line = f"{rng}  {emoji} <b>{name}</b>{note}"
    if current:
        line = f"▶ <b>{rng}</b>  {emoji} <b>{name}</b>{note} · <i>сейчас</i>"
    return line


def activity_status(act: Activity | None, tz_name: str, now: datetime | None = None) -> str:
    """"▶️ 📚 <b>Учёба</b> · 1 ч 5 мин (с 14:20)" или пустая строка."""
    if not act or not act.is_running:
        return ""
    now = now or now_utc()
    mins = max(0, int((now - act.started_at).total_seconds() // 60))
    desc = f" — {esc(truncate(act.description, 40))}" if act.description else ""
    started = to_local(act.started_at, tz_name)
    emoji, name = ACTIVITY_CATEGORIES.get(act.category, ACTIVITY_CATEGORIES["other"])
    return f"▶️ {emoji} <b>{name}</b>{desc} · {human_duration(mins)} <i>(с {started:%H:%M})</i>"


# ================================================================ ОБЯЗАТЕЛЬНЫЕ (их вызывает notifier)

def _now_marker(now_local: datetime, items: list[PlanItem]) -> tuple[int | None, int | None, str]:
    """Определяет текущий блок или место вставки маркера «сейчас».

    Возвращает (индекс текущего блока, индекс перед которым вставить маркер, текст маркера).
    """
    nowm = now_local.hour * 60 + now_local.minute
    hhmm = f"{now_local:%H:%M}"
    for idx, it in enumerate(items):
        try:
            s, e = minutes_of(it.start), minutes_of(it.end)
        except Exception:
            continue
        if s <= nowm < e:
            return idx, None, ""
    for idx, it in enumerate(items):
        try:
            s = minutes_of(it.start)
        except Exception:
            continue
        if s > nowm:
            gap = s - nowm
            label = "до начала дня" if idx == 0 else "свободно"
            return None, idx, f"▶ <i>сейчас {hhmm} · {label} {human_duration(gap)}</i>"
    return None, len(items), f"▶ <i>сейчас {hhmm} · план на сегодня закончился</i>"


def plan_summary(plan: DayPlan) -> str:
    items = plan.items
    lessons = sum(1 for i in items if i.kind == "lesson")
    events = sum(1 for i in items if i.kind == "event")
    tasks = [i for i in items if i.kind == "task"]
    task_min = sum(item_minutes(i.start, i.end) for i in tasks)
    parts = []
    if lessons:
        parts.append(f"📚 {count(lessons, F_LESSON)}")
    if events:
        parts.append(f"📌 {count(events, F_EVENT)}")
    if tasks:
        parts.append(f"🎯 {count(len(tasks), F_TASK)} · {human_duration(task_min)}")
    return " · ".join(parts)


def day_plan(plan: DayPlan, *, header: str | None = None, now_local: datetime | None = None) -> str:
    """Таймлайн плана дня.

    header — готовый HTML-заголовок (начинается с «<») или простой текст вроде «План на завтра»:
    простой текст оформляется в фирменный заголовок с датой.
    """
    if header and header.lstrip().startswith("<"):
        head = header
    elif header:
        head = title("🗓", f"{esc(header)} · {fmt_date(plan.date)}")
    else:
        head = title("🗓", f"План · {fmt_date(plan.date)}")
    lines = [head, SEP]
    items = list(plan.items)
    if not items:
        lines.append("<i>План пуст — свободный день 🌿</i>")
    else:
        current_idx, marker_at, marker = (None, None, "")
        if now_local is not None and now_local.date() == plan.date:
            current_idx, marker_at, marker = _now_marker(now_local, items)
        for idx, it in enumerate(items):
            if marker_at == idx:
                lines.append(marker)
            lines.append(plan_item_line(it, current=(idx == current_idx)))
        if marker_at is not None and marker_at >= len(items):
            lines.append(marker)
    lines.append(SEP)
    summary = plan_summary(plan)
    if summary:
        lines.append(summary)
    trackable = [i for i in items if i.kind not in MINOR_KINDS]
    done = sum(1 for i in trackable if i.done)
    if trackable and done:
        lines.append(f"{bar(done, len(trackable))} {done}/{len(trackable)} выполнено")
    if plan.status == "accepted":
        lines.append("🟢 <i>План принят — напомню о каждом блоке</i>")
    elif items:
        lines.append("📝 <i>Черновик — прими, чтобы включить напоминания</i>")
    if plan.ai_comment:
        lines.append(f"<blockquote>🤖 {sanitize_html(plan.ai_comment)}</blockquote>")
    return "\n".join(lines)


def _greeting(hour: int) -> str:
    if 4 <= hour < 12:
        return "☀️ Доброе утро"
    if 12 <= hour < 17:
        return "🌤 Добрый день"
    if 17 <= hour < 23:
        return "🌆 Добрый вечер"
    return "🌙 Доброй ночи"


def week_label(d: date, settings: UserSettings) -> str:
    """"неделя 10 · нечётная · числитель" (или без номера, если семестр не задан)."""
    try:
        from bot.services.timetable import week_number, week_parity
        parity = week_parity(d, settings)
        n = week_number(d, settings)
    except Exception:
        return ""
    label = WEEK_PARITY_LABELS.get(parity, "")
    return f"неделя {n} · {label}" if n else label


def in_semester(d: date, settings: UserSettings) -> bool:
    try:
        from bot.services.timetable import in_semester as _in_semester
        return _in_semester(d, settings)
    except Exception:
        return True


VACATION_LINE = "🏖 Каникулы — пар нет"


def location(settings: UserSettings) -> str:
    """Где сейчас пользователь: «Шэньчжэнь» (при автосмене пояса) или название пояса."""
    if settings.tz_auto:
        try:
            from bot.services.tzrules import location_label
            return location_label(settings)
        except Exception:
            pass
    return tz_label(settings.tz)


def tz_line(settings: UserSettings) -> str:
    """«Шэньчжэнь (UTC+8) · авто»."""
    from bot.ui.parsing import utc_offset_label
    out = f"{esc(location(settings))} ({utc_offset_label(settings.tz)})"
    return out + (" · авто" if settings.tz_auto else "")


def _md_label(md: str) -> str:
    try:
        m, d = (int(x) for x in md.split("-"))
        return f"{d} {MONTHS_SHORT[m - 1]}"
    except Exception:
        return esc(md)


def tz_rules_text(settings: UserSettings) -> str:
    """Описание правил автосмены пояса: «1 сен – 31 янв, 1 мар – 15 июл → Шэньчжэнь; иначе Москва»."""
    if not settings.tz_rules:
        return ""
    groups: dict[str, list[str]] = {}
    for rule in settings.tz_rules:
        try:
            label = rule.get("label") or tz_label(rule["tz"])
            groups.setdefault(label, []).append(f"{_md_label(rule['from'])} – {_md_label(rule['to'])}")
        except (KeyError, AttributeError):
            continue
    parts = [f"{', '.join(ranges)} → {esc(label)}" for label, ranges in groups.items()]
    return "; ".join(parts) + f"; иначе — {esc(tz_label(settings.home_tz))}"


def morning_brief(user: User, d: date, lessons: list[Lesson], events: list[Event],
                  top_tasks: list[Task], plan: DayPlan | None) -> str:
    tz_name = user.settings.tz
    local_hour = to_local(now_utc(), tz_name).hour
    name = f", {esc(user.first_name)}" if user.first_name else ""
    sub = fmt_date(d)
    wl = week_label(d, user.settings) if in_semester(d, user.settings) else ""
    if wl:
        sub += f" · {wl}"
    if user.settings.tz_auto:
        sub += f" · 📍 {esc(location(user.settings))}"
    lines = [title("", f"{_greeting(local_hour)}{name}!", sub), SEP]
    if lessons:
        lines.append(f"<b>🎓 Пары</b> · {count(len(lessons), F_LESSON)}, "
                     f"с {lessons[0].start_time} до {lessons[-1].end_time}")
        lines.extend(lesson_line(l) for l in lessons)
        lines.append("")
    if events:
        lines.append("<b>📌 События</b>")
        lines.extend(event_line(e, tz_name) for e in events)
        lines.append("")
    if top_tasks:
        lines.append("<b>🎯 Главное на сегодня</b>")
        for n, t in enumerate(top_tasks[:5], 1):
            lines.append(task_line(n, t, tz_name))
        lines.append("")
    if not lessons and not in_semester(d, user.settings):
        lines.append(VACATION_LINE)
        lines.append("")
    if not lessons and not events and not top_tasks:
        lines.append("Свободный день — пар и событий нет. Отличный момент для важного 💪")
        lines.append("")
    if plan and plan.items:
        first = next((i for i in plan.items if i.kind not in MINOR_KINDS), plan.items[0])
        status = "принят" if plan.status == "accepted" else "черновик"
        lines.append(f"📋 План {status}: {count(len(plan.items), F_BLOCK)}, "
                     f"первый в {first.start} — {esc(first.title)}")
    else:
        lines.append("📋 Плана на сегодня нет — открой «📅 Сегодня», чтобы составить.")
    return "\n".join(lines).rstrip()


def lesson_reminder(lesson: Lesson, minutes_left: int) -> str:
    if minutes_left > 0:
        head = title("🔔", f"Через {human_duration(minutes_left)} — пара")
    else:
        head = title("🔔", "Пара началась")
    meta = " · ".join([esc(lesson.kind)] if lesson.kind else [])
    lines = [head, f"📚 <b>{esc(lesson.subject)}</b>" + (f" · {meta}" if meta else "")]
    where = f"🕘 {fmt_range(lesson.start_time, lesson.end_time)}"
    if lesson.room:
        where += f" · 📍 {esc(room_label(lesson.room))}"
    lines.append(where)
    if lesson.teacher:
        lines.append(f"👤 {esc(lesson.teacher)}")
    return "\n".join(lines)


def event_reminder(event: Event, minutes_left: int, tz_name: str) -> str:
    if minutes_left >= 24 * 60 - 30:
        head = title("⏰", f"Напоминаю: {fmt_left(minutes_left)}")
    elif minutes_left > 0:
        head = title("⏰", f"Через {human_duration(minutes_left)}")
    else:
        head = title("⏰", "Начинается сейчас")
    start = to_local(event.start_at, tz_name)
    today = to_local(now_utc(), tz_name).date()
    when = f"{start:%H:%M}"
    if event.end_at:
        when = fmt_range(when, f"{to_local(event.end_at, tz_name):%H:%M}")
    lines = [head, f"{event_emoji(event.kind)} <b>{esc(event.title)}</b>",
             f"🕐 {fmt_day_rel(start.date(), today)}, {when}"]
    if event.location:
        lines.append(f"📍 {esc(event.location)}")
    if event.notes:
        lines.append(f"<i>{esc(truncate(event.notes, 300))}</i>")
    return "\n".join(lines)


def plan_item_reminder(item: PlanItem) -> str:
    emoji = PLAN_KIND_EMOJI.get(item.kind, "•")
    mins = item_minutes(item.start, item.end)
    lines = [title("⏰", "По плану сейчас"), f"{emoji} <b>{esc(item.title)}</b>"]
    when = f"🕑 {fmt_range(item.start, item.end)}"
    if mins:
        when += f" · {human_duration(mins)}"
    lines.append(when)
    if item.note:
        lines.append(f"<i>{esc(item.note)}</i>")
    if item.kind == "task":
        lines.append("<i>Нажми «▶️ Начать» — запущу трекер.</i>")
    return "\n".join(lines)


def deadline_reminder(task: Task, tz_name: str, hours_left: float) -> str:
    if hours_left <= 0:
        head = title("🔥", "Дедлайн прошёл")
    elif hours_left >= 20:
        head = title("⏳", f"Дедлайн {fmt_left(hours_left * 60)}")
    else:
        head = title("⏳", f"Дедлайн через {human_duration(int(round(hours_left * 60)))}!")
    lines = [head, f"{TASK_CATEGORIES.get(task.category, TASK_CATEGORIES['other'])[0]} "
                   f"<b>{esc(task.title)}</b>"]
    meta = []
    if task.deadline:
        meta.append(f"⏰ {fmt_when(task.deadline, tz_name)}")
    meta.append(IMPORTANCE_STARS.get(task.importance, "⭐⭐"))
    meta.append(f"⏱ {human_duration(task.estimate_min)}")
    lines.append(" · ".join(meta))
    return "\n".join(lines)


def checkin_prompt(current: Activity | None, tz_name: str) -> str:
    lines = [title("👋", "Что делаешь сейчас?")]
    status = activity_status(current, tz_name)
    if status:
        lines.append(f"Сейчас записано: {status}")
        lines.append("<i>Если всё так же — жми «🔁 То же самое».</i>")
    else:
        lines.append("<i>Трекер стоит. Выбери категорию — запущу таймер.</i>")
    return "\n".join(lines)


def category_bars(minutes_by_category: dict[str, int], *, limit: int = 8) -> list[str]:
    """📚 ▰▰▰▰▰▰▱▱▱▱ Учёба · <b>3 ч 20 мин</b>"""
    items = sorted(((k, v) for k, v in minutes_by_category.items() if v > 0),
                   key=lambda kv: kv[1], reverse=True)[:limit]
    if not items:
        return []
    top = items[0][1]
    total = sum(v for _, v in minutes_by_category.items() if v > 0) or 1
    out = []
    for key, mins in items:
        emoji, name = ACTIVITY_CATEGORIES.get(key, ACTIVITY_CATEGORIES["other"])
        pct = int(round(mins * 100 / total))
        out.append(f"{emoji} {bar(mins, top)} {name} · <b>{human_duration(mins)}</b> <i>{pct}%</i>")
    return out


def _focus_block(score: int) -> list[str]:
    return [f"🎯 Фокус: <b>{score}</b>/100 {focus_badge(score)}", bar(score, 100)]


def day_report(stats: DayStats, ai_comment: str | None = None) -> str:
    lines = [title("🌆", "Итоги дня", fmt_date(stats.date)), SEP]
    lines.extend(_focus_block(stats.focus_score))
    if stats.tracked_min:
        lines.append(f"⏱ Отслежено <b>{human_duration(stats.tracked_min)}</b>, "
                     f"продуктивно <b>{human_duration(stats.productive_min)}</b>")
    else:
        lines.append("⏱ <i>Трекер сегодня не запускался</i>")
    facts = [f"✅ Задач: <b>{stats.tasks_done}</b>"]
    if stats.plan_items_total:
        facts.append(f"📋 План: {stats.plan_items_done}/{stats.plan_items_total}")
    if stats.lessons_count:
        facts.append(f"🎓 {count(stats.lessons_count, F_LESSON)}")
    if stats.avg_rating:
        facts.append(f"⭐ {stats.avg_rating:.1f}")
    lines.append(" · ".join(facts))
    bars = category_bars(stats.minutes_by_category)
    if bars:
        lines.append("")
        lines.append("<b>Куда ушло время</b>")
        lines.extend(bars)
    if ai_comment:
        lines.append("")
        lines.append(f"<blockquote>🤖 {sanitize_html(ai_comment)}</blockquote>")
    return "\n".join(lines)


# ================================================================ экраны

def welcome(user: User, lessons_count: int, *, created: bool, ai_on: bool) -> str:
    name = esc(user.first_name) or "студент"
    lines = [title("👋", f"Привет, {name}!", "Я твой личный планировщик учёбы и дня"), SEP,
             "📅 Собираю <b>план дня</b> из пар, событий и задач",
             "✅ Сортирую <b>задачи</b> по приоритету — сначала главное",
             "⏱ Веду <b>трекер</b> времени и спрашиваю, чем занят",
             "🔔 Напоминаю о парах, событиях и дедлайнах",
             "📊 Показываю <b>статистику</b> и фокус дня"]
    if ai_on:
        lines.append("🤖 Понимаю обычный текст: «завтра в 18 встреча с научруком»")
    lines.append("")
    if lessons_count:
        verb = "Импортировал" if created else "В расписании"
        lines.append(f"🎓 {verb} <b>{count(lessons_count, F_LESSON)}</b> из расписания")
    else:
        lines.append("🎓 Расписание пока пустое — добавь пары в «🎓 Расписание» или пришли фото")
    lines.append(f"📍 Сейчас: {tz_line(user.settings)}"
                 + (" — пояс меняю сам по датам" if user.settings.tz_auto else ""))
    lines.append("")
    lines.append("<i>Меню всегда внизу ⬇️ Любой текст — новая задача или вопрос.</i>")
    return "\n".join(lines)


def setup_prompt(step: str, settings: UserSettings) -> str:
    if step == "tz":
        lines = [title("⚙️", "Быстрая настройка · 1/3"), SEP,
                 "🌍 Выбери свой <b>часовой пояс</b> — по нему считаю время пар и напоминаний.",
                 f"Сейчас: <b>{tz_line(settings)}</b>"]
        rules = tz_rules_text(settings)
        if rules:
            lines.append(f"🔄 <i>Автосмена: {rules}</i>")
            lines.append("<i>Оставь авто или выбери пояс вручную.</i>")
        return "\n".join(lines)
    if step == "wake":
        return "\n".join([title("⚙️", "Быстрая настройка · 2/3"), SEP,
                          f"🌍 Пояс: <b>{tz_line(settings)}</b>",
                          "⏰ Во сколько обычно <b>встаёшь</b>?"])
    if step == "sleep":
        return "\n".join([title("⚙️", "Быстрая настройка · 3/3"), SEP,
                          f"⏰ Подъём: <b>{settings.wake_time}</b>",
                          "🌙 А во сколько <b>ложишься</b>?"])
    return "\n".join([title("✅", "Готово!"), SEP,
                      f"🌍 {tz_line(settings)} · ⏰ {settings.wake_time} · 🌙 {settings.sleep_time}",
                      f"☀️ Утренняя сводка в <b>{settings.morning_brief_time}</b>, "
                      f"план на завтра — в <b>{settings.evening_plan_time}</b>",
                      "",
                      "Начни с «📅 Сегодня» или добавь задачу через «➕ Добавить».",
                      "<i>Всё можно поменять в «⚙️ Настройки».</i>"])


def tz_label(tz_name: str) -> str:
    from bot.ui.parsing import TIMEZONES
    for label, name in TIMEZONES.values():
        if name == tz_name:
            return label
    return tz_name


def help_text(ai_on: bool) -> str:
    lines = [title("❓", "Как мной пользоваться"), SEP,
             "<b>Меню внизу</b> — всё главное в один тап.",
             "",
             "/today — план и дела на сегодня",
             "/tomorrow, /plan — план на завтра",
             "/tasks — задачи по приоритету",
             "/add <i>текст</i> — новая задача",
             "/event <i>текст</i> — новое событие",
             "/track <i>категория</i> — запустить трекер · /stop — стоп",
             "/stats — статистика · /week — расписание",
             "/settings — настройки · /ai — ИИ-помощник",
             "/cancel — выйти из мастера",
             "",
             "💡 Просто напиши текст — " + ("ИИ поймёт, что сделать." if ai_on else "предложу сделать из него задачу.")]
    return "\n".join(lines)


def today_overview(d: date, lessons: list[Lesson], events: list[Event], top_tasks: list[Task],
                   tz_name: str, *, header: str, vacation: bool = False) -> str:
    """Экран «Сегодня», когда плана ещё нет."""
    lines = [header, SEP]
    if lessons:
        lines.append(f"<b>🎓 Пары</b> · {count(len(lessons), F_LESSON)}")
        lines.extend(lesson_line(l) for l in lessons)
    elif vacation:
        lines.append(VACATION_LINE)
    else:
        lines.append("🎓 <i>Пар нет</i>")
    if events:
        lines.append("")
        lines.append("<b>📌 События</b>")
        lines.extend(event_line(e, tz_name) for e in events)
    if top_tasks:
        lines.append("")
        lines.append("<b>🎯 Главные задачи</b>")
        for n, t in enumerate(top_tasks, 1):
            lines.append(task_line(n, t, tz_name))
    lines.append(SEP)
    lines.append("<i>Плана ещё нет — нажми «🧩 Составить план», разложу задачи по свободным окнам.</i>")
    return "\n".join(lines)


# ---------------------------------------------------------------- задачи

def task_list(groups: list[tuple[str, list[tuple[int, Task, float | None]]]], *, total: int,
              page: int, pages: int, tz_name: str, now: datetime | None = None,
              done_today: int = 0) -> str:
    """groups: [(заголовок квадранта, [(номер, задача, score)])]."""
    sub = f"{count(total, F_TASK)} в работе"
    if done_today:
        sub += f" · сегодня сделано {done_today}"
    lines = [title("✅", "Задачи", sub), SEP]
    if not total:
        lines.append("Пусто — ни одной задачи 🎉")
        lines.append("<i>Нажми «➕ Добавить» или просто напиши, что нужно сделать.</i>")
        return "\n".join(lines)
    for label, entries in groups:
        if not entries:
            continue
        lines.append(f"<b>{esc(label)}</b>")
        for n, t, score in entries:
            lines.append(task_line(n, t, tz_name, score=score, now=now))
        lines.append("")
    if pages > 1:
        lines.append(f"<i>Стр. {page + 1}/{pages}</i>")
    lines.append("<i>Нажми номер — откроется карточка задачи. Число справа — приоритет.</i>")
    return "\n".join(lines).rstrip()


def _task_fields(values: dict[str, Any], tz_name: str, now: datetime | None = None) -> list[str]:
    imp = int(values.get("importance") or 2)
    est = int(values.get("estimate_min") or 30)
    energy = values.get("energy") or "medium"
    cat = values.get("category") or "study"
    dl = values.get("deadline")
    lines = [f"⭐ Важность: <b>{IMPORTANCE_LABELS.get(imp, 'средняя')}</b> {IMPORTANCE_STARS.get(imp, '')}"]
    if dl:
        now = now or now_utc()
        left = (dl - now).total_seconds() / 60
        rel = f"просрочено на {fmt_span(-left)}" if left < 0 else fmt_left(left)
        lines.append(f"⏰ Дедлайн: <b>{fmt_when(dl, tz_name)}</b> <i>({rel})</i>")
    else:
        lines.append("⏰ Дедлайн: <i>без срока</i>")
    lines.append(f"⏱ Время: <b>{human_duration(est)}</b>")
    lines.append(f"🧠 Сложность: {ENERGY_EMOJI.get(energy, '🟡')} <b>{ENERGY_LABELS.get(energy, energy)}</b>")
    lines.append(f"🏷 Категория: <b>{task_category_label(cat)}</b>")
    return lines


def task_card(task: Task, tz_name: str, *, now: datetime | None = None, score: float | None = None,
              quadrant_label: str | None = None, explanation: str | None = None) -> str:
    now = now or now_utc()
    status = {"done": "✅ ", "cancelled": "✖️ "}.get(task.status, "")
    lines = [f"<b>{status}📝 {esc(task.title)}</b>", SEP]
    if score is not None or quadrant_label:
        pr = []
        if quadrant_label:
            pr.append(esc(quadrant_label))
        if score is not None:
            pr.append(f"приоритет <b>{int(round(score))}</b>/100")
        lines.append(" · ".join(pr))
        if score is not None:
            lines.append(bar(score, 100))
    lines.extend(_task_fields(task.__dict__, tz_name, now))
    if task.planned_date:
        lines.append(f"📅 Запланирована: <b>{fmt_day_rel(task.planned_date, to_local(now, tz_name).date())}</b>")
    if task.notes:
        lines.append(f"<i>{esc(truncate(task.notes, 400))}</i>")
    if task.status == "done" and task.done_at:
        lines.append(f"🏁 Выполнена {fmt_when(task.done_at, tz_name)}")
    if explanation:
        lines.append("")
        lines.append(f"<blockquote>❓ {esc(explanation)}</blockquote>")
    return "\n".join(lines)


def task_draft(draft: dict[str, Any], tz_name: str, *, ai_used: bool = False) -> str:
    """Карточка черновика задачи в мастере добавления."""
    lines = [title("➕", "Новая задача"), f"📝 <b>{esc(draft.get('title', ''))}</b>", SEP]
    lines.extend(_task_fields(draft, tz_name))
    lines.append(SEP)
    if ai_used:
        lines.append("<i>🤖 Поля подобрал ИИ — поправь кнопками, если что.</i>")
    lines.append("<i>Переключай кнопками и жми «💾 Сохранить». Новый текст — переименую.</i>")
    return "\n".join(lines)


def task_edit(task: Task, tz_name: str) -> str:
    lines = [title("✏️", "Изменить задачу"), f"📝 <b>{esc(task.title)}</b>", SEP]
    lines.extend(_task_fields(task.__dict__, tz_name))
    lines.append(SEP)
    lines.append("<i>Изменения сохраняются сразу.</i>")
    return "\n".join(lines)


# ---------------------------------------------------------------- события

def event_list(events: list[Event], tz_name: str) -> str:
    lines = [title("📌", "Ближайшие события"), SEP]
    if not events:
        lines.append("Событий нет. Добавь встречу, экзамен или дедлайн — напомню заранее.")
        return "\n".join(lines)
    today = to_local(now_utc(), tz_name).date()
    current_day: date | None = None
    for n, e in enumerate(events, 1):
        d = to_local(e.start_at, tz_name).date()
        if d != current_day:
            if current_day is not None:
                lines.append("")
            current_day = d
            rel = fmt_day_rel(d, today)
            lines.append(f"<b>{rel.capitalize()}</b>"
                         + (f" · {fmt_date(d)}" if rel in ("сегодня", "завтра", "послезавтра") else ""))
        lines.append(f"<b>{n}.</b> {event_line(e, tz_name)}")
    lines.append("")
    lines.append("<i>Нажми номер, чтобы открыть событие.</i>")
    return "\n".join(lines)


def event_card(event: Event, tz_name: str) -> str:
    start = to_local(event.start_at, tz_name)
    when = f"{start:%H:%M}"
    if event.end_at:
        when = fmt_range(when, f"{to_local(event.end_at, tz_name):%H:%M}")
    today = to_local(now_utc(), tz_name).date()
    lines = [f"<b>{event_emoji(event.kind)} {esc(event.title)}</b>", SEP,
             f"🏷 {esc(event_kind_name(event.kind))}",
             f"🕐 {fmt_day_rel(start.date(), today)}, {when}" + (
                 f" · {fmt_date(start.date())}" if (start.date() - today).days in (0, 1, 2) else "")]
    if event.location:
        lines.append(f"📍 {esc(event.location)}")
    lines.append(f"🔔 Напомню {remind_label(event.remind_before_min)}")
    left = (event.start_at - now_utc()).total_seconds() / 60
    lines.append(f"<i>{'Уже прошло' if left < -5 else fmt_left(left).capitalize()}</i>")
    if event.notes:
        lines.append(f"<i>{esc(truncate(event.notes, 400))}</i>")
    return "\n".join(lines)


def remind_label(minutes: int) -> str:
    if minutes <= 0:
        return "в момент начала"
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        return "за день" if days == 1 else f"за {count(days, F_DAY)}"
    return f"за {human_duration(minutes)}"


def event_draft(draft: dict[str, Any], prompt: str) -> str:
    lines = [title("📌", "Новое событие")]
    if draft.get("title"):
        lines.append(f"<b>{esc(draft['title'])}</b>")
    lines.append(SEP)
    if draft.get("date"):
        d = date.fromisoformat(draft["date"])
        lines.append(f"📅 {fmt_date(d)}" + (f", {draft['time']}" if draft.get("time") else ""))
    if draft.get("remind") is not None:
        lines.append(f"🔔 Напомню {remind_label(int(draft['remind']))}")
    lines.append(prompt)
    return "\n".join(lines)


# ---------------------------------------------------------------- трекер

def tracker_screen(current: Activity | None, today_min: int, tz_name: str,
                   by_category: dict[str, int] | None = None, now: datetime | None = None) -> str:
    lines = [title("⏱", "Трекер"), SEP]
    if current and current.is_running:
        lines.append(f"Сейчас: {activity_status(current, tz_name, now)}")
        lines.append("<i>Нажми другую категорию — переключу, «⏹ Стоп» — остановлю.</i>")
    else:
        lines.append("⏸ <i>Сейчас ничего не идёт.</i>")
        lines.append("Выбери, чем займёшься, — запущу таймер.")
    lines.append("")
    lines.append(f"Сегодня отслежено: <b>{human_duration(today_min)}</b>")
    bars = category_bars(by_category or {}, limit=5)
    if bars:
        lines.extend(bars)
    return "\n".join(lines)


def tracker_stopped(act: Activity, tz_name: str) -> str:
    end = act.ended_at or now_utc()
    mins = max(0, int((end - act.started_at).total_seconds() // 60))
    s, e = to_local(act.started_at, tz_name), to_local(end, tz_name)
    desc = f" — {esc(truncate(act.description, 50))}" if act.description else ""
    return "\n".join([title("⏹", "Записал"),
                      f"{activity_label(act.category)}{desc}",
                      f"🕐 {s:%H:%M}{DASH}{e:%H:%M} · <b>{human_duration(mins)}</b>",
                      "",
                      "Насколько продуктивно было?"])


def tracker_rated(act: Activity, tz_name: str, rating: int | None) -> str:
    """Итог записи трекера после оценки (или пропуска оценки)."""
    end = act.ended_at or now_utc()
    mins = max(0, int((end - act.started_at).total_seconds() // 60))
    s, e = to_local(act.started_at, tz_name), to_local(end, tz_name)
    desc = f" — {esc(truncate(act.description, 50))}" if act.description else ""
    lines = [title("✅", "Записал"),
             f"{activity_label(act.category)}{desc}",
             f"🕐 {s:%H:%M}{DASH}{e:%H:%M} · <b>{human_duration(mins)}</b>"]
    if rating:
        lines.append(f"Продуктивность: {RATING_EMOJI.get(rating, '')} <b>{rating}/5</b>")
    else:
        lines.append("<i>Без оценки</i>")
    return "\n".join(lines)


def past_intro() -> str:
    return "\n".join([title("➕", "Записать прошедшее"), SEP, "Чем занимался? Выбери категорию ⬇️"])


def past_prompt(cat: str, step: str, ago: int | None = None) -> str:
    lines = [title("➕", "Записать прошедшее"), f"{activity_label(cat)}", SEP]
    if step == "ago":
        lines.append("⏪ Когда начал?")
    else:
        lines.append(f"⏪ Начал {human_duration(ago or 0)} назад")
        lines.append("⏱ Сколько длилось?")
    return "\n".join(lines)


# ---------------------------------------------------------------- статистика

def stats_day(stats: DayStats, heading: str) -> str:
    lines = [title("📊", "Статистика", heading), SEP]
    lines.extend(_focus_block(stats.focus_score))
    if stats.tracked_min:
        share = int(round(stats.productive_min * 100 / stats.tracked_min)) if stats.tracked_min else 0
        lines.append(f"⏱ Отслежено <b>{human_duration(stats.tracked_min)}</b>")
        lines.append(f"💼 Продуктивно <b>{human_duration(stats.productive_min)}</b> <i>({share}%)</i>")
    else:
        lines.append("⏱ <i>Трекер не запускался</i>")
    facts = [f"✅ Задач сделано: <b>{stats.tasks_done}</b>"]
    if stats.plan_items_total:
        facts.append(f"📋 План {stats.plan_items_done}/{stats.plan_items_total}")
    lines.append(" · ".join(facts))
    extra = []
    if stats.lessons_count:
        extra.append(f"🎓 {count(stats.lessons_count, F_LESSON)}")
    if stats.avg_rating:
        extra.append(f"⭐ Оценка {stats.avg_rating:.1f}/5")
    if extra:
        lines.append(" · ".join(extra))
    bars = category_bars(stats.minutes_by_category)
    if bars:
        lines.append("")
        lines.append("<b>По категориям</b>")
        lines.extend(bars)
    return "\n".join(lines)


def stats_period(stats: PeriodStats, heading: str) -> str:
    lines = [title("📊", "Статистика", heading), SEP]
    lines.extend(_focus_block(stats.avg_focus_score))
    days_n = max(1, (stats.end - stats.start).days + 1)
    if stats.tracked_min:
        lines.append(f"⏱ Отслежено <b>{human_duration(stats.tracked_min)}</b> "
                     f"<i>(≈{human_duration(stats.tracked_min // days_n)} в день)</i>")
        lines.append(f"💼 Продуктивно <b>{human_duration(stats.productive_min)}</b>")
    else:
        lines.append("⏱ <i>Трекер не запускался</i>")
    facts = [f"✅ Задач сделано: <b>{stats.tasks_done}</b>"]
    if stats.avg_rating:
        facts.append(f"⭐ {stats.avg_rating:.1f}/5")
    lines.append(" · ".join(facts))
    if stats.days:
        scores = [d.focus_score for d in stats.days]
        lines.append("")
        if len(stats.days) <= 7:
            lines.append("<b>Фокус по дням</b>")
            for day in stats.days:
                cup = " 🏆" if stats.best_day == day.date and day.focus_score else ""
                lines.append(f"{WEEKDAYS_SHORT[day.date.weekday()]} {bar(day.focus_score, 100)} "
                             f"{day.focus_score}{cup}")
        else:
            lines.append(f"<b>Фокус по дням</b>  {spark(scores, 100)}")
    if stats.best_day:
        best = next((d for d in stats.days if d.date == stats.best_day), None)
        lines.append(f"🏆 Лучший день: <b>{fmt_date(stats.best_day)}</b>"
                     + (f" — {best.focus_score}/100" if best else ""))
    bars = category_bars(stats.minutes_by_category)
    if bars:
        lines.append("")
        lines.append("<b>По категориям</b>")
        lines.extend(bars)
    return "\n".join(lines)


# ---------------------------------------------------------------- расписание

def week_timetable(monday: date, days: dict[int, list[Lesson]], *, parity: str, week_no: int | None,
                   today: date, study_days: set[int] | None = None) -> str:
    """study_days — дни недели (0..6), попадающие в семестр; остальные — каникулы."""
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        rng = f"{monday.day}{DASH}{sunday.day} {MONTHS_GEN[sunday.month - 1]}"
    else:
        rng = f"{monday.day} {MONTHS_SHORT[monday.month - 1]} {DASH} {sunday.day} {MONTHS_SHORT[sunday.month - 1]}"
    study = set(range(7)) if study_days is None else study_days
    if not study:
        lines = [title("🎓", f"Расписание · {rng}"), SEP, VACATION_LINE,
                 "<i>Учёба вне дат семестра не показывается — даты меняются в «⚙️ Настройки».</i>"]
        return "\n".join(lines)
    sub = (f"неделя {week_no} · " if week_no and week_no > 0 else "") + WEEK_PARITY_LABELS.get(parity, "")
    lines = [title("🎓", f"Расписание · {rng}", sub), SEP]
    total = 0
    for wd in range(7):
        d = monday + timedelta(days=wd)
        lessons = days.get(wd, [])
        mark = " · <i>сегодня</i>" if d == today else ""
        if wd not in study:
            if wd < 6 or lessons:
                lines.append(f"<b>{WEEKDAYS_SHORT[wd].capitalize()}, {d.day}</b> — 🏖 <i>каникулы</i>{mark}")
            continue
        if not lessons:
            if wd < 6:
                lines.append(f"<b>{WEEKDAYS_SHORT[wd].capitalize()}, {d.day}</b> — <i>нет пар</i>{mark}")
            continue
        total += len(lessons)
        lines.append(f"<b>{WEEKDAYS_FULL[wd]}, {d.day} {MONTHS_GEN[d.month - 1]}</b>{mark}")
        lines.extend(lesson_line(l, show_parity=True) for l in lessons)
        lines.append("")
    lines.append(SEP)
    lines.append(f"Всего {count(total, F_LESSON)} на неделе")
    return "\n".join(lines)


def lesson_draft(draft: dict[str, Any], prompt: str) -> str:
    lines = [title("➕", "Новая пара"), SEP]
    if draft.get("weekday") is not None:
        lines.append(f"📅 {WEEKDAYS_FULL[int(draft['weekday'])]}")
    if draft.get("start_time"):
        lines.append(f"🕘 {fmt_range(draft['start_time'], draft['end_time'])}")
    if draft.get("subject"):
        lines.append(f"📚 <b>{esc(draft['subject'])}</b>")
    if draft.get("kind") is not None:
        lines.append(f"🏷 {esc(draft['kind']) or '—'}")
    if draft.get("room") is not None:
        lines.append(f"📍 {esc(room_label(draft['room'])) or '—'}")
    lines.append("")
    lines.append(prompt)
    return "\n".join(lines)


def timetable_preview(lessons: list[dict[str, Any]], skipped: int = 0) -> str:
    lines = [title("📷", "Распознал расписание", count(len(lessons), F_LESSON)), SEP]
    by_day: dict[int, list[dict[str, Any]]] = {}
    for l in lessons:
        by_day.setdefault(int(l["weekday"]), []).append(l)
    for wd in sorted(by_day):
        lines.append(f"<b>{WEEKDAYS_FULL[wd]}</b>")
        for l in sorted(by_day[wd], key=lambda x: x["start_time"]):
            fake = Lesson(id=0, user_id=0, weekday=wd, start_time=l["start_time"], end_time=l["end_time"],
                          subject=l["subject"], kind=l.get("kind") or "", room=l.get("room"),
                          teacher=l.get("teacher"), parity=l.get("parity") or "all")
            lines.append(lesson_line(fake, show_parity=True))
    if skipped:
        lines.append("")
        lines.append(f"<i>⚠️ Не разобрал строк: {skipped}</i>")
    lines.append("")
    lines.append("Что сделать с текущим расписанием?")
    return "\n".join(lines)


# ---------------------------------------------------------------- настройки

def settings_screen(s: UserSettings, today: date) -> str:
    onoff = {True: "вкл", False: "выкл"}
    checkins = f"каждые {human_duration(s.checkin_interval_min)}" if s.checkin_enabled else "выкл"
    lines = [title("⚙️", "Настройки"), SEP,
             f"🌍 Пояс: <b>{tz_line(s)}</b>",
             f"⏰ Подъём <b>{s.wake_time}</b> · 🌙 Отбой <b>{s.sleep_time}</b>",
             f"☀️ Сводка <b>{s.morning_brief_time}</b> · 🌆 План на завтра <b>{s.evening_plan_time}</b>",
             f"👋 Чек-ины: <b>{checkins}</b>",
             f"🎓 О паре за <b>{s.class_reminder_min} мин</b> · 📌 О событии {remind_label(s.event_reminder_min)}",
             f"📋 Напоминания плана: <b>{onoff[bool(s.plan_reminders)]}</b>",
             f"⚡ Пик продуктивности: <b>{FOCUS_PEAK_LABELS.get(s.focus_peak, s.focus_peak)}</b>",
             f"🚌 Дорога до универа: <b>{human_duration(s.commute_min) if s.commute_min else 'нет'}</b>"]
    def _d(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return fmt_date(date.fromisoformat(value), weekday=False, year=True)
        except ValueError:
            return esc(value)

    start, end = _d(s.semester_start), _d(s.semester_end)
    if start or end:
        lines.append(f"📆 Семестр: <b>{start or '…'}</b> — <b>{end or '…'}</b>")
    else:
        lines.append("📆 Семестр: <i>даты не заданы (чётность по календарю)</i>")
    if not in_semester(today, s):
        lines.append(f"   <i>{VACATION_LINE}</i>")
    else:
        wl = week_label(today, s)
        if wl:
            lines.append(f"   <i>сейчас {wl}</i>")
    lines.append(f"🤫 Тихий режим: <b>{onoff[bool(s.quiet)]}</b> · 🤖 ИИ: <b>{onoff[bool(s.ai_enabled)]}</b>")
    lines.append(SEP)
    lines.append("<i>Выбери, что поменять:</i>")
    return "\n".join(lines)


SETTING_TITLES = {
    "tz": "🌍 Часовой пояс", "wake": "⏰ Подъём", "sleep": "🌙 Отбой",
    "mb": "☀️ Утренняя сводка", "ep": "🌆 Вечерний план", "ci": "👋 Чек-ины",
    "cr": "🎓 Напоминание о паре", "er": "📌 Напоминание о событии",
    "pr": "📋 Напоминания плана", "fp": "⚡ Пик продуктивности", "cm": "🚌 Дорога до универа",
    "ss": "📆 Начало семестра", "se": "🏁 Конец семестра", "q": "🤫 Тихий режим", "ai": "🤖 ИИ",
    "ta": "🔄 Автосмена пояса",
}


def setting_prompt(field: str, s: UserSettings) -> str:
    hints = {
        "tz": "Выбери город или напиши свой: «Europe/Berlin», «UTC+5».",
        "wake": "Во сколько встаёшь? Можно написать своё время, например «6:45».",
        "sleep": "Во сколько ложишься?",
        "mb": "Когда присылать утреннюю сводку?",
        "ep": "Когда присылать итоги дня и план на завтра?",
        "ci": "Как часто спрашивать «Что делаешь?»",
        "cr": "За сколько минут напоминать о паре?",
        "er": "За сколько напоминать о новых событиях (по умолчанию)?",
        "fp": "Когда у тебя больше всего сил? Сложные задачи поставлю туда.",
        "cm": "Сколько ехать до универа? Учту буфер перед первой парой.",
        "ss": "С какой даты начался семестр? Первая неделя — нечётная (числитель).\n"
              "Или просто скажи, какая неделя сейчас. Можно написать дату: «01.09.2026».",
        "se": "Когда заканчивается семестр? После этой даты пары не показываю — 🏖 каникулы.\n"
              "Можно написать дату: «31.01.2027».",
    }
    lines = [title("", SETTING_TITLES.get(field, "Настройка")), SEP]
    if field == "tz":
        lines.append(f"Сейчас: <b>{tz_line(s)}</b>")
        rules = tz_rules_text(s)
        if rules:
            lines.append(f"🔄 Автосмена: <i>{rules}</i>")
            lines.append("<i>Ручной выбор пояса выключит автосмену.</i>")
    lines.append(hints.get(field, "Выбери вариант:"))
    return "\n".join(lines)


# ---------------------------------------------------------------- ИИ

def ai_help(*, available: bool, enabled: bool) -> str:
    lines = [title("🤖", "ИИ-помощник"), SEP]
    if not available:
        lines.append("⚠️ ИИ не подключён: в .env не задан <code>ANTHROPIC_API_KEY</code>.")
        lines.append("Без него всё остальное работает: задачи, план, трекер, расписание.")
        return "\n".join(lines)
    if not enabled:
        lines.append("⏸ ИИ выключен в настройках — включи, чтобы я понимал обычный текст.")
        return "\n".join(lines)
    lines.extend([
        "Пиши обычным текстом — я сам создам задачи и события, запущу трекер, отвечу про расписание.",
        "",
        "<b>Например:</b>",
        "• <i>завтра в 18:00 встреча с научруком, напомни за час</i>",
        "• <i>курсовая по матану до пятницы, часа на 4</i>",
        "• <i>начинаю делать домашку по физике</i>",
        "• <i>какие пары в четверг?</i>",
        "• <i>сколько я сегодня учился?</i>",
        "• <i>что лучше сделать сейчас?</i>",
        "",
        "📷 Пришли фото расписания — распознаю пары.",
        "<i>Я помню последние сообщения. «🧹 Очистить контекст» — начать с чистого листа.</i>",
    ])
    return "\n".join(lines)


def ai_reply(text: str, actions: Iterable[str] = ()) -> str:
    body = sanitize_html(text).strip() or "🤔"
    acts = [esc(a) for a in actions if a]
    if acts:
        body += "\n\n<blockquote>" + "\n".join(acts) + "</blockquote>"
    return body


def free_text_offer(text: str) -> str:
    return "\n".join([title("💡", "Записать?"),
                      f"«{esc(truncate(text, 200))}»",
                      "",
                      "<i>Сделать из этого задачу или событие?</i>"])
