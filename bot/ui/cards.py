"""PNG-карточка плана дня (Pillow): вертикальный таймлайн, светлая тема.

Рисуем с 2× суперсэмплингом и уменьшаем до 1080 px — так скругления и кружки
получаются гладкими (Pillow не сглаживает фигуры). Вызывать из хендлеров через
``asyncio.to_thread`` — рендер синхронный.
"""
from __future__ import annotations

import io
import os
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.models import WEEKDAYS_FULL, DayPlan, PlanItem
from bot.timeutil import human_duration, minutes_of

# ---------------------------------------------------------------- палитра

BG = (244, 246, 251)
CARD = (255, 255, 255)
CARD_DONE = (248, 249, 252)
INK = (31, 36, 51)
INK_SOFT = (74, 81, 104)
MUTED = (122, 130, 153)
LINE = (221, 226, 236)
SHADOW = (27, 36, 64)

# kind -> (акцент, светлый фон)
PALETTE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "lesson": ((79, 107, 237), (234, 239, 255)),
    "event": ((242, 135, 60), (255, 241, 229)),
    "task": ((34, 170, 110), (229, 247, 238)),
    "break": ((64, 182, 230), (232, 247, 253)),
    "meal": ((232, 177, 20), (255, 247, 222)),
    "buffer": ((140, 151, 173), (239, 241, 246)),
    "routine": ((155, 81, 224), (244, 235, 253)),
}
KIND_TITLES = {
    "lesson": "Пара", "event": "Событие", "task": "Задача", "break": "Перерыв",
    "meal": "Еда", "buffer": "Буфер", "routine": "Рутина",
}
MINOR = frozenset({"break", "meal", "buffer", "routine"})
GREEN = (34, 170, 110)
GREEN_BG = (229, 247, 238)
GREY_BG = (234, 237, 243)

# ---------------------------------------------------------------- темы (светлая / тёмная / авто)

def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


_DARK_CARD = (30, 33, 45)
_DARK_ACCENTS = {
    "lesson": (124, 108, 255), "event": (255, 122, 89), "task": (45, 212, 191),
    "break": (90, 190, 240), "meal": (240, 190, 60), "buffer": (150, 160, 185), "routine": (190, 120, 255),
}
THEMES: dict[str, dict] = {
    "light": dict(BG=BG, CARD=CARD, CARD_DONE=CARD_DONE, INK=INK, INK_SOFT=INK_SOFT, MUTED=MUTED, LINE=LINE,
                  SHADOW=SHADOW, GREEN=GREEN, GREEN_BG=GREEN_BG, GREY_BG=GREY_BG, PALETTE=dict(PALETTE)),
    "dark": dict(BG=(18, 20, 28), CARD=_DARK_CARD, CARD_DONE=(25, 27, 37), INK=(236, 239, 247),
                 INK_SOFT=(190, 196, 214), MUTED=(128, 136, 160), LINE=(52, 57, 74), SHADOW=(0, 0, 0),
                 GREEN=(45, 212, 140), GREEN_BG=(22, 60, 46), GREY_BG=(44, 48, 62),
                 PALETTE={k: (a, _mix(_DARK_CARD, a, 0.22)) for k, a in _DARK_ACCENTS.items()}),
}
_THEME_LOCK = threading.Lock()


def resolve_theme(setting: str | None, local_hour: int) -> str:
    """auto → светлая днём (07:00–18:59), тёмная вечером и ночью."""
    if setting in THEMES:
        return setting  # type: ignore[return-value]
    return "light" if 7 <= local_hour < 19 else "dark"


def _apply_theme(name: str) -> None:
    globals().update(THEMES.get(name, THEMES["light"]))


MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]

# ---------------------------------------------------------------- шрифты

_REGULAR_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
_BOLD_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)


@lru_cache(maxsize=4)
def find_font(bold: bool = False) -> str | None:
    """Путь к TTF с кириллицей (BOT_FONT / BOT_FONT_BOLD переопределяют поиск)."""
    env = os.getenv("BOT_FONT_BOLD" if bold else "BOT_FONT")
    candidates = ([env] if env else []) + list(_BOLD_FONTS if bold else _REGULAR_FONTS)
    for path in candidates:
        if path and Path(path).is_file():
            return path
    if bold:  # нет жирного — возьмём обычный
        return find_font(False)
    return None


