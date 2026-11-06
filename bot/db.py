"""SQLite-хранилище. Единственная точка доступа к данным для всех модулей.

Все datetime хранятся в UTC ISO-строках, наружу отдаются aware datetime.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from bot.models import (
    Activity,
    DayPlan,
    Event,
    Lesson,
    PlanItem,
    Task,
    User,
    UserSettings,
)
from bot.timeutil import iso, now_utc, parse_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    first_name TEXT NOT NULL DEFAULT '',
    settings TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    notes TEXT,
    importance INTEGER NOT NULL DEFAULT 2,
    deadline TEXT,
    estimate_min INTEGER NOT NULL DEFAULT 30,
    energy TEXT NOT NULL DEFAULT 'medium',
    category TEXT NOT NULL DEFAULT 'study',
    status TEXT NOT NULL DEFAULT 'todo',
    created_at TEXT NOT NULL,
    done_at TEXT,
    planned_date TEXT
);
CREATE INDEX IF NOT EXISTS ix_tasks_user_status ON tasks(user_id, status);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT,
    location TEXT,
    notes TEXT,
    remind_before_min INTEGER NOT NULL DEFAULT 30,
    kind TEXT NOT NULL DEFAULT 'event'
);
CREATE INDEX IF NOT EXISTS ix_events_user_start ON events(user_id, start_at);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    weekday INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    subject TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    room TEXT,
    teacher TEXT,
    parity TEXT NOT NULL DEFAULT 'all'
);
CREATE INDEX IF NOT EXISTS ix_lessons_user_day ON lessons(user_id, weekday);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    rating INTEGER,
    source TEXT NOT NULL DEFAULT 'timer'
);
CREATE INDEX IF NOT EXISTS ix_activities_user_start ON activities(user_id, started_at);
CREATE TABLE IF NOT EXISTS plans (
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    items TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    ai_comment TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS sent_notifications (
    key TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ai_messages_user ON ai_messages(user_id, id);
CREATE TABLE IF NOT EXISTS user_state (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (user_id, key)
);
"""

_TASK_FIELDS = {"title", "notes", "importance", "deadline", "estimate_min", "energy",
                "category", "status", "done_at", "planned_date"}
_EVENT_FIELDS = {"title", "start_at", "end_at", "location", "notes", "remind_before_min", "kind"}
_LESSON_FIELDS = {"weekday", "start_time", "end_time", "subject", "kind", "room", "teacher", "parity"}


