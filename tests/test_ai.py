"""ИИ-модуль: инструменты на in-memory БД, агентный цикл с фейковым клиентом, структурированные ответы.

Сети нет: AIAssistant._client подменяется FakeClient с заготовленными ответами.
"""
from __future__ import annotations

import base64
import io
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from bot.ai import assistant as assistant_mod
from bot.ai.assistant import (
    DEFAULT_MODEL,
    FALLBACK_BETA,
    MAX_TOOL_ITERATIONS,
    PLAN_FAILED_COMMENT,
    TEXT_AUTH,
    TEXT_CONNECTION,
    TEXT_DISABLED,
    TEXT_OVERLOADED,
    TEXT_RATE_LIMIT,
    TEXT_REFUSAL,
    TEXT_TIMEOUT,
    TEXT_USER_DISABLED,
    AIAssistant,
    AIReply,
    _echo_content,
)
from bot.ai.prompts import CHAT_SYSTEM_PROMPT
from bot.ai.tools import TOOLS, ToolExecutor
from bot.config import Config
from bot.models import DayPlan, DayStats, PeriodStats, PlanItem, UserSettings
from bot.services import planner, prioritizer, stats
from bot.services.timetable import import_lessons, load_timetable_file, normalize_lesson_dict
from bot.timeutil import combine_local, iso, local_today, now_utc, parse_iso

TZ = "Europe/Moscow"


# ---------------------------------------------------------------- фейковый Claude

def text(t):
    return SimpleNamespace(type="text", text=t)


def thinking():
    return SimpleNamespace(type="thinking", thinking="", signature="sig-abc")


def tool(name, input_, id_="toolu_1"):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def msg(*blocks, stop="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, stop_details=None, model=DEFAULT_MODEL,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                                 cache_creation_input_tokens=0, iterations=None))


class _Messages:
    def __init__(self, owner, path):
        self.owner, self.path = owner, path

    async def create(self, **kwargs):
        return self.owner.handle(self.path, kwargs)


class FakeClient:
    def __init__(self, *responses):
        self.queue = list(responses)
        self.calls: list[dict] = []
        self.messages = _Messages(self, "messages")
        self.beta = SimpleNamespace(messages=_Messages(self, "beta"))

    def handle(self, path, kwargs):
        snap = dict(kwargs, _path=path, messages=list(kwargs["messages"]))
        self.calls.append(snap)
        assert self.queue, "неожиданный вызов API"
        r = self.queue.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, code, message="error"):
    return cls(message, response=httpx2.Response(code, request=_REQ),
               body={"type": "error", "error": {"type": "invalid_request_error", "message": message}})


@pytest.fixture
def make_ai(db):
    def _make(*responses):
        ai = AIAssistant(db, "test-key")
        ai._client = FakeClient(*responses)
        return ai
    return _make


def day_local(days: int, hhmm: str = "18:00") -> tuple[date, str]:
    d = local_today(TZ) + timedelta(days=days)
    return d, f"{d.isoformat()}T{hhmm}"


# ---------------------------------------------------------------- схемы инструментов

def test_tool_schemas_are_strict_compatible():
    names = [t["name"] for t in TOOLS]
    assert len(names) == len(set(names)) and len(names) <= 20
    expected = {"add_task", "list_tasks", "update_task", "complete_task", "delete_task", "add_event", "list_events",
                "delete_event", "get_day", "get_week_timetable", "start_tracking", "stop_tracking", "log_activity",
                "get_stats", "build_plan", "add_lesson"}
    assert set(names) == expected
    optional = 0
    for t in TOOLS:
        schema = t["input_schema"]
        assert schema["additionalProperties"] is False
        assert "user_id" not in schema["properties"]
        for prop in schema["properties"].values():  # strict: без min/max/minLength
            assert not {"minimum", "maximum", "minLength", "maxLength", "pattern"} & set(prop)
        optional += len(set(schema["properties"]) - set(schema["required"]))
    assert optional <= 24


def test_default_model_comes_from_config():
    assert DEFAULT_MODEL == Config.anthropic_model == "claude-opus-5-5"


# ---------------------------------------------------------------- инструменты на БД

async def test_add_task_converts_local_deadline(db, user):
    ex = ToolExecutor(db, user)
    d, dl = day_local(3)
    out, err = await ex.run("add_task", {"title": "Курсач", "importance": 3, "estimate_min": 240,
                                         "energy": "high", "category": "study", "deadline": dl})
    assert not err, out
    [task] = await db.list_tasks(user.id)
    assert task.title == "Курсач" and task.estimate_min == 240 and task.importance == 3
    assert task.deadline == combine_local(d, "18:00", TZ)
    assert task.deadline.utcoffset() == timedelta(0)  # в БД — UTC
    assert ex.changed
    assert ex.actions[0].startswith("➕ Задача «Курсач» (до ") and "18:00" in ex.actions[0]
    assert json.loads(out)["task"]["id"] == task.id


