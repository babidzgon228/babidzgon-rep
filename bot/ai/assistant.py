"""[Агент «ИИ»] Claude-ассистент планировщика.

Параметры API (Claude Opus 5.5, anthropic SDK 2.6):
- модель — из bot.config (Config.anthropic_model / ANTHROPIC_MODEL), здесь не дублируется;
- thinking не передаём (на Opus 5.5 он всегда adaptive; disabled/budget_tokens -> 400), глубину задаёт
  output_config.effort: chat/insight/suggest — "low", improve_plan/parse_timetable — "medium";
- tool_choice не передаём (auto; any/tool на Opus 5.5 -> 400), инструменты strict + additionalProperties:false;
- структурированные ответы — output_config.format (JSON Schema из pydantic через anthropic.transform_schema);
- server-side fallbacks: client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default").
  Отключается переменной AI_SERVER_FALLBACKS=0 и автоматически, если API отвергает параметр (400);
- prompt caching: breakpoint на последнем блоке system (кеширует tools+system) + автоматический для хвоста
  диалога в агентном цикле. В system нет дат — текущее время идёт в user-сообщении (<context>);
- stop_reason проверяется до чтения content (refusal / max_tokens / pause_turn / tool_use).
Ни один метод не бросает исключений наружу.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

import anthropic
from pydantic import ValidationError

from bot.ai import prompts
from bot.ai.context import build_context, next_days_line, now_line, week_line
from bot.ai.formatting import plain_text, sanitize_html, strip_tags
from bot.ai.schemas import (
    PLAN_FORMAT,
    TASK_FIELDS_FORMAT,
    TIMETABLE_FORMAT,
    AIOutputError,
    PlanProposal,
    TaskFieldsOut,
    clean_task_fields,
    clean_timetable,
    load_json,
    validate_plan,
    validation_message,
)
from bot.ai.tools import TOOLS, TOOLS_STRICT, ToolError, ToolExecutor, parse_local_dt, safe_prioritize
from bot.config import Config
from bot.models import (
    ACTIVITY_CATEGORIES,
    WEEKDAYS_FULL,
    Activity,
    DayPlan,
    DayStats,
    Event,
    Lesson,
    PlanItem,
    Task,
    User,
)
from bot.timeutil import local_now, local_today, now_utc, to_local

log = logging.getLogger(__name__)

DEFAULT_MODEL: str = Config.anthropic_model  # единственный источник — bot/config.py
FALLBACK_BETA = "server-side-fallback-2026-07-01"   # для scalar-формы fallbacks="default"

CHAT_EFFORT, PLAN_EFFORT, INSIGHT_EFFORT, TIMETABLE_EFFORT, SUGGEST_EFFORT = "low", "medium", "low", "medium", "low"
# thinking тоже входит в max_tokens; значения < ~21k, чтобы SDK не требовал стриминга
CHAT_MAX_TOKENS, PLAN_MAX_TOKENS, INSIGHT_MAX_TOKENS, TIMETABLE_MAX_TOKENS, SUGGEST_MAX_TOKENS = (
    8000, 12000, 2000, 16000, 1500)
MAX_TOOL_ITERATIONS = 8
HISTORY_LIMIT = 12
MAX_USER_TEXT = 4000
MAX_HISTORY_CHARS = 2000
REQUEST_TIMEOUT = 120.0
MAX_IMAGE_BYTES = 4_500_000
SUPPORTED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")

TEXT_DISABLED = ("🤖 ИИ-ассистент не подключён: нужен ANTHROPIC_API_KEY в .env. "
                 "Остальные функции бота работают как обычно — пользуйся кнопками меню.")
TEXT_USER_DISABLED = "🤖 ИИ-ассистент выключен в настройках. Включи его там, и я снова буду помогать текстом."
TEXT_EMPTY_INPUT = "✍️ Напиши, что нужно сделать — например: «завтра в 15 встреча с куратором»."
TEXT_REFUSAL = ("🙈 С этим запросом я помочь не могу. Давай лучше про задачи, расписание или планы — "
                "в этом я силён.")
TEXT_RATE_LIMIT = "⏳ Слишком много запросов к ИИ. Подожди минутку и попробуй ещё раз."
TEXT_OVERLOADED = "😮‍💨 ИИ сейчас перегружен. Попробуй чуть позже."
TEXT_CONNECTION = "📡 Не удалось связаться с ИИ. Проверь интернет и попробуй ещё раз."
TEXT_TIMEOUT = "⌛ ИИ слишком долго отвечал. Попробуй ещё раз или сформулируй короче."
TEXT_AUTH = "🔑 ИИ недоступен: проблема с ключом API (ANTHROPIC_API_KEY)."
TEXT_BAD_REQUEST = "⚠️ ИИ не смог обработать запрос. Попробуй переформулировать."
TEXT_ERROR = "⚠️ Что-то пошло не так с ИИ. Попробуй ещё раз чуть позже."
TEXT_TOO_LONG = "✂️ Ответ получился слишком длинным. Спроси покороче или по частям."
TEXT_NO_ANSWER = "🤔 Не нашёлся с ответом. Переформулируй, пожалуйста."
TEXT_DONE = "Готово ✅"
PLAN_FAILED_COMMENT = "🤖 Улучшить план с ИИ не получилось — оставил исходный вариант."


@dataclass
class AIReply:
    text: str                                         # Telegram-HTML-safe
    actions: list[str] = field(default_factory=list)  # что сделано: ["➕ Задача «Курсач» добавлена"] (HTML-safe)
    changed: bool = False                             # менял ли данные (задачи/события/трекер/...)


# ---------------------------------------------------------------- helpers для блоков ответа

def _btype(block: Any) -> str | None:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


_PRE_FALLBACK_DROP = {"thinking", "redacted_thinking", "tool_use", "server_tool_use", "fallback"}


def _echo_content(content: Any) -> list[Any]:
    """response.content для истории. Блоки остаются неизменными (thinking — как есть).

    Если был server-side fallback, то до последнего блока `fallback` выкидываем thinking/tool_use
    отказавшей модели (правило «echoing fallback turns back»), сам маркер `fallback` тоже убираем."""
    blocks = list(content or [])
    last = max((i for i, b in enumerate(blocks) if _btype(b) == "fallback"), default=-1)
    if last < 0:
        return blocks
    return [b for b in blocks[:last] if _btype(b) not in _PRE_FALLBACK_DROP] + blocks[last + 1:]


def _text_of(blocks: list[Any], sep: str = "\n\n") -> str:
    parts = []
    for b in blocks:
        if _btype(b) == "text":
            t = b.get("text") if isinstance(b, dict) else getattr(b, "text", None)
            if t and t.strip():
                parts.append(t if sep == "" else t.strip())
    return sep.join(parts).strip()


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "нет")


def _sniff_image(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _reencode_jpeg(data: bytes) -> bytes:
    from PIL import Image  # Pillow уже в зависимостях

    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((2400, 2400))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return buf.getvalue()


# ---------------------------------------------------------------- ассистент

class AIAssistant:
    def __init__(self, db, api_key: str | None, model: str = DEFAULT_MODEL) -> None:
        self.db, self.api_key, self.model = db, api_key, model or DEFAULT_MODEL
        # Server-side fallbacks (бета). Выключаются env-переменной или сами при 400 от API.
        self.use_fallbacks: bool = _env_flag("AI_SERVER_FALLBACKS", True)
        self._strict_tools = True
        self._effort_ok = True
        self._cache_ok = True
        self._client: Any = None
        self._locks: dict[int, asyncio.Lock] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key, max_retries=2, timeout=REQUEST_TIMEOUT)
        return self._client

    async def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            try:
                await self._client.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ транспорт

    def _params(self, *, system: str, messages: list[dict[str, Any]], effort: str | None, max_tokens: int,
                tools: bool, output_format: dict[str, Any] | None, cache_tail: bool) -> dict[str, Any]:
        params: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        if self._cache_ok:
            # breakpoint на последнем блоке system кеширует tools + system (порядок рендера: tools -> system)
            params["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if cache_tail:
                params["cache_control"] = {"type": "ephemeral"}  # авто-breakpoint на растущем хвосте цикла
        else:
            params["system"] = system
        output_config: dict[str, Any] = {}
        if effort and self._effort_ok:
            output_config["effort"] = effort
        if output_format:
            output_config["format"] = output_format
        if output_config:
            params["output_config"] = output_config
        if tools:
            params["tools"] = TOOLS_STRICT if self._strict_tools else TOOLS
        return params

    def _degrade(self, e: anthropic.BadRequestError, *, tools: bool) -> str | None:
        """Если 400 вызван необязательной фичей — выключаем её и даём повторить запрос."""
        msg = f"{getattr(e, 'message', '')} {getattr(e, 'body', '')}".lower()
        if self.use_fallbacks and ("fallback" in msg or "beta" in msg):
            self.use_fallbacks = False
            return "server-side fallbacks"
        if tools and self._strict_tools and "strict" in msg:
            self._strict_tools = False
            return "strict tools"
        if self._effort_ok and "effort" in msg:
            self._effort_ok = False
            return "output_config.effort"
        if self._cache_ok and "cache_control" in msg:
            self._cache_ok = False
            return "cache_control"
        return None

    async def _request(self, *, system: str, messages: list[dict[str, Any]], effort: str | None,
                       max_tokens: int, tools: bool = False, output_format: dict[str, Any] | None = None,
                       cache_tail: bool = False) -> Any:
        for _attempt in range(5):
            params = self._params(system=system, messages=messages, effort=effort, max_tokens=max_tokens,
                                  tools=tools, output_format=output_format, cache_tail=cache_tail)
            try:
                if self.use_fallbacks:
                    resp = await self.client.beta.messages.create(
                        betas=[FALLBACK_BETA], fallbacks="default", **params)
                else:
                    resp = await self.client.messages.create(**params)
            except anthropic.BadRequestError as e:
                feature = self._degrade(e, tools=tools)
                if feature is None:
                    raise
                log.warning("Claude API отклонил %s (%s) — отключаю и повторяю запрос", feature, e.message)
                continue
            self._log_usage(resp)
            return resp
        raise RuntimeError("не удалось подобрать параметры запроса к Claude API")

    @staticmethod
    def _log_usage(resp: Any) -> None:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        iterations = getattr(usage, "iterations", None) or []
        if any(getattr(it, "type", None) == "fallback_message" for it in iterations):
            log.info("Ответ дала fallback-модель %s (stop_reason=%s)", getattr(resp, "model", "?"),
                     getattr(resp, "stop_reason", None))
        log.debug("usage: in=%s out=%s cache_read=%s cache_write=%s",
                  getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None),
                  getattr(usage, "cache_read_input_tokens", None),
                  getattr(usage, "cache_creation_input_tokens", None))

    @staticmethod
    def _log_api_error(where: str, e: BaseException) -> None:
        if isinstance(e, anthropic.RateLimitError):
            log.warning("%s: rate limit (%s)", where, e)
        elif isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            log.error("%s: ключ API отклонён (%s)", where, e)
        elif isinstance(e, anthropic.APIStatusError):
            log.error("%s: API %s: %s (request_id=%s)", where, e.status_code, e.message,
                      getattr(e, "request_id", None))
        elif isinstance(e, anthropic.APIConnectionError):
            log.warning("%s: нет связи с API (%s)", where, e)
        else:
            log.exception("%s: ошибка ИИ", where, exc_info=e)

    def _structured(self, resp: Any) -> Any:
        stop = getattr(resp, "stop_reason", None)
        if stop == "refusal":
            raise AIOutputError("модель отказалась (refusal)")
        if stop == "max_tokens":
            raise AIOutputError("ответ обрезан (max_tokens)")
        return load_json(_text_of(_echo_content(getattr(resp, "content", None)), sep=""))

    def _lock(self, user_id: int) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    # ------------------------------------------------------------ chat

    async def chat(self, user: User, text: str) -> AIReply:
        text = (text or "").strip()
        if not self.enabled:
            return AIReply(TEXT_DISABLED)
        if not user.settings.ai_enabled:
            return AIReply(TEXT_USER_DISABLED)
        if not text:
            return AIReply(TEXT_EMPTY_INPUT)

        async with self._lock(user.id):
            executor = ToolExecutor(self.db, user)
            ok = False
            try:
                raw, ok = await self._chat_loop(user, text[:MAX_USER_TEXT], executor)
                reply = sanitize_html(raw) if ok else raw
                if ok and not reply:
                    reply = TEXT_DONE if executor.actions else TEXT_NO_ANSWER
            except anthropic.RateLimitError as e:
                self._log_api_error("chat", e)
                reply = TEXT_RATE_LIMIT
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
                self._log_api_error("chat", e)
                reply = TEXT_AUTH
            except anthropic.BadRequestError as e:
                self._log_api_error("chat", e)
                reply = TEXT_BAD_REQUEST
            except anthropic.APIStatusError as e:  # 5xx, 529 overloaded и прочие
                self._log_api_error("chat", e)
                reply = TEXT_OVERLOADED if e.status_code >= 500 else TEXT_ERROR
            except anthropic.APITimeoutError as e:
                self._log_api_error("chat", e)
                reply = TEXT_TIMEOUT
            except anthropic.APIConnectionError as e:
                self._log_api_error("chat", e)
                reply = TEXT_CONNECTION
            except anthropic.AnthropicError as e:
                self._log_api_error("chat", e)
                reply = TEXT_ERROR
            except Exception:  # noqa: BLE001 — бот не должен падать из-за ИИ
                log.exception("chat: неожиданная ошибка")
                reply = TEXT_ERROR

            if ok or executor.actions:
                await self._remember(user, text, reply if ok else "", executor.actions)
            return AIReply(text=reply, actions=list(executor.actions), changed=executor.changed)

    async def _chat_loop(self, user: User, text: str, executor: ToolExecutor) -> tuple[str, bool]:
        """Ручной агентный цикл. Возвращает (текст ответа модели, ok)."""
        messages = await self._history(user)
        context = await build_context(self.db, user)
        messages.append({"role": "user", "content": [{"type": "text", "text": context},
                                                     {"type": "text", "text": text}]})
        for iteration in range(1, MAX_TOOL_ITERATIONS + 1):
            resp = await self._request(system=prompts.CHAT_SYSTEM_PROMPT, messages=messages, effort=CHAT_EFFORT,
                                       max_tokens=CHAT_MAX_TOKENS, tools=True, cache_tail=True)
            stop = getattr(resp, "stop_reason", None)
            if stop == "refusal":  # до чтения content; инструменты этого хода не выполняем
                details = getattr(resp, "stop_details", None)
                log.warning("chat: refusal (category=%s)", getattr(details, "category", None))
                return TEXT_REFUSAL, False
            content = _echo_content(getattr(resp, "content", None))
            tool_uses = [b for b in content if _btype(b) == "tool_use"]

            if stop == "tool_use" and tool_uses:
                messages.append({"role": "assistant", "content": content})  # целиком, thinking неизменны
                results = await self._run_tools(executor, tool_uses)
                if iteration == MAX_TOOL_ITERATIONS:
                    log.warning("chat: достигнут лимит %d итераций инструментов", MAX_TOOL_ITERATIONS)
                    return _text_of(content), True
                messages.append({"role": "user", "content": results})  # все tool_result — одним сообщением
                continue
            if stop == "pause_turn":
                messages.append({"role": "assistant", "content": content})
                continue
            if stop == "max_tokens":
                partial = _text_of(content)
                return (partial, True) if partial else (TEXT_TOO_LONG, False)
            return _text_of(content), True
        return "", True

    @staticmethod
    async def _run_tools(executor: ToolExecutor, blocks: list[Any]) -> list[dict[str, Any]]:
        results = []
        for b in blocks:  # последовательно: операции с БД зависят друг от друга
            out, is_error = await executor.run(getattr(b, "name", ""), getattr(b, "input", None))
            result: dict[str, Any] = {"type": "tool_result", "tool_use_id": b.id, "content": out}
            if is_error:
                result["is_error"] = True
            results.append(result)
        return results

    async def _history(self, user: User) -> list[dict[str, Any]]:
        try:
            rows = await self.db.get_ai_history(user.id, limit=HISTORY_LIMIT)
        except Exception:  # noqa: BLE001
            log.exception("chat: не удалось прочитать историю")
            return []
        messages: list[dict[str, Any]] = []
        for role, content in rows:
            content = (content or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            content = content[:MAX_HISTORY_CHARS]
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += "\n\n" + content
            else:
                messages.append({"role": role, "content": content})
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    async def _remember(self, user: User, text: str, reply: str, actions: list[str]) -> None:
        stored = reply
        if actions:
            done = "; ".join(strip_tags(a) for a in actions)
            stored = f"{stored}\n\n(Действия бота: {done})".strip()
        try:
            await self.db.add_ai_message(user.id, "user", text)
            await self.db.add_ai_message(user.id, "assistant", stored)
        except Exception:  # noqa: BLE001
            log.exception("chat: не удалось сохранить историю")

    # ------------------------------------------------------------ improve_plan

    async def improve_plan(self, user: User, plan: DayPlan, *, lessons: list[Lesson],
                           events: list[Event], tasks: list[Task]) -> DayPlan:
        if not self.enabled or not user.settings.ai_enabled:
            return plan
        try:
            payload = self._plan_payload(user, plan, lessons, events, tasks)
            resp = await self._request(system=prompts.PLAN_SYSTEM_PROMPT,
                                       messages=[{"role": "user", "content": payload}],
                                       effort=PLAN_EFFORT, max_tokens=PLAN_MAX_TOKENS, output_format=PLAN_FORMAT)
            proposal = PlanProposal.model_validate(self._structured(resp))
            items = validate_plan(proposal, plan, user.settings, {t.id for t in tasks})
        except AIOutputError as e:
            log.warning("improve_plan: ответ отклонён: %s", e)
            return self._plan_fallback(plan)
        except ValidationError as e:
            log.warning("improve_plan: ответ не по схеме: %s", validation_message(e))
            return self._plan_fallback(plan)
        except anthropic.AnthropicError as e:
            self._log_api_error("improve_plan", e)
            return self._plan_fallback(plan)
        except Exception:  # noqa: BLE001
            log.exception("improve_plan: неожиданная ошибка")
            return self._plan_fallback(plan)
        comment = plain_text(proposal.comment, limit=400) or None
        return DayPlan(user_id=plan.user_id, date=plan.date, items=items, status="draft", ai_comment=comment)

    @staticmethod
    def _plan_fallback(plan: DayPlan) -> DayPlan:
        return replace(plan, items=[PlanItem.from_dict(i.to_dict()) for i in plan.items],
                       ai_comment=PLAN_FAILED_COMMENT)

    def _plan_payload(self, user: User, plan: DayPlan, lessons: list[Lesson], events: list[Event],
                      tasks: list[Task]) -> str:
        s = user.settings
        tzn = s.tz
        d = plan.date
        now_l = local_now(tzn)

        def local(dt: datetime | None) -> str | None:
            if dt is None:
                return None
            l = to_local(dt, tzn)
            return l.strftime("%H:%M") if l.date() == d else l.strftime("%Y-%m-%d %H:%M")

        ranked = safe_prioritize([t for t in tasks if t.status == "todo"], now_utc())
        data = {
            "date": d.isoformat(), "weekday": WEEKDAYS_FULL[d.weekday()].lower(), "week": week_line(d, user),
            "now": now_l.strftime("%H:%M") if d == now_l.date() else None,
            "settings": {"wake_time": s.wake_time, "sleep_time": s.sleep_time, "focus_peak": s.focus_peak,
                         "commute_min": s.commute_min},
            "draft_plan": [{"start": i.start, "end": i.end, "kind": i.kind, "title": i.title, "ref_id": i.ref_id,
                            "note": i.note} for i in plan.items],
            "lessons": [{"id": l.id, "start": l.start_time, "end": l.end_time, "subject": l.subject,
                         "kind": l.kind or None, "room": l.room} for l in lessons],
            "events": [{"id": e.id, "title": e.title, "start": local(e.start_at), "end": local(e.end_at),
                        "location": e.location} for e in events],
            "tasks": [{"id": t.id, "title": t.title, "importance": t.importance,
                       "deadline": to_local(t.deadline, tzn).strftime("%Y-%m-%d %H:%M") if t.deadline else None,
                       "estimate_min": t.estimate_min, "energy": t.energy, "category": t.category,
                       "score": round(score) if score is not None else None, "quadrant": q}
                      for t, score, q in ranked],
        }
        return "Улучши план этого дня. Данные:\n" + json.dumps(data, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------ day_insight

    async def day_insight(self, user: User, stats: DayStats, plan: DayPlan | None,
                          activities: list[Activity]) -> str | None:
        if not self.enabled or not user.settings.ai_enabled:
            return None
        try:
            payload = self._insight_payload(user, stats, plan, activities)
            resp = await self._request(system=prompts.INSIGHT_SYSTEM_PROMPT,
                                       messages=[{"role": "user", "content": payload}],
                                       effort=INSIGHT_EFFORT, max_tokens=INSIGHT_MAX_TOKENS)
            if getattr(resp, "stop_reason", None) == "refusal":
                log.warning("day_insight: refusal")
                return None
            text = sanitize_html(_text_of(_echo_content(getattr(resp, "content", None))), limit=1200)
            return text or None
        except anthropic.AnthropicError as e:
            self._log_api_error("day_insight", e)
        except Exception:  # noqa: BLE001
            log.exception("day_insight: неожиданная ошибка")
        return None

    def _insight_payload(self, user: User, stats: DayStats, plan: DayPlan | None,
                         activities: list[Activity]) -> str:
        tzn = user.settings.tz

        def label(cat: str) -> str:
            return ACTIVITY_CATEGORIES.get(cat, ("", cat))[1]

        acts = []
        for a in activities:
            end = a.ended_at or now_utc()
            acts.append({"category": label(a.category), "description": a.description,
                         "from": to_local(a.started_at, tzn).strftime("%H:%M"),
                         "to": to_local(end, tzn).strftime("%H:%M") if a.ended_at else "сейчас",
                         "minutes": int((end - a.started_at).total_seconds() // 60), "rating": a.rating})
        data = {
            "date": stats.date.isoformat(), "weekday": WEEKDAYS_FULL[stats.date.weekday()].lower(),
            "focus_peak": user.settings.focus_peak,
            "stats": {
                "minutes_by_category": {label(k): v for k, v in stats.minutes_by_category.items()},
                "tracked_min": stats.tracked_min, "productive_min": stats.productive_min,
                "avg_rating": stats.avg_rating, "tasks_done": stats.tasks_done, "tasks_planned": stats.tasks_planned,
                "plan_items_done": stats.plan_items_done, "plan_items_total": stats.plan_items_total,
                "lessons_count": stats.lessons_count, "focus_score": stats.focus_score,
            },
            "plan": [{"start": i.start, "end": i.end, "kind": i.kind, "title": i.title, "done": i.done}
                     for i in (plan.items if plan else [])],
            "activities": acts[:40],
        }
        return "Итоги дня:\n" + json.dumps(data, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------ parse_timetable

    async def parse_timetable(self, *, text: str | None = None, image: bytes | None = None,
                              mime: str = "image/jpeg") -> list[dict[str, Any]]:
        if not self.enabled or (not (text and text.strip()) and not image):
            return []
        try:
            content: list[dict[str, Any]] = []
            if image:
                prepared = await self._prepare_image(image, mime)
                if prepared is None:
                    return []
                media_type, data = prepared
                content.append({"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                            "data": data}})
            instruction = "Распознай учебное расписание"
            instruction += " на фото." if image else "."
            if text and text.strip():
                instruction += "\n\nТекст расписания:\n" + text.strip()[:12000]
            content.append({"type": "text", "text": instruction})
            resp = await self._request(system=prompts.TIMETABLE_SYSTEM_PROMPT,
                                       messages=[{"role": "user", "content": content}],
                                       effort=TIMETABLE_EFFORT, max_tokens=TIMETABLE_MAX_TOKENS,
                                       output_format=TIMETABLE_FORMAT)
            data_out = self._structured(resp)
            lessons = clean_timetable(data_out.get("lessons") if isinstance(data_out, dict) else None)
            log.info("parse_timetable: распознано %d пар", len(lessons))
            return lessons
        except AIOutputError as e:
            log.warning("parse_timetable: %s", e)
        except anthropic.AnthropicError as e:
            self._log_api_error("parse_timetable", e)
        except Exception:  # noqa: BLE001
            log.exception("parse_timetable: неожиданная ошибка")
        return []

    @staticmethod
    async def _prepare_image(image: bytes, mime: str) -> tuple[str, str] | None:
        media_type = _sniff_image(image) or (mime if mime in SUPPORTED_IMAGE_TYPES else None)
        if media_type is None or len(image) > MAX_IMAGE_BYTES:
            try:
                image = await asyncio.to_thread(_reencode_jpeg, image)
                media_type = "image/jpeg"
            except Exception as e:  # noqa: BLE001
                log.warning("parse_timetable: не удалось подготовить изображение (%s)", e)
                return None
        return media_type, base64.standard_b64encode(image).decode("ascii")

    # ------------------------------------------------------------ suggest_task_fields

    async def suggest_task_fields(self, user: User, title: str) -> dict[str, Any]:
        """{importance, estimate_min, energy, category, deadline}; deadline — ISO-строка UTC
        (как в БД, parse_iso -> aware datetime) или None. {} — если ИИ выключен или ошибка."""
        title = (title or "").strip()
        if not self.enabled or not user.settings.ai_enabled or not title:
            return {}
        try:
            today = local_today(user.settings.tz)
            payload = f"{now_line(user)}\n{next_days_line(today)}\n\nЗадача: «{title[:300]}»"
            resp = await self._request(system=prompts.SUGGEST_SYSTEM_PROMPT,
                                       messages=[{"role": "user", "content": payload}],
                                       effort=SUGGEST_EFFORT, max_tokens=SUGGEST_MAX_TOKENS,
                                       output_format=TASK_FIELDS_FORMAT)
            data = TaskFieldsOut.model_validate(self._structured(resp))

            def parse_deadline(value: str) -> datetime:
                dt, has_time = parse_local_dt(value, user.settings.tz)
                return dt if has_time else dt.replace(hour=23, minute=59)

            return clean_task_fields(data, parse_deadline=parse_deadline)
        except (AIOutputError, ValidationError, ToolError) as e:
            log.warning("suggest_task_fields: %s", e)
        except anthropic.AnthropicError as e:
            self._log_api_error("suggest_task_fields", e)
        except Exception:  # noqa: BLE001
            log.exception("suggest_task_fields: неожиданная ошибка")
        return {}