def _dump(value: Any) -> Any:
    """Python-значение -> значение для SQLite."""
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class Database:
    def __init__(self, path: str | Path = "data/bot.db") -> None:
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------ lifecycle
    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if not self._conn:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def _fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    async def _exec(self, sql: str, params: tuple = ()) -> int:
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur.lastrowid or 0

    # ------------------------------------------------------------ users
    @staticmethod
    def _user(row: aiosqlite.Row) -> User:
        return User(
            id=row["id"], chat_id=row["chat_id"], first_name=row["first_name"],
            settings=UserSettings.from_dict(json.loads(row["settings"] or "{}")),
            created_at=parse_iso(row["created_at"]),
        )

    async def get_user(self, user_id: int) -> User | None:
        row = await self._fetchone("SELECT * FROM users WHERE id=?", (user_id,))
        return self._user(row) if row else None

    async def get_or_create_user(self, user_id: int, chat_id: int, first_name: str = "",
                                 default_settings: UserSettings | None = None) -> tuple[User, bool]:
        """Возвращает (user, created)."""
        user = await self.get_user(user_id)
        if user:
            if user.chat_id != chat_id or (first_name and user.first_name != first_name):
                await self._exec("UPDATE users SET chat_id=?, first_name=? WHERE id=?",
                                 (chat_id, first_name or user.first_name, user_id))
                user.chat_id, user.first_name = chat_id, first_name or user.first_name
            return user, False
        settings = default_settings or UserSettings()
        await self._exec(
            "INSERT INTO users (id, chat_id, first_name, settings, created_at) VALUES (?,?,?,?,?)",
            (user_id, chat_id, first_name, json.dumps(settings.to_dict()), iso(now_utc())),
        )
        return (await self.get_user(user_id)), True  # type: ignore[return-value]

    async def list_users(self) -> list[User]:
        return [self._user(r) for r in await self._fetchall("SELECT * FROM users")]

    async def update_settings(self, user_id: int, **changes: Any) -> UserSettings:
        user = await self.get_user(user_id)
        if not user:
            raise KeyError(user_id)
        data = user.settings.to_dict()
        for k, v in changes.items():
            if k not in data:
                raise KeyError(f"unknown setting: {k}")
            data[k] = v
        await self._exec("UPDATE users SET settings=? WHERE id=?", (json.dumps(data), user_id))
        return UserSettings.from_dict(data)

    # ------------------------------------------------------------ tasks
    @staticmethod
    def _task(row: aiosqlite.Row) -> Task:
        return Task(
            id=row["id"], user_id=row["user_id"], title=row["title"], notes=row["notes"],
            importance=row["importance"], deadline=parse_iso(row["deadline"]),
            estimate_min=row["estimate_min"], energy=row["energy"], category=row["category"],
            status=row["status"], created_at=parse_iso(row["created_at"]),
            done_at=parse_iso(row["done_at"]), planned_date=_date(row["planned_date"]),
        )

    async def add_task(self, user_id: int, title: str, *, notes: str | None = None,
                       importance: int = 2, deadline: datetime | None = None,
                       estimate_min: int = 30, energy: str = "medium", category: str = "study",
                       planned_date: date | None = None) -> Task:
        importance = max(1, min(3, int(importance)))
        estimate_min = max(5, int(estimate_min))
        task_id = await self._exec(
            "INSERT INTO tasks (user_id, title, notes, importance, deadline, estimate_min, energy,"
            " category, status, created_at, planned_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, title.strip(), notes, importance, _dump(deadline), estimate_min, energy,
             category, "todo", iso(now_utc()), _dump(planned_date)),
        )
        return await self.get_task(task_id)  # type: ignore[return-value]

    async def get_task(self, task_id: int) -> Task | None:
        row = await self._fetchone("SELECT * FROM tasks WHERE id=?", (task_id,))
        return self._task(row) if row else None

    async def list_tasks(self, user_id: int, status: str | None = "todo") -> list[Task]:
        if status is None:
            rows = await self._fetchall("SELECT * FROM tasks WHERE user_id=? ORDER BY id", (user_id,))
        else:
            rows = await self._fetchall(
                "SELECT * FROM tasks WHERE user_id=? AND status=? ORDER BY id", (user_id, status))
        return [self._task(r) for r in rows]

    async def list_tasks_done_between(self, user_id: int, start: datetime, end: datetime) -> list[Task]:
        rows = await self._fetchall(
            "SELECT * FROM tasks WHERE user_id=? AND status='done' AND done_at>=? AND done_at<?",
            (user_id, iso(start), iso(end)))
        return [self._task(r) for r in rows]

    async def update_task(self, task_id: int, **fields: Any) -> Task:
        bad = set(fields) - _TASK_FIELDS
        if bad:
            raise KeyError(f"unknown task fields: {bad}")
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            await self._exec(f"UPDATE tasks SET {cols} WHERE id=?",
                             (*[_dump(v) for v in fields.values()], task_id))
        return await self.get_task(task_id)  # type: ignore[return-value]

    async def complete_task(self, task_id: int) -> Task:
        return await self.update_task(task_id, status="done", done_at=now_utc())

    async def delete_task(self, task_id: int) -> None:
        await self._exec("DELETE FROM tasks WHERE id=?", (task_id,))

    # ------------------------------------------------------------ events
    @staticmethod
    def _event(row: aiosqlite.Row) -> Event:
        return Event(
            id=row["id"], user_id=row["user_id"], title=row["title"],
            start_at=parse_iso(row["start_at"]), end_at=parse_iso(row["end_at"]),
            location=row["location"], notes=row["notes"],
            remind_before_min=row["remind_before_min"], kind=row["kind"],
        )

    async def add_event(self, user_id: int, title: str, start_at: datetime, *,
                        end_at: datetime | None = None, location: str | None = None,
                        notes: str | None = None, remind_before_min: int = 30,
                        kind: str = "event") -> Event:
        event_id = await self._exec(
            "INSERT INTO events (user_id, title, start_at, end_at, location, notes,"
            " remind_before_min, kind) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, title.strip(), iso(start_at), iso(end_at), location, notes,
             int(remind_before_min), kind),
        )
        return await self.get_event(event_id)  # type: ignore[return-value]

    async def get_event(self, event_id: int) -> Event | None:
        row = await self._fetchone("SELECT * FROM events WHERE id=?", (event_id,))
        return self._event(row) if row else None

    async def list_events(self, user_id: int, start: datetime, end: datetime) -> list[Event]:
        """События, начинающиеся в [start, end)."""
        rows = await self._fetchall(
            "SELECT * FROM events WHERE user_id=? AND start_at>=? AND start_at<? ORDER BY start_at",
            (user_id, iso(start), iso(end)))
        return [self._event(r) for r in rows]

    async def upcoming_events(self, user_id: int, limit: int = 10) -> list[Event]:
        rows = await self._fetchall(
            "SELECT * FROM events WHERE user_id=? AND start_at>=? ORDER BY start_at LIMIT ?",
            (user_id, iso(now_utc()), limit))
        return [self._event(r) for r in rows]

    async def update_event(self, event_id: int, **fields: Any) -> Event:
        bad = set(fields) - _EVENT_FIELDS
        if bad:
            raise KeyError(f"unknown event fields: {bad}")
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            await self._exec(f"UPDATE events SET {cols} WHERE id=?",
                             (*[_dump(v) for v in fields.values()], event_id))
        return await self.get_event(event_id)  # type: ignore[return-value]

    async def delete_event(self, event_id: int) -> None:
        await self._exec("DELETE FROM events WHERE id=?", (event_id,))

    # ------------------------------------------------------------ timetable
    @staticmethod
    def _lesson(row: aiosqlite.Row) -> Lesson:
        return Lesson(
            id=row["id"], user_id=row["user_id"], weekday=row["weekday"],
            start_time=row["start_time"], end_time=row["end_time"], subject=row["subject"],
            kind=row["kind"], room=row["room"], teacher=row["teacher"], parity=row["parity"],
        )

    async def add_lesson(self, user_id: int, weekday: int, start_time: str, end_time: str,
                         subject: str, *, kind: str = "", room: str | None = None,
                         teacher: str | None = None, parity: str = "all") -> Lesson:
        lesson_id = await self._exec(
            "INSERT INTO lessons (user_id, weekday, start_time, end_time, subject, kind, room,"
            " teacher, parity) VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, int(weekday), start_time, end_time, subject.strip(), kind or "",
             room, teacher, parity if parity in ("all", "odd", "even") else "all"),
        )
        row = await self._fetchone("SELECT * FROM lessons WHERE id=?", (lesson_id,))
        return self._lesson(row)  # type: ignore[arg-type]

    async def list_lessons(self, user_id: int, weekday: int | None = None) -> list[Lesson]:
        if weekday is None:
            rows = await self._fetchall(
                "SELECT * FROM lessons WHERE user_id=? ORDER BY weekday, start_time", (user_id,))
        else:
            rows = await self._fetchall(
                "SELECT * FROM lessons WHERE user_id=? AND weekday=? ORDER BY start_time",
                (user_id, weekday))
        return [self._lesson(r) for r in rows]

    async def update_lesson(self, lesson_id: int, **fields: Any) -> None:
        bad = set(fields) - _LESSON_FIELDS
        if bad:
            raise KeyError(f"unknown lesson fields: {bad}")
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            await self._exec(f"UPDATE lessons SET {cols} WHERE id=?", (*fields.values(), lesson_id))

    async def delete_lesson(self, lesson_id: int) -> None:
        await self._exec("DELETE FROM lessons WHERE id=?", (lesson_id,))

    async def clear_lessons(self, user_id: int) -> None:
        await self._exec("DELETE FROM lessons WHERE user_id=?", (user_id,))

    # ------------------------------------------------------------ activities (трекер)
    @staticmethod
    def _activity(row: aiosqlite.Row) -> Activity:
        return Activity(
            id=row["id"], user_id=row["user_id"], category=row["category"],
            started_at=parse_iso(row["started_at"]), ended_at=parse_iso(row["ended_at"]),
            description=row["description"], rating=row["rating"], source=row["source"],
        )

    async def current_activity(self, user_id: int) -> Activity | None:
        row = await self._fetchone(
            "SELECT * FROM activities WHERE user_id=? AND ended_at IS NULL"
            " ORDER BY started_at DESC LIMIT 1", (user_id,))
        return self._activity(row) if row else None

    async def start_activity(self, user_id: int, category: str, description: str | None = None,
                             source: str = "timer", started_at: datetime | None = None) -> Activity:
        """Запускает активность. Текущая (если есть) автоматически останавливается."""
        started_at = started_at or now_utc()
        await self.stop_activity(user_id, ended_at=started_at)
        act_id = await self._exec(
            "INSERT INTO activities (user_id, category, description, started_at, source)"
            " VALUES (?,?,?,?,?)", (user_id, category, description, iso(started_at), source))
        row = await self._fetchone("SELECT * FROM activities WHERE id=?", (act_id,))
        return self._activity(row)  # type: ignore[arg-type]

    async def stop_activity(self, user_id: int, ended_at: datetime | None = None) -> Activity | None:
        """Останавливает текущую активность, возвращает её (или None)."""
        current = await self.current_activity(user_id)
        if not current:
            return None
        ended_at = ended_at or now_utc()
        if ended_at < current.started_at:
            ended_at = current.started_at
        await self._exec("UPDATE activities SET ended_at=? WHERE id=?", (iso(ended_at), current.id))
        current.ended_at = ended_at
        return current

    async def add_activity(self, user_id: int, category: str, started_at: datetime,
                           ended_at: datetime, description: str | None = None,
                           rating: int | None = None, source: str = "manual") -> Activity:
        act_id = await self._exec(
            "INSERT INTO activities (user_id, category, description, started_at, ended_at, rating,"
            " source) VALUES (?,?,?,?,?,?,?)",
            (user_id, category, description, iso(started_at), iso(ended_at), rating, source))
        row = await self._fetchone("SELECT * FROM activities WHERE id=?", (act_id,))
        return self._activity(row)  # type: ignore[arg-type]

    async def get_activity(self, activity_id: int) -> Activity | None:
        row = await self._fetchone("SELECT * FROM activities WHERE id=?", (activity_id,))
        return self._activity(row) if row else None

    async def rate_activity(self, activity_id: int, rating: int) -> None:
        await self._exec("UPDATE activities SET rating=? WHERE id=?",
                         (max(1, min(5, int(rating))), activity_id))

    async def update_activity(self, activity_id: int, **fields: Any) -> None:
        allowed = {"category", "description", "started_at", "ended_at", "rating"}
        bad = set(fields) - allowed
        if bad:
            raise KeyError(f"unknown activity fields: {bad}")
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            await self._exec(f"UPDATE activities SET {cols} WHERE id=?",
                             (*[_dump(v) for v in fields.values()], activity_id))

    async def delete_activity(self, activity_id: int) -> None:
        await self._exec("DELETE FROM activities WHERE id=?", (activity_id,))

    async def list_activities(self, user_id: int, start: datetime, end: datetime) -> list[Activity]:
        """Активности, пересекающиеся с интервалом [start, end) (включая текущую)."""
        rows = await self._fetchall(
            "SELECT * FROM activities WHERE user_id=? AND started_at<?"
            " AND (ended_at IS NULL OR ended_at>?) ORDER BY started_at",
            (user_id, iso(end), iso(start)))
        return [self._activity(r) for r in rows]

    # ------------------------------------------------------------ plans
    async def save_plan(self, plan: DayPlan) -> DayPlan:
        """Сохраняет план (upsert по user_id+date)."""
        plan.created_at = plan.created_at or now_utc()
        await self._exec(
            "INSERT INTO plans (user_id, date, items, status, ai_comment, created_at)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(user_id, date) DO UPDATE SET"
            " items=excluded.items, status=excluded.status, ai_comment=excluded.ai_comment,"
            " created_at=excluded.created_at",
            (plan.user_id, plan.date.isoformat(),
             json.dumps([i.to_dict() for i in plan.items], ensure_ascii=False),
             plan.status, plan.ai_comment, iso(plan.created_at)),
        )
        return plan

    async def get_plan(self, user_id: int, d: date) -> DayPlan | None:
        row = await self._fetchone("SELECT * FROM plans WHERE user_id=? AND date=?",
                                   (user_id, d.isoformat()))
        if not row:
            return None
        return DayPlan(
            user_id=row["user_id"], date=date.fromisoformat(row["date"]),
            items=[PlanItem.from_dict(x) for x in json.loads(row["items"] or "[]")],
            status=row["status"], ai_comment=row["ai_comment"],
            created_at=parse_iso(row["created_at"]),
        )

    async def set_plan_status(self, user_id: int, d: date, status: str) -> None:
        await self._exec("UPDATE plans SET status=? WHERE user_id=? AND date=?",
                         (status, user_id, d.isoformat()))

    async def mark_plan_item_done(self, user_id: int, d: date, index: int, done: bool = True) -> DayPlan | None:
        plan = await self.get_plan(user_id, d)
        if not plan or not (0 <= index < len(plan.items)):
            return plan
        plan.items[index].done = done
        await self.save_plan(plan)
        return plan

    # ------------------------------------------------------------ notification dedupe
    async def was_sent(self, key: str) -> bool:
        return await self._fetchone("SELECT 1 FROM sent_notifications WHERE key=?", (key,)) is not None

    async def mark_sent(self, key: str) -> bool:
        """Помечает уведомление отправленным. False, если уже было помечено."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO sent_notifications (key, sent_at) VALUES (?,?)",
            (key, iso(now_utc())))
        await self.conn.commit()
        return cur.rowcount > 0

    async def cleanup_sent(self, older_than: datetime) -> None:
        await self._exec("DELETE FROM sent_notifications WHERE sent_at<?", (iso(older_than),))

    # ------------------------------------------------------------ AI memory
    async def add_ai_message(self, user_id: int, role: str, content: str) -> None:
        await self._exec("INSERT INTO ai_messages (user_id, role, content, created_at) VALUES (?,?,?,?)",
                         (user_id, role, content, iso(now_utc())))

    async def get_ai_history(self, user_id: int, limit: int = 20) -> list[tuple[str, str]]:
        """Последние limit сообщений [(role, content)] в хронологическом порядке."""
        rows = await self._fetchall(
            "SELECT role, content FROM ai_messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit))
        return [(r["role"], r["content"]) for r in reversed(rows)]

    async def clear_ai_history(self, user_id: int) -> None:
        await self._exec("DELETE FROM ai_messages WHERE user_id=?", (user_id,))

    # ------------------------------------------------------------ key-value state
    async def get_state(self, user_id: int, key: str) -> str | None:
        row = await self._fetchone("SELECT value FROM user_state WHERE user_id=? AND key=?",
                                   (user_id, key))
        return row["value"] if row else None

    async def set_state(self, user_id: int, key: str, value: str | None) -> None:
        await self._exec(
            "INSERT INTO user_state (user_id, key, value) VALUES (?,?,?)"
            " ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value", (user_id, key, value))
