# -*- coding: utf-8 -*-
"""Пиксель-арт: примитивы, спрайты (Плагин, агенты) и все сцены ролика.

Всё рисуется на маленьком холсте 180x320 и потом увеличивается x6
(nearest neighbour) до 1080x1920.
"""
import math
import random

from PIL import Image, ImageDraw, ImageFont

W, H = 180, 320

P = dict(
    out="#24141a",
    skin="#f4c7aa", skin_sh="#dc9c82", skin_dk="#b8735e", blush="#ec9a86",
    hair="#e3b874", hair_dk="#b98a4c", hair_lt="#f4d79a",
    lens="#1d1d2b", lens_hl="#6c76a0",
    eye_w="#f7f3ef", iris="#3f71c9", pupil="#121522",
    brow="#b4824a", lip="#b9575a", mouth="#5a1c22", tongue="#c95a5a",
    tee="#f3f1ee", tee_sh="#c9c6cf",
    chk_a="#17161c", chk_b="#ecebef",
    jeans="#3b4b7e", jeans_dk="#2a355c", shoe="#f2f2f2",
    ag="#f2763a", ag_lt="#ff9e62", ag_dk="#c4502a", ag_out="#4a1c10",
    wood="#7a4428", wood_lt="#9a5c36", wood_dk="#55301e",
    lamp="#ffd27a", lampglow="#ffb45a",
    night0="#0c0f2c", night1="#1a1c48", night2="#33275e", night3="#5a3264",
    bld0="#1b1e40", bld1="#23285a", bld2="#2c2f66",
    win_on="#ffcf6b", win_on2="#f2a33a", win_off="#2a2d55",
    wall="#3a2734", wall_lt="#4a3240",
    board="#2d5a47", board_dk="#234638", chalk="#e8efe6",
    white="#ffffff", black="#0b0b10", red="#e8473a", green="#5fd068",
)

_FONT_CACHE = {}


def font(size, bold=True, mono=False):
    key = (size, bold, mono)
    if key not in _FONT_CACHE:
        if mono:
            path = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
        else:
            path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else \
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        _FONT_CACHE[key] = ImageFont.truetype(path, size)
    return _FONT_CACHE[key]


def drw(img):
    d = ImageDraw.Draw(img)
    d.fontmode = "1"  # без сглаживания — честные пиксели
    return d


def R(d, x0, y0, x1, y1, c):
    if x1 < x0 or y1 < y0:
        return
    d.rectangle([int(x0), int(y0), int(x1), int(y1)], fill=c)


def E(d, x0, y0, x1, y1, c, o=None):
    if o:
        d.ellipse([int(x0) - 1, int(y0) - 1, int(x1) + 1, int(y1) + 1], fill=o)
    d.ellipse([int(x0), int(y0), int(x1), int(y1)], fill=c)


def ptext(d, x, y, s, size=8, c="#ffffff", anchor="la", mono=False, shadow=None):
    f = font(size, mono=mono)
    if shadow:
        d.text((x + 1, y + 1), s, font=f, fill=shadow, anchor=anchor)
    d.text((x, y), s, font=f, fill=c, anchor=anchor)


def paste(dst, spr, x, y, k=1):
    if k != 1:
        spr = spr.resize((spr.width * k, spr.height * k), Image.NEAREST)
    dst.alpha_composite(spr, (int(x), int(y)))


def lerp(a, b, t):
    return a + (b - a) * t


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def blend(c1, c2, t):
    c1 = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    c2 = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


