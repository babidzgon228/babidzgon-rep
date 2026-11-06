"""Санитайзер Telegram-HTML для ответов ИИ."""
import re
from datetime import date, datetime

import pytest

from bot.ai.formatting import TELEGRAM_LIMIT, human_date, human_dt, plain_text, sanitize_html, strip_tags


def _balanced(html: str) -> bool:
    stack = []
    for closing, name in re.findall(r"<(/?)([a-z]+)>", html):
        if closing:
            if not stack or stack[-1] != name:
                return False
            stack.pop()
        else:
            stack.append(name)
    return not stack


@pytest.mark.parametrize("src, expected", [
    ("**Жирный** и *курсив*", "<b>Жирный</b> и <i>курсив</i>"),
    ("`код **x**`", "<code>код **x**</code>"),
    ("# Заголовок\n- пункт 1\n* пункт 2", "<b>Заголовок</b>\n• пункт 1\n• пункт 2"),
    ("2*3*4 = 24, snake_case_var", "2*3*4 = 24, snake_case_var"),
    ("~~старое~~ __важно__", "<s>старое</s> <b>важно</b>"),
    ("[Сайт](https://example.com)", "Сайт (https://example.com)"),
    ("> цитата\n> вторая\nтекст", "<blockquote>цитата\nвторая</blockquote>\nтекст"),
    ("```python\nprint('<hi>')\n```", "<pre>print('&lt;hi&gt;')</pre>"),
])
def test_markdown_converted(src, expected):
    assert sanitize_html(src) == expected


def test_escapes_everything_except_allowed_tags():
    out = sanitize_html('a < b && c > d <script>alert(1)</script> <b>ok</b> <a href="x">ссылка</a>')
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "a &lt; b &amp;&amp; c &gt; d" in out
    assert "<b>ok</b>" in out
    assert "<a" not in out and "ссылка" in out


def test_keeps_valid_entities_and_fixes_bare_ampersand():
    assert sanitize_html("AT&T &lt;ok&gt; &amp; &#169;") == "AT&amp;T &lt;ok&gt; &amp; &#169;"


def test_aliases_and_br():
    assert sanitize_html("<strong>x</strong><br>y<em>z</em>") == "<b>x</b>\ny<i>z</i>"


def test_balances_tags():
    assert sanitize_html("<b>незакрытый") == "<b>незакрытый</b>"
    assert sanitize_html("текст</i>") == "текст"
    assert sanitize_html("<b>a <i>b</b> c</i>") == "<b>a <i>b</i></b> c"
    assert sanitize_html("<b>x <b>y</b></b>") == "<b>x y</b>"


def test_no_markup_inside_code():
    assert sanitize_html("<code><b>x</b> &lt;tag&gt;</code>") == "<code>x &lt;tag&gt;</code>"
    assert sanitize_html('<pre><code class="language-py">x = 1 < 2</code></pre>') == "<pre>x = 1 &lt; 2</pre>"


def test_truncates_without_breaking_markup():
    src = "<b>" + "абв & где " * 1000 + "</b>"
    out = sanitize_html(src)
    assert len(out) <= TELEGRAM_LIMIT
    assert out.endswith("…</b>")
    assert _balanced(out)
    assert not re.search(r"&[#\w]*…", out)  # сущность не разорвана


def test_empty_and_plain_helpers():
    assert sanitize_html(None) == "" and sanitize_html("   ") == ""
    assert plain_text("**Хорошо** <i>и</i> a<b") == "Хорошо и a&lt;b"
    assert strip_tags("<b>a &amp; b</b>") == "a & b"


def test_human_dates():
    today = date(2026, 11, 6)  # пятница
    assert human_date(today, today) == "сегодня"
    assert human_date(date(2026, 11, 7), today) == "завтра"
    assert human_dt(datetime(2026, 11, 13, 18, 0), today) == "пт 13.11 18:00"
