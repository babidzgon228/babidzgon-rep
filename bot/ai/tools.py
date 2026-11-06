"""Инструменты ассистента: JSON-схемы для Claude и их исполнение на БД конкретного пользователя.

user_id модель никогда не передаёт: ToolExecutor привязан к одному User.
Время от модели — локальное (user.settings.tz), внутри конвертируется в aware datetime.
"""
from __future__ import annotations

import json
import logging
import re
from calendar import monthrange
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Awaitable, Callable

from bot.ai.formatting import escape, human_date, human_dt
from bot.models import (
    ACTIVITY_CATEGORIES,
    ENERGY_LABELS,
    ENERGY_LEVELS,
    EVENT_KINDS,
    IMPORTANCE_LABELS,
    TASK_CATEGORIES,
    WEEKDAYS_FULL,
    WEEKDAYS_SHORT,
    Event,
    Lesson,
    Task,
    User,
)
from bot.services import planner, prioritizer, stats
from bot.services.timetable import lessons_for_date, normalize_lesson_dict, week_number, week_parity
from bot.timeutil import (
    day_bounds_utc,
    human_duration,
    local_today,
    minutes_of,
    now_utc,
    to_local,
    tz,
)

log = logging.getLogger(__name__)

PARITY_LABELS = {"all": "каждую неделю", "odd": "числитель", "even": "знаменатель"}
MAX_TASK_ESTIMATE = 24 * 60
MAX_LIST_RANGE_DAYS = 92


class ToolError(Exception):
    """Ошибка входных данных инструмента — возвращается модели как tool_result is_error=true."""


# ---------------------------------------------------------------- схемы