def checker(d, box, cell=2, a=P["chk_a"], b=P["chk_b"], mask=None):
    x0, y0, x1, y1 = [int(v) for v in box]
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if mask is not None and not mask(x, y):
                continue
            c = a if ((x // cell) + (y // cell)) % 2 == 0 else b
            d.point((x, y), fill=c)


# ================================================================ backgrounds
def sky_night(d, x0, y0, x1, y1):
    cols = [P["night0"], P["night1"], P["night2"], P["night3"]]
    h = y1 - y0 + 1
    for i, c in enumerate(cols):
        R(d, x0, y0 + h * i // 4, x1, y0 + h * (i + 1) // 4, c)
    # дизеринг на стыках
    for i in range(1, 4):
        yy = y0 + h * i // 4
        for x in range(x0, x1 + 1, 2):
            d.point((x + (yy % 2), yy - 1), fill=cols[i])


def skyline(d, x0, y0, x1, y1, t, seed=3):
    rnd = random.Random(seed)
    sky_night(d, x0, y0, x1, y1)
    for _ in range(18):
        sx, sy = rnd.randint(x0, x1), rnd.randint(y0, y0 + (y1 - y0) // 3)
        if (int(t * 2) + sx) % 7:
            d.point((sx, sy), fill="#c9c6ff")
    # дальний ряд
    x = x0 - 4
    while x < x1:
        w = rnd.randint(10, 20)
        h = rnd.randint((y1 - y0) // 4, (y1 - y0) // 2)
        R(d, x, y1 - h, x + w, y1, P["bld0"])
        x += w + rnd.randint(0, 2)
    # ближний ряд с окнами
    x = x0 - 6
    k = 0
    while x < x1:
        w = rnd.randint(14, 26)
        h = rnd.randint((y1 - y0) // 3, int((y1 - y0) * 0.8))
        col = P["bld1"] if k % 2 else P["bld2"]
        R(d, x, y1 - h, x + w, y1, col)
        if rnd.random() < 0.4:
            R(d, x + w // 2, y1 - h - 6, x + w // 2, y1 - h, col)
            if int(t * 1.5) % 2 == 0:
                d.point((x + w // 2, y1 - h - 7), fill=P["red"])
        for wy in range(y1 - h + 3, y1 - 2, 4):
            for wx in range(x + 2, x + w - 1, 3):
                r = rnd.random()
                on = r < 0.45
                if on and rnd.random() < 0.05 and int(t * 3 + wx) % 5 == 0:
                    on = False
                d.point((wx, wy), fill=(P["win_on"] if r < 0.3 else P["win_on2"]) if on else P["win_off"])
                d.point((wx + 1, wy), fill=(P["win_on"] if r < 0.3 else P["win_on2"]) if on else P["win_off"])
        x += w + 1
        k += 1


def window_frame(d, x0, y0, x1, y1, n=3):
    c = P["wood_dk"]
    R(d, x0, y0, x1, y0 + 2, c)
    R(d, x0, y1 - 2, x1, y1, c)
    R(d, x0, y0, x0 + 2, y1, c)
    R(d, x1 - 2, y0, x1, y1, c)
    for i in range(1, n):
        xx = x0 + (x1 - x0) * i // n
        R(d, xx - 1, y0, xx + 1, y1, c)


def plant(d, x, y, s=1.0, t=0):
    # горшок
    R(d, x - 6, y, x + 6, y + 10, "#8e4b2e")
    R(d, x - 7, y, x + 7, y + 2, "#a65a38")
    sway = int(math.sin(t * 1.5) * 1)
    leaves = [(-8, -10), (-4, -16), (2, -18), (6, -12), (9, -6), (-10, -4), (0, -10)]
    for i, (lx, ly) in enumerate(leaves):
        E(d, x + lx - 3 + sway * (i % 2), y + ly - 2, x + lx + 3 + sway * (i % 2), y + ly + 2,
          "#3f8f4c" if i % 2 else "#2f6f3c")
        R(d, x, y + ly // 2, x, y, "#2f6f3c")


def desk_lamp(d, x, y, on=True):
    # основание
    R(d, x - 6, y - 2, x + 6, y, "#22202a")
    R(d, x - 1, y - 18, x + 1, y - 2, "#2b2933")
    R(d, x, y - 26, x + 10, y - 24, "#2b2933")
    # плафон
    d.polygon([(x + 6, y - 30), (x + 18, y - 26), (x + 14, y - 18), (x + 2, y - 22)], fill="#2e2c38")
    if on:
        R(d, x + 6, y - 20, x + 12, y - 18, P["lamp"])


def light_cone(img, x, y, w, h, color=(255, 190, 110), alpha=40):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.polygon([(x - 4, y), (x + 4, y), (x + w, y + h), (x - w, y + h)], fill=color + (alpha,))
    img.alpha_composite(ov)


def glow(img, cx, cy, r, color=(255, 170, 80), alpha=60):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for i in range(4, 0, -1):
        rr = r * i / 4
        od.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color + (int(alpha / 4),))
    img.alpha_composite(ov)


def mug(d, x, y):
    R(d, x, y, x + 7, y + 8, "#2a2630")
    R(d, x + 1, y + 1, x + 6, y + 2, "#3c3644")
    R(d, x + 8, y + 2, x + 9, y + 6, "#2a2630")


def monitor(d, x0, y0, x1, y1, screen="#14141f"):
    R(d, x0, y0, x1, y1, "#1d1c24")
    R(d, x0 + 2, y0 + 2, x1 - 2, y1 - 2, screen)
    mx = (x0 + x1) // 2
    R(d, mx - 3, y1, mx + 3, y1 + 6, "#1d1c24")
    R(d, mx - 10, y1 + 6, mx + 10, y1 + 8, "#1d1c24")


def keyboard(d, x, y, w=40):
    R(d, x, y, x + w, y + 5, "#24222c")
    for i in range(x + 2, x + w - 1, 3):
        d.point((i, y + 2), fill="#4a4656")
        d.point((i + 1, y + 4), fill="#4a4656")


def room_night(img, t, desk_y=208, seed=3, lamp=True):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, P["wall"])
    # окно на всю ширину
    skyline(d, 4, 4, W - 5, desk_y - 30, t, seed)
    window_frame(d, 2, 2, W - 3, desk_y - 28, 3)
    R(d, 0, desk_y - 28, W - 1, desk_y - 25, P["wood_dk"])
    plant(d, 12, desk_y - 46, t=t)
    # стол
    R(d, 0, desk_y, W - 1, desk_y + 4, P["wood_lt"])
    R(d, 0, desk_y + 5, W - 1, H - 1, P["wood"])
    for yy in range(desk_y + 12, H, 9):
        R(d, 0, yy, W - 1, yy, P["wood_dk"])
    R(d, 0, H - 22, W - 1, H - 1, "#1f1b2e")
    for x in range(0, W, 6):
        R(d, x, H - 22, x + 2, H - 21, "#2a2540")
    if lamp:
        desk_lamp(d, 16, desk_y + 1)
        light_cone(img, 30, desk_y - 20, 34, 30)
    return d


def lecture_bg(img, t, front=False):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#6b4a52")
    R(d, 0, 0, W - 1, 6, "#5a3c44")
    # окна справа — дневной свет
    for wx in (128,):
        R(d, wx, 18, wx + 44, 110, "#9fd3ff")
        R(d, wx, 80, wx + 44, 110, "#c7e6ff")
        window_frame(d, wx - 2, 16, wx + 46, 112, 2)
    # доска
    R(d, 10, 22, 116, 96, P["wood_dk"])
    R(d, 13, 25, 113, 93, P["board"])
    R(d, 14, 26, 112, 30, "#33644f")
    if not front:
        ptext(d, 18, 34, "∫ f(x)dx = ?", 9, P["chalk"])
        ptext(d, 18, 50, "lim n→∞", 8, P["chalk"])
        R(d, 18, 66, 70, 66, P["chalk"])
        R(d, 18, 74, 96, 74, P["chalk"])
        R(d, 18, 82, 56, 82, P["chalk"])
    R(d, 10, 96, 116, 99, P["wood_lt"])
    # пол
    R(d, 0, 150, W - 1, H - 1, "#4a3a3e")
    return d


# ================================================================ sprites
def plagin_bust(expr="neutral", pose="rest", t=0.0, blink=True):
    """Детальный бюст Плагина ~72x100. expr: neutral|sleep|o|happy|smirk|tired|yell"""
    im = Image.new("RGBA", (76, 100), (0, 0, 0, 0))
    d = drw(im)
    cx, ty = 38, 4
    o = P["out"]
    # --- торс: клетчатая куртка + белая футболка
    sy = ty + 52
    E(d, cx - 33, sy, cx + 33, sy + 70, o)
    E(d, cx - 32, sy + 1, cx + 32, sy + 69, P["chk_a"])

    def inside(x, y):
        return ((x - cx) / 32.0) ** 2 + ((y - (sy + 35)) / 34.0) ** 2 <= 1.0
    checker(d, (cx - 32, sy + 1, cx + 32, 99), 3, mask=inside)
    d.polygon([(cx - 10, sy), (cx + 10, sy), (cx + 13, 99), (cx - 13, 99)], fill=P["tee"])
    R(d, cx + 6, sy + 6, cx + 12, 99, P["tee_sh"])
    R(d, cx - 11, sy, cx - 10, 99, o)
    R(d, cx + 10, sy, cx + 11, 99, o)
    # шея
    R(d, cx - 6, ty + 42, cx + 6, sy + 4, P["skin_sh"])
    E(d, cx - 8, sy - 2, cx + 8, sy + 6, P["tee"])
    E(d, cx - 6, sy - 3, cx + 6, sy + 3, P["skin_sh"])
    # --- уши
    E(d, cx - 20, ty + 22, cx - 13, ty + 33, P["skin_sh"], o)
    E(d, cx + 13, ty + 22, cx + 20, ty + 33, P["skin_sh"], o)
    R(d, cx - 18, ty + 26, cx - 17, ty + 30, P["skin_dk"])
    R(d, cx + 17, ty + 26, cx + 18, ty + 30, P["skin_dk"])
    # --- лицо (с тенью справа)
    E(d, cx - 16, ty + 6, cx + 16, ty + 46, P["skin_sh"], o)
    E(d, cx - 16, ty + 6, cx + 13, ty + 44, P["skin"])
    # --- волосы: короткий светлый ёжик
    d.chord([cx - 17, ty + 2, cx + 17, ty + 34], 180, 360, fill=P["hair"])
    R(d, cx - 17, ty + 17, cx - 14, ty + 24, P["hair"])
    R(d, cx + 14, ty + 17, cx + 17, ty + 24, P["hair"])
    rnd = random.Random(5)
    for _ in range(70):
        x = rnd.randint(cx - 15, cx + 15)
        y = rnd.randint(ty + 4, ty + 17)
        if ((x - cx) / 16.5) ** 2 + ((y - (ty + 18)) / 15.5) ** 2 < 1:
            d.point((x, y), fill=P["hair_dk"] if rnd.random() < 0.6 else P["hair_lt"])
    d.arc([cx - 17, ty + 2, cx + 17, ty + 34], 180, 360, fill=o)
    # --- очки на голове
    E(d, cx - 14, ty + 6, cx - 3, ty + 12, P["lens"], o)
    E(d, cx + 3, ty + 6, cx + 14, ty + 12, P["lens"], o)
    R(d, cx - 3, ty + 8, cx + 3, ty + 9, o)
    d.point((cx - 11, ty + 7), fill=P["lens_hl"])
    d.point((cx - 10, ty + 7), fill=P["lens_hl"])
    d.point((cx + 6, ty + 7), fill=P["lens_hl"])
    d.point((cx + 7, ty + 7), fill=P["lens_hl"])
    d.line([(cx - 15, ty + 10), (cx - 17, ty + 19)], fill=o)
    d.line([(cx + 15, ty + 10), (cx + 17, ty + 19)], fill=o)

    blink_now = blink and expr not in ("sleep", "happy") and (t % 3.1) > 2.95
    # --- брови
    by = ty + 20
    if expr == "o" or expr == "yell":
        by -= 3
    if expr == "tired":
        by += 1
    if expr == "angry":
        d.line([(cx - 11, by), (cx - 5, by + 2)], fill=P["brow"], width=2)
        d.line([(cx + 5, by + 2), (cx + 11, by)], fill=P["brow"], width=2)
    elif expr == "smirk":
        R(d, cx - 11, by + 1, cx - 5, by + 2, P["brow"])
        R(d, cx + 5, by - 1, cx + 11, by, P["brow"])
    else:
        R(d, cx - 11, by, cx - 5, by + 1, P["brow"])
        R(d, cx + 5, by, cx + 11, by + 1, P["brow"])
    # --- глаза
    ey = ty + 24
    for sx in (-1, 1):
        x0 = cx - 11 if sx < 0 else cx + 4
        if expr in ("sleep",) or blink_now:
            d.line([(x0, ey + 3), (x0 + 1, ey + 4), (x0 + 5, ey + 4), (x0 + 6, ey + 3)], fill=o)
        elif expr == "happy":
            d.line([(x0, ey + 4), (x0 + 1, ey + 2), (x0 + 5, ey + 2), (x0 + 6, ey + 4)], fill=o)
        elif expr == "tired":
            R(d, x0, ey + 2, x0 + 6, ey + 5, P["eye_w"])
            R(d, x0, ey + 1, x0 + 6, ey + 2, P["skin_sh"])
            R(d, x0, ey + 2, x0 + 6, ey + 2, o)
            R(d, x0 + 2, ey + 3, x0 + 4, ey + 5, P["iris"])
            d.point((x0 + 3, ey + 4), fill=P["pupil"])
            R(d, x0, ey + 7, x0 + 6, ey + 7, "#c98a9a")  # мешки под глазами
        elif expr in ("o", "yell"):
            R(d, x0 - 1, ey - 1, x0 + 7, ey + 6, P["eye_w"])
            R(d, x0 - 1, ey - 2, x0 + 7, ey - 2, o)
            R(d, x0 + 2, ey + 1, x0 + 4, ey + 4, P["iris"])
            R(d, x0 + 3, ey + 2, x0 + 3, ey + 3, P["pupil"])
        else:
            R(d, x0, ey, x0 + 6, ey + 5, P["eye_w"])
            R(d, x0, ey - 1, x0 + 6, ey - 1, o)
            ix = x0 + 2 if sx < 0 else x0 + 2
            R(d, ix, ey + 1, ix + 3, ey + 5, P["iris"])
            R(d, ix + 1, ey + 2, ix + 2, ey + 4, P["pupil"])
            d.point((ix, ey + 1), fill=P["white"])
    # --- нос
    R(d, cx + 1, ty + 28, cx + 2, ty + 34, P["skin_sh"])
    R(d, cx - 2, ty + 35, cx + 3, ty + 35, P["skin_dk"])
    # --- румянец
    R(d, cx - 14, ty + 33, cx - 10, ty + 35, P["blush"])
    R(d, cx + 8, ty + 33, cx + 11, ty + 35, P["blush"])
    # --- рот
    my = ty + 39
    if expr == "o":
        E(d, cx - 4, my - 3, cx + 4, my + 5, P["lip"])
        E(d, cx - 2, my - 1, cx + 2, my + 3, P["mouth"])
    elif expr == "yell":
        E(d, cx - 6, my - 3, cx + 6, my + 6, P["mouth"], o)
        R(d, cx - 3, my + 3, cx + 3, my + 5, P["tongue"])
        R(d, cx - 4, my - 2, cx + 4, my - 2, P["white"])
    elif expr == "happy":
        d.line([(cx - 6, my - 1), (cx - 4, my + 2), (cx + 4, my + 2), (cx + 6, my - 1)], fill=o, width=1)
        R(d, cx - 3, my + 1, cx + 3, my + 1, P["mouth"])
    elif expr == "smirk":
        d.line([(cx - 4, my + 1), (cx + 3, my + 1), (cx + 6, my - 1)], fill=o)
    elif expr == "sleep":
        E(d, cx - 2, my, cx + 2, my + 3, P["mouth"])
        # слюна
        if pose != "nodrool":
            dl = int((t * 3) % 4)
            R(d, cx + 2, my + 3, cx + 2, my + 4 + dl, "#bfe6ff")
    elif expr == "tired":
        d.line([(cx - 4, my + 1), (cx + 4, my)], fill=o)
    else:
        R(d, cx - 4, my, cx + 4, my, o)
        R(d, cx - 3, my + 1, cx + 3, my + 1, P["skin_sh"])
    # --- поза: палец вверх
    if pose == "finger":
        hx, hy = cx + 24, ty + 46
        d.polygon([(cx + 22, sy + 20), (cx + 30, sy + 22), (hx + 6, hy + 4), (hx - 2, hy + 4)], fill=P["chk_b"])
        checker(d, (cx + 20, hy + 4, cx + 32, sy + 24), 3,
                mask=lambda x, y: x >= hx - 2 + (y - hy) * 0.2 and x <= hx + 8)
        E(d, hx - 3, hy - 4, hx + 6, hy + 6, P["skin"], o)
        R(d, hx + 1, hy - 16, hx + 3, hy - 4, P["skin"])
        R(d, hx, hy - 16, hx, hy - 4, o)
        R(d, hx + 4, hy - 16, hx + 4, hy - 4, o)
        R(d, hx + 1, hy - 17, hx + 3, hy - 17, o)
    elif pose == "hands":
        for hx in (cx - 22, cx + 14):
            E(d, hx - 1, 90, hx + 9, 99, P["skin"], o)
    return im


def plagin_mini(frame=0, expr="tired", walking=True):
    """Маленький Плагин в полный рост, 22x54."""
    im = Image.new("RGBA", (22, 56), (0, 0, 0, 0))
    d = drw(im)
    o = P["out"]
    ph = frame % 4 if walking else 0
    bob = 1 if ph in (1, 3) else 0
    y = bob
    # ноги
    legs = {0: (-2, 2), 1: (0, 0), 2: (2, -2), 3: (0, 0)}[ph]
    for i, dx in enumerate(legs):
        lx = 6 + i * 6 + dx
        R(d, lx, 34 + y, lx + 4, 48, P["jeans"])
        R(d, lx, 34 + y, lx, 48, P["jeans_dk"])
        R(d, lx - 1, 49, lx + 5, 51, P["shoe"])
        R(d, lx - 1, 51, lx + 5, 51, "#9aa0b0")
    # торс
    R(d, 4, 18 + y, 17, 35 + y, P["chk_a"])
    checker(d, (4, 18 + y, 17, 35 + y), 2)
    R(d, 9, 18 + y, 12, 35 + y, P["tee"])
    # руки
    sw = {0: 2, 1: 0, 2: -2, 3: 0}[ph]
    for side, s in ((2, sw), (18, -sw)):
        R(d, side - 1, 19 + y, side + 1, 30 + y + s // 2, P["chk_b"])
        checker(d, (side - 1, 19 + y, side + 1, 30 + y + s // 2), 2)
        R(d, side - 1, 31 + y + s // 2, side + 1, 33 + y + s // 2, P["skin"])
    # голова
    E(d, 4, 3 + y, 17, 17 + y, P["skin"], o)
    d.chord([4, 1 + y, 17, 15 + y], 180, 360, fill=P["hair"])
    R(d, 5, 4 + y, 16, 5 + y, P["lens"])
    d.point((7, 4 + y), fill=P["lens_hl"])
    if expr == "tired":
        R(d, 7, 10 + y, 9, 10 + y, o)
        R(d, 12, 10 + y, 14, 10 + y, o)
    elif expr == "o":
        R(d, 7, 9 + y, 8, 10 + y, o)
        R(d, 12, 9 + y, 13, 10 + y, o)
        E(d, 9, 12 + y, 11, 15 + y, P["mouth"])
    else:
        R(d, 8, 9 + y, 8, 10 + y, o)
        R(d, 13, 9 + y, 13, 10 + y, o)
    R(d, 8, 14 + y, 12, 14 + y, P["skin_sh"])
    return im


def agent(s=22, eyes="normal", frame=0, walk=False, arms="down", squash=0.0, color=None):
    """Оранжевый агент-кубик. Возвращает (img, anchors)."""
    m = 8
    hgt = int(s * 0.86)
    im = Image.new("RGBA", (s + 2 * m, hgt + 2 * m + 6), (0, 0, 0, 0))
    d = drw(im)
    base = color or P["ag"]
    o = P["ag_out"]
    sq = int(squash * 3)
    x0, y0, x1, y1 = m, m + sq, m + s, m + hgt
    # ножки
    ph = frame % 4 if walk else 0
    fl = {0: 0, 1: -2, 2: 0, 3: 0}[ph]
    fr = {0: 0, 1: 0, 2: 0, 3: -2}[ph]
    R(d, x0 + 3, y1 + fl, x0 + 7, y1 + 4 + fl, P["ag_dk"])
    R(d, x1 - 7, y1 + fr, x1 - 3, y1 + 4 + fr, P["ag_dk"])
    # ручки
    if arms == "up":
        R(d, x0 - 4, y0 - 2, x0 - 1, y0 + 6, P["ag_dk"])
        R(d, x1 + 1, y0 - 2, x1 + 4, y0 + 6, P["ag_dk"])
        hands = ((x0 - 3, y0 - 3), (x1 + 3, y0 - 3))
    elif arms == "side":
        R(d, x0 - 5, y0 + hgt // 2 - 1, x0, y0 + hgt // 2 + 2, P["ag_dk"])
        R(d, x1, y0 + hgt // 2 - 1, x1 + 5, y0 + hgt // 2 + 2, P["ag_dk"])
        hands = ((x0 - 5, y0 + hgt // 2), (x1 + 5, y0 + hgt // 2))
    else:
        R(d, x0 - 3, y0 + hgt // 2, x0, y0 + hgt // 2 + 6, P["ag_dk"])
        R(d, x1, y0 + hgt // 2, x1 + 3, y0 + hgt // 2 + 6, P["ag_dk"])
        hands = ((x0 - 2, y0 + hgt // 2 + 6), (x1 + 2, y0 + hgt // 2 + 6))
    # тело
    d.rounded_rectangle([x0 - 1, y0 - 1, x1 + 1, y1 + 1], radius=5, fill=o)
    d.rounded_rectangle([x0, y0, x1, y1], radius=4, fill=base)
    R(d, x0 + 2, y1 - 3, x1 - 2, y1 - 1, P["ag_dk"])
    R(d, x1 - 3, y0 + 3, x1 - 1, y1 - 2, P["ag_dk"])
    R(d, x0 + 2, y0 + 1, x1 - 6, y0 + 2, P["ag_lt"])
    R(d, x0 + 1, y0 + 2, x0 + 2, y0 + 7, P["ag_lt"])
    # глаза
    ex1, ex2 = x0 + int(s * 0.32), x0 + int(s * 0.62)
    ey = y0 + int(hgt * 0.32)
    eh = max(4, int(s * 0.24))
    blink = (frame // 1) % 47 == 0
    for ex in (ex1, ex2):
        if eyes == "sleep" or blink:
            R(d, ex - 1, ey + eh // 2, ex + 2, ey + eh // 2, P["black"])
        elif eyes == "happy":
            d.line([(ex - 1, ey + eh // 2 + 1), (ex, ey + eh // 2 - 1), (ex + 1, ey + eh // 2 - 1),
                    (ex + 2, ey + eh // 2 + 1)], fill=P["black"])
        elif eyes == "heart":
            R(d, ex - 2, ey + 1, ex - 1, ey + 2, P["red"])
            R(d, ex + 1, ey + 1, ex + 2, ey + 2, P["red"])
            R(d, ex - 2, ey + 2, ex + 2, ey + 3, P["red"])
            R(d, ex - 1, ey + 4, ex + 1, ey + 4, P["red"])
            d.point((ex, ey + 5), fill=P["red"])
        elif eyes == "angry":
            R(d, ex, ey + 1, ex + 1, ey + eh, P["black"])
        else:
            R(d, ex, ey, ex + 1, ey + eh, P["black"])
            d.point((ex, ey), fill=P["white"])
    if eyes == "angry":
        d.line([(ex1 - 2, ey - 2), (ex1 + 2, ey)], fill=P["black"])
        d.line([(ex2 - 1, ey), (ex2 + 3, ey - 2)], fill=P["black"])
    if eyes == "glasses":
        for ex in (ex1, ex2):
            d.rectangle([ex - 3, ey - 1, ex + 4, ey + eh], outline=P["black"])
        R(d, ex1 + 4, ey + 1, ex2 - 3, ey + 1, P["black"])
    if eyes == "shades":
        R(d, ex1 - 3, ey, ex2 + 4, ey + 3, P["black"])
        R(d, ex1 - 2, ey + 1, ex1, ey + 1, "#6a6a80")
    anchors = dict(top=((x0 + x1) // 2, y0), lh=hands[0], rh=hands[1], body=(x0, y0, x1, y1),
                   eyes=(ex1, ex2, ey), w=im.width, h=im.height)
    return im, anchors


def fish(t, s=1.0):
    im = Image.new("RGBA", (70, 56), (0, 0, 0, 0))
    d = drw(im)
    o = "#1c2a40"
    wig = int(math.sin(t * 6) * 2)
    # хвост
    d.polygon([(10, 28), (0, 16 + wig), (0, 40 + wig)], fill="#6b7fb0", outline=o)
    # тело
    E(d, 8, 10, 58, 46, "#b7c3dc", o)
    E(d, 10, 26, 56, 46, "#e6ecf6")
    d.polygon([(26, 12), (40, 2), (46, 12)], fill="#f2d24a", outline=o)
    R(d, 18, 12, 22, 44, "#f2d24a")
    # глаз
    E(d, 44, 16, 52, 24, P["white"], o)
    R(d, 47, 18, 49, 21, P["black"])
    # рот «О»
    E(d, 54, 26, 62, 36, "#7c5a6a", o)
    E(d, 56, 28, 60, 34, "#2a1a24")
    return im


# ================================================================ utilities
def zzz(d, x, y, t, c="#ffffff"):
    for i in range(3):
        ph = (t * 0.8 + i / 3) % 1
        yy = y - int(ph * 22)
        xx = x + int(math.sin(ph * 6) * 3) + i * 4
        sz = 7 + i * 2
        if ph < 0.9:
            ptext(d, xx, yy, "z", sz, c, shadow="#20182a")


def bubble(d, x, y, w, h, text, size=8, tail="down"):
    R(d, x - 1, y, x + w + 1, y + h, P["out"])
    R(d, x, y - 1, x + w, y + h + 1, P["out"])
    R(d, x, y, x + w, y + h, P["white"])
    if tail == "down":
        d.polygon([(x + 8, y + h), (x + 14, y + h), (x + 8, y + h + 6)], fill=P["white"], outline=P["out"])
        R(d, x + 9, y + h, x + 13, y + h, P["white"])
    ptext(d, x + w // 2 + 1, y + h // 2 + 1, text, size, "#222", anchor="mm")


def hearts(d, t, x, y, n=5):
    for i in range(n):
        ph = (t * 0.6 + i / n) % 1
        hx = x + int(math.sin(i * 2.3 + ph * 4) * 26)
        hy = y - int(ph * 70)
        c = P["red"] if i % 2 else "#ff7aa8"
        R(d, hx, hy, hx + 1, hy + 1, c)
        R(d, hx + 3, hy, hx + 4, hy + 1, c)
        R(d, hx - 1, hy + 1, hx + 5, hy + 3, c)
        R(d, hx, hy + 4, hx + 4, hy + 4, c)
        R(d, hx + 1, hy + 5, hx + 3, hy + 5, c)
        d.point((hx + 2, hy + 6), fill=c)


def sunburst(img, t, c1="#f28a3c", c2="#ffb070", cx=W // 2, cy=150):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, c1)
    n = 14
    rot = t * 0.15
    for i in range(n):
        a0 = rot + i * 2 * math.pi / n
        a1 = a0 + math.pi / n
        L = 500
        d.polygon([(cx, cy), (cx + L * math.cos(a0), cy + L * math.sin(a0)),
                   (cx + L * math.cos(a1), cy + L * math.sin(a1))], fill=c2)
    return d


# ================================================================ scenes
def base():
    return Image.new("RGBA", (W, H), (0, 0, 0, 255))


def sc_lecture_sleep(t, f, dur):
    img = base()
    d = lecture_bg(img, t)
    # препод у доски
    px = 70 + int(math.sin(t * 0.8) * 10)
    R(d, px, 60, px + 12, 118, "#2a2b3a")
    E(d, px + 1, 46, px + 11, 60, "#e0b090", P["out"])
    R(d, px + 1, 44, px + 11, 49, "#8a8a8a")
    if int(t * 4) % 2:
        R(d, px + 12, 64, px + 20, 66, "#2a2b3a")
    # затылки студентов
    for row, yy in enumerate((126, 142)):
        for i in range(6):
            hx = 6 + i * 30 + (row * 12)
            E(d, hx, yy, hx + 14, yy + 16, ["#3a2a20", "#1c1c22", "#7a4a2a", "#c08a50"][(i + row) % 4], P["out"])
            R(d, hx - 2, yy + 14, hx + 16, yy + 30, ["#3b5a8a", "#8a3a3a", "#3a7a5a", "#5a4a8a"][(i + row) % 4])
    # парта на переднем плане
    R(d, 0, 222, W - 1, 228, P["wood_lt"])
    R(d, 0, 229, W - 1, H - 1, P["wood"])
    for yy in range(236, H, 9):
        R(d, 0, yy, W - 1, yy, P["wood_dk"])
    # Плагин спит, голова наклонена
    b = plagin_bust("sleep", t=t).rotate(-18 + math.sin(t * 1.5) * 2, resample=Image.NEAREST, expand=True)
    paste(img, b, 46, 132)
    d = drw(img)
    R(d, 0, 222, W - 1, 228, P["wood_lt"])
    R(d, 0, 229, W - 1, H - 1, P["wood"])
    for yy in range(236, H, 9):
        R(d, 0, yy, W - 1, yy, P["wood_dk"])
    # тетрадь
    d.polygon([(110, 218), (150, 214), (156, 226), (114, 230)], fill="#f2efe4", outline=P["out"])
    zzz(d, 112, 150, t)
    return img


def sc_bus_sleep(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#2e3446")
    # окно автобуса — едущий город
    R(d, 6, 30, W - 7, 160, "#7fb6e8")
    off = int(t * 60)
    rnd = random.Random(1)
    blds = [(rnd.randint(14, 30), rnd.randint(40, 100), rnd.choice(["#4a5a7a", "#5a6a8a", "#3e4a6a", "#6a5a7a"]))
            for _ in range(30)]
    x = -(off % 600)
    while x < W:
        for bw, bh, bc in blds:
            if x > W:
                break
            R(d, x, 160 - bh, x + bw, 160, bc)
            for wy in range(160 - bh + 4, 158, 6):
                for wx in range(x + 3, x + bw - 2, 5):
                    R(d, wx, wy, wx + 1, wy + 2, "#a9cdf0")
            x += bw + 2
    # столбы
    for k in range(4):
        sx = (k * 70 - off * 2) % 260 - 40
        R(d, sx, 40, sx + 2, 160, "#2a2a30")
    window_frame(d, 4, 28, W - 5, 162, 2)
    R(d, 0, 162, W - 1, 168, "#3e4658")
    # поручень
    R(d, 0, 18, W - 1, 20, "#b8bcc8")
    # сиденье
    R(d, 10, 190, 170, H - 1, "#2b4f9e")
    for x in range(10, 170, 8):
        R(d, x, 190, x + 3, H - 1, "#24438a")
    R(d, 10, 186, 170, 192, "#1e3a78")
    b = plagin_bust("sleep", t=t).rotate(16 + math.sin(t * 9) * 1.2, resample=Image.NEAREST, expand=True)
    paste(img, b, 50 + int(math.sin(t * 9) * 1), 120 + int(abs(math.sin(t * 7)) * 2))
    d = drw(img)
    zzz(d, 46, 120, t)
    return img


def sc_room_idea(t, f, dur):
    img = base()
    room_night(img, t)
    d = drw(img)
    monitor(d, 120, 150, 172, 196, "#1b1f33")
    paste(img, plagin_bust("o" if t < 0.4 else "neutral", "finger", t), 46, 116)
    d = drw(img)
    keyboard(d, 60, 212, 50)
    mug(d, 150, 202)
    # лампочка-идея
    if t > 0.3:
        bx, by = 116, 92
        glow(img, bx + 6, by + 6, 16, (255, 230, 120), 90)
        d = drw(img)
        E(d, bx, by, bx + 12, by + 12, "#ffe680", P["out"])
        R(d, bx + 4, by + 13, bx + 8, by + 16, "#9a9aa8")
        for a in range(0, 360, 45):
            r1, r2 = 10, 13 + int(math.sin(t * 10) * 1)
            d.line([(bx + 6 + r1 * math.cos(math.radians(a)), by + 6 + r1 * math.sin(math.radians(a))),
                    (bx + 6 + r2 * math.cos(math.radians(a)), by + 6 + r2 * math.sin(math.radians(a)))],
                   fill="#ffe680")
    return img


def sc_monitor_download(t, f, dur):
    img = base()
    room_night(img, t)
    d = drw(img)
    # монитор крупным планом
    monitor(d, 8, 60, 172, 176, "#11131d")
    R(d, 12, 64, 168, 72, "#1c1f2e")
    for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        R(d, 15 + i * 6, 66, 18 + i * 6, 69, c)
    ptext(d, 20, 82, "> install claude", 8, "#c9d1d9", mono=True)
    p = min(100, int(ease(t / max(0.1, dur - 0.3)) * 100))
    ptext(d, 20, 100, "Загрузка Клода...", 8, "#e8e8f0")
    R(d, 20, 116, 160, 128, "#e8e8f0")
    R(d, 22, 118, 158, 126, "#11131d")
    R(d, 23, 119, 23 + int(134 * p / 100), 125, P["ag"])
    ptext(d, 90, 140, f"{p}%", 10, P["ag_lt"], anchor="ma")
    if p >= 100:
        ptext(d, 90, 156, "ГОТОВО ✓", 9, P["green"], anchor="ma")
    return img


def uni_building(d, t):
    R(d, 0, 0, W - 1, 200, "#ffb98a")
    R(d, 0, 0, W - 1, 60, "#ff9f78")
    R(d, 0, 60, W - 1, 110, "#ffc79a")
    E(d, 130, 40, 154, 64, "#fff0b0")
    R(d, 20, 80, 160, 210, "#d8c6a8")
    d.polygon([(14, 82), (90, 50), (166, 82)], fill="#c0ab8a", outline=P["out"])
    R(d, 14, 82, 166, 88, "#b8a080")
    ptext(d, 90, 64, "УНИВЕР", 8, "#5a3a2a", anchor="mm")
    for cxx in range(28, 160, 22):
        R(d, cxx, 90, cxx + 6, 200, "#efe3cc")
        R(d, cxx + 5, 90, cxx + 6, 200, "#c9b89a")
    R(d, 76, 150, 104, 210, "#5a3424")
    R(d, 89, 150, 90, 210, "#3a2016")
    R(d, 0, 210, W - 1, H - 1, "#8c8f9c")
    for x in range(0, W, 12):
        R(d, x, 210, x, H - 1, "#7a7d8a")
    for y in range(222, H, 12):
        R(d, 0, y, W - 1, y, "#7a7d8a")
    # деревья
    for tx in (4, 168):
        E(d, tx - 14, 120, tx + 14, 170, "#3f8f4c", P["out"])
        R(d, tx - 2, 168, tx + 2, 212, "#6a3e24")


def sc_agent_to_uni(t, f, dur):
    img = base()
    d = drw(img)
    uni_building(d, t)
    x = int(lerp(-30, 72, ease(t / dur)))
    im, a = agent(36, "normal", f // 4, walk=True)
    paste(img, im, x, 186)
    d = drw(img)
    # рюкзак
    bx0, by0, bx1, by1 = a["body"]
    R(d, x + bx0 - 7, 186 + by0 + 4, x + bx0 - 1, 186 + by0 + 20, "#3a6ad0")
    R(d, x + bx0 - 7, 186 + by0 + 4, x + bx0 - 1, 186 + by0 + 6, "#2a4ea0")
    return img


def sc_agent_notes(t, f, dur):
    img = base()
    room_night(img, t, desk_y=200)
    d = drw(img)
    im, a = agent(40, "glasses", f, arms="side")
    paste(img, im, 66, 150)
    d = drw(img)
    # тетрадь
    d.polygon([(30, 214), (150, 214), (158, 250), (22, 250)], fill="#f4f1e6", outline=P["out"])
    R(d, 89, 214, 90, 250, "#c8c2b0")
    lines = int(t * 18)
    for i in range(min(lines, 14)):
        row = i % 7
        side = i // 7
        lx = 34 + side * 62
        R(d, lx, 219 + row * 4, lx + 20 + (i * 7) % 26, 219 + row * 4, "#3a4aa0")
    # ручка бегает
    px = 34 + (lines % 7) * 6 + int(math.sin(t * 40) * 3)
    py = 214 + (lines % 7) * 4
    d.line([(px, py), (px + 10, py - 14)], fill="#2a2a3a", width=2)
    # линии скорости
    for i in range(6):
        yy = 150 + i * 9
        R(d, 8 + (f * 3 + i * 17) % 30, yy, 30 + (f * 3 + i * 17) % 30, yy, "#ffd8a0")
    return img


def sc_agent_alarm(t, f, dur):
    img = base()
    d = lecture_bg(img, t)
    R(d, 0, 222, W - 1, H - 1, P["wood"])
    shake = int(math.sin(t * 50) * 2) if (t % 0.8) < 0.4 else 0
    b = plagin_bust("o" if (t % 0.8) < 0.4 and t > 0.5 else "sleep", t=t)
    paste(img, b, 70 + shake, 126)
    d = drw(img)
    R(d, 0, 222, W - 1, 228, P["wood_lt"])
    R(d, 0, 229, W - 1, H - 1, P["wood"])
    for yy in range(236, H, 9):
        R(d, 0, yy, W - 1, yy, P["wood_dk"])
    up = (t % 0.8) < 0.4
    im, a = agent(30, "angry", f, arms="up" if up else "side")
    paste(img, im, 6, 176)
    d = drw(img)
    # тарелки
    for (hx, hy) in (a["lh"], a["rh"]):
        cx_, cy_ = 6 + hx, 176 + hy
        E(d, cx_ - 7, cy_ - 2, cx_ + 7, cy_ + 2, "#e8c040", P["out"])
    if up:
        ptext(d, 24, 150, "ДЗЫНЬ!", 10, "#ffe680", shadow=P["out"])
        for i in range(5):
            ang = i * 0.6 - 1.2
            d.line([(24 + 20 * math.cos(ang), 176 + 20 * math.sin(ang) - 6),
                    (24 + 28 * math.cos(ang), 176 + 28 * math.sin(ang) - 6)], fill="#ffe680")
    return img


def bedroom_bg(img, t):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#6a4a6e")
    # окно с солнцем
    R(d, 100, 24, 168, 104, "#ffd9a0")
    R(d, 100, 70, 168, 104, "#ffc080")
    E(d, 120, 50, 146, 76, "#fff2b0")
    window_frame(d, 98, 22, 170, 106, 2)
    # лучи
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.polygon([(100, 104), (168, 104), (120, 260), (10, 260)], fill=(255, 220, 150, 40))
    img.alpha_composite(ov)
    d = drw(img)
    # кровать
    R(d, 0, 180, W - 1, 186, "#5a3424")
    R(d, 0, 186, W - 1, H - 1, "#8a5a3a")
    return d


def sc_bed_happy(t, f, dur):
    img = base()
    d = bedroom_bg(img, t)
    # подушка
    E(d, 14, 150, 110, 190, "#f4f1ea", P["out"])
    b = plagin_bust("happy" if t > dur * 0.35 else "sleep", "nodrool", t)
    b = b.rotate(70, resample=Image.NEAREST, expand=True)
    paste(img, b, 6, 128)
    d = drw(img)
    # одеяло
    d.polygon([(0, 196), (W - 1, 176), (W - 1, H - 1), (0, H - 1)], fill="#3f6fc4")
    checker(d, (0, 190, W - 1, H - 1), 6, "#3f6fc4", "#4f80d6",
            mask=lambda x, y: y >= 196 - x * 20 / 180)
    d.line([(0, 196), (W - 1, 176)], fill=P["out"])
    # будильник показывает 12:47
    R(d, 140, 150, 172, 170, "#e8473a")
    R(d, 143, 153, 169, 167, "#1a1a20")
    ptext(d, 156, 160, "12:47", 7, P["green"], anchor="mm", mono=True)
    if t > dur * 0.35:
        for i in range(4):
            sx = 60 + i * 22
            sy = 120 + int(math.sin(t * 3 + i) * 4)
            ptext(d, sx, sy, "✦", 9, "#fff2b0")
    return img


def ring_bg(img, t):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#1a1428")
    for i in range(30):
        x = (i * 37) % W
        y = 10 + (i * 53) % 120
        if (int(t * 6) + i) % 9 == 0:
            R(d, x, y, x + 1, y + 1, "#ffffff")
        else:
            d.point((x, y), fill="#5a4a7a")
    # прожектор
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.polygon([(80, 0), (100, 0), (170, 240), (10, 240)], fill=(255, 230, 180, 35))
    img.alpha_composite(ov)
    d = drw(img)
    # ринг
    d.polygon([(0, 190), (W - 1, 190), (W - 1, 260), (0, 260)], fill="#d8cdbb")
    R(d, 0, 260, W - 1, H - 1, "#3a2a3a")
    R(d, 0, 260, W - 1, 266, "#b02a2a")
    for x in (2, W - 8):
        R(d, x, 120, x + 6, 262, "#c0c0c8")
    for yy in (140, 160, 180):
        R(d, 0, yy, W - 1, yy + 2, "#e8473a")
    return d


def sc_ring_fight(t, f, dur):
    img = base()
    ring_bg(img, t)
    hop = int(abs(math.sin(t * 8)) * 6)
    hop2 = int(abs(math.sin(t * 8 + 1.5)) * 6)
    second = t > dur * 0.58
    # если вторая фраза — тянут тетрадку
    if second:
        pull = int(math.sin(t * 6) * 6)
        im1, _ = agent(34, "angry", f, arms="side")
        im2, _ = agent(34, "angry", f, arms="side", color="#e8663a")
        paste(img, im1, 16 + pull, 180)
        paste(img, im2.transpose(Image.FLIP_LEFT_RIGHT), 112 + pull, 180)
        d = drw(img)
        R(d, 66 + pull, 194, 112 + pull, 214, "#f4f1e6")
        R(d, 66 + pull, 194, 112 + pull, 196, "#3a6ad0")
        R(d, 88 + pull, 194, 89 + pull, 214, "#c8c2b0")
        ptext(d, 90 + pull, 222, "ТЕТРАДЬ", 6, "#3a3a3a", anchor="ma")
    else:
        im1, a1 = agent(34, "angry", f, arms="up" if int(t * 6) % 2 else "side")
        im2, a2 = agent(34, "angry", f, arms="side" if int(t * 6) % 2 else "up", color="#e8663a")
        paste(img, im1, 20, 180 - hop)
        paste(img, im2.transpose(Image.FLIP_LEFT_RIGHT), 108, 180 - hop2)
        d = drw(img)
        # перчатки
        for (x, y) in ((20 + a1["rh"][0], 180 - hop + a1["rh"][1]),
                       (108 + im2.width - a2["rh"][0], 180 - hop2 + a2["rh"][1])):
            E(d, x - 4, y - 4, x + 4, y + 4, P["red"], P["out"])
        # подписи
        ptext(d, 44, 172 - hop, "КОНСПЕКТЫ", 6, "#ffe0c0", anchor="ma", shadow=P["out"])
        ptext(d, 134, 172 - hop2, "ПАРЫ", 6, "#ffe0c0", anchor="ma", shadow=P["out"])
        if int(t * 5) % 2:
            ptext(d, 90, 150, "БАМ!", 11, "#ffe680", anchor="ma", shadow=P["out"])
    # судья
    im3, a3 = agent(22, "normal", f, arms="up")
    paste(img, im3, 76, 140)
    d = drw(img)
    bx0, by0, bx1, by1 = a3["body"]
    for xx in range(76 + bx0 + 2, 76 + bx1 - 1, 4):
        R(d, xx, 140 + by0 + 8, xx + 1, 140 + by1 - 2, P["black"])
    R(d, 76 + a3["rh"][0] - 2, 140 + a3["rh"][1] - 6, 76 + a3["rh"][0] + 2, 140 + a3["rh"][1], "#ffe14a")
    return img


def sc_agent_quit(t, f, dur):
    img = base()
    room_night(img, t, desk_y=230, lamp=False)
    d = drw(img)
    # дверь
    R(d, 130, 60, 176, 230, "#5a3424")
    R(d, 134, 64, 172, 230, "#1a1420")
    second = t > dur * 0.45
    x = int(lerp(20, 120, ease(t / dur)))
    im, a = agent(30, "sleep" if second else "angry", f // 3, walk=True, arms="side")
    paste(img, im, x, 190)
    d = drw(img)
    # коробка с вещами
    bx = x + a["rh"][0] - 6
    by = 190 + a["rh"][1] - 14
    R(d, bx, by, bx + 18, by + 12, "#c09060")
    R(d, bx, by, bx + 18, by + 2, "#a07040")
    E(d, bx + 4, by - 8, bx + 12, by, P["red"], P["out"])
    R(d, bx + 7, by - 6, bx + 8, by - 3, P["white"])
    # табличка
    R(d, 30, 120, 110, 140, P["white"])
    d.rectangle([30, 120, 110, 140], outline=P["out"])
    ptext(d, 70, 130, "УВОЛЬНЯЮСЬ", 7, P["red"], anchor="mm")
    if second:
        zzz(d, x + 30, 186, t, "#ffe0c0")
    return img


def corridor_bg(img, t, off=0):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#3a2a34")
    # перспектива коридора
    vx, vy = 90, 120
    d.polygon([(0, 0), (W - 1, 0), (vx + 14, vy - 20), (vx - 14, vy - 20)], fill="#2a1e28")
    d.polygon([(0, H - 1), (W - 1, H - 1), (vx + 14, vy + 20), (vx - 14, vy + 20)], fill="#4a3428")
    d.polygon([(0, 0), (vx - 14, vy - 20), (vx - 14, vy + 20), (0, H - 1)], fill="#5a4048")
    d.polygon([(W - 1, 0), (vx + 14, vy - 20), (vx + 14, vy + 20), (W - 1, H - 1)], fill="#4c363e")
    R(d, vx - 14, vy - 20, vx + 14, vy + 20, "#ffd9a0")
    # ковровая дорожка
    d.polygon([(50, H - 1), (130, H - 1), (vx + 6, vy + 20), (vx - 6, vy + 20)], fill="#2c3a6a")
    for k in range(8):
        z = ((k / 8) + off) % 1
        yy = int(vy + 20 + (H - vy - 20) * z * z)
        R(d, 0, yy, W - 1, yy, "#3a2a24")
    # двери по сторонам
    for k in range(4):
        z = ((k / 4) + off * 0.5) % 1
        s = 0.2 + z * z * 1.4
        dx = int(vx - 14 - (vx - 14) * z * z)
        top = int(vy - 20 - 70 * s)
        bot = int(vy + 20 + 80 * s * 0.9)
        R(d, dx, top, dx + max(2, int(12 * s)), bot, "#6a3e28")
        dx2 = W - 1 - dx - max(2, int(12 * s))
        R(d, dx2, top, dx2 + max(2, int(12 * s)), bot, "#6a3e28")
    # лампы
    for k in range(3):
        z = ((k / 3) + off * 0.5) % 1
        yy = int(vy - 20 - (vy - 20) * z * z)
        w = int(4 + 30 * z * z)
        R(d, vx - w, yy, vx + w, yy + 1 + int(2 * z), "#ffe6b0")
    return d


def sc_corridor_walk(t, f, dur):
    img = base()
    corridor_bg(img, t, off=t * 0.25)
    sway = int(math.sin(t * 3) * 6)
    m = plagin_mini(f // 4, "tired")
    paste(img, m, 68 + sway, 170, 2)
    d = drw(img)
    zzz(d, 108 + sway, 170, t)
    return img


def sc_door_open(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#5a4048")
    R(d, 0, 250, W - 1, H - 1, "#4a3428")
    # проём
    R(d, 36, 40, 144, 252, "#3a2418")
    R(d, 40, 44, 140, 252, "#fff1d0")
    # внутри силуэты студентов
    for i in range(5):
        hx = 46 + i * 20
        E(d, hx, 150, hx + 12, 162, "#c9a88a")
        R(d, hx - 2, 162, hx + 14, 190, ["#3b5a8a", "#8a3a3a", "#3a7a5a", "#5a4a8a", "#7a6a3a"][i])
    R(d, 40, 186, 140, 196, P["wood_lt"])
    # открывающаяся дверь
    op = ease((t - 0.25) / 0.9)
    dw = int(100 * (1 - op * 0.85))
    R(d, 40, 44, 40 + dw, 252, "#7a4428")
    R(d, 40 + dw - 2, 44, 40 + dw, 252, "#55301e")
    if dw > 30:
        R(d, 40 + dw - 12, 150, 40 + dw - 8, 154, "#e8c040")
        R(d, 40 + 10, 80, 40 + min(dw - 10, 70), 100, "#e8e0c8")
        ptext(d, 40 + min(dw, 80) // 2 + 6, 90, "ауд. 404", 7, "#3a2418", anchor="mm")
    # табличка над дверью
    R(d, 64, 18, 116, 34, "#2a5a8a")
    ptext(d, 90, 26, "404", 9, P["white"], anchor="mm")
    # спина Плагина
    m = plagin_mini(0, "tired", walking=False)
    paste(img, m, 70, 214, 2)
    return img


def sc_class_stare(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#6b4a52")
    R(d, 30, 10, 150, 60, P["board"])
    d.rectangle([30, 10, 150, 60], outline=P["wood_dk"])
    ptext(d, 90, 34, "ГРУППА Б-21", 8, P["chalk"], anchor="mm")
    rnd = random.Random(9)
    second = t > dur * 0.45
    rows = [(78, 6, 18), (124, 5, 24), (176, 4, 32)]
    for ri, (yy, n, s) in enumerate(rows):
        step = W // n
        for i in range(n):
            hx = i * step + (step - s) // 2
            skin = rnd.choice(["#f4c7aa", "#e0a882", "#c98e6a", "#f6d2bc"])
            hair = rnd.choice(["#3a2a20", "#1c1c22", "#7a4a2a", "#c08a50", "#a03a2a"])
            shirt = rnd.choice(["#3b5a8a", "#8a3a3a", "#3a7a5a", "#5a4a8a", "#7a6a3a"])
            R(d, hx - 2, yy + s - 2, hx + s + 2, yy + s * 2, shirt)
            E(d, hx, yy, hx + s, yy + int(s * 1.1), skin, P["out"])
            d.chord([hx - 1, yy - 2, hx + s + 1, yy + int(s * 0.8)], 180, 360, fill=hair)
            # глаза смотрят прямо в камеру
            ew = max(2, s // 6)
            for ex in (hx + s // 4, hx + s - s // 4 - ew):
                R(d, ex - 1, yy + s // 2 - 1, ex + ew, yy + s // 2 + ew, P["white"])
                R(d, ex, yy + s // 2, ex + ew - 1, yy + s // 2 + ew - 1, P["black"])
            # брови осуждения
            if second:
                d.line([(hx + s // 4 - 1, yy + s // 2 - 3), (hx + s // 2 - 2, yy + s // 2 - 1)], fill=P["out"])
                d.line([(hx + s // 2 + 2, yy + s // 2 - 1), (hx + s - s // 4 + 1, yy + s // 2 - 3)], fill=P["out"])
        R(d, 0, yy + s * 2 - 6, W - 1, yy + s * 2, P["wood_lt"])
        R(d, 0, yy + s * 2, W - 1, yy + s * 2 + 4, P["wood"])
    if second:
        for i in range(5):
            qx = 14 + i * 36
            qy = 60 + int(math.sin(t * 6 + i) * 3)
            ptext(d, qx, qy, "?", 12, "#ffe680", shadow=P["out"])
    # зум-«наезд» в конце — драматизм
    return img


def sc_aquarium(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#1a2a6a")
    for y in range(0, H, 1):
        if y % 3 == 0:
            R(d, 0, y, W - 1, y, blend("#2a3a8a", "#3a6ac0", y / H))
        else:
            R(d, 0, y, W - 1, y, blend("#22337a", "#3462b4", y / H))
    # блики сверху
    glow(img, 120, 20, 40, (220, 230, 255), 90)
    d = drw(img)
    # водоросли
    for i, x in enumerate((96, 120, 150, 170)):
        for k in range(10):
            yy = 300 - k * 8
            sx = x + int(math.sin(t * 2 + k * 0.6 + i) * 3)
            R(d, sx, yy, sx + 3, yy + 7, "#3f9f6c" if k % 2 else "#2f7f5c")
    # пузырьки
    for i in range(10):
        bx = 90 + (i * 23) % 90
        by = H - int((t * 40 + i * 37) % H)
        d.ellipse([bx, by, bx + 3, by + 3], outline="#cfe8ff")
    # рыба с ртом «О»
    fx = 96 + int(math.sin(t * 1.2) * 4)
    paste(img, fish(t).transpose(Image.FLIP_LEFT_RIGHT), fx, 120 + int(math.sin(t * 2) * 4), 1)
    # рама аквариума
    R(d := drw(img), 0, 0, 8, H - 1, "#141c40")
    # Плагин, крупно, лицо «О» — как на фото
    b = plagin_bust("o", t=t, blink=False)
    paste(img, b.crop((0, 0, 76, 100)), -14, 140, 2)
    # синий фильтр поверх Плагина (свет аквариума)
    ov = Image.new("RGBA", img.size, (60, 90, 255, 38))
    img.alpha_composite(ov)
    return img


def sc_agent_front_desk(t, f, dur):
    img = base()
    d = lecture_bg(img, t, front=True)
    ptext(d, 64, 50, "ЛЕКЦИЯ №7", 9, P["chalk"], anchor="mm")
    second = t > dur * 0.4
    if not second:
        # прожектор ищет
        sx = 90 + int(math.sin(t * 3) * 40)
        ov = Image.new("RGBA", img.size, (0, 0, 0, 120))
        od = ImageDraw.Draw(ov)
        od.ellipse([sx - 30, 150, sx + 30, 230], fill=(0, 0, 0, 0))
        img.alpha_composite(ov)
    im, a = agent(40, "glasses", f, arms="up" if second and int(t * 4) % 2 else "side")
    paste(img, im, 64, 156)
    d = drw(img)
    R(d, 0, 206, W - 1, 212, P["wood_lt"])
    R(d, 0, 213, W - 1, H - 1, P["wood"])
    for yy in range(222, H, 9):
        R(d, 0, yy, W - 1, yy, P["wood_dk"])
    R(d, 60, 196, 120, 206, "#f4f1e6")
    if second:
        R(d, 130, 120, 176, 140, P["white"])
        d.rectangle([130, 120, 176, 140], outline=P["out"])
        ptext(d, 153, 130, "ПРИВЕТ :)", 6, "#222", anchor="mm")
    return img


def sc_agent_hearts(t, f, dur):
    img = base()
    sunburst(img, t, "#f07aa0", "#ff9ec0")
    d = drw(img)
    bounce = int(abs(math.sin(t * 5)) * 6)
    im, a = agent(56, "heart", f, arms="up")
    paste(img, im, 54, 140 - bounce)
    d = drw(img)
    hearts(d, t, 90, 150, 7)
    return img


def sc_gradebook(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#3a2a34")
    R(d, 0, 230, W - 1, H - 1, P["wood"])
    # зачётка
    R(d, 14, 40, 166, 236, "#f4f1e6")
    d.rectangle([14, 40, 166, 236], outline=P["out"])
    R(d, 14, 40, 166, 58, "#2a5a8a")
    ptext(d, 90, 49, "ЗАЧЁТКА", 9, P["white"], anchor="mm")
    rows = [("Агент", "ОТЛ. 5", "#2a8a3a"), ("Агент", "ОТЛ. 5", "#2a8a3a"),
            ("Агент", "ОТЛ. 5", "#2a8a3a"), ("Плагин", "НЕУД. 2", P["red"])]
    for i, (n, g, c) in enumerate(rows):
        yy = 70 + i * 30
        R(d, 22, yy + 18, 158, yy + 18, "#c8c2b0")
        ptext(d, 24, yy + 4, n, 9, "#333")
        if t > 0.3 + i * 0.25 or i < 3 and t > 0.1 + i * 0.12:
            ptext(d, 156, yy + 4, g, 9, c, anchor="ra")
    if t > dur * 0.5:
        k = ease((t - dur * 0.5) / 0.2)
        sz = int(lerp(26, 12, k))
        st = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
        sd = drw(st)
        sd.rectangle([2, 2, 117, 37], outline=P["red"], width=2)
        ptext(sd, 60, 20, "ПЕРЕСДАЧА", sz if sz < 14 else 12, P["red"], anchor="mm")
        st = st.rotate(12, resample=Image.NEAREST, expand=True)
        paste(img, st, 26, 186)
    return img


def sc_plagin_tired(t, f, dur):
    img = base()
    room_night(img, t)
    d = drw(img)
    monitor(d, 118, 150, 172, 196, "#1b1f33")
    b = plagin_bust("sleep", t=t).rotate(-14, resample=Image.NEAREST, expand=True)
    paste(img, b, 34, 126)
    d = drw(img)
    R(d, 0, 208, W - 1, 212, P["wood_lt"])
    R(d, 0, 213, W - 1, H - 1, P["wood"])
    for yy in range(220, H, 9):
        R(d, 0, yy, W - 1, yy, P["wood_dk"])
    R(d, 0, H - 22, W - 1, H - 1, "#1f1b2e")
    zzz(d, 92, 140, t)
    # агент выглядывает
    im, a = agent(26, "normal", f, arms="side")
    paste(img, im, 130, 172)
    return img


def sc_recording(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#3a2430")
    glow(img, 90, 120, 90, (255, 170, 90), 70)
    d = drw(img)
    # кольцевая лампа
    d.ellipse([40, 50, 140, 150], outline="#fff1c0", width=6)
    R(d, 88, 150, 92, 250, "#2a2630")
    # агент с маской-лицом Плагина
    im, a = agent(70, "normal", f, arms="side")
    paste(img, im, 46, 150)
    face = plagin_bust("smirk", t=t).crop((14, 0, 62, 54))
    paste(img, face, 66, 150)
    d = drw(img)
    R(d, 62, 172, 66, 174, "#d8d0c8")  # резинка маски
    R(d, 110, 172, 116, 174, "#d8d0c8")
    # REC
    R(d, 30, 14, 150, 32, "#1a1218")
    d.rectangle([30, 14, 150, 32], outline=P["red"])
    if int(t * 2) % 2 == 0:
        E(d, 36, 19, 44, 27, P["red"])
    ptext(d, 96, 23, "ИДЁТ ЗАПИСЬ", 8, "#ffe0e0", anchor="mm")
    # камера
    R(d, 140, 230, 176, 252, "#1a1a20")
    E(d, 128, 234, 142, 248, "#2a2a3a", P["out"])
    R(d, 156, 252, 158, 300, "#1a1a20")
    return img


def sc_outro(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#121220")
    # логотип-агент
    im, a = agent(40, "happy", f, arms="up")
    paste(img, im, 62, 70 + int(abs(math.sin(t * 4)) * 4))
    d = drw(img)
    ptext(d, 90, 140, "Plagin", 18, P["white"], anchor="mm", shadow="#ff4a6a")
    # строка поиска
    R(d, 24, 170, 156, 188, P["white"])
    d.rectangle([24, 170, 156, 188], outline="#3ad0e0")
    full = "@Plagin"
    n = min(len(full), int(t * 8))
    ptext(d, 34, 179, full[:n] + ("|" if int(t * 3) % 2 else ""), 9, "#222", anchor="lm")
    d.ellipse([140, 174, 150, 184], outline="#444")
    ptext(d, 90, 214, "ПОДПИШИСЬ ↓", 10, P["ag_lt"], anchor="mm")
    return img


SCENE_FUNCS = {k[3:]: v for k, v in globals().items() if k.startswith("sc_")}