async def test_add_task_date_only_deadline_is_end_of_day(db, user):
    ex = ToolExecutor(db, user)
    d, _ = day_local(2)
    _, err = await ex.run("add_task", {"title": "Лаба", "importance": 2, "estimate_min": 1, "energy": "low",
                                       "category": "study", "deadline": d.isoformat()})
    assert not err
    [task] = await db.list_tasks(user.id)
    assert task.deadline == combine_local(d, "23:59", TZ)
    assert task.estimate_min == 5  # зажато снизу


@pytest.mark.parametrize("args", [
    {"title": "X", "importance": 5, "estimate_min": 30, "energy": "low", "category": "study"},
    {"title": "X", "importance": 2, "estimate_min": 30, "energy": "low", "category": "study", "user_id": 7},
    {"title": "X", "importance": 2, "energy": "low", "category": "study"},
    {"title": "X", "importance": 2, "estimate_min": "много", "energy": "low", "category": "study"},
    {"title": "X", "importance": 2, "estimate_min": 30, "energy": "low", "category": "study", "deadline": "пятница"},
    {"title": "   ", "importance": 2, "estimate_min": 30, "energy": "low", "category": "study"},
])
async def test_tool_input_validation(db, user, args):
    ex = ToolExecutor(db, user)
    out, err = await ex.run("add_task", args)
    assert err and "error" in json.loads(out)
    assert await db.list_tasks(user.id) == []
    assert not ex.changed and ex.actions == []


async def test_unknown_tool_and_non_dict_args(db, user):
    ex = ToolExecutor(db, user)
    assert (await ex.run("rm_rf", {}))[1]
    assert (await ex.run("list_tasks", "oops"))[1]


async def test_task_tools_respect_owner(db, user):
    other, _ = await db.get_or_create_user(2002, 2002, "Чужой")
    foreign = await db.add_task(other.id, "Чужая задача")
    mine = await db.add_task(user.id, "Моя задача")
    ex = ToolExecutor(db, user)
    for name in ("complete_task", "delete_task", "update_task"):
        args = {"task_id": foreign.id} | ({"title": "взлом"} if name == "update_task" else {})
        out, err = await ex.run(name, args)
        assert err, name
    assert (await db.get_task(foreign.id)).title == "Чужая задача"

    _, err = await ex.run("update_task", {"task_id": mine.id, "title": "Моя задача v2", "deadline": "none",
                                          "importance": 3})
    assert not err
    t = await db.get_task(mine.id)
    assert (t.title, t.deadline, t.importance) == ("Моя задача v2", None, 3)
    _, err = await ex.run("complete_task", {"task_id": mine.id})
    assert not err and (await db.get_task(mine.id)).status == "done"
    _, err = await ex.run("delete_task", {"task_id": mine.id})
    assert not err and await db.get_task(mine.id) is None
    assert [a.split(" ")[0] for a in ex.actions] == ["✏️", "✅", "🗑"]


async def test_event_tools(db, user):
    ex = ToolExecutor(db, user)
    d, start = day_local(1, "15:00")
    _, err = await ex.run("add_event", {"title": "Куратор", "start": start, "end": f"{d.isoformat()}T14:00"})
    assert err  # конец раньше начала
    _, err = await ex.run("add_event", {"title": "Куратор", "start": d.isoformat()})
    assert err  # нет времени
    out, err = await ex.run("add_event", {"title": "Встреча с куратором", "start": start,
                                          "end": f"{d.isoformat()}T16:00", "kind": "meeting", "location": "3-313"})
    assert not err, out
    [ev] = await db.list_events(user.id, now_utc(), now_utc() + timedelta(days=3))
    assert ev.start_at == combine_local(d, "15:00", TZ) and ev.kind == "meeting" and ev.location == "3-313"
    assert ev.remind_before_min == user.settings.event_reminder_min
    assert ex.actions[-1] == "🤝 Событие «Встреча с куратором» — завтра 15:00–16:00"

    out, err = await ex.run("list_events", {"date_from": d.isoformat(), "date_to": d.isoformat()})
    assert not err and json.loads(out)["events"][0]["id"] == ev.id
    _, err = await ex.run("delete_event", {"event_id": ev.id})
    assert not err and await db.get_event(ev.id) is None


async def test_tracking_tools(db, user):
    ex = ToolExecutor(db, user)
    _, err = await ex.run("stop_tracking", {})
    assert err  # ничего не запущено
    _, err = await ex.run("start_tracking", {"category": "study", "description": "матан"})
    assert not err
    cur = await db.current_activity(user.id)
    assert (cur.category, cur.description, cur.source) == ("study", "матан", "ai")
    _, err = await ex.run("start_tracking", {"category": "rest"})
    assert not err and (await db.current_activity(user.id)).category == "rest"
    assert any(a.startswith("⏹ Остановлено: 📚 Учёба") for a in ex.actions)
    out, err = await ex.run("stop_tracking", {"rating": 4})
    assert not err
    act = await db.get_activity(json.loads(out)["activity_id"])
    assert act.rating == 4 and act.ended_at is not None
    assert await db.current_activity(user.id) is None
    assert ex.changed


