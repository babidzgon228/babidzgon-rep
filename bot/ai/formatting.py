"""Форматирование ответов ИИ для Telegram (parse_mode=HTML).

`sanitize_html(text)` превращает произвольный ответ модели в безопасный Telegram-HTML:
- оставляет только разрешённые теги <b> <i> <u> <s> <code> <pre> <blockquote> (без атрибутов);
- экранирует всё остальное (<, >, & вне корректных сущностей);
- конвертирует случайный Markdown (**жирный**, *курсив*, `код`, ```блок```, # заголовки, списки, ссылки);
- балансирует теги и обрезает до лимита, не ломая разметку.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime

from bot.models import WEEKDAYS_SHORT

TELEGRAM_LIMIT = 4000

ALLOWED_TAGS = ("b", "i", "u", "s", "code", "pre", "blockquote")
_TAG_ALIASES = {"strong": "b", "em": "i", "ins": "u", "strike": "s", "del": "s",
                "h1": "b", "h2": "b", "h3": "b", "h4": "b", "h5": "b", "h6": "b"}
_DROP_TAGS = {"p", "div", "span", "ul", "ol", "a", "tg-spoiler", "html", "body", "section"}
_CODE_TAGS = ("code", "pre")

_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)(?:\s[^<>]*)?\s*(/?)>")
_ENTITY_RE = re.compile(r"&(?:[a-zA-Z]+|#\d{1,7}|#[xX][0-9a-fA-F]{1,6});")
_BARE_AMP_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|#\d{1,7}|#[xX][0-9a-fA-F]{1,6});)")

# Код: ```lang\n...```, <pre>...</pre>, <code>...</code>, `...`
_CODE_RE = re.compile(
    r"```[\w+\-#.]*[ \t]*\n?(?P<fence>.*?)```"
    r"|<pre(?:\s[^<>]*)?>(?P<pre>.*?)</pre\s*>"
    r"|<code(?:\s[^<>]*)?>(?P<code>.*?)</code\s*>"
    r"|`(?P<tick>[^`\n]+)`",
    re.DOTALL | re.IGNORECASE,
)

# Markdown -> HTML (применяется к тексту вне кода)
_MD_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$", re.M), "—————"),         # --- / ***
    (re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M), r"<b>\1</b>"),  # # Заголовок
    (re.compile(r"^([ \t]*)[*\-+][ \t]+(?=\S)", re.M), r"\1• "),                    # - пункт
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S), r"<b>\1</b>"),
    (re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)", re.S), r"<b>\1</b>"),
    (re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S), r"<s>\1</s>"),
    (re.compile(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])"), r"<i>\1</i>"),
    (re.compile(r"(?<![\w_])_(?=[^\s_])([^_\n]+?)(?<=[^\s_])_(?![\w_])"), r"<i>\1</i>"),
    (re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)"), r"\1 (\2)"),
]
_QUOTE_BLOCK_RE = re.compile(r"(?:^[ \t]*>[ \t]?.*(?:\n|$))+", re.M)


def escape(text: object) -> str:
    """html.escape для пользовательского текста (кавычки не трогаем — Telegram их понимает)."""
    return html.escape(str(text), quote=False)


def _escape_text(text: str) -> str:
    """Экранирует < > и «голые» &, сохраняя корректные HTML-сущности."""
    text = _BARE_AMP_RE.sub("&amp;", text)
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _escape_code(raw: str, *, from_html: bool) -> str:
    if from_html:
        raw = re.sub(r"</?[a-zA-Z][^<>]*>", "", raw)  # теги внутри <pre>/<code> выкидываем
        raw = html.unescape(raw)
    return escape(raw)


def _markdown_to_html(text: str) -> str:
    def quote(m: re.Match[str]) -> str:
        body = "\n".join(re.sub(r"^[ \t]*>[ \t]?", "", line) for line in m.group(0).rstrip("\n").split("\n"))
        tail = "\n" if m.group(0).endswith("\n") else ""
        return f"<blockquote>{body}</blockquote>{tail}"

    text = _QUOTE_BLOCK_RE.sub(quote, text)
    for pattern, repl in _MD_RULES:
        text = pattern.sub(repl, text)
    return text


# Токены: ("text", escaped) | ("open", tag) | ("close", tag)
Token = tuple[str, str]


def _tokenize_markup(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    for m in _TAG_RE.finditer(text):
        if m.start() > pos:
            tokens.append(("text", _escape_text(text[pos:m.start()])))
        closing, name, self_closing = m.group(1) == "/", m.group(2).lower(), m.group(3) == "/"
        name = _TAG_ALIASES.get(name, name)
        if name == "br":
            tokens.append(("text", "\n"))
        elif name == "li":
            if not closing:
                tokens.append(("text", "• "))
        elif name in _DROP_TAGS:
            pass
        elif name in ALLOWED_TAGS and not self_closing:
            tokens.append(("close" if closing else "open", name))
        else:
            tokens.append(("text", _escape_text(m.group(0))))
        pos = m.end()
    if pos < len(text):
        tokens.append(("text", _escape_text(text[pos:])))
    return tokens


def _tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    for m in _CODE_RE.finditer(text):
        if m.start() > pos:
            tokens.extend(_tokenize_markup(_markdown_to_html(text[pos:m.start()])))
        if m.group("fence") is not None:
            tag, body = "pre", _escape_code(m.group("fence").rstrip("\n"), from_html=False)
        elif m.group("pre") is not None:
            tag, body = "pre", _escape_code(m.group("pre"), from_html=True)
        elif m.group("code") is not None:
            tag, body = "code", _escape_code(m.group("code"), from_html=True)
        else:
            tag, body = "code", _escape_code(m.group("tick"), from_html=False)
        if body.strip():
            tokens += [("open", tag), ("text", body), ("close", tag)]
        pos = m.end()
    if pos < len(text):
        tokens.extend(_tokenize_markup(_markdown_to_html(text[pos:])))
    return tokens


def _balance(tokens: list[Token]) -> list[Token]:
    """Убирает лишние/вложенные теги, закрывает незакрытые."""
    out: list[Token] = []
    stack: list[str] = []
    skipped: dict[str, int] = {}
    for kind, value in tokens:
        if kind == "text":
            out.append((kind, value))
            continue
        in_code = any(t in _CODE_TAGS for t in stack)
        if kind == "open":
            if in_code or value in stack:      # внутри кода разметки нет; повторная вложенность не нужна
                skipped[value] = skipped.get(value, 0) + 1
                continue
            stack.append(value)
            out.append((kind, value))
            continue
        # close
        if skipped.get(value):
            skipped[value] -= 1
            continue
        if value not in stack:
            continue
        while stack:
            top = stack.pop()
            out.append(("close", top))
            if top == value:
                break
    out.extend(("close", t) for t in reversed(stack))
    # пустые пары <b></b> выкидываем
    cleaned: list[Token] = []
    for tok in out:
        if tok[0] == "close" and cleaned and cleaned[-1] == ("open", tok[1]):
            cleaned.pop()
            continue
        cleaned.append(tok)
    return cleaned


def _render(tokens: list[Token], limit: int) -> str:
    full = "".join(_tok_str(t) for t in tokens)
    if len(full) <= limit:
        return full
    ellipsis = "…"
    parts: list[str] = []
    stack: list[str] = []
    used = 0

    def closing_len() -> int:
        return sum(len(f"</{t}>") for t in stack)

    for tok in tokens:
        s = _tok_str(tok)
        budget = limit - used - len(ellipsis) - closing_len()
        if tok[0] == "open":
            if len(s) + len(f"</{tok[1]}>") + 1 > budget:
                break
            stack.append(tok[1])
        elif tok[0] == "close":
            if stack and stack[-1] == tok[1]:
                stack.pop()
        else:
            if len(s) > budget:
                cut = s[:max(0, budget)]
                cut = re.sub(r"&[#\w]*$", "", cut)  # не рвём сущность
                parts.append(cut.rstrip())
                used += len(parts[-1])
                break
        parts.append(s)
        used += len(s)
    parts.append(ellipsis)
    parts.extend(f"</{t}>" for t in reversed(stack))
    return "".join(parts)


def _tok_str(tok: Token) -> str:
    kind, value = tok
    if kind == "open":
        return f"<{value}>"
    if kind == "close":
        return f"</{value}>"
    return value


def sanitize_html(text: str | None, limit: int = TELEGRAM_LIMIT) -> str:
    """Ответ модели -> безопасный Telegram-HTML не длиннее limit символов."""
    if not text:
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    tokens = _balance(_tokenize(text.strip()))
    result = _render(tokens, limit)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def strip_tags(text: str | None) -> str:
    """Безопасный HTML -> plain text (для сохранения в историю/логов)."""
    if not text:
        return ""
    return html.unescape(re.sub(r"</?[a-zA-Z][^<>]*>", "", text))


def plain_text(text: str | None, limit: int = 1000) -> str:
    """Ответ модели -> HTML-safe текст БЕЗ тегов (для коротких комментариев)."""
    s = strip_tags(sanitize_html(text, limit=max(limit * 2, 100)))
    s = re.sub(r"[ \t]+", " ", s).strip()
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return escape(s)


# ---------------------------------------------------------------- даты для людей

def human_date(d: date, today: date | None = None) -> str:
    """'сегодня' / 'завтра' / 'пт 13.11'."""
    if today is not None:
        delta = (d - today).days
        if delta == 0:
            return "сегодня"
        if delta == 1:
            return "завтра"
        if delta == -1:
            return "вчера"
    return f"{WEEKDAYS_SHORT[d.weekday()]} {d.strftime('%d.%m')}"


def human_dt(dt: datetime, today: date | None = None) -> str:
    """Локальный datetime -> 'завтра 15:00' / 'пт 13.11 18:00'."""
    return f"{human_date(dt.date(), today)} {dt.strftime('%H:%M')}"
