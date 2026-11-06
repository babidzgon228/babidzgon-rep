"""Мультиязычность: ru / en / zh.

    from bot.i18n import t, tp, L
    t("menu.today", lang)                       -> "📅 Сегодня" / "📅 Today" / "📅 今天"
    t("plan.saved", lang, n=3)                  -> подстановка {n}
    tp("unit.lesson", 5, lang)                  -> "5 пар" / "5 classes" / "5 节课"
    t("joke.done", lang)                        -> значение-список: случайный шуточный вариант

Каталоги: bot/i18n/ru.py, en.py, zh.py (словарь CATALOG). Ключи — "раздел.имя".
Если ключа нет в языке — берётся русский, если нет и там — сам ключ (видно в интерфейсе, легко найти).
"""
from __future__ import annotations

import random
from typing import Any

from bot.i18n import en, ru, zh

LANGS: tuple[str, ...] = ("ru", "en", "zh")
DEFAULT_LANG = "ru"
LANG_NAMES = {"ru": "🇷🇺 Русский", "en": "🇬🇧 English", "zh": "🇨🇳 中文"}
CATALOGS: dict[str, dict[str, Any]] = {"ru": ru.CATALOG, "en": en.CATALOG, "zh": zh.CATALOG}

_rng = random.Random()


def norm_lang(lang: str | None) -> str:
    return lang if lang in CATALOGS else DEFAULT_LANG


def L(obj: Any) -> str:
    """Язык пользователя из User / UserSettings / строки."""
    if isinstance(obj, str):
        return norm_lang(obj)
    settings = getattr(obj, "settings", obj)
    return norm_lang(getattr(settings, "lang", None))


def _raw(key: str, lang: str) -> Any:
    lang = norm_lang(lang)
    if key in CATALOGS[lang]:
        return CATALOGS[lang][key]
    return CATALOGS[DEFAULT_LANG].get(key, key)


def t(key: str, lang: str | None = None, /, **kw: Any) -> str:
    value = _raw(key, lang or DEFAULT_LANG)
    if isinstance(value, (list, tuple)):          # шуточные варианты — случайный
        value = _rng.choice(value) if value else key
    if kw:
        try:
            return str(value).format(**kw)
        except (KeyError, IndexError, ValueError):
            return str(value)
    return str(value)


def variants(key: str, lang: str | None = None) -> list[str]:
    """Все варианты значения (например, все подписи кнопки на всех языках — для распознавания)."""
    value = _raw(key, lang or DEFAULT_LANG)
    return list(value) if isinstance(value, (list, tuple)) else [str(value)]


def all_langs(key: str) -> set[str]:
    """Значение ключа во всех языках (для фильтров кнопок меню)."""
    out: set[str] = set()
    for lang in LANGS:
        out.update(variants(key, lang))
    return out


def plural_form(n: int, lang: str) -> int:
    """Индекс формы: ru — 0 (1 пара) / 1 (2 пары) / 2 (5 пар); en — 0 / 1; zh — 0."""
    n = abs(int(n))
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return 0
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return 1
        return 2
    if lang == "en":
        return 0 if n == 1 else 1
    return 0


def tp(key: str, n: int, lang: str | None = None, /, *, with_number: bool = True, **kw: Any) -> str:
    """Склонение по числу. Значение ключа — кортеж форм: ru (1, 2, 5), en (1, many), zh (одна)."""
    lang = norm_lang(lang)
    forms = _raw(key, lang)
    if not isinstance(forms, (list, tuple)):
        forms = (str(forms),)
    word = forms[min(plural_form(n, lang), len(forms) - 1)]
    if kw:
        word = word.format(n=n, **kw)
    if not with_number:
        return word
    return f"{n}{'' if lang == 'zh' else ' '}{word}"