@lru_cache(maxsize=64)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = find_font(bold)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


_EMOJI_RE = re.compile("[\U0001F000-\U0001FFFF\u200d\ufe0f\u20e3]")


def _clean(text: str | None) -> str:
    """Убираем эмодзи — в обычных TTF их нет, получатся «квадратики»."""
    return " ".join(_EMOJI_RE.sub("", text or "").split())


# ---------------------------------------------------------------- холст с масштабом

class _Canvas:
    def __init__(self, width: int, height: int, k: int) -> None:
        self.k = k
        self.img = Image.new("RGB", (width * k, height * k), BG)
        self.draw = ImageDraw.Draw(self.img)

    def _box(self, box):
        return [int(round(v * self.k)) for v in box]

    def rect(self, box, radius: float, fill, outline=None, width: int = 0) -> None:
        self.draw.rounded_rectangle(self._box(box), radius=int(radius * self.k), fill=fill,
                                    outline=outline, width=int(width * self.k))

    def circle(self, cx: float, cy: float, r: float, fill, outline=None, width: int = 0) -> None:
        self.draw.ellipse(self._box((cx - r, cy - r, cx + r, cy + r)), fill=fill, outline=outline,
                          width=int(width * self.k))

    def line(self, points, fill, width: float) -> None:
        self.draw.line([(int(x * self.k), int(y * self.k)) for x, y in points], fill=fill,
                       width=max(1, int(width * self.k)))

    def text(self, x: float, y: float, text: str, size: int, *, bold: bool = False, fill=INK,
             anchor: str = "la") -> None:
        font = _font(size * self.k, bold)
        try:
            self.draw.text((x * self.k, y * self.k), text, font=font, fill=fill, anchor=anchor)
        except ValueError:  # bitmap-шрифт без поддержки anchor
            self.draw.text((x * self.k, y * self.k), text, font=font, fill=fill)

    def tlen(self, text: str, size: int, bold: bool = False) -> float:
        return self.draw.textlength(text, font=_font(size * self.k, bold)) / self.k

    def wrap(self, text: str, size: int, bold: bool, max_width: float, max_lines: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        cur = ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if self.tlen(cand, size, bold) <= max_width:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            cur = w
            while self.tlen(cur, size, bold) > max_width and len(cur) > 1:  # очень длинное слово
                cut = len(cur)
                while cut > 1 and self.tlen(cur[:cut], size, bold) > max_width:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and self.tlen(last + "…", size, bold) > max_width:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"
        return lines or [""]

    def fit(self, text: str, size: int, bold: bool, max_width: float) -> str:
        return self.wrap(text, size, bold, max_width, 1)[0]


# ---------------------------------------------------------------- раскладка

W = 1080
PAD = 64
TIME_X = PAD
RAIL_X = 226
CARD_X0 = 258
CARD_X1 = W - PAD
CONTENT_X = CARD_X0 + 40
GAP_Y = 18
MIN_GAP_MIN = 30


@dataclass
class _Row:
    kind: str                  # item / gap
    y: float
    h: float
    item: PlanItem | None = None
    minutes: int = 0
    title_lines: list[str] | None = None
    note: str | None = None


def _dur(item: PlanItem) -> int:
    try:
        return max(0, minutes_of(item.end) - minutes_of(item.start))
    except Exception:
        return 0


def _layout(cv: _Canvas, items: list[PlanItem], y0: float) -> tuple[list[_Row], float]:
    rows: list[_Row] = []
    y = y0
    prev_end: int | None = None
    max_title_w = CARD_X1 - 28 - CONTENT_X
    for it in items:
        try:
            start_m = minutes_of(it.start)
        except Exception:
            start_m = None
        if prev_end is not None and start_m is not None and start_m - prev_end >= MIN_GAP_MIN:
            rows.append(_Row("gap", y, 50, minutes=start_m - prev_end))
            y += 50 + GAP_Y
        if it.kind in MINOR:
            rows.append(_Row("item", y, 66, item=it))
            y += 66 + GAP_Y
        else:
            title_lines = cv.wrap(_clean(it.title) or KIND_TITLES.get(it.kind, ""), 34, True, max_title_w, 2)
            note = _clean(it.note) or None
            content_h = 70 + 44 * len(title_lines) + (40 if note else 0) + 22
            dur_h = 96 + _dur(it) * 0.7
            h = max(content_h, min(250.0, dur_h))
            rows.append(_Row("item", y, h, item=it, title_lines=title_lines, note=note))
            y += h + GAP_Y
        try:
            prev_end = max(prev_end or 0, minutes_of(it.end))
        except Exception:
            pass
    return rows, y


# ---------------------------------------------------------------- отрисовка частей

def _pill(cv: _Canvas, x: float, y: float, text: str, fg, bg, size: int = 20) -> float:
    """Рисует «таблетку» с текстом, возвращает её ширину."""
    w = cv.tlen(text, size, True) + 28
    h = size + 16
    cv.rect((x, y, x + w, y + h), h / 2, bg)
    cv.text(x + 14, y + h / 2, text, size, bold=True, fill=fg, anchor="lm")
    return w


def _check(cv: _Canvas, cx: float, cy: float, r: float, color=(255, 255, 255)) -> None:
    cv.line([(cx - r * 0.45, cy + r * 0.02), (cx - r * 0.1, cy + r * 0.38), (cx + r * 0.5, cy - r * 0.35)],
            fill=color, width=max(2.0, r * 0.28))


def _draw_item(cv: _Canvas, row: _Row) -> None:
    it = row.item
    assert it is not None
    accent, tint = PALETTE.get(it.kind, PALETTE["buffer"])
    x0, y0, x1, y1 = CARD_X0, row.y, CARD_X1, row.y + row.h
    dur = _dur(it)
    dur_text = human_duration(dur) if dur else ""

    if it.kind in MINOR:
        cy = y0 + row.h / 2
        cv.rect((x0, y0, x1, y1), 20, CARD_DONE if it.done else tint)
        cv.text(TIME_X, cy, it.start, 26, fill=MUTED, anchor="lm")
        cv.circle(RAIL_X, cy, 9, accent if not it.done else GREEN, outline=BG, width=4)
        label = _clean(it.title) or KIND_TITLES.get(it.kind, "")
        if it.note:
            label = f"{label} · {_clean(it.note)}"
        text_x = x0 + 28
        right = cv.tlen(dur_text, 24) + 40 if dur_text else 28
        cv.text(text_x, cy, cv.fit(label, 26, False, x1 - text_x - right), 26,
                fill=MUTED if it.done else INK_SOFT, anchor="lm")
        if dur_text:
            cv.text(x1 - 24, cy, dur_text, 24, fill=MUTED, anchor="rm")
        return

    # время слева
    cv.text(TIME_X, y0 + 22, it.start, 32, bold=True, fill=MUTED if it.done else INK)
    if it.end and it.end != it.start:
        cv.text(TIME_X, y0 + 64, it.end, 24, fill=MUTED)
    # узел на рельсе
    node_y = y0 + 40
    if it.done:
        cv.circle(RAIL_X, node_y, 15, GREEN, outline=BG, width=5)
        _check(cv, RAIL_X, node_y, 11)
    else:
        cv.circle(RAIL_X, node_y, 14, accent, outline=BG, width=5)
        cv.circle(RAIL_X, node_y, 5, (255, 255, 255))
    # карточка
    cv.rect((x0, y0, x1, y1), 24, CARD_DONE if it.done else CARD)
    cv.rect((x0 + 14, y0 + 18, x0 + 22, y1 - 18), 4, GREEN if it.done else accent)
    pill_fg, pill_bg = (MUTED, GREY_BG) if it.done else (accent, tint)
    pw = _pill(cv, CONTENT_X, y0 + 20, KIND_TITLES.get(it.kind, it.kind).upper(), pill_fg, pill_bg)
    if it.done:
        _pill(cv, CONTENT_X + pw + 10, y0 + 20, "ГОТОВО", GREEN, GREEN_BG)
    if dur_text:
        cv.text(x1 - 28, y0 + 38, dur_text, 24, fill=MUTED, anchor="rm")
    ty = y0 + 70
    for line in row.title_lines or []:
        cv.text(CONTENT_X, ty, line, 34, bold=True, fill=MUTED if it.done else INK)
        if it.done:
            lw = cv.tlen(line, 34, True)
            cv.line([(CONTENT_X, ty + 22), (CONTENT_X + lw, ty + 22)], fill=MUTED, width=3)
        ty += 44
    if row.note:
        cv.text(CONTENT_X, ty + 4, cv.fit(row.note, 26, False, x1 - 28 - CONTENT_X), 26, fill=MUTED)


def _draw_gap(cv: _Canvas, row: _Row) -> None:
    cy = row.y + row.h / 2
    for dy in range(-18, 22, 12):
        cv.circle(RAIL_X, cy + dy, 3, (196, 202, 216))
    cv.text(CARD_X0 + 8, cy, f"свободно {human_duration(row.minutes)}", 24, fill=MUTED, anchor="lm")


def _summary_chips(items: list[PlanItem]) -> list[tuple[str, tuple[int, int, int]]]:
    def plural(n: int, forms: tuple[str, str, str]) -> str:
        if n % 10 == 1 and n % 100 != 11:
            return forms[0]
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return forms[1]
        return forms[2]

    chips = []
    lessons = sum(1 for i in items if i.kind == "lesson")
    tasks = [i for i in items if i.kind == "task"]
    events = sum(1 for i in items if i.kind == "event")
    if lessons:
        chips.append((f"{lessons} {plural(lessons, ('пара', 'пары', 'пар'))}", PALETTE["lesson"][0]))
    if tasks:
        mins = sum(_dur(i) for i in tasks)
        chips.append((f"{len(tasks)} {plural(len(tasks), ('задача', 'задачи', 'задач'))} · {human_duration(mins)}",
                      PALETTE["task"][0]))
    if events:
        chips.append((f"{events} {plural(events, ('событие', 'события', 'событий'))}", PALETTE["event"][0]))
    return chips


def _default_subtitle(plan: DayPlan) -> str:
    d = plan.date
    return f"{WEEKDAYS_FULL[d.weekday()]}, {d.day} {MONTHS_GEN[d.month - 1]}"


# ---------------------------------------------------------------- публичная функция

def render_day_card(plan: DayPlan, *, title: str, subtitle: str | None = None,
                    theme: str = "light") -> bytes:
    """PNG-картинка расписания/плана дня. theme: light / dark (см. resolve_theme). Возвращает bytes PNG."""
    with _THEME_LOCK:
        _apply_theme(theme)
        try:
            return _render(plan, title=title, subtitle=subtitle)
        finally:
            _apply_theme("light")


def _render(plan: DayPlan, *, title: str, subtitle: str | None) -> bytes:
    k = 2
    items = sorted(plan.items, key=lambda i: (i.start, i.end))
    title = _clean(title) or "План дня"
    subtitle = _clean(subtitle) if subtitle is not None else _default_subtitle(plan)

    # 1) раскладка на временном холсте (нужны размеры текста)
    probe = _Canvas(1, 1, k)
    title_lines = probe.wrap(title, 58, True, W - 2 * PAD - 220, 2)
    header_h = PAD + 70 * len(title_lines) + (48 if subtitle else 0) + 24
    chips = _summary_chips(items)
    chips_y = header_h
    timeline_y = chips_y + (78 if chips else 16)
    if items:
        rows, y_end = _layout(probe, items, timeline_y)
    else:
        rows, y_end = [], timeline_y + 220 + GAP_Y
    major = [i for i in items if i.kind not in MINOR]
    done = sum(1 for i in major if i.done)
    kinds_present = [kd for kd in PALETTE if any(i.kind == kd for i in items)]
    footer_h = 40 + (56 if kinds_present else 0) + (64 if done else 0) + 40
    height = int(y_end + footer_h)

    cv = _Canvas(W, height, k)

    # 2) фон: мягкое пятно сверху
    glow_h = min(height, int(header_h + 260))
    glow = Image.new("L", (W * k, glow_h * k), 0)
    ImageDraw.Draw(glow).ellipse((int(W * k * 0.58), -int(260 * k), int(W * k * 1.2), int(header_h * k * 0.8)),
                                 fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(70 * k))
    cv.img.paste(Image.new("RGB", glow.size, (205, 214, 255)), (0, 0), mask=glow)

    # 3) заголовок
    y = PAD
    for line in title_lines:
        cv.text(PAD, y, line, 58, bold=True, fill=INK)
        y += 70
    if subtitle:
        cv.text(PAD, y + 4, cv.fit(subtitle, 30, False, W - 2 * PAD - 220), 30, fill=MUTED)
    if plan.status == "accepted":
        label, fg, bg = "ПРИНЯТ", GREEN, GREEN_BG
    else:
        label, fg, bg = "ЧЕРНОВИК", MUTED, GREY_BG
    pw = cv.tlen(label, 22, True) + 28
    _pill(cv, W - PAD - pw, PAD + 14, label, fg, bg, size=22)

    # 4) чипы-сводка
    x = PAD
    for text, color in chips:
        w = cv.tlen(text, 24, True) + 60
        if x + w > W - PAD:
            break
        cv.rect((x, chips_y, x + w, chips_y + 50), 25, CARD)
        cv.circle(x + 24, chips_y + 25, 7, color)
        cv.text(x + 40, chips_y + 25, text, 24, bold=True, fill=INK_SOFT, anchor="lm")
        x += w + 12

    # 5) тени карточек (одним проходом размытия)
    shadow = Image.new("L", cv.img.size, 0)
    sd = ImageDraw.Draw(shadow)
    for row in rows:
        if row.kind == "item" and row.item and row.item.kind not in MINOR:
            sd.rounded_rectangle([int(CARD_X0 * k), int((row.y + 6) * k), int(CARD_X1 * k),
                                  int((row.y + row.h + 6) * k)], radius=24 * k, fill=34)
    if not items:
        sd.rounded_rectangle([PAD * k, int((timeline_y + 6) * k), (W - PAD) * k,
                              int((timeline_y + 226) * k)], radius=28 * k, fill=30)
    shadow = shadow.filter(ImageFilter.GaussianBlur(14 * k))
    cv.img.paste(Image.new("RGB", cv.img.size, SHADOW), (0, 0), mask=shadow)

    # 6) таймлайн
    if rows:
        first = rows[0].y + (40 if rows[0].item and rows[0].item.kind not in MINOR else rows[0].h / 2)
        last_row = rows[-1]
        last = last_row.y + (40 if last_row.item and last_row.item.kind not in MINOR else last_row.h / 2)
        cv.line([(RAIL_X, first), (RAIL_X, last)], fill=LINE, width=4)
        for row in rows:
            if row.kind == "gap":
                _draw_gap(cv, row)
            else:
                _draw_item(cv, row)
    else:
        box = (PAD, timeline_y, W - PAD, timeline_y + 220)
        cv.rect(box, 28, CARD)
        cv.text(W / 2, timeline_y + 88, "План пуст", 44, bold=True, fill=INK, anchor="mm")
        cv.text(W / 2, timeline_y + 146, "Свободный день — отдохни или займись важным", 26,
                fill=MUTED, anchor="mm")

    # 7) подвал: легенда и прогресс
    fy = y_end + 16
    cv.line([(PAD, fy), (W - PAD, fy)], fill=LINE, width=2)
    fy += 30
    if kinds_present:
        x = PAD
        for kd in kinds_present:
            label = KIND_TITLES[kd]
            w = cv.tlen(label, 22) + 44
            if x + w > W - PAD:
                break
            cv.circle(x + 9, fy + 14, 8, PALETTE[kd][0])
            cv.text(x + 26, fy + 14, label, 22, fill=MUTED, anchor="lm")
            x += w + 8
        fy += 56
    if done:
        text = f"Выполнено {done} из {len(major)}"
        cv.text(PAD, fy + 14, text, 24, bold=True, fill=INK_SOFT, anchor="lm")
        bx0 = PAD + cv.tlen(text, 24, True) + 24
        bx1 = W - PAD
        cv.rect((bx0, fy + 6, bx1, fy + 22), 8, GREY_BG)
        frac = done / max(1, len(major))
        cv.rect((bx0, fy + 6, bx0 + max(16, (bx1 - bx0) * frac), fy + 22), 8, GREEN)

    # 8) сглаживание и PNG
    out = cv.img.resize((W, height), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=False)
    return buf.getvalue()
