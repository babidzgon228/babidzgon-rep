"""Структурированные ответы Claude (output_config.format) и их строгая проверка.

Схемы строятся из pydantic-моделей через anthropic.transform_schema (как в client.messages.parse),
один раз при импорте — байты схемы стабильны между запросами.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError

from bot.models import (
    ENERGY_LEVELS,
    PLAN_ITEM_KINDS,
    TASK_CATEGORIES,
    WEEKDAYS_SHORT,
    DayPlan,
    PlanItem,
    UserSettings,
)
from bot.services.timetable import normalize_lesson_dict
from bot.timeutil import hhmm_of, iso, minutes_of

log = logging.getLogger(__name__)

FIXED_KINDS = ("lesson", "event")
DAY_LAST_MINUTE = 23 * 60 + 59  # "23:59": элементы плана всегда в пределах суток
MAX_PLAN_ITEMS = 60


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- модели ответа

class PlanItemOut(_Strict):
    start: str
    end: str
    kind: Literal[tuple(PLAN_ITEM_KINDS)]  # type: ignore[valid-type]
    title: str
    ref_id: int | None
    note: str | None


class PlanProposal(_Strict):
    items: list[PlanItemOut]
    comment: str


class LessonOut(_Strict):
    day: Literal[tuple(WEEKDAYS_SHORT)]  # type: ignore[valid-type]
    time: str
    subject: str
    kind: str
    room: str | None
    teacher: str | None
    weeks: Literal["all", "odd", "even"]


class TimetableOut(_Strict):
    lessons: list[LessonOut]


class TaskFieldsOut(_Strict):
    importance: Literal[1, 2, 3]
    estimate_min: int
    energy: Literal[tuple(ENERGY_LEVELS)]  # type: ignore[valid-type]
    category: Literal[tuple(TASK_CATEGORIES)]  # type: ignore[valid-type]
    deadline: str | None




def json_format(model: type[BaseModel]) -> dict[str, Any]:
    return {"type": "json_schema", "schema": anthropic.transform_schema(model)}


PLAN_FORMAT = json_format(PlanProposal)
TIMETABLE_FORMAT = json_format(TimetableOut)
TASK_FIELDS_FORMAT = json_format(TaskFieldsOut)


class AIOutputError(Exception):
    """Модель не дала пригодный структурированный ответ (отказ, обрезка, невалидный JSON, нарушение правил)."""


def load_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise AIOutputError("пустой ответ")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)  # на случай текста вокруг JSON (без output_config не бывает)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        raise AIOutputError("ответ не является JSON") from None


# ---------------------------------------------------------------- план дня

_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _norm_hhmm(value: str) -> str:
    m = _HHMM_RE.match((value or "").strip())
    if not m:
        raise AIOutputError(f"время {value!r} не в формате HH:MM")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise AIOutputError(f"некорректное время {value!r}")
    return f"{h:02d}:{mi:02d}"


def _key(item: PlanItem) -> tuple[str, str, str, int | None]:
    return item.kind, item.start, item.end, item.ref_id


def validate_plan(proposal: PlanProposal, original: DayPlan, settings: UserSettings,
                  task_ids: set[int]) -> list[PlanItem]:
    """Проверяет предложенный план. Возвращает готовые PlanItem или бросает AIOutputError."""
    if not proposal.items:
        raise AIOutputError("пустой план")
    if len(proposal.items) > MAX_PLAN_ITEMS:
        raise AIOutputError("слишком много блоков")

    fixed_orig = [i for i in original.items if i.kind in FIXED_KINDS]
    fixed_by_key: dict[tuple, list[PlanItem]] = {}
    for i in fixed_orig:
        fixed_by_key.setdefault(_key(i), []).append(i)
    allowed_tasks = set(task_ids) | {i.ref_id for i in original.items if i.kind == "task" and i.ref_id is not None}
    done_keys = {_key(i) for i in original.items if i.done}

    items: list[PlanItem] = []
    for raw in proposal.items:
        start, end = _norm_hhmm(raw.start), _norm_hhmm(raw.end)
        if minutes_of(start) >= minutes_of(end):
            raise AIOutputError(f"блок {start}-{end}: начало не раньше конца")
        title = " ".join((raw.title or "").split())[:80]
        note = " ".join(raw.note.split())[:200] if raw.note else None
        kind, ref_id = raw.kind, raw.ref_id
        if kind == "task":
            if ref_id is None:
                kind = "routine"  # «задача» без id — просто блок времени
            elif ref_id not in allowed_tasks:
                raise AIOutputError(f"неизвестная задача ref_id={ref_id}")
        elif kind not in FIXED_KINDS:
            ref_id = None
        item = PlanItem(start=start, end=end, kind=kind, title=title, ref_id=ref_id, note=note or None)
        if kind in FIXED_KINDS:
            originals = fixed_by_key.get(_key(item))
            if not originals:
                raise AIOutputError(f"пара/событие {start}-{end} «{title}» изменено или добавлено")
            item = PlanItem(**originals.pop(0).to_dict())  # фиксированный блок — ровно как в исходном плане
        else:
            if not title:
                raise AIOutputError("блок без названия")
            item.done = _key(item) in done_keys
        items.append(item)

    missing = [i for lst in fixed_by_key.values() for i in lst]
    if missing:
        raise AIOutputError(f"пропали пары/события: {', '.join(i.title for i in missing)}")

    items.sort(key=lambda i: (minutes_of(i.start), minutes_of(i.end)))
    # Гибкие блоки не пересекаются ни с чем; фиксированные между собой могут (как в исходных данных).
    spans = [(minutes_of(i.start), minutes_of(i.end), i) for i in items]
    for n, (s1, e1, a) in enumerate(spans):
        for s2, e2, b in spans[n + 1:]:
            if s2 >= e1:
                break
            if a.kind not in FIXED_KINDS or b.kind not in FIXED_KINDS:
                raise AIOutputError(f"пересечение {a.start}-{a.end} и {b.start}-{b.end}")

    wake, sleep = minutes_of(settings.wake_time), minutes_of(settings.sleep_time)
    if sleep <= wake:  # отбой после полуночи (08:30..00:30) — план дня до 23:59
        sleep = DAY_LAST_MINUTE
    lo = min([wake] + [minutes_of(i.start) for i in original.items])
    hi = max([sleep] + [minutes_of(i.end) for i in original.items])
    for i in items:
        if i.kind in FIXED_KINDS:
            continue
        if minutes_of(i.start) < lo or minutes_of(i.end) > hi:
            raise AIOutputError(f"блок {i.start}-{i.end} вне времени {hhmm_of(lo)}–{hhmm_of(hi)}")
    return items


# ---------------------------------------------------------------- расписание

_KIND_ALIASES = {
    "лекция": "лекция", "лек": "лекция", "лк": "лекция", "лекции": "лекция",
    "практика": "практика", "пр": "практика", "практ": "практика", "пз": "практика", "практическое": "практика",
    "практическое занятие": "практика",
    "лаба": "лаба", "лаб": "лаба", "лр": "лаба", "лабораторная": "лаба", "лабораторная работа": "лаба",
    "семинар": "семинар", "сем": "семинар",
    "讲座": "лекция", "讲课": "лекция", "理论": "лекция", "实验": "лаба", "实践": "практика", "练习": "практика",
    "研讨": "семинар", "讨论": "семинар",
}


def _norm_kind(kind: Any) -> str:
    k = str(kind or "").strip().lower().rstrip(".")
    return _KIND_ALIASES.get(k, str(kind or "").strip()[:30])


def clean_timetable(raw_lessons: Any) -> list[dict[str, Any]]:
    """Отбрасывает мусор. Возвращает словари {day, time, subject, kind, room, teacher, weeks},
    каждый из которых гарантированно проходит normalize_lesson_dict."""
    if not isinstance(raw_lessons, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for raw in raw_lessons:
        if not isinstance(raw, dict):
            continue
        try:
            norm = normalize_lesson_dict(raw)
            s, e = _norm_hhmm(norm["start_time"]), _norm_hhmm(norm["end_time"])
            if minutes_of(s) >= minutes_of(e):
                raise ValueError("начало позже конца")
        except (ValueError, TypeError, AIOutputError) as exc:
            log.debug("timetable: пропускаю %r: %s", raw, exc)
            continue
        subject = " ".join(norm["subject"].split())[:120]
        item = {
            "day": WEEKDAYS_SHORT[norm["weekday"]], "time": f"{s}-{e}", "subject": subject,
            "kind": _norm_kind(norm["kind"]),
            "room": (norm["room"] or "")[:40] or None, "teacher": (norm["teacher"] or "")[:80] or None,
            "weeks": norm["parity"],
        }
        key = (item["day"], item["time"], subject.lower(), item["weeks"])
        if key in seen:
            continue
        seen.add(key)
        normalize_lesson_dict(item)  # контракт: совместимо с normalize_lesson_dict
        out.append(item)
    out.sort(key=lambda x: (WEEKDAYS_SHORT.index(x["day"]), x["time"]))
    return out


# ---------------------------------------------------------------- поля задачи

def clean_task_fields(data: TaskFieldsOut, *, parse_deadline) -> dict[str, Any]:
    """deadline -> ISO-строка в UTC (как хранит БД) или None. parse_deadline(str) -> aware datetime."""
    deadline: str | None = None
    if data.deadline:
        try:
            dt: datetime = parse_deadline(data.deadline)
            deadline = iso(dt)
        except Exception as e:  # noqa: BLE001
            log.debug("suggest: плохой дедлайн %r: %s", data.deadline, e)
    return {
        "importance": int(data.importance),
        "estimate_min": max(5, min(24 * 60, int(data.estimate_min))),
        "energy": data.energy,
        "category": data.category,
        "deadline": deadline,
    }


def validation_message(e: ValidationError) -> str:
    errs = e.errors()
    return "; ".join(f"{'.'.join(map(str, x.get('loc', ())))}: {x.get('msg')}" for x in errs[:3])


__all__ = ["AIOutputError", "PLAN_FORMAT", "TIMETABLE_FORMAT", "TASK_FIELDS_FORMAT", "PlanProposal",
           "TimetableOut", "TaskFieldsOut", "validate_plan", "clean_timetable", "clean_task_fields", "load_json"]