_DT = "Локальное время пользователя: YYYY-MM-DDTHH:MM"
_DATE = "Дата YYYY-MM-DD (локальная)"
_HHMM = "Время HH:MM (24 ч)"


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [],
            "additionalProperties": False}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "add_task",
        "description": (
            "Создать задачу (дело, которое нужно сделать, возможно с дедлайном). Вызывай, когда пользователь "
            "говорит, что ему надо что-то сделать/подготовить/не забыть. Если важность, время или сложность "
            "не названы — оцени сами. Для встреч и мероприятий в конкретное время используй add_event."),
        "input_schema": _obj({
            "title": {"type": "string", "description": "Короткое название задачи без даты, например «Курсач по ТАУ»"},
            "importance": {"type": "integer", "enum": [1, 2, 3],
                           "description": "1 — низкая, 2 — средняя, 3 — высокая"},
            "estimate_min": {"type": "integer", "description": "Оценка времени в минутах (5–1440)"},
            "energy": {"type": "string", "enum": list(ENERGY_LEVELS),
                       "description": "Сложность: low — рутина, medium — средне, high — тяжёлая умственная работа"},
            "category": {"type": "string", "enum": list(TASK_CATEGORIES)},
            "deadline": {"type": "string",
                         "description": f"Дедлайн. {_DT}. Без названного времени — 23:59. Не передавай, если срока нет"},
            "notes": {"type": "string", "description": "Заметки/подробности, если есть"},
        }, ["title", "importance", "estimate_min", "energy", "category"]),
    },
    {
        "name": "list_tasks",
        "description": (
            "Список активных задач, отсортированный по приоритету (score 0–100 и квадрант Эйзенхауэра). "
            "Вызывай, когда спрашивают про задачи/дела/что важнее, или когда нужен id задачи, которого нет в контексте."),
        "input_schema": _obj({}),
    },
    {
        "name": "update_task",
        "description": "Изменить задачу: перенести дедлайн, переименовать, поменять важность/оценку/сложность.",
        "input_schema": _obj({
            "task_id": {"type": "integer"},
            "title": {"type": "string"},
            "importance": {"type": "integer", "enum": [1, 2, 3]},
            "deadline": {"type": "string", "description": f"{_DT}; строка «none» — убрать дедлайн"},
            "estimate_min": {"type": "integer"},
            "energy": {"type": "string", "enum": list(ENERGY_LEVELS)},
            "category": {"type": "string", "enum": list(TASK_CATEGORIES)},
            "notes": {"type": "string"},
        }, ["task_id"]),
    },
    {
        "name": "complete_task",
        "description": "Отметить задачу выполненной. Вызывай, когда пользователь говорит, что сделал задачу.",
        "input_schema": _obj({"task_id": {"type": "integer"}}, ["task_id"]),
    },
    {
        "name": "delete_task",
        "description": "Удалить задачу совсем (только если пользователь явно просит удалить/отменить её).",
        "input_schema": _obj({"task_id": {"type": "integer"}}, ["task_id"]),
    },
    {
        "name": "add_event",
        "description": (
            "Добавить событие в календарь: встречу, консультацию, экзамен, дедлайн сдачи, день рождения — "
            "всё, что происходит в конкретное время. Бот напомнит заранее."),
        "input_schema": _obj({
            "title": {"type": "string", "description": "Название, например «Встреча с куратором»"},
            "start": {"type": "string", "description": f"Начало. {_DT}"},
            "end": {"type": "string", "description": f"Конец (если известен). {_DT}"},
            "location": {"type": "string", "description": "Место, если названо"},
            "remind_before_min": {"type": "integer",
                                  "description": "За сколько минут напомнить (по умолчанию — из настроек)"},
            "kind": {"type": "string", "enum": list(EVENT_KINDS),
                     "description": "event — обычное, meeting — встреча, exam — экзамен/зачёт, deadline, birthday"},
        }, ["title", "start"]),
    },
    {
        "name": "list_events",
        "description": "События в диапазоне дат (включительно). Вызывай для вопросов о встречах/экзаменах на период.",
        "input_schema": _obj({
            "date_from": {"type": "string", "description": _DATE},
            "date_to": {"type": "string", "description": f"{_DATE}, включительно"},
        }, ["date_from", "date_to"]),
    },
    {
        "name": "delete_event",
        "description": "Удалить событие (только если пользователь явно просит удалить/отменить его).",
        "input_schema": _obj({"event_id": {"type": "integer"}}, ["event_id"]),
    },
    {
        "name": "get_day",
        "description": (
            "Всё о конкретном дне: пары (с учётом чётности недели), события, дедлайны задач и план дня. "
            "Вызывай на вопросы «что у меня сегодня/завтра/в четверг»."),
        "input_schema": _obj({"date": {"type": "string", "description": _DATE}}, ["date"]),
    },
    {
        "name": "get_week_timetable",
        "description": "Расписание пар на текущую или следующую неделю с учётом числителя/знаменателя.",
        "input_schema": _obj({"week": {"type": "string", "enum": ["current", "next"]}}, ["week"]),
    },
    {
        "name": "start_tracking",
        "description": (
            "Запустить трекер времени: пользователь начинает чем-то заниматься прямо сейчас. "
            "Текущая активность (если есть) остановится автоматически."),
        "input_schema": _obj({
            "category": {"type": "string", "enum": list(ACTIVITY_CATEGORIES),
                         "description": ", ".join(f"{k} — {v[1]}" for k, v in ACTIVITY_CATEGORIES.items())},
            "description": {"type": "string", "description": "Чем именно занят, например «курсач» или «матан»"},
        }, ["category"]),
    },
    {
        "name": "stop_tracking",
        "description": "Остановить текущую активность трекера, по возможности с самооценкой продуктивности 1–5.",
        "input_schema": _obj({
            "rating": {"type": "integer", "enum": [1, 2, 3, 4, 5],
                       "description": "1 — совсем непродуктивно … 5 — отлично. Не передавай, если оценки нет"},
        }),
    },
    {
        "name": "log_activity",
        "description": "Записать в трекер уже прошедшую активность («вчера с 18 до 19 был в зале»).",
        "input_schema": _obj({
            "category": {"type": "string", "enum": list(ACTIVITY_CATEGORIES)},
            "start": {"type": "string", "description": f"Начало. {_DT}"},
            "end": {"type": "string", "description": f"Конец. {_DT}. Либо end, либо duration_min"},
            "duration_min": {"type": "integer", "description": "Длительность в минутах, если конец не назван"},
            "description": {"type": "string"},
            "rating": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        }, ["category", "start"]),
    },
    {
        "name": "get_stats",
        "description": (
            "Статистика трекера и эффективности: время по категориям, продуктивное время, оценки, выполненные "
            "задачи, focus score. period: day — за дату, week — календарная неделя с этой датой, month — месяц."),
        "input_schema": _obj({
            "period": {"type": "string", "enum": ["day", "week", "month"]},
            "date": {"type": "string", "description": f"{_DATE}; обычно сегодня"},
        }, ["period", "date"]),
    },
    {
        "name": "build_plan",
        "description": (
            "Составить (пересоставить) план дня алгоритмом: пары и события — фиксированно, задачи — в свободные "
            "окна по приоритету. Сохраняется как черновик. Вызывай на «составь/обнови план на …»."),
        "input_schema": _obj({"date": {"type": "string", "description": _DATE}}, ["date"]),
    },
    {
        "name": "add_lesson",
        "description": "Добавить пару в недельное учебное расписание.",
        "input_schema": _obj({
            "weekday": {"type": "string", "enum": WEEKDAYS_SHORT},
            "start": {"type": "string", "description": _HHMM},
            "end": {"type": "string", "description": _HHMM},
            "subject": {"type": "string"},
            "weeks": {"type": "string", "enum": ["all", "odd", "even"],
                      "description": "all — каждую неделю, odd — числитель, even — знаменатель"},
            "kind": {"type": "string", "description": "лекция / практика / лаба / семинар"},
            "room": {"type": "string"},
            "teacher": {"type": "string"},
        }, ["weekday", "start", "end", "subject", "weeks"]),
    },
]

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {t["name"]: t["input_schema"] for t in TOOLS}
# Стабильные (байт-в-байт) списки для запросов — важно для prompt caching.
TOOLS_STRICT: list[dict[str, Any]] = [{**t, "strict": True} for t in TOOLS]

