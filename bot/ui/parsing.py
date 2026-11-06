"""Разбор пользовательского ввода: даты, время, длительности, часовые пояса, категории.

Все функции чистые и не бросают исключений — при непонятном вводе возвращают None.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from bot.models import ACTIVITY_CATEGORIES

_TIME_RE = re.compile(r"^\s*(\d{1,2})(?:\s*[:.\-ч]\s*(\d{2}))?\s*(?:мин)?\s*$", re.I)
_TIME_COMPACT_RE = re.compile(r"^\s*(\d{2})(\d{2})\s*$")
_DATE_RE = re.compile(r"^\s*(\d{1,2})[./\-](\d{1,2})(?:[./\-](\d{2}|\d{4}))?\s*$")
_ISO_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")
_RANGE_RE = re.compile(r"^\s*(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2})\s*$")

_REL_DAYS = {"сегодня": 0, "сёдня": 0, "today": 0, "завтра": 1, "tomorrow": 1,
             "послезавтра": 2}
_WEEKDAYS = {
    "пн": 0, "пон": 0, "понедельник": 0, "вт": 1, "вторник": 1, "ср": 2, "среда": 2, "среду": 2,
    "чт": 3, "четверг": 3, "пт": 4, "пятница": 4, "пятницу": 4, "сб": 5, "суббота": 5,
    "субботу": 5, "вс": 6, "воскресенье": 6,
}
_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7,
    "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}


def parse_time(text: str | None) -> str | None:
    """"18:30", "18.30", "1830", "9", "9:05" -> "HH:MM"."""
    if not text:
        return None
    s = text.strip().lower()
    m = _TIME_COMPACT_RE.match(s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        m = _TIME_RE.match(s)
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return f"{h:02d}:{mi:02d}"


def parse_time_range(text: str | None) -> tuple[str, str] | None:
    """"08:30-10:00" / "8.30 – 10.05" -> ("08:30", "10:00"). Конец должен быть позже начала."""
    if not text:
        return None
    m = _RANGE_RE.match(text)
    if not m:
        return None
    start, end = parse_time(m.group(1)), parse_time(m.group(2))
    if not start or not end or end <= start:
        return None
    return start, end


def _safe_date(y: int, mo: int, d: int) -> date | None:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_date(text: str | None, today: date) -> date | None:
    """"12.11", "12.11.2026", "12/11/26", "2026-11-12", "сегодня", "завтра", "пт", "12 ноября".

    Дата без года, которая уже прошла, считается датой следующего года.
    День недели — ближайший такой день, начиная с сегодняшнего.
    """
    if not text:
        return None
    s = text.strip().lower().rstrip(".")
    if s in _REL_DAYS:
        return today + timedelta(days=_REL_DAYS[s])
    if s in _WEEKDAYS:
        delta = (_WEEKDAYS[s] - today.weekday()) % 7
        return today + timedelta(days=delta)
    m = _ISO_DATE_RE.match(s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _DATE_RE.match(s)
    year_given = False
    if m:
        dd, mm = int(m.group(1)), int(m.group(2))
        y = m.group(3)
        if y:
            year_given = True
            year = int(y) + (2000 if len(y) == 2 else 0)
        else:
            year = today.year
    else:
        parts = s.split()
        if len(parts) not in (2, 3) or not parts[0].isdigit():
            return None
        month = next((n for k, n in _MONTHS.items() if parts[1].startswith(k)), None)
        if not month:
            return None
        dd, mm = int(parts[0]), month
        if len(parts) == 3 and parts[2].isdigit():
            year_given, year = True, int(parts[2])
        else:
            year = today.year
    result = _safe_date(year, mm, dd)
    if result and not year_given and result < today:
        result = _safe_date(year + 1, mm, dd)
    return result


def parse_datetime(text: str | None, today: date, now_hhmm: str | None = None,
                   default_time: str = "23:59") -> tuple[date, str] | None:
    """Дата+время: "12.11 18:00", "завтра 10:00", "пт", "18:30".

    Только время -> сегодня (или завтра, если это время сегодня уже прошло).
    Только дата -> default_time.
    """
    if not text:
        return None
    s = " ".join(text.strip().replace(",", " ").split())
    if not s:
        return None
    s = re.sub(r"\s+в\s+", " ", s)
    tokens = s.split(" ")
    if len(tokens) >= 2:
        t = parse_time(tokens[-1])
        if t:
            d = parse_date(" ".join(tokens[:-1]), today)
            if d:
                return d, t
        d = parse_date(s, today)
        return (d, default_time) if d else None
    token = tokens[0]
    d = None if ":" in token else parse_date(token, today)
    if d:
        return d, default_time
    t = parse_time(token)
    if not t:
        return None
    if now_hhmm and t <= now_hhmm:
        return today + timedelta(days=1), t
    return today, t


_DUR_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ч|час|часа|часов|h|м|мин|минут|минуты|m)?", re.I)


def parse_minutes(text: str | None) -> int | None:
    """"90", "45 мин", "1.5ч", "1ч 30м", "2 часа" -> минуты."""
    if not text:
        return None
    s = text.strip().lower()
    total = 0.0
    found = False
    for num, unit in _DUR_RE.findall(s):
        found = True
        value = float(num.replace(",", "."))
        if unit and unit[0] in "чh":
            total += value * 60
        else:
            total += value
    if not found or total <= 0:
        return None
    return int(round(total))


# ---------------------------------------------------------------- часовые пояса

TIMEZONES: dict[str, tuple[str, str]] = {
    "msk": ("Москва", "Europe/Moscow"),
    "szx": ("Шэньчжэнь", "Asia/Shanghai"),
    "kgd": ("Калининград", "Europe/Kaliningrad"),
    "sam": ("Самара", "Europe/Samara"),
    "ekb": ("Екатеринбург", "Asia/Yekaterinburg"),
    "nsk": ("Новосибирск", "Asia/Novosibirsk"),
    "krs": ("Красноярск", "Asia/Krasnoyarsk"),
    "irk": ("Иркутск", "Asia/Irkutsk"),
    "vvo": ("Владивосток", "Asia/Vladivostok"),
    "min": ("Минск", "Europe/Minsk"),
    "ala": ("Алматы", "Asia/Almaty"),
    "tas": ("Ташкент", "Asia/Tashkent"),
}
_TZ_CITY_ALIASES = {
    "питер": "Europe/Moscow", "спб": "Europe/Moscow", "санкт-петербург": "Europe/Moscow",
    "казань": "Europe/Moscow", "екб": "Asia/Yekaterinburg", "нск": "Asia/Novosibirsk",
    "новосиб": "Asia/Novosibirsk", "уфа": "Asia/Yekaterinburg", "пермь": "Asia/Yekaterinburg",
    "челябинск": "Asia/Yekaterinburg", "тюмень": "Asia/Yekaterinburg", "томск": "Asia/Tomsk",
    "барнаул": "Asia/Barnaul", "хабаровск": "Asia/Vladivostok", "якутск": "Asia/Yakutsk",
    "саратов": "Europe/Saratov", "ульяновск": "Europe/Ulyanovsk", "волгоград": "Europe/Volgograd",
    "астана": "Asia/Almaty", "киев": "Europe/Kyiv", "киів": "Europe/Kyiv", "ереван": "Asia/Yerevan",
    "тбилиси": "Asia/Tbilisi", "баку": "Asia/Baku", "бишкек": "Asia/Bishkek",
    "омск": "Asia/Omsk", "шеньчжень": "Asia/Shanghai", "шэньчжень": "Asia/Shanghai",
    "шенчжень": "Asia/Shanghai", "пекин": "Asia/Shanghai", "шанхай": "Asia/Shanghai",
    "гуанчжоу": "Asia/Shanghai", "китай": "Asia/Shanghai", "гонконг": "Asia/Hong_Kong",
}


def _valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def parse_tz(text: str | None) -> str | None:
    """"Europe/Berlin", "Москва", "UTC+5", "+3", "GMT-2" -> имя IANA-пояса."""
    if not text:
        return None
    s = text.strip()
    low = s.lower()
    for _key, (label, name) in TIMEZONES.items():
        if low == label.lower():
            return name
    if low in _TZ_CITY_ALIASES:
        return _TZ_CITY_ALIASES[low]
    m = re.fullmatch(r"(?:utc|gmt|мск)?\s*([+-])\s*(\d{1,2})(?::00)?", low)
    if m:
        sign, hours = m.group(1), int(m.group(2))
        if low.startswith("мск"):
            hours = hours + 3 if sign == "+" else 3 - hours
            sign = "+" if hours >= 0 else "-"
            hours = abs(hours)
        if hours > 14:
            return None
        if hours == 0:
            return "Etc/UTC"
        # В Etc/GMT знак инвертирован: UTC+5 == Etc/GMT-5
        return f"Etc/GMT{'-' if sign == '+' else '+'}{hours}"
    if low in ("utc", "gmt"):
        return "Etc/UTC"
    if "/" in s and _valid_tz(s):
        return s
    return None


def utc_offset_label(tz_name: str, at: datetime | None = None) -> str:
    """"Europe/Moscow" -> "UTC+3"."""
    try:
        z = ZoneInfo(tz_name)
    except Exception:
        return "UTC"
    at = at or datetime.now(z)
    off = at.astimezone(z).utcoffset() or timedelta(0)
    total = int(off.total_seconds() // 60)
    sign = "+" if total >= 0 else "−"
    h, m = divmod(abs(total), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


# ---------------------------------------------------------------- категории трекера

_CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "study": ("учеба", "учёба", "study", "пара", "пары", "универ", "домашка", "дз", "лекция",
              "семинар", "курсовая", "курсач", "диплом", "экзамен", "матан", "конспект", "учусь"),
    "work": ("работа", "work", "работаю", "подработка", "проект", "код", "кодинг"),
    "sport": ("спорт", "sport", "зал", "тренировка", "бег", "пробежка", "йога", "качалка"),
    "chores": ("дела", "chores", "уборка", "быт", "стирка", "магазин", "покупки", "готовка"),
    "road": ("дорога", "road", "метро", "автобус", "еду", "поездка", "транспорт"),
    "food": ("еда", "food", "обед", "ужин", "завтрак", "перекус", "ем"),
    "social": ("общение", "social", "друзья", "встреча", "звонок", "гуляю", "прогулка"),
    "rest": ("отдых", "rest", "игры", "сериал", "фильм", "кино", "ютуб", "отдыхаю", "чилл"),
    "sleep": ("сон", "sleep", "сплю", "дрема", "дрёма"),
    "other": ("другое", "other"),
}


def match_category(text: str | None) -> tuple[str, str | None]:
    """/track <текст> -> (ключ категории, описание или None).

    Первое слово — категория (ключ, название или синоним) — остальное описание.
    Если первое слово не категория, ищем синоним среди слов; иначе "other" с описанием = весь текст.
    """
    if not text or not text.strip():
        return "other", None
    s = text.strip()
    words = s.split(maxsplit=1)
    first = words[0].lower().strip(".,!?:")
    rest = words[1].strip() if len(words) > 1 else None

    def lookup(word: str) -> str | None:
        for key, (_emoji, name) in ACTIVITY_CATEGORIES.items():
            if word == key or word == name.lower() or word == name.lower().replace("ё", "е"):
                return key
        for key, aliases in _CATEGORY_ALIASES.items():
            if word in aliases:
                return key
        return None

    key = lookup(first)
    if key:
        return key, rest
    for w in re.findall(r"[\wё-]+", s.lower()):
        key = lookup(w)
        if key:
            return key, s
    return "other", s