async def test_log_activity(db, user):
    ex = ToolExecutor(db, user)
    d, start = day_local(-1, "18:00")
    _, err = await ex.run("log_activity", {"category": "sport", "start": start, "duration_min": 90, "rating": 5})
    assert not err
    [act] = await db.list_activities(user.id, now_utc() - timedelta(days=3), now_utc())
    assert act.started_at == combine_local(d, "18:00", TZ)
    assert act.ended_at - act.started_at == timedelta(minutes=90) and act.rating == 5
    assert ex.actions[-1] == "📝 Записал: 🏃 Спорт, вчера 18:00–19:30 (1 ч 30 мин)"
    _, future = day_local(2, "10:00")
    assert (await ex.run("log_activity", {"category": "sport", "start": future, "duration_min": 30}))[1]
    assert (await ex.run("log_activity", {"category": "sport", "start": start}))[1]  # нет конца


async def test_lessons_and_day_tools(db, user):
    ex = ToolExecutor(db, user)
    _, err = await ex.run("add_lesson", {"weekday": "пн", "start": "10:00", "end": "08:30",
                                         "subject": "Матан", "weeks": "all"})
    assert err
    _, err = await ex.run("add_lesson", {"weekday": "пн", "start": "8:30", "end": "10:00", "subject": "Матан",
                                         "weeks": "odd", "kind": "лекция", "room": "101"})
    assert not err
    out, err = await ex.run("add_lesson", {"weekday": "пн", "start": "08:30", "end": "10:00", "subject": "матан",
                                           "weeks": "odd"})
    assert not err and json.loads(out)["noop"]
    [lesson] = await db.list_lessons(user.id)
    assert (lesson.start_time, lesson.parity, lesson.room) == ("08:30", "odd", "101")
    assert ex.actions == ["🎓 Пара «Матан» — пн 08:30–10:00 (числитель)"]

    out, err = await ex.run("get_week_timetable", {"week": "current"})
    assert not err
    week = json.loads(out)
    assert len(week["days"]) == 7 and week["days"][0]["weekday"] == "пн"


async def test_real_timetable_yaml(db):
    """Реальный профиль из data/timetable.yaml: Шэньчжэнь, пары пн–пт."""
    u, _ = await db.get_or_create_user(3003, 3003, "Студент", default_settings=UserSettings(
        tz="Asia/Shanghai", semester_start="2026-09-01", semester_end="2027-01-31"))
    _, lessons = load_timetable_file("data/timetable.yaml")
    await import_lessons(db, u.id, lessons)
    ex = ToolExecutor(db, u)
    wed = date(2026, 11, 11)
    out, err = await ex.run("get_day", {"date": wed.isoformat()})
    assert not err
    day = json.loads(out)
    expected = [x for x in lessons if x["weekday"] == 2]
    assert [l["start"] for l in day["lessons"]] == sorted(x["start_time"] for x in expected)
    assert day["weekday"] == "среда"
    # Каникулы (после semester_end) — пар нет
    out, _ = await ex.run("get_day", {"date": "2027-02-10"})
    assert json.loads(out)["lessons"] == []


async def test_list_tasks_uses_prioritizer(db, user, monkeypatch):
    a = await db.add_task(user.id, "A", importance=1)
    b = await db.add_task(user.id, "B", importance=3)
    monkeypatch.setattr(prioritizer, "prioritize", lambda tasks, now: sorted(tasks, key=lambda t: -t.importance))
    monkeypatch.setattr(prioritizer, "score_task", lambda t, now: 30.0 * t.importance)
    monkeypatch.setattr(prioritizer, "quadrant", lambda t, now: "do" if t.importance == 3 else "later")
    out, err = await ToolExecutor(db, user).run("list_tasks", {})
    assert not err
    data = json.loads(out)
    assert [t["id"] for t in data["tasks"]] == [b.id, a.id]
    assert data["tasks"][0]["score"] == 90 and data["tasks"][0]["quadrant"] == prioritizer.QUADRANT_LABELS["do"]


async def test_list_tasks_survives_broken_prioritizer(db, user, monkeypatch):
    await db.add_task(user.id, "A")

    def boom(*_a, **_k):
        raise NotImplementedError

    monkeypatch.setattr(prioritizer, "prioritize", boom)
    out, err = await ToolExecutor(db, user).run("list_tasks", {})
    assert not err and json.loads(out)["count"] == 1