MUTATING_TOOLS = frozenset({"add_task", "update_task", "complete_task", "delete_task", "add_event",
                            "delete_event", "start_tracking", "stop_tracking", "log_activity",
                            "build_plan", "add_lesson"})


# ---------------------------------------------------------------- валидация

_PY_TYPES: dict[str, Any] = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
                             "object": dict, "array": list, "null": type(None)}


def validate_input(schema: dict[str, Any], value: Any, path: str = "input") -> None:
    """Мини-валидатор JSON Schema (type/enum/required/additionalProperties/items).

    Strict tool use гарантирует схему на стороне API, но проверяем всё равно (защита от деградации)."""
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        ok = False
        for tt in types:
            if tt in ("integer", "number") and isinstance(value, bool):
                continue
            if tt == "integer" and isinstance(value, float) and value.is_integer():
                ok = True
                break
            if isinstance(value, _PY_TYPES[tt]):
                ok = True
                break
        if not ok:
            raise ToolError(f"{path}: ожидался тип {t}, получено {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolError(f"{path}: допустимые значения {schema['enum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        missing = [k for k in schema.get("required", []) if k not in value]
        if missing:
            raise ToolError(f"{path}: нет обязательных полей {missing}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(props))
            if extra:
                raise ToolError(f"{path}: лишние поля {extra}")
        for k, v in value.items():
            if k in props:
                validate_input(props[k], v, f"{path}.{k}")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            validate_input(schema["items"], v, f"{path}[{i}]")


_RELATIVE_DAYS = {"today": 0, "сегодня": 0, "tomorrow": 1, "завтра": 1, "yesterday": -1, "вчера": -1,
                  "послезавтра": 2}


def parse_date(value: str, tz_name: str) -> date:
    s = (value or "").strip().lower()
    if s in _RELATIVE_DAYS:
        return local_today(tz_name) + timedelta(days=_RELATIVE_DAYS[s])
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        raise ToolError(f"Не понял дату {value!r}: нужен формат YYYY-MM-DD") from None


def parse_local_dt(value: str, tz_name: str) -> tuple[datetime, bool]:
    """'2026-11-07T15:00' (локальное) -> (aware datetime, было ли время)."""
    s = (value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{1,2}:\d{2}(:\d{2})?", s):
        s = s.replace(" ", "T", 1)
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return datetime.combine(date.fromisoformat(s), time(0, 0), tzinfo=tz(tz_name)), False
        except ValueError:
            raise ToolError(f"Не понял дату {value!r}") from None
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T(\d{1,2}):(\d{2})(.*)", s)
    if m:  # 'T9:00' -> 'T09:00'
        s = f"{m.group(1)}T{int(m.group(2)):02d}:{m.group(3)}{m.group(4)}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ToolError(f"Не понял дату/время {value!r}: нужен формат YYYY-MM-DDTHH:MM") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz(tz_name))
    return dt, True


def safe_prioritize(tasks: list[Task], now: datetime) -> list[tuple[Task, float | None, str | None]]:
    """[(task, score, quadrant)] по убыванию приоритета. Не падает, если prioritizer ещё не готов."""
    todo = [t for t in tasks if t.status == "todo"]
    try:
        ordered = prioritizer.prioritize(todo, now)
        return [(t, float(prioritizer.score_task(t, now)), prioritizer.quadrant(t, now)) for t in ordered]
    except Exception as e:  # noqa: BLE001 — сервис чужой, не даём ему уронить ИИ
        log.debug("prioritizer недоступен (%s), сортирую по дедлайну/важности", e)
        far = datetime.max.replace(tzinfo=now.tzinfo)
        ordered = sorted(todo, key=lambda t: (t.deadline or far, -t.importance, t.id))
        return [(t, None, None) for t in ordered]


def _json(obj: Any) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if is_dataclass(o):
            return asdict(o)  # type: ignore[arg-type]
        return str(o)
    return json.dumps(obj, ensure_ascii=False, default=default)


def _short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _q(text: str) -> str:
    """«Название» — экранировано для Telegram-HTML."""
    return f"«{escape(_short(text))}»"


# ---------------------------------------------------------------- исполнитель

Handler = Callable[["ToolExecutor", dict[str, Any]], Awaitable[dict[str, Any]]]


class ToolExecutor:
    """Выполняет вызовы инструментов для одного пользователя, копит actions/changed."""

    def __init__(self, db, user: User) -> None:
        self.db = db
        self.user = user
        self.tz = user.settings.tz
        self.actions: list[str] = []
        self.changed = False

    # ---- helpers
    @property
    def today(self) -> date:
        return local_today(self.tz)

    def _loc(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        l = to_local(dt, self.tz)
        return f"{l:%Y-%m-%d %H:%M} ({WEEKDAYS_SHORT[l.weekday()]})"

    def _human(self, dt: datetime) -> str:
        return human_dt(to_local(dt, self.tz), self.today)

    def _dt(self, value: str, *, need_time: bool = True, end_of_day: bool = False) -> datetime:
        dt, has_time = parse_local_dt(value, self.tz)
        if not has_time:
            if end_of_day:
                dt = dt.replace(hour=23, minute=59)
            elif need_time:
                raise ToolError(f"В {value!r} нет времени: нужен формат YYYY-MM-DDTHH:MM. Если время неизвестно — "
                                "уточни у пользователя (для событий на весь день можно 09:00).")
        return dt

    async def _own_task(self, task_id: int) -> Task:
        task = await self.db.get_task(int(task_id))
        if not task or task.user_id != self.user.id:
            raise ToolError(f"Задача id={task_id} не найдена. Посмотри актуальные id через list_tasks.")
        return task

    async def _own_event(self, event_id: int) -> Event:
        event = await self.db.get_event(int(event_id))
        if not event or event.user_id != self.user.id:
            raise ToolError(f"Событие id={event_id} не найдено. Посмотри актуальные id через list_events.")
        return event

    def _act(self, text: str) -> None:
        self.actions.append(text)

    def _task_brief(self, t: Task, score: float | None = None, q: str | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": t.id, "title": t.title, "importance": t.importance, "deadline": self._loc(t.deadline),
            "estimate_min": t.estimate_min, "energy": t.energy, "category": t.category,
        }
        if t.notes:
            d["notes"] = _short(t.notes, 200)
        if t.planned_date:
            d["planned_date"] = t.planned_date.isoformat()
        if score is not None:
            d["score"] = round(score)
        if q:
            d["quadrant"] = prioritizer.QUADRANT_LABELS.get(q, q)
        return d

    def _lesson_brief(self, l: Lesson) -> dict[str, Any]:
        return {"id": l.id, "start": l.start_time, "end": l.end_time, "subject": l.subject, "kind": l.kind or None,
                "room": l.room, "teacher": l.teacher, "weeks": PARITY_LABELS.get(l.parity, l.parity)}

    def _event_brief(self, e: Event) -> dict[str, Any]:
        return {"id": e.id, "title": e.title, "start": self._loc(e.start_at), "end": self._loc(e.end_at),
                "location": e.location, "kind": e.kind, "remind_before_min": e.remind_before_min}

    # ---- entry point
    async def run(self, name: str, args: Any) -> tuple[str, bool]:
        """Возвращает (content для tool_result, is_error)."""
        handler = _HANDLERS.get(name)
        if handler is None:
            return _json({"error": f"Неизвестный инструмент {name!r}"}), True
        try:
            if not isinstance(args, dict):
                raise ToolError("Аргументы инструмента должны быть JSON-объектом")
            validate_input(TOOL_SCHEMAS[name], args)
            result = await handler(self, args)
            if name in MUTATING_TOOLS and result.get("ok", True) and not result.get("noop"):
                self.changed = True
            return _json(result), False
        except ToolError as e:
            log.info("tool %s: ошибка входа: %s", name, e)
            return _json({"error": str(e)}), True
        except Exception:  # noqa: BLE001
            log.exception("tool %s упал", name)
            return _json({"error": "Внутренняя ошибка при выполнении. Не повторяй этот вызов, "
                                   "скажи пользователю, что действие не удалось."}), True

    # ---- tasks
    async def add_task(self, a: dict[str, Any]) -> dict[str, Any]:
        title = a["title"].strip()
        if not title:
            raise ToolError("Пустое название задачи")
        deadline = self._dt(a["deadline"], end_of_day=True) if a.get("deadline") else None
        est = max(5, min(MAX_TASK_ESTIMATE, int(a["estimate_min"])))
        task = await self.db.add_task(
            self.user.id, title[:200], notes=(a.get("notes") or "").strip() or None,
            importance=int(a["importance"]), deadline=deadline, estimate_min=est,
            energy=a["energy"], category=a["category"])
        suffix = f" (до {self._human(deadline)})" if deadline else ""
        self._act(f"➕ Задача {_q(task.title)}{suffix}")
        return {"ok": True, "task": self._task_brief(task)}

    async def list_tasks(self, a: dict[str, Any]) -> dict[str, Any]:
        tasks = await self.db.list_tasks(self.user.id, "todo")
        ranked = safe_prioritize(tasks, now_utc())
        return {"count": len(ranked), "tasks": [self._task_brief(t, s, q) for t, s, q in ranked[:30]],
                **({"note": f"показаны первые 30 из {len(ranked)}"} if len(ranked) > 30 else {})}

    async def update_task(self, a: dict[str, Any]) -> dict[str, Any]:
        task = await self._own_task(a["task_id"])
        fields: dict[str, Any] = {}
        changes: list[str] = []
        if "title" in a:
            title = a["title"].strip()
            if not title:
                raise ToolError("Пустое название задачи")
            fields["title"] = title[:200]
            changes.append(f"название → {_q(title)}")
        if "importance" in a:
            fields["importance"] = int(a["importance"])
            changes.append(f"важность → {IMPORTANCE_LABELS[int(a['importance'])]}")
        if "deadline" in a:
            raw = a["deadline"].strip()
            if raw.lower() in ("", "none", "null", "нет"):
                fields["deadline"] = None
                changes.append("без дедлайна")
            else:
                dl = self._dt(raw, end_of_day=True)
                fields["deadline"] = dl
                changes.append(f"дедлайн → {self._human(dl)}")
        if "estimate_min" in a:
            fields["estimate_min"] = max(5, min(MAX_TASK_ESTIMATE, int(a["estimate_min"])))
            changes.append(f"оценка → {human_duration(fields['estimate_min'])}")
        if "energy" in a:
            fields["energy"] = a["energy"]
            changes.append(f"сложность → {ENERGY_LABELS[a['energy']]}")
        if "category" in a:
            fields["category"] = a["category"]
            changes.append(f"категория → {TASK_CATEGORIES[a['category']][1].lower()}")
        if "notes" in a:
            fields["notes"] = a["notes"].strip() or None
            changes.append("заметки")
        if not fields:
            raise ToolError("Нечего менять: передай хотя бы одно поле")
        updated = await self.db.update_task(task.id, **fields)
        self._act(f"✏️ Задача {_q(task.title)}: {', '.join(changes)}")
        return {"ok": True, "task": self._task_brief(updated)}

    async def complete_task(self, a: dict[str, Any]) -> dict[str, Any]:
        task = await self._own_task(a["task_id"])
        if task.status == "done":
            return {"ok": True, "noop": True, "note": "задача уже была выполнена"}
        await self.db.complete_task(task.id)
        self._act(f"✅ Задача {_q(task.title)} выполнена")
        return {"ok": True, "task_id": task.id, "status": "done"}

    async def delete_task(self, a: dict[str, Any]) -> dict[str, Any]:
        task = await self._own_task(a["task_id"])
        await self.db.delete_task(task.id)
        self._act(f"🗑 Задача {_q(task.title)} удалена")
        return {"ok": True, "deleted_task_id": task.id}

    # ---- events
    async def add_event(self, a: dict[str, Any]) -> dict[str, Any]:
        title = a["title"].strip()
        if not title:
            raise ToolError("Пустое название события")
        start = self._dt(a["start"])
        end = self._dt(a["end"]) if a.get("end") else None
        if end is not None and end <= start:
            raise ToolError("Конец события должен быть позже начала")
        if end is not None and end - start > timedelta(days=7):
            raise ToolError("Событие длиннее недели — проверь даты")
        remind = int(a.get("remind_before_min", self.user.settings.event_reminder_min))
        remind = max(0, min(remind, 7 * 24 * 60))
        kind = a.get("kind") or "event"
        event = await self.db.add_event(self.user.id, title[:200], start, end_at=end,
                                        location=(a.get("location") or "").strip() or None,
                                        remind_before_min=remind, kind=kind)
        when = self._human(start) + (f"–{to_local(end, self.tz):%H:%M}" if end and
                                     to_local(end, self.tz).date() == to_local(start, self.tz).date() else "")
        emoji = EVENT_KINDS.get(kind, "📌").split(" ")[0]
        self._act(f"{emoji} Событие {_q(event.title)} — {when}")
        warn = {"warning": "Событие в прошлом — проверь дату"} if start < now_utc() - timedelta(minutes=5) else {}
        return {"ok": True, "event": self._event_brief(event), **warn}

    async def list_events(self, a: dict[str, Any]) -> dict[str, Any]:
        d1, d2 = parse_date(a["date_from"], self.tz), parse_date(a["date_to"], self.tz)
        if d2 < d1:
            d1, d2 = d2, d1
        if (d2 - d1).days > MAX_LIST_RANGE_DAYS:
            raise ToolError(f"Слишком большой диапазон: максимум {MAX_LIST_RANGE_DAYS} дней")
        start, _ = day_bounds_utc(d1, self.tz)
        _, end = day_bounds_utc(d2, self.tz)
        events = await self.db.list_events(self.user.id, start, end)
        return {"from": d1.isoformat(), "to": d2.isoformat(), "count": len(events),
                "events": [self._event_brief(e) for e in events]}

    async def delete_event(self, a: dict[str, Any]) -> dict[str, Any]:
        event = await self._own_event(a["event_id"])
        await self.db.delete_event(event.id)
        self._act(f"🗑 Событие {_q(event.title)} удалено")
        return {"ok": True, "deleted_event_id": event.id}

    # ---- days / timetable
    async def get_day(self, a: dict[str, Any]) -> dict[str, Any]:
        d = parse_date(a["date"], self.tz)
        s = self.user.settings
        lessons = await lessons_for_date(self.db, self.user, d)
        start, end = day_bounds_utc(d, self.tz)
        events = await self.db.list_events(self.user.id, start, end)
        tasks = await self.db.list_tasks(self.user.id, "todo")
        deadlines = [t for t in tasks if t.deadline and start <= t.deadline < end]
        plan = await self.db.get_plan(self.user.id, d)
        parity = week_parity(d, s)
        return {
            "date": d.isoformat(), "weekday": WEEKDAYS_FULL[d.weekday()].lower(),
            "week_number": week_number(d, s), "week_parity": f"{parity} ({PARITY_LABELS[parity]})",
            "lessons": [self._lesson_brief(l) for l in lessons],
            "events": [self._event_brief(e) for e in events],
            "deadlines": [{"task_id": t.id, "title": t.title, "deadline": self._loc(t.deadline)} for t in deadlines],
            "plan": None if not plan else {
                "status": plan.status,
                "items": [{"start": i.start, "end": i.end, "kind": i.kind, "title": i.title, "done": i.done}
                          for i in plan.items],
            },
        }

    async def get_week_timetable(self, a: dict[str, Any]) -> dict[str, Any]:
        today = self.today
        monday = today - timedelta(days=today.weekday()) + timedelta(days=7 if a["week"] == "next" else 0)
        s = self.user.settings
        parity = week_parity(monday, s)
        days = []
        for i in range(7):
            d = monday + timedelta(days=i)
            lessons = await lessons_for_date(self.db, self.user, d)
            days.append({"date": d.isoformat(), "weekday": WEEKDAYS_SHORT[i],
                         "lessons": [self._lesson_brief(l) for l in lessons]})
        return {"week": a["week"], "week_number": week_number(monday, s),
                "week_parity": f"{parity} ({PARITY_LABELS[parity]})", "days": days}

    async def add_lesson(self, a: dict[str, Any]) -> dict[str, Any]:
        raw = {"day": a["weekday"], "time": f"{a['start'].strip()}-{a['end'].strip()}", "subject": a["subject"],
               "kind": a.get("kind"), "room": a.get("room"), "teacher": a.get("teacher"), "weeks": a["weeks"]}
        try:
            norm = normalize_lesson_dict(raw)
            if minutes_of(norm["start_time"]) >= minutes_of(norm["end_time"]):
                raise ValueError("начало пары должно быть раньше конца")
        except ValueError as e:
            raise ToolError(f"Некорректная пара: {e}") from None
        existing = await self.db.list_lessons(self.user.id, weekday=norm["weekday"])
        for l in existing:
            if (l.start_time, l.subject.lower(), l.parity) == (norm["start_time"], norm["subject"].lower(),
                                                                norm["parity"]):
                return {"ok": True, "noop": True, "note": "такая пара уже есть", "lesson": self._lesson_brief(l)}
        lesson = await self.db.add_lesson(self.user.id, **norm)
        parity = "" if lesson.parity == "all" else f" ({PARITY_LABELS[lesson.parity]})"
        self._act(f"🎓 Пара {_q(lesson.subject)} — {WEEKDAYS_SHORT[lesson.weekday]} "
                  f"{lesson.start_time}–{lesson.end_time}{parity}")
        return {"ok": True, "lesson": self._lesson_brief(lesson)}

    # ---- tracker
    async def start_tracking(self, a: dict[str, Any]) -> dict[str, Any]:
        cat = a["category"]
        desc = (a.get("description") or "").strip() or None
        prev = await self.db.current_activity(self.user.id)
        act = await self.db.start_activity(self.user.id, cat, desc, source="ai")
        result: dict[str, Any] = {"ok": True, "activity_id": act.id, "category": cat,
                                  "started_at": self._loc(act.started_at)}
        if prev:
            mins = int((act.started_at - prev.started_at).total_seconds() // 60)
            result["stopped_previous"] = {"category": prev.category, "minutes": mins}
            self._act(f"⏹ Остановлено: {self._cat(prev.category)} ({human_duration(mins)})")
        self._act(f"▶️ Трекер: {self._cat(cat)}" + (f" — {_q(desc)}" if desc else ""))
        return result

    async def stop_tracking(self, a: dict[str, Any]) -> dict[str, Any]:
        act = await self.db.stop_activity(self.user.id)
        if act is None:
            raise ToolError("Сейчас трекер не запущен — останавливать нечего")
        mins = int(((act.ended_at or now_utc()) - act.started_at).total_seconds() // 60)
        rating = a.get("rating")
        if rating is not None:
            await self.db.rate_activity(act.id, int(rating))
        self._act(f"⏹ Трекер остановлен: {self._cat(act.category)}, {human_duration(mins)}"
                  + (f", оценка {int(rating)}/5" if rating is not None else ""))
        return {"ok": True, "activity_id": act.id, "category": act.category, "minutes": mins,
                "rating": rating}

    async def log_activity(self, a: dict[str, Any]) -> dict[str, Any]:
        start = self._dt(a["start"])
        if a.get("end"):
            end = self._dt(a["end"])
        elif a.get("duration_min") is not None:
            end = start + timedelta(minutes=int(a["duration_min"]))
        else:
            raise ToolError("Нужен end или duration_min")
        if end <= start:
            raise ToolError("Конец должен быть позже начала")
        if end - start > timedelta(hours=24):
            raise ToolError("Активность длиннее суток — проверь время")
        if end > now_utc() + timedelta(minutes=10):
            raise ToolError("Активность ещё не закончилась — для текущих дел используй start_tracking")
        desc = (a.get("description") or "").strip() or None
        rating = a.get("rating")
        act = await self.db.add_activity(self.user.id, a["category"], start, end, description=desc,
                                         rating=int(rating) if rating is not None else None, source="ai")
        mins = int((end - start).total_seconds() // 60)
        ls, le = to_local(start, self.tz), to_local(end, self.tz)
        self._act(f"📝 Записал: {self._cat(act.category)}, {human_date(ls.date(), self.today)} "
                  f"{ls:%H:%M}–{le:%H:%M} ({human_duration(mins)})")
        return {"ok": True, "activity_id": act.id, "minutes": mins}

    def _cat(self, key: str) -> str:
        emoji, label = ACTIVITY_CATEGORIES.get(key, ("✍️", key))
        return f"{emoji} {label}"

    # ---- stats / plan
    async def get_stats(self, a: dict[str, Any]) -> dict[str, Any]:
        d = parse_date(a["date"], self.tz)
        today = self.today
        if a["period"] == "day":
            st = await stats.day_stats(self.db, self.user, d)
            return {"period": "day", **self._stats_dict(st)}
        if a["period"] == "week":
            start = d - timedelta(days=d.weekday())
            end = start + timedelta(days=6)
        else:
            start = d.replace(day=1)
            end = d.replace(day=monthrange(d.year, d.month)[1])
        if start <= today < end:
            end = today
        ps = await stats.period_stats(self.db, self.user, start, end)
        data = self._stats_dict(ps)
        data["days"] = [{"date": x.date.isoformat(), "tracked_min": x.tracked_min,
                         "productive_min": x.productive_min, "focus_score": x.focus_score,
                         "tasks_done": x.tasks_done} for x in ps.days]
        return {"period": a["period"], **data}

    @staticmethod
    def _stats_dict(st: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in asdict(st).items():
            if k == "days":
                continue
            if k == "minutes_by_category":
                v = {f"{ACTIVITY_CATEGORIES.get(c, ('', c))[1]}": m for c, m in v.items()}
            out[k] = v.isoformat() if isinstance(v, date) else v
        return out

    async def build_plan(self, a: dict[str, Any]) -> dict[str, Any]:
        d = parse_date(a["date"], self.tz)
        if d < self.today:
            raise ToolError("План можно составить только на сегодня или будущие дни")
        if d > self.today + timedelta(days=14):
            raise ToolError("План можно составить не дальше чем на 2 недели вперёд")
        plan = await planner.build_plan(self.db, self.user, d, save=True)
        self._act(f"🗓 План на {human_date(d, self.today)} составлен ({len(plan.items)} блоков, черновик)")
        return {"ok": True, "date": d.isoformat(), "status": plan.status,
                "items": [{"start": i.start, "end": i.end, "kind": i.kind, "title": i.title} for i in plan.items]}


_HANDLERS: dict[str, Handler] = {t["name"]: getattr(ToolExecutor, t["name"]) for t in TOOLS}