async def test_stats_and_build_plan_tools(db, user, monkeypatch):
    today = local_today(TZ)

    async def fake_day_stats(db_, user_, d):
        return DayStats(date=d, minutes_by_category={"study": 120}, tracked_min=120, productive_min=120,
                        focus_score=70)

    async def fake_period_stats(db_, user_, start, end):
        return PeriodStats(start=start, end=end, days=[DayStats(date=start, tracked_min=60)], tracked_min=60)

    async def fake_build_plan(db_, user_, d, *, save=True):
        assert save
        return DayPlan(user_id=user_.id, date=d, items=[PlanItem("09:00", "10:00", "task", "Курсач", 1)])

    monkeypatch.setattr(stats, "day_stats", fake_day_stats)
    monkeypatch.setattr(stats, "period_stats", fake_period_stats)
    monkeypatch.setattr(planner, "build_plan", fake_build_plan)
    ex = ToolExecutor(db, user)
    out, err = await ex.run("get_stats", {"period": "day", "date": today.isoformat()})
    assert not err and json.loads(out)["minutes_by_category"] == {"Учёба": 120}
    out, err = await ex.run("get_stats", {"period": "week", "date": today.isoformat()})
    data = json.loads(out)
    assert not err and data["start"] == (today - timedelta(days=today.weekday())).isoformat()
    assert data["end"] == today.isoformat()  # текущая неделя — по сегодня
    assert not ex.changed
    out, err = await ex.run("build_plan", {"date": (today + timedelta(days=1)).isoformat()})
    assert not err and json.loads(out)["items"][0]["title"] == "Курсач"
    assert ex.changed and ex.actions[-1].startswith("🗓 План на завтра")
    assert (await ex.run("build_plan", {"date": (today - timedelta(days=1)).isoformat()}))[1]


# ---------------------------------------------------------------- агентный цикл chat()

async def test_chat_creates_task_through_tool_loop(db, user, make_ai):
    d, dl = day_local(4)
    first = msg(thinking(), tool("add_task", {"title": "Курсач", "importance": 3, "estimate_min": 240,
                                              "energy": "high", "category": "study", "deadline": dl}),
                stop="tool_use")
    ai = make_ai(first, msg(text("Добавил **курсач**, дедлайн учёл 👍")))
    reply = await ai.chat(user, "надо сделать курсач до пятницы, часа на 4")

    assert isinstance(reply, AIReply)
    assert reply.text == "Добавил <b>курсач</b>, дедлайн учёл 👍"
    assert reply.changed and len(reply.actions) == 1 and reply.actions[0].startswith("➕ Задача «Курсач»")
    [task] = await db.list_tasks(user.id)
    assert task.deadline == combine_local(d, "18:00", TZ) and task.energy == "high"

    calls = ai._client.calls
    assert len(calls) == 2
    c = calls[0]
    assert c["_path"] == "beta" and c["betas"] == [FALLBACK_BETA] and c["fallbacks"] == "default"
    assert c["model"] == DEFAULT_MODEL
    assert c["output_config"] == {"effort": "low"}
    assert "thinking" not in c and "tool_choice" not in c
    assert all(t["strict"] is True and t["input_schema"]["additionalProperties"] is False for t in c["tools"])
    assert c["system"] == [{"type": "text", "text": CHAT_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    assert c["cache_control"] == {"type": "ephemeral"}
    assert local_today(TZ).isoformat() not in CHAT_SYSTEM_PROMPT
    user_msg = c["messages"][-1]
    assert user_msg["role"] == "user"
    ctx, said = user_msg["content"]
    assert ctx["text"].startswith("<context>") and local_today(TZ).isoformat() in ctx["text"]
    assert "Москва" in ctx["text"] and said["text"] == "надо сделать курсач до пятницы, часа на 4"

    # второй запрос: ответ модели целиком (thinking неизменен), затем tool_result одним user-сообщением
    assistant_turn, results_turn = calls[1]["messages"][-2:]
    assert assistant_turn == {"role": "assistant", "content": first.content}
    assert assistant_turn["content"][0] is first.content[0]
    assert results_turn["role"] == "user"
    [res] = results_turn["content"]
    assert res["type"] == "tool_result" and res["tool_use_id"] == "toolu_1" and "is_error" not in res

    history = await db.get_ai_history(user.id)
    assert history[0] == ("user", "надо сделать курсач до пятницы, часа на 4")
    assert history[1][0] == "assistant" and "Действия бота" in history[1][1]


async def test_chat_parallel_tools_and_errors_in_one_user_message(db, user, make_ai):
    _, start = day_local(1, "15:00")
    ai = make_ai(
        msg(tool("add_event", {"title": "Встреча с куратором", "start": start, "kind": "meeting"}, "t1"),
            tool("complete_task", {"task_id": 999}, "t2"), stop="tool_use"),
        msg(text("Встречу добавил, а задачу 999 не нашёл.")))
    reply = await ai.chat(user, "завтра в 15 встреча с куратором и закрой задачу 999")
    results = ai._client.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert "is_error" not in results[0] and results[1]["is_error"] is True
    assert reply.changed and len(reply.actions) == 1
    assert len(await db.list_events(user.id, now_utc(), now_utc() + timedelta(days=3))) == 1


async def test_chat_history_is_text_only_and_starts_with_user(db, user, make_ai):
    await db.add_ai_message(user.id, "assistant", "осиротевший ответ")
    await db.add_ai_message(user.id, "user", "привет")
    await db.add_ai_message(user.id, "assistant", "Привет! Чем помочь?")
    ai = make_ai(msg(text("Ок")))
    await ai.chat(user, "что у меня завтра?")
    messages = ai._client.calls[0]["messages"]
    assert messages[0] == {"role": "user", "content": "привет"}
    assert messages[1] == {"role": "assistant", "content": "Привет! Чем помочь?"}
    assert len(messages) == 3


async def test_chat_refusal_runs_no_tools(db, user, make_ai):
    ai = make_ai(msg(tool("add_task", {"title": "X", "importance": 1, "estimate_min": 10, "energy": "low",
                                       "category": "other"}), stop="refusal"))
    reply = await ai.chat(user, "...")
    assert reply.text == TEXT_REFUSAL and not reply.changed and reply.actions == []
    assert await db.list_tasks(user.id) == []
    assert await db.get_ai_history(user.id) == []


async def test_chat_pause_turn_continues(db, user, make_ai):
    ai = make_ai(msg(thinking(), stop="pause_turn"), msg(text("Готово")))
    reply = await ai.chat(user, "привет")
    assert reply.text == "Готово" and len(ai._client.calls) == 2


async def test_chat_iteration_limit(db, user, make_ai):
    ai = make_ai(*[msg(tool("list_tasks", {}, f"t{i}"), stop="tool_use") for i in range(MAX_TOOL_ITERATIONS)])
    reply = await ai.chat(user, "зациклись")
    assert len(ai._client.calls) == MAX_TOOL_ITERATIONS and reply.text


@pytest.mark.parametrize("exc, expected", [
    (status_error(anthropic.RateLimitError, 429), TEXT_RATE_LIMIT),
    (status_error(anthropic.InternalServerError, 500), TEXT_OVERLOADED),
    (status_error(anthropic.APIStatusError, 529, "overloaded"), TEXT_OVERLOADED),
    (status_error(anthropic.AuthenticationError, 401), TEXT_AUTH),
    (anthropic.APIConnectionError(request=_REQ), TEXT_CONNECTION),
    (anthropic.APITimeoutError(request=_REQ), TEXT_TIMEOUT),
    (RuntimeError("boom"), assistant_mod.TEXT_ERROR),
])
async def test_chat_never_raises_on_api_errors(db, user, make_ai, exc, expected):
    reply = await make_ai(exc).chat(user, "привет")
    assert reply.text == expected and reply.actions == [] and not reply.changed


async def test_chat_error_after_tool_keeps_actions(db, user, make_ai):
    ai = make_ai(msg(tool("start_tracking", {"category": "study"}), stop="tool_use"),
                 status_error(anthropic.RateLimitError, 429))
    reply = await ai.chat(user, "сел за матан")
    assert reply.text == TEXT_RATE_LIMIT and reply.changed and reply.actions[0].startswith("▶️ Трекер")


async def test_fallbacks_disable_themselves_on_400(db, user, make_ai):
    ai = make_ai(status_error(anthropic.BadRequestError, 400, "fallbacks: Extra inputs are not permitted"),
                 msg(text("ок")), msg(text("ещё ок")))
    assert (await ai.chat(user, "привет")).text == "ок"
    assert not ai.use_fallbacks
    await ai.chat(user, "ещё")
    paths = [(c["_path"], "betas" in c, "fallbacks" in c) for c in ai._client.calls]
    assert paths == [("beta", True, True), ("messages", False, False), ("messages", False, False)]


async def test_fallbacks_can_be_disabled_by_env(db, monkeypatch):
    monkeypatch.setenv("AI_SERVER_FALLBACKS", "0")
    assert AIAssistant(db, "k").use_fallbacks is False


async def test_strict_tools_degrade_on_400(db, user, make_ai):
    ai = make_ai(status_error(anthropic.BadRequestError, 400, "tools.3: strict schema has too many optional params"),
                 msg(text("ок")))
    assert (await ai.chat(user, "привет")).text == "ок"
    assert all("strict" not in t for t in ai._client.calls[1]["tools"])


async def test_other_bad_request_is_not_retried(db, user, make_ai):
    ai = make_ai(status_error(anthropic.BadRequestError, 400, "messages: roles must alternate"))
    reply = await ai.chat(user, "привет")
    assert reply.text == assistant_mod.TEXT_BAD_REQUEST and len(ai._client.calls) == 1


async def test_chat_disabled_modes(db, user):
    reply = await AIAssistant(db, None).chat(user, "привет")
    assert reply.text == TEXT_DISABLED and not reply.changed
    ai = AIAssistant(db, "k")
    ai._client = FakeClient()  # любой вызов API упадёт в assert
    off = replace(user, settings=replace(user.settings, ai_enabled=False))
    assert (await ai.chat(off, "привет")).text == TEXT_USER_DISABLED


def test_echo_content_drops_declined_partial_after_fallback():
    fb = SimpleNamespace(type="fallback")
    kept_text, tail = text("частичный"), text("ответ fallback-модели")
    blocks = [thinking(), tool("x", {}), kept_text, fb, tail]
    assert _echo_content(blocks) == [kept_text, tail]
    plain = [thinking(), text("a")]
    assert _echo_content(plain) == plain and _echo_content(plain)[0] is plain[0]


# ---------------------------------------------------------------- improve_plan

@pytest.fixture
async def plan_setup(db, user):
    d = local_today(TZ) + timedelta(days=1)
    task = await db.add_task(user.id, "Курсач", importance=3, energy="high", estimate_min=120)
    ev_start = combine_local(d, "15:00", TZ)
    event = await db.add_event(user.id, "Куратор", ev_start, end_at=ev_start + timedelta(hours=1))
    lesson = await db.add_lesson(user.id, d.weekday(), "09:00", "10:30", "Английский язык")
    plan = DayPlan(user_id=user.id, date=d, items=[
        PlanItem("09:00", "10:30", "lesson", "Английский язык", lesson.id, "ауд. 1-301"),
        PlanItem("12:00", "13:00", "task", "Курсач", task.id),
        PlanItem("13:00", "13:30", "meal", "Обед"),
        PlanItem("15:00", "16:00", "event", "Куратор", event.id),
    ])
    return SimpleNamespace(plan=plan, lessons=[lesson], events=[event], tasks=[task], task=task,
                           lesson=lesson, event=event)


def plan_json(items, comment="Курсач перенёс на утро — это твой пик."):
    return msg(text(json.dumps({"items": items, "comment": comment}, ensure_ascii=False)))


def good_items(s):
    return [
        {"start": "08:00", "end": "08:30", "kind": "meal", "title": "Завтрак", "ref_id": None, "note": None},
        {"start": "09:00", "end": "10:30", "kind": "lesson", "title": "Англ", "ref_id": s.lesson.id, "note": None},
        {"start": "10:45", "end": "12:15", "kind": "task", "title": "Курсач", "ref_id": s.task.id,
         "note": "сложное — в пик"},
        {"start": "13:00", "end": "13:30", "kind": "meal", "title": "Обед", "ref_id": 77, "note": None},
        {"start": "15:00", "end": "16:00", "kind": "event", "title": "Куратор", "ref_id": s.event.id, "note": None},
    ]


async def test_improve_plan_valid(user, make_ai, plan_setup):
    s = plan_setup
    original_items = [i.to_dict() for i in s.plan.items]
    ai = make_ai(plan_json(good_items(s)))
    result = await ai.improve_plan(user, s.plan, lessons=s.lessons, events=s.events, tasks=s.tasks)
    assert result is not s.plan and result.status == "draft" and result.date == s.plan.date
    assert result.ai_comment == "Курсач перенёс на утро — это твой пик."
    assert [(i.start, i.kind) for i in result.items] == [("08:00", "meal"), ("09:00", "lesson"), ("10:45", "task"),
                                                        ("13:00", "meal"), ("15:00", "event")]
    lesson_item = result.items[1]
    assert lesson_item.title == "Английский язык" and lesson_item.note == "ауд. 1-301"  # фикс. блок из оригинала
    assert result.items[3].ref_id is None  # у еды ref_id обнулён
    assert [i.to_dict() for i in s.plan.items] == original_items  # исходник не тронут
    c = ai._client.calls[0]
    assert c["output_config"]["effort"] == "medium"
    assert c["output_config"]["format"]["type"] == "json_schema"
    payload = c["messages"][0]["content"]
    assert "Курсач" in payload and str(s.task.id) in payload


@pytest.mark.parametrize("mutate", [
    lambda it, s: it[1].update(start="09:15"),                                   # пара сдвинута
    lambda it, s: it.pop(4),                                                     # событие пропало
    lambda it, s: it.append({"start": "18:00", "end": "19:00", "kind": "event", "title": "Новое",
                             "ref_id": 999, "note": None}),                      # выдуманное событие
    lambda it, s: it[2].update(start="10:00"),                                   # пересечение с парой
    lambda it, s: it[2].update(ref_id=424242),                                   # несуществующая задача
    lambda it, s: it[0].update(start="05:00"),                                   # раньше подъёма
    lambda it, s: it[0].update(start="8.00"),                                    # не HH:MM
    lambda it, s: it[3].update(end="24:00"),                                     # 24:00 нельзя
    lambda it, s: it[3].update(start="13:30", end="13:00"),                      # start >= end
    lambda it, s: it.clear(),                                                    # пустой план
])
async def test_improve_plan_rejects_invalid(user, make_ai, plan_setup, mutate):
    s = plan_setup
    items = good_items(s)
    mutate(items, s)
    result = await make_ai(plan_json(items)).improve_plan(user, s.plan, lessons=s.lessons, events=s.events,
                                                          tasks=s.tasks)
    assert [i.to_dict() for i in result.items] == [i.to_dict() for i in s.plan.items]
    assert result.ai_comment == PLAN_FAILED_COMMENT


@pytest.mark.parametrize("response", [
    msg(text("это не json")),
    msg(text('{"items": [], "comment": 1}')),
    msg(stop="refusal"),
    msg(text('{"items": ['), stop="max_tokens"),
    status_error(anthropic.RateLimitError, 429),
    anthropic.APIConnectionError(request=_REQ),
])
async def test_improve_plan_falls_back_on_errors(user, make_ai, plan_setup, response):
    s = plan_setup
    result = await make_ai(response).improve_plan(user, s.plan, lessons=s.lessons, events=s.events, tasks=s.tasks)
    assert [i.to_dict() for i in result.items] == [i.to_dict() for i in s.plan.items]
    assert result.ai_comment == PLAN_FAILED_COMMENT


async def test_improve_plan_after_midnight_sleep_and_overlapping_fixed(db, make_ai, plan_setup):
    s = plan_setup
    night_owl, _ = await db.get_or_create_user(4004, 4004, "Сова", default_settings=UserSettings(
        tz=TZ, wake_time="08:30", sleep_time="00:30"))
    ev2 = replace(s.plan.items[3], title="Второе событие", ref_id=s.event.id + 100)  # пересекается с первым
    plan = replace(s.plan, user_id=night_owl.id, items=s.plan.items + [replace(ev2, start="15:30", end="16:30")])
    items = good_items(s)[1:] + [
        {"start": "15:30", "end": "16:30", "kind": "event", "title": "x", "ref_id": ev2.ref_id, "note": None},
        {"start": "23:00", "end": "23:59", "kind": "routine", "title": "Подготовка ко сну", "ref_id": None,
         "note": None}]
    result = await make_ai(plan_json(items)).improve_plan(night_owl, plan, lessons=s.lessons, events=s.events,
                                                          tasks=s.tasks)
    assert result.ai_comment != PLAN_FAILED_COMMENT
    assert result.items[-1].end == "23:59"


async def test_improve_plan_disabled_returns_same_plan(db, user, plan_setup):
    s = plan_setup
    assert await AIAssistant(db, None).improve_plan(user, s.plan, lessons=[], events=[], tasks=[]) is s.plan


# ---------------------------------------------------------------- parse_timetable

def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "PNG")
    return buf.getvalue()


def timetable_response(lessons):
    return msg(text(json.dumps({"lessons": lessons}, ensure_ascii=False)))


def L(day, time, subject, weeks="all", kind="", room=None, teacher=None):
    return {"day": day, "time": time, "subject": subject, "kind": kind, "room": room, "teacher": teacher,
            "weeks": weeks}


async def test_parse_timetable_image_filters_garbage(make_ai):
    raw = [
        L("пн", "09:00-10:30", "Английский язык", room="1-301"),
        L("пн", "10:45-12:15", "Деловой китайский", weeks="odd", kind="讲座", room="3-313"),  # 单周
        L("пн", "10:45-12:15", "Деловой китайский", weeks="odd", room="3-313"),               # дубль
        L("xx", "09:00-10:30", "Мусор"),
        L("вт", "9-10", "Плохое время"),
        L("вт", "12:00-11:00", "Наоборот"),
        L("ср", "25:00-26:00", "Нет такого времени"),
        L("ср", "14:00-15:30", "   "),
        "не словарь",
        L("пт", "15:45-17:15", "Чтение", weeks="even", kind="сем.", teacher="Ли"),
    ]
    ai = make_ai(timetable_response(raw))
    png = _png()
    lessons = await ai.parse_timetable(image=png, mime="application/octet-stream")
    assert [(x["day"], x["time"], x["subject"], x["weeks"]) for x in lessons] == [
        ("пн", "09:00-10:30", "Английский язык", "all"),
        ("пн", "10:45-12:15", "Деловой китайский", "odd"),
        ("пт", "15:45-17:15", "Чтение", "even"),
    ]
    assert lessons[1]["kind"] == "лекция" and lessons[2]["kind"] == "семинар" and lessons[2]["teacher"] == "Ли"
    for x in lessons:
        normalize_lesson_dict(x)
    c = ai._client.calls[0]
    image_block, text_block = c["messages"][0]["content"]
    assert image_block["source"] == {"type": "base64", "media_type": "image/png",
                                     "data": base64.standard_b64encode(png).decode()}
    assert text_block["type"] == "text"
    assert c["output_config"]["effort"] == "medium" and c["output_config"]["format"]["type"] == "json_schema"
    schema = json.dumps(c["output_config"]["format"]["schema"], ensure_ascii=False)
    assert '"пн"' in schema and '"odd"' in schema


async def test_parse_timetable_realistic_text(make_ai):
    _, expected = load_timetable_file("data/timetable.yaml")
    days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    raw = [L(days[x["weekday"]], f"{x['start_time']}-{x['end_time']}", x["subject"], room=x["room"],
             teacher=x["teacher"]) for x in expected]
    ai = make_ai(timetable_response(raw))
    lessons = await ai.parse_timetable(text="星期一 第1-2节 英语 1-301 ...")
    assert len(lessons) == len(expected)
    assert [normalize_lesson_dict(x)["start_time"] for x in lessons[:3]] == ["09:00", "10:45", "15:45"]
    [only_text] = ai._client.calls[0]["messages"][0]["content"]
    assert "星期一" in only_text["text"]


async def test_parse_timetable_empty_and_errors(db, make_ai):
    ai = make_ai()
    assert await ai.parse_timetable() == [] and ai._client.calls == []
    assert await make_ai(msg(stop="refusal")).parse_timetable(text="пн 9:00 матан") == []
    assert await make_ai(anthropic.APIConnectionError(request=_REQ)).parse_timetable(text="x") == []
    assert await make_ai(msg(text("[1, 2]"))).parse_timetable(text="x") == []
    assert await AIAssistant(db, None).parse_timetable(text="пн 9:00 матан") == []


# ---------------------------------------------------------------- suggest_task_fields / day_insight

async def test_suggest_task_fields(user, make_ai):
    d, dl = day_local(5, "18:00")
    ai = make_ai(msg(text(json.dumps({"importance": 3, "estimate_min": 5000, "energy": "high",
                                      "category": "study", "deadline": dl}))))
    fields = await ai.suggest_task_fields(user, "Курсач до пятницы")
    assert fields == {"importance": 3, "estimate_min": 1440, "energy": "high", "category": "study",
                      "deadline": iso(combine_local(d, "18:00", TZ))}
    assert parse_iso(fields["deadline"]).tzinfo is not None
    c = ai._client.calls[0]
    assert c["output_config"]["effort"] == "low" and "Курсач до пятницы" in c["messages"][0]["content"]


async def test_suggest_task_fields_failures(db, user, make_ai):
    assert await make_ai(msg(text('{"importance": 9}'))).suggest_task_fields(user, "x") == {}
    assert await make_ai(status_error(anthropic.RateLimitError, 429)).suggest_task_fields(user, "x") == {}
    assert await AIAssistant(db, None).suggest_task_fields(user, "x") == {}
    ok = await make_ai(msg(text(json.dumps({"importance": 1, "estimate_min": 15, "energy": "low",
                                            "category": "personal", "deadline": None})))).suggest_task_fields(
        user, "Купить молоко")
    assert ok["deadline"] is None and ok["category"] == "personal"


async def test_day_insight(user, make_ai):
    st = DayStats(date=local_today(TZ), minutes_by_category={"study": 180, "rest": 90}, tracked_min=270,
                  productive_min=180, avg_rating=4.0, tasks_done=2, focus_score=72)
    ai = make_ai(msg(thinking(), text("**Сильный день**: 3 ч учёбы <3. Завтра начни с курсача в 9:00.")))
    out = await ai.day_insight(user, st, None, [])
    assert out == "<b>Сильный день</b>: 3 ч учёбы &lt;3. Завтра начни с курсача в 9:00."
    c = ai._client.calls[0]
    assert c["output_config"] == {"effort": "low"} and "Учёба" in c["messages"][0]["content"]


async def test_day_insight_failures(db, user, make_ai):
    st = DayStats(date=local_today(TZ))
    assert await make_ai(msg(stop="refusal")).day_insight(user, st, None, []) is None
    assert await make_ai(status_error(anthropic.InternalServerError, 500)).day_insight(user, st, None, []) is None
    assert await make_ai(msg(text("  "))).day_insight(user, st, None, []) is None
    assert await AIAssistant(db, None).day_insight(user, st, None, []) is None


async def test_context_mentions_location_and_parity(db, make_ai):
    shz, _ = await db.get_or_create_user(5005, 5005, "Студент", default_settings=UserSettings(
        tz="Asia/Shanghai", tz_auto=True, semester_start="2026-09-01",
        tz_rules=[{"from": "09-01", "to": "01-31", "tz": "Asia/Shanghai", "label": "Шэньчжэнь"}]))
    ai = make_ai(msg(text("ок")))
    await ai.chat(shz, "привет")
    ctx = ai._client.calls[0]["messages"][-1]["content"][0]["text"]
    assert "Шэньчжэнь" in ctx and "Asia/Shanghai" in ctx and "UTC+08:00" in ctx
    assert ("числитель" in ctx) or ("знаменатель" in ctx)
    assert datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai")).date().isoformat() \
        in ctx
