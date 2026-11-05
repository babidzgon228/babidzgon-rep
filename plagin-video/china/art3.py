# -*- coding: utf-8 -*-
"""Сцены для ролика «Жизнь в Китае» (поверх рисуются xBR-сглаживание, фото и субтитры)."""
import math
import random

from PIL import Image, ImageDraw

import art
from art import (P, W, H, R, E, drw, ptext, paste, lerp, ease, checker, glow, zzz, bubble, hearts, sunburst,
                 agent, plagin_bust, plagin_mini, room_night, lecture_bg, window_frame, base, skyline, blend)
from art2 import (O, paper, stamp, desk_front, shake, confetti, star_burst, night_overlay, person_mini, man_bust,
                  crown, thumbs, speed_lines, office_bg, cat, startup_bg)

HANDLE = "@Plaginstory"
PEOPLE = [dict(hair="#141418", top="#c0303a"), dict(hair="#2a1a14", top="#3a6ad0"), dict(hair="#141418", top="#f2f2f2"),
          dict(hair="#3a2a20", top="#3a8a4a"), dict(hair="#141418", top="#e8a020"), dict(hair="#5a3a2a", top="#8a4ad0")]


# ================================================================ helpers
def sky_day(d, y0=0, y1=200, top="#7ac8f0", bot="#cfeeff"):
    for y in range(y0, y1):
        R(d, 0, y, W - 1, y, blend(top, bot, (y - y0) / max(1, y1 - y0)))


def clouds(d, t, y=30, n=3, seed=1):
    rnd = random.Random(seed)
    for i in range(n):
        x = (rnd.randint(0, W) + t * 6 * (i + 1)) % (W + 60) - 30
        yy = y + rnd.randint(0, 40)
        for dx, r in ((0, 8), (9, 11), (20, 8)):
            E(d, x + dx - r, yy - r // 2, x + dx + r, yy + r // 2 + 2, P["white"])


def city_day(d, t, y1=210, seed=5, tall=False):
    sky_day(d, 0, y1)
    clouds(d, t)
    rnd = random.Random(seed)
    x = -4
    while x < W:
        w = rnd.randint(14, 26)
        h = rnd.randint(60, 150 if tall else 110)
        c = rnd.choice(["#6a8ab0", "#8aa6c8", "#5a7898", "#9ab4d0"])
        R(d, x, y1 - h, x + w, y1, c)
        R(d, x + w - 3, y1 - h, x + w, y1, blend(c, "#000000", 0.2))
        for wy in range(y1 - h + 4, y1 - 3, 6):
            for wx in range(x + 3, x + w - 4, 5):
                R(d, wx, wy, wx + 2, wy + 2, "#d8ecff" if (wx + wy) % 3 else "#a8c8e8")
        x += w + 1
    if tall:
        R(d, 84, y1 - 190, 100, y1, "#4a6888")
        d.polygon([(84, y1 - 190), (92, y1 - 210), (100, y1 - 190)], fill="#4a6888")
        R(d, 91, y1 - 222, 92, y1 - 210, "#4a6888")


def ground(d, y=210, c="#8c8f9c"):
    R(d, 0, y, W - 1, H - 1, c)
    for x in range(0, W, 14):
        R(d, x, y, x, H - 1, blend(c, "#000000", 0.1))


def flag_ru(d, x, y, w=24, h=16):
    R(d, x, y, x + w, y + h // 3, "#ffffff")
    R(d, x, y + h // 3, x + w, y + 2 * h // 3, "#2a5ad0")
    R(d, x, y + 2 * h // 3, x + w, y + h, "#d82a2a")
    d.rectangle([x, y, x + w, y + h], outline=O)


def flag_cn(d, x, y, w=24, h=16):
    R(d, x, y, x + w, y + h, "#de2910")
    star_burst(d, x + 6, y + 5, 4, "#ffde00")
    for k in range(4):
        d.point((x + 11 + (k % 2) * 2, y + 2 + k * 2), fill="#ffde00")
    d.rectangle([x, y, x + w, y + h], outline=O)


def moped(t=0.0, c="#e8473a", rider=None, frame=0):
    im = Image.new("RGBA", (44, 40), (0, 0, 0, 0))
    d = drw(im)
    for wx in (8, 34):
        E(d, wx - 6, 28, wx + 6, 39, "#1a1a20")
        E(d, wx - 2, 32, wx + 2, 35, "#8a8a98")
    d.polygon([(6, 30), (14, 22), (34, 22), (38, 30), (30, 32), (12, 32)], fill=c, outline=O)
    R(d, 32, 10, 34, 24, "#3a3a44")
    R(d, 30, 9, 38, 11, "#3a3a44")
    R(d, 14, 19, 28, 22, "#2a2a30")
    if rider:
        R(d, 16, 4, 26, 19, rider.get("top", "#3a6ad0"))
        E(d, 16, -2, 27, 8, "#f2d0b0", O)
        d.chord([15, -4, 28, 6], 180, 360, fill=rider.get("helmet", "#ffd25a"))
        R(d, 26, 10, 32, 12, rider.get("top", "#3a6ad0"))
    return im


def bunk_bed(d, x, y, w=60, h=90):
    R(d, x, y, x + 3, y + h, "#7a5a3a")
    R(d, x + w - 3, y, x + w, y + h, "#7a5a3a")
    for yy in (y + 30, y + h - 14):
        R(d, x + 3, yy, x + w - 3, yy + 6, "#3f6fc4")
        R(d, x + 3, yy + 6, x + w - 3, yy + 8, "#7a5a3a")
        E(d, x + 5, yy - 4, x + 18, yy + 3, "#f4f1ea", O)
    for k in range(5):
        R(d, x + w - 10, y + 4 + k * 8, x + w - 4, y + 5 + k * 8, "#7a5a3a")


def toilet(d, x, y, s=1.0):
    R(d, x + 2, y, x + 18, y + 12, "#f2f2f6")
    d.rectangle([x + 2, y, x + 18, y + 12], outline=O)
    E(d, x, y + 12, x + 24, y + 22, "#f2f2f6", O)
    R(d, x + 6, y + 22, x + 18, y + 30, "#e2e2ea")
    d.rectangle([x + 6, y + 22, x + 18, y + 30], outline=O)


def shower(d, x, y, t, on=True):
    R(d, x, y, x + 2, y + 50, "#b8bcc8")
    R(d, x, y, x + 14, y + 2, "#b8bcc8")
    E(d, x + 10, y, x + 20, y + 6, "#c8ccd8", O)
    if on:
        rnd = random.Random(int(t * 10))
        for _ in range(14):
            dx = rnd.randint(10, 22)
            dy = rnd.randint(8, 70)
            R(d, x + dx, y + dy, x + dx, y + dy + 2, "#9fd3ff")


def thermometer(d, x, y, val, c="#e8473a", label=""):
    R(d, x, y, x + 6, y + 60, P["white"])
    d.rectangle([x, y, x + 6, y + 60], outline=O)
    hh = int(56 * val)
    R(d, x + 2, y + 58 - hh, x + 4, y + 58, c)
    E(d, x - 3, y + 56, x + 9, y + 68, c, O)
    if label:
        ptext(d, x + 14, y + 20, label, 10, P["white"], shadow=O)


def coffee_cup(d, x, y, s=1, c="#2a5ad0"):
    d.polygon([(x, y), (x + 20 * s, y), (x + 17 * s, y + 26 * s), (x + 3 * s, y + 26 * s)], fill=P["white"], outline=O)
    R(d, x - 1, y - 4 * s, x + 21 * s, y, c)
    d.rectangle([x - 1, y - 4 * s, x + 21 * s, y], outline=O)
    E(d, x + 5 * s, y + 8 * s, x + 15 * s, y + 18 * s, c)


def bottle(d, x, y, h=40):
    R(d, x + 4, y, x + 10, y + 6, "#3a8ad0")
    R(d, x, y + 6, x + 14, y + h, "#bfe6ff")
    d.rectangle([x, y + 6, x + 14, y + h], outline=O)
    R(d, x, y + 16, x + 14, y + 24, "#3a8ad0")


def price_tag(d, x, y, text, c="#ffd25a", size=10):
    w = len(text) * size * 0.65 + 12
    d.polygon([(x, y), (x + w, y), (x + w + 8, y + 9), (x + w, y + 18), (x, y + 18)], fill=c, outline=O)
    ptext(d, x + w / 2 + 2, y + 9, text, size, O, anchor="mm")


def phone(d, x, y, w=60, h=110):
    R(d, x, y, x + w, y + h, "#111")
    R(d, x + 3, y + 8, x + w - 3, y + h - 8, "#f4f4f8")


def beach_bg(img, t, morning=False):
    d = drw(img)
    if morning:
        sky_day(d, 0, 150, "#ffb07a", "#ffe0b0")
        E(d, 70, 120, 110, 160, "#fff0a0")
    else:
        sky_day(d, 0, 150)
        E(d, 130, 20, 160, 50, "#fff2a0")
        clouds(d, t)
    for y in range(150, 210):
        R(d, 0, y, W - 1, y, "#2a8ac0" if (y + int(t * 8)) % 7 else "#6ab8e8")
    R(d, 0, 210, W - 1, H - 1, "#f2d090")
    rnd = random.Random(2)
    for _ in range(40):
        x, y = rnd.randint(0, W), rnd.randint(214, H)
        d.point((x, y), fill="#d8b070")
    return drw(img)


def hk_night(img, t):
    d = drw(img)
    skyline(d, 0, 0, W - 1, 200, t, seed=8)
    # высотки Гонконга — выше и с неоном
    for i, (x, w, h, c) in enumerate(((10, 22, 170, "#1e2250"), (40, 18, 130, "#252a5c"), (66, 26, 190, "#1b1e48"),
                                      (100, 20, 150, "#2a2f66"), (128, 30, 175, "#1e2250"), (160, 18, 120, "#252a5c"))):
        R(d, x, 200 - h, x + w, 200, c)
        for wy in range(200 - h + 4, 198, 5):
            for wx in range(x + 2, x + w - 2, 4):
                if (wx * 7 + wy * 3 + i) % 5:
                    R(d, wx, wy, wx + 1, wy + 1, "#ffd27a" if (wx + wy) % 3 else "#7ad8ff")
        if i % 2 == 0:
            R(d, x + 2, 200 - h + 10, x + w - 2, 200 - h + 14, ["#ff4a8a", "#4ad0ff", "#ffd25a"][i % 3])
    for y in range(200, 250):
        R(d, 0, y, W - 1, y, "#0e1a3a" if (y + int(t * 6)) % 5 else "#3a4a8a")
    R(d, 0, 250, W - 1, H - 1, "#2a2a34")
    return drw(img)


def spa_bg(img, t):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#3a2a2a")
    for x in range(0, W, 16):
        R(d, x, 0, x + 1, 230, "#4a3430")
    R(d, 0, 230, W - 1, H - 1, "#5a3a2a")
    glow(img, 40, 60, 40, (255, 190, 120), 40)
    glow(img, 140, 60, 40, (255, 190, 120), 40)
    d = drw(img)
    for x in (40, 140):
        E(d, x - 8, 50, x + 8, 70, "#e0302a", O)
        R(d, x - 5, 48, x + 5, 50, "#ffd25a")
        R(d, x - 5, 70, x + 5, 72, "#ffd25a")
    return d


# ================================================================ сцены, часть 1
def sc_plagin_wave(t, f, dur, handle=False):
    img = base()
    room_night(img, t)
    paste(img, plagin_bust("happy" if int(t * 2) % 3 else "neutral", t=t), 52, 116)
    d = drw(img)
    wave = int(math.sin(t * 10) * 4)
    E(d, 124 + wave, 140, 136 + wave, 152, P["skin"], O)
    for k in range(4):
        R(d, 125 + wave + k * 3, 132, 126 + wave + k * 3, 141, P["skin"])
    R(d, 118, 152, 128, 190, P["chk_b"])
    desk_front(d, 208)
    if handle:
        R(d, 30, 236, 150, 252, P["white"])
        d.rectangle([30, 236, 150, 252], outline="#3ad0e0")
        ptext(d, 40, 244, HANDLE, 9, "#222", anchor="lm")
    return img


def sc_plagin_wave2(t, f, dur):
    return sc_plagin_wave(t, f, dur, handle=True)


def sc_china_map(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#5ab0e0")
    rnd = random.Random(3)
    for _ in range(40):
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        R(d, x, y, x + 3, y, "#7ac8f0")
    # Россия сверху, Китай снизу
    d.polygon([(0, 30), (60, 20), (120, 34), (180, 24), (180, 110), (130, 120), (80, 104), (30, 118), (0, 100)],
              fill="#7ac070", outline=O)
    d.polygon([(40, 150), (100, 140), (150, 160), (160, 220), (120, 250), (70, 244), (36, 210)],
              fill="#e0b060", outline=O)
    ptext(d, 90, 70, "РОССИЯ", 12, P["white"], anchor="mm", shadow=O)
    ptext(d, 98, 200, "КИТАЙ", 12, P["white"], anchor="mm", shadow=O)
    flag_ru(d, 40, 76)
    flag_cn(d, 112, 206)
    k = ease(t / max(0.5, dur * 0.8))
    x0, y0, x1, y1 = 60, 90, 120, 230
    for i in range(int(k * 20)):
        q = i / 20
        R(d, lerp(x0, x1, q), lerp(y0, y1, q) - math.sin(q * math.pi) * 30, lerp(x0, x1, q) + 1,
          lerp(y0, y1, q) - math.sin(q * math.pi) * 30, P["red"])
    px, py = lerp(x0, x1, k), lerp(y0, y1, k) - math.sin(k * math.pi) * 30
    ptext(d, px, py, "✈", 14, P["white"], anchor="mm", shadow=O)
    return img


def sc_shenzhen_city(t, f, dur):
    img = base()
    d = drw(img)
    city_day(d, t, tall=True)
    ground(d)
    R(d, 30, 222, 150, 244, "#c0303a")
    d.rectangle([30, 222, 150, 244], outline=O)
    ptext(d, 90, 233, "ШЭНЬЧЖЭНЬ", 10, "#ffe680", anchor="mm")
    paste(img, plagin_mini(f // 4, "normal"), int(lerp(10, 60, ease(t / dur))), 250, 2)
    return img


def sc_birthday_cake(t, f, dur):
    img = base()
    sunburst(img, t, "#ff8ab0", "#ffb0cc")
    d = drw(img)
    R(d, 40, 170, 140, 230, "#f4e0c0")
    R(d, 40, 170, 140, 180, "#ff6a9a")
    d.rectangle([40, 170, 140, 230], outline=O)
    R(d, 54, 130, 126, 170, "#f4e0c0")
    R(d, 54, 130, 126, 138, "#ff6a9a")
    d.rectangle([54, 130, 126, 170], outline=O)
    ptext(d, 90, 154, "40", 18, P["red"], anchor="mm")
    for k in range(5):
        x = 62 + k * 14
        R(d, x, 112, x + 3, 130, ["#5ad0ff", "#ffd25a", "#7aff8a", "#ff8ad8", "#ffffff"][k])
        fl = int(math.sin(t * 12 + k) * 1)
        E(d, x - 1 + fl, 104, x + 4 + fl, 112, "#ffb030")
    ptext(d, 90, 60, "С ДНЁМ", 14, P["white"], anchor="mm", shadow=O)
    ptext(d, 90, 80, "РОЖДЕНИЯ!", 14, P["white"], anchor="mm", shadow=O)
    ptext(d, 90, 252, "(опять)", 10, P["white"], anchor="mm", shadow=O)
    confetti(d, t)
    return img


def sc_prof_40(t, f, dur):
    img = base()
    d = lecture_bg(img, t, front=True)
    ptext(d, 64, 40, "МАТАН", 10, P["chalk"], anchor="mm")
    ptext(d, 64, 60, "∫∫∫ dx dy dz", 8, P["chalk"], anchor="mm")
    paste(img, man_bust("neutral", t, bald=True, glasses=True), 52, 116)
    d = drw(img)
    desk_front(d, 212)
    R(d, 104, 160, 128, 176, "#ffd25a")
    d.rectangle([104, 160, 128, 176], outline=O)
    ptext(d, 116, 168, "40", 9, P["red"], anchor="mm")
    if t > dur * 0.5:
        bubble(d, 100, 100, 70, 20, "МНЕ 40!", 9)
    return img


def scroll(d, x, y, w=60, h=40, text="ДИПЛОМ", c="#f4ecd8", seal=P["red"]):
    R(d, x, y, x + w, y + h, c)
    d.rectangle([x, y, x + w, y + h], outline=O)
    for xx in (x - 4, x + w):
        R(d, xx, y - 2, xx + 4, y + h + 2, "#d8c8a0")
        d.rectangle([xx, y - 2, xx + 4, y + h + 2], outline=O)
    ptext(d, x + w // 2, y + 10, text, 7, O, anchor="mm")
    for k in range(3):
        R(d, x + 8, y + 18 + k * 5, x + w - 8, y + 18 + k * 5, "#b8a880")
    E(d, x + w - 14, y + h - 12, x + w - 4, y + h - 2, seal, O)


def sc_two_diplomas(t, f, dur):
    img = base()
    sunburst(img, t, "#3a5aa0", "#4a6ac0")
    d = drw(img)
    b1 = int(abs(math.sin(t * 4)) * 4)
    b2 = int(abs(math.sin(t * 4 + 1.5)) * 4)
    scroll(d, 18, 90 - b1, 64, 44, "МГУ")
    scroll(d, 100, 90 - b2, 64, 44, "ПЕКИН")
    flag_ru(d, 38, 60 - b1)
    flag_cn(d, 120, 60 - b2)
    paste(img, plagin_mini(0, "normal", walking=False), 68, 160, 2)
    d = drw(img)
    ptext(d, 90, 150, "×2", 14, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_x2_stats(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#1e2238")
    rows = [("ПАРЫ", "#3f71c9"), ("ДОМАШКА", "#8e5ad0"), ("ЭКЗАМЕНЫ", "#e8473a")]
    for i, (s, c) in enumerate(rows):
        k = ease((t - i * dur * 0.25) / 0.5)
        y = 50 + i * 60
        ptext(d, 20, y, s, 10, P["white"])
        R(d, 20, y + 16, 160, y + 32, "#2a3050")
        R(d, 20, y + 16, 20 + int(140 * min(1, k) * 0.5), y + 32, c)
        if k > 0.6:
            R(d, 20, y + 16, 20 + int(140 * min(1, k)), y + 32, c)
            ptext(d, 160, y, "×2", 12, "#ffe680", anchor="ra")
    paste(img, plagin_bust("tired", t=t).crop((0, 0, 76, 70)), 52, 230)
    return img


def sc_nerves_bar(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#2a1a24")
    ptext(d, 90, 50, "НЕРВЫ", 14, P["white"], anchor="mm", shadow=O)
    k = 1 - 0.5 * ease(t / 1.0)
    R(d, 20, 70, 160, 90, "#3a2a34")
    R(d, 20, 70, 20 + int(140 * k), 90, "#5ad068" if k > 0.6 else "#e8a020")
    d.rectangle([20, 70, 160, 90], outline=O)
    ptext(d, 90, 80, f"{int(k * 100)}%", 9, P["white"], anchor="mm")
    sx, sy = shake(t, 1, 30)
    paste(img, plagin_bust("tired", t=t), 52 + sx, 120 + sy)
    d = drw(img)
    # дёргающийся глаз
    if int(t * 6) % 2:
        ptext(d, 120, 130, "!", 12, "#ffe680", shadow=O)
    return img


def sc_game_show(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#1a1030")
    for i in range(10):
        x = i * 18 + 4
        on = (int(t * 8) + i) % 2
        E(d, x, 6, x + 8, 14, "#ffd25a" if on else "#8a6a20")
    R(d, 14, 26, 166, 76, "#3a1a5a")
    d.rectangle([14, 26, 166, 76], outline="#ffd25a", width=2)
    ptext(d, 90, 42, "СДОХНИ", 13, P["red"], anchor="mm", shadow=O)
    ptext(d, 90, 62, "ИЛИ УМРИ", 13, "#ffe680", anchor="mm", shadow=O)
    for x in (10, 150):
        d.polygon([(x, 80), (x + 20, 80), (x + 40, 240), (x - 20, 240)], fill=(255, 240, 180))
    paste(img, plagin_bust("happy", t=t), 52, 120)
    d = drw(img)
    # микрофон
    R(d, 112, 150, 114, 180, "#2a2a30")
    E(d, 108, 142, 118, 152, "#4a4a56", O)
    R(d, 30, 212, 150, 222, "#5a2a8a")
    R(d, 30, 222, 150, H - 1, "#3a1a5a")
    ptext(d, 90, 217, "ВЕДУЩИЙ", 7, "#ffe680", anchor="mm")
    return img


def sc_loh_choice(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#4a3a4a")
    R(d, 0, 230, W - 1, H - 1, "#3a2a2a")
    for i, (x, lab, c) in enumerate(((16, "1 ДИПЛОМ", "#6a8a6a"), (100, "2 ДИПЛОМА", "#8a4a3a"))):
        R(d, x, 80, x + 64, 230, c)
        d.rectangle([x, 80, x + 64, 230], outline=O)
        R(d, x + 50, 150, x + 54, 156, "#ffd25a")
        R(d, x + 4, 60, x + 60, 76, P["white"])
        ptext(d, x + 32, 68, lab, 7, O, anchor="mm")
    if t > dur * 0.5:
        stamp(img, "ЛОХ", 48, 150, dur * 0.5, t, size=14, angle=-14)
    paste(img, plagin_mini(0, "normal", walking=False), 118, 180, 2)
    return img


def sc_two_langs(t, f, dur):
    img = base()
    sunburst(img, t, "#6a2a3a", "#8a3a4a")
    d = drw(img)
    flag_ru(d, 16, 60, 44, 30)
    flag_cn(d, 120, 60, 44, 30)
    paste(img, plagin_bust("tired", t=t), 52, 120)
    d = drw(img)
    bubble(d, 8, 110, 50, 18, "БЛИН!", 8)
    bubble(d, 122, 110, 50, 18, "ДА ЛАН!", 8)
    for k in range(2):
        ph = (t * 1.3 + k * 0.5) % 1
        R(d, 70 + k * 36, 160 + int(ph * 20), 71 + k * 36, 163 + int(ph * 20), "#9fd3ff")
    return img


def photo_bg(img, t, c1="#2a2a44", c2="#4a3a6a"):
    d = drw(img)
    for y in range(H):
        R(d, 0, y, W - 1, y, blend(c1, c2, y / H))
    rnd = random.Random(4)
    for i in range(30):
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        if (int(t * 3) + i) % 5:
            d.point((x, y), fill="#8a8ab0")
    return d


def sc_photo_campus(t, f, dur):
    img = base()
    photo_bg(img, t, "#1e3a2a", "#3a6a4a")
    d = drw(img)
    ptext(d, 90, 34, "НАШ КАМПУС", 13, P["white"], anchor="mm", shadow=O)
    paste(img, plagin_mini(0, "o", walking=False), 130, 196, 2)
    return img


def sc_photo_skyscrapers(t, f, dur):
    img = base()
    photo_bg(img, t, "#1e2a4a", "#3a5a8a")
    paste(img, plagin_mini(0, "o", walking=False), 20, 196, 2)
    return img


def sc_photo_temples(t, f, dur):
    img = base()
    photo_bg(img, t, "#3a1a1a", "#7a2a2a")
    paste(img, plagin_mini(0, "normal", walking=False), 130, 196, 2)
    return img


def sc_photo_sea(t, f, dur):
    img = base()
    photo_bg(img, t, "#ffb07a", "#3a6aa0")
    return img


def sc_small_campus(t, f, dur):
    img = base()
    d = drw(img)
    sky_day(d, 0, 220)
    ground(d, 220, "#7aa060")
    # огромные китайские кампусы по бокам и наш маленький
    R(d, 0, 60, 50, 220, "#c8b8a0")
    R(d, 130, 40, 179, 220, "#c8b8a0")
    for x0 in (0, 130):
        for y in range(70, 210, 10):
            for x in range(x0 + 4, x0 + 46, 8):
                R(d, x, y, x + 4, y + 5, "#9ab4d0")
    R(d, 78, 196, 102, 220, "#e8d8c0")
    d.polygon([(76, 196), (90, 188), (104, 196)], fill="#c04a3a")
    R(d, 88, 210, 92, 220, "#5a3424")
    # лупа
    lx, ly = 90 + int(math.sin(t * 2) * 6), 200
    d.ellipse([lx - 22, ly - 22, lx + 22, ly + 22], outline="#3a3a44", width=3)
    d.line([(lx + 16, ly + 16), (lx + 32, ly + 32)], fill="#5a3424", width=4)
    ptext(d, 90, 100, "НАШ →", 10, P["white"], anchor="mm", shadow=O)
    return img


def sc_murino(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#e8e0d0")
    R(d, 0, 200, W - 1, H - 1, "#b8a890")
    # крошечная студия
    R(d, 60, 100, 120, 160, "#f4f4f8")
    d.rectangle([60, 100, 120, 160], outline=O)
    R(d, 64, 140, 84, 156, "#3f6fc4")
    R(d, 98, 136, 116, 156, "#8a8a98")
    R(d, 88, 104, 116, 124, "#9fd3ff")
    ptext(d, 90, 88, "СТУДИЯ 12 м²", 8, O, anchor="mm")
    ptext(d, 90, 70, "МУРИНО", 12, P["red"], anchor="mm")
    for i in range(4):
        pm = person_mini(0, walking=False, **PEOPLE[i])
        paste(img, pm, 6 + i * 44, 210, 1)
        d = drw(img)
        if int(t * 2 + i) % 3 == 0:
            ptext(d, 18 + i * 44, 196, "?", 10, P["red"], shadow=O)
    return img


def big_campus(d, x0, y0, w, h, c="#d8c8b0"):
    R(d, x0, y0, x0 + w, y0 + h, c)
    d.rectangle([x0, y0, x0 + w, y0 + h], outline=O)
    for y in range(y0 + 6, y0 + h - 4, 8):
        for x in range(x0 + 4, x0 + w - 4, 7):
            R(d, x, y, x + 3, y + 4, "#9ab4d0")


def sc_hku_campus(t, f, dur):
    img = base()
    d = drw(img)
    sky_day(d, 0, 230)
    ground(d, 230, "#6a9a5a")
    big_campus(d, 10, 60, 70, 170)
    big_campus(d, 90, 40, 80, 190, "#c8d0d8")
    R(d, 20, 30, 160, 48, "#2a5a8a")
    ptext(d, 90, 39, "ГОНКОНГСКИЙ УНИВЕР", 7, P["white"], anchor="mm")
    R(d, 82, 216, 92, 230, "#e8d8c0")  # наш — малыш
    ptext(d, 87, 210, "мы", 6, O, anchor="mm")
    return img


def sc_x10_campus(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#2a3a2a")
    k = ease(t / 1.0)
    for i in range(3):
        s = int(lerp(10, 46, k))
        x = 10 + i * 58
        R(d, x, 120 - s, x + s, 120 + s, ["#4a8a4a", "#5a9a5a", "#3a7a3a"][i])
        d.rectangle([x, 120 - s, x + s, 120 + s], outline=O)
        ptext(d, x + s // 2, 120, str(i + 1), 12, P["white"], anchor="mm")
    R(d, 84, 200, 94, 210, "#e8d8c0")
    d.rectangle([84, 200, 94, 210], outline=O)
    ptext(d, 89, 222, "наш", 7, P["white"], anchor="mm")
    ptext(d, 90, 60, "×10", 20, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_campus_bus(t, f, dur):
    img = base()
    d = drw(img)
    sky_day(d, 0, 200)
    clouds(d, t)
    R(d, 0, 200, W - 1, H - 1, "#6a9a5a")
    R(d, 0, 214, W - 1, 240, "#5a5a64")
    for x in range(-int(t * 60) % 30 - 30, W, 30):
        R(d, x, 226, x + 14, 227, P["white"])
    big_campus(d, 4, 120, 40, 80)
    big_campus(d, 140, 110, 36, 90, "#c8d0d8")
    x = int(lerp(-80, 120, (t / dur)))
    R(d, x, 186, x + 70, 226, "#ffd25a")
    d.rectangle([x, 186, x + 70, 226], outline=O)
    for k in range(5):
        R(d, x + 4 + k * 13, 192, x + 14 + k * 13, 204, "#9fd3ff")
    for wx in (x + 14, x + 56):
        E(d, wx - 7, 220, wx + 7, 234, "#1a1a20")
    ptext(d, 90, 60, "ОБЩАГА → УЧЕБКА", 9, P["white"], anchor="mm", shadow=O)
    ptext(d, 90, 76, "15 минут", 9, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_spit(t, f, dur):
    img = base()
    d = drw(img)
    sky_day(d, 0, 220)
    ground(d, 220, "#7aa060")
    R(d, 10, 100, 64, 220, "#e8d8c0")
    d.rectangle([10, 100, 64, 220], outline=O)
    ptext(d, 37, 92, "ОБЩАГА", 7, O, anchor="mm")
    R(d, 116, 100, 170, 220, "#d8c8b0")
    d.rectangle([116, 100, 170, 220], outline=O)
    ptext(d, 143, 92, "УЧЕБКА", 7, O, anchor="mm")
    paste(img, plagin_mini(0, "o", walking=False), 40, 64, 1)
    d = drw(img)
    k = (t % 1.4) / 1.0
    if k <= 1:
        x = lerp(56, 120, k)
        y = 76 - math.sin(k * math.pi) * 20 + k * 20
        E(d, x - 2, y - 2, x + 2, y + 2, "#bfe6ff", O)
    else:
        ptext(d, 128, 96, "ПЛЮХ", 7, "#3a6ad0", shadow=P["white"])
    ptext(d, 90, 150, "2 метра", 10, P["white"], anchor="mm", shadow=O)
    return img


def stall(d, x, y, title, c, icon):
    R(d, x, y + 10, x + 50, y + 70, "#f4f0e8")
    d.rectangle([x, y + 10, x + 50, y + 70], outline=O)
    for k in range(5):
        R(d, x + k * 10, y, x + k * 10 + 10, y + 10, c if k % 2 == 0 else P["white"])
    d.rectangle([x, y, x + 50, y + 10], outline=O)
    ptext(d, x + 25, y + 20, title, 7, c, anchor="mm")
    icon(d, x + 25, y + 46)


def _sandwich(d, x, y):
    R(d, x - 14, y - 4, x + 14, y + 4, "#e8b860")
    R(d, x - 12, y - 1, x + 12, y + 1, "#5ad068")
    R(d, x - 12, y + 1, x + 12, y + 2, P["red"])


def _burger(d, x, y):
    d.chord([x - 12, y - 10, x + 12, y + 6], 180, 360, fill="#e8a040")
    R(d, x - 12, y - 2, x + 12, y + 1, "#5a3020")
    R(d, x - 12, y + 2, x + 12, y + 5, "#e8a040")


def _coffee(d, x, y):
    coffee_cup(d, x - 9, y - 10, 1, "#2a7a4a")


def sc_food_court(t, f, dur):
    img = base()
    d = drw(img)
    sky_day(d, 0, 230)
    ground(d, 230, "#b8b0a0")
    stall(d, 4, 120, "САНДВИЧИ", "#2a8a3a", _sandwich)
    stall(d, 64, 120, "БУРГЕРЫ", "#d82a2a", _burger)
    stall(d, 124, 120, "КОФЕ", "#2a6a4a", _coffee)
    for i in range(3):
        paste(img, person_mini((f // 4 + i), **PEOPLE[i + 2]), int((i * 70 + t * 30) % 220) - 20, 220, 1)
    return img


def sc_luckin(t, f, dur):
    img = base()
    d = drw(img)
    sky_day(d, 0, 230, "#c8b090", "#e8d8b0")
    ground(d, 230, "#c8b090")
    R(d, 60, 150, 120, 230, "#f4f4f8")
    d.rectangle([60, 150, 120, 230], outline=O)
    R(d, 56, 140, 124, 152, "#2a4ab0")
    ptext(d, 90, 146, "КОФЕ", 7, P["white"], anchor="mm")
    coffee_cup(d, 80, 180, 1, "#2a4ab0")
    # перекати-поле
    x = int((t * 50) % 220) - 20
    d.ellipse([x, 236, x + 14, 250], outline="#8a6a3a", width=2)
    d.line([(x + 2, 240), (x + 12, 246)], fill="#8a6a3a")
    ptext(d, 90, 100, "...и всё.", 12, O, anchor="mm")
    return img


def sc_coffee_love(t, f, dur):
    img = base()
    sunburst(img, t, "#ff8ab0", "#ffb0cc")
    d = drw(img)
    paste(img, plagin_bust("happy", t=t), 30, 120)
    d = drw(img)
    coffee_cup(d, 108, 150, 2, "#2a4ab0")
    hearts(d, t, 90, 140, 6)
    return img


def dorm_bg(img, t):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#d8d0c0")
    R(d, 0, 240, W - 1, H - 1, "#a08060")
    R(d, 70, 30, 110, 80, "#9fd3ff")
    window_frame(d, 68, 28, 112, 82, 2)
    return d


def sc_dorm_room(t, f, dur):
    img = base()
    d = dorm_bg(img, t)
    bunk_bed(d, 4, 150, 64, 90)
    bunk_bed(d, 112, 150, 64, 90)
    R(d, 70, 120, 110, 240, "#8a6a4a")
    d.rectangle([70, 120, 110, 240], outline=O)
    R(d, 89, 120, 90, 240, O)
    ptext(d, 90, 104, "4 ЧЕЛ.", 9, P["red"], anchor="mm", shadow=P["white"])
    # головы соседей
    for (x, y) in ((10, 166), (118, 166), (10, 214), (118, 214)):
        E(d, x, y, x + 10, y + 9, P["skin"], O)
    return img


def sc_dorm_flip(t, f, dur):
    img = base()
    d = dorm_bg(img, t)
    ang = math.sin(t * 5) * 8
    tmp = Image.new("RGBA", (90, 110), (0, 0, 0, 0))
    td = drw(tmp)
    bunk_bed(td, 14, 10, 64, 90)
    E(td, 20, 26, 30, 35, P["skin"], O)
    E(td, 20, 74, 30, 83, P["skin"], O)
    tmp = tmp.rotate(ang, resample=Image.NEAREST, expand=True)
    paste(img, tmp, 40, 130)
    d = drw(img)
    ptext(d, 90, 100, "ВРУУМ", 10, P["red"], anchor="mm", shadow=P["white"])
    return img


def sc_balcony(t, f, dur):
    img = base()
    d = drw(img)
    skyline(d, 0, 0, W - 1, 160, t, seed=12)
    R(d, 0, 160, W - 1, H - 1, "#6a6a74")
    for x in range(0, W, 8):
        R(d, x, 170, x + 2, 210, "#b8bcc8")
    R(d, 0, 168, W - 1, 170, "#b8bcc8")
    toilet(d, 24, 206)
    shower(d, 120, 150, t)
    R(d, 116, 150, 118, 240, "#b8bcc8")
    if t > dur * 0.6:
        hearts(d, t, 90, 160, 6)
    return img


def sc_sweat(t, f, dur):
    img = base()
    sunburst(img, t, "#ff8a3a", "#ffb060")
    d = drw(img)
    thermometer(d, 14, 40, 0.95, label="35°")
    ptext(d, 120, 40, "100%", 14, "#3a6ad0", anchor="mm", shadow=P["white"])
    ptext(d, 120, 58, "влажность", 8, P["white"], anchor="mm", shadow=O)
    paste(img, plagin_bust("tired", t=t), 52, 120)
    d = drw(img)
    for k in range(6):
        ph = (t * 1.5 + k / 6) % 1
        x = 56 + (k * 13) % 70
        R(d, x, 130 + int(ph * 60), x + 1, 133 + int(ph * 60), "#9fd3ff")
    E(d, 30, 228, 150, 250, "#9fd3ff")
    return img


def sc_shower_loop(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#3a4a5a")
    shower(d, 60, 40, t)
    paste(img, plagin_mini(0, "tired", walking=False), 66, 96, 2)
    d = drw(img)
    a = t * 4
    d.arc([20, 60, 160, 240], math.degrees(a), math.degrees(a) + 270, fill="#ffe680", width=3)
    ptext(d, 90, 30, "ДУШ → ПОТ → ДУШ", 8, P["white"], anchor="mm", shadow=O)
    return img


def sc_winter_cold(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#2a3a5a")
    rnd = random.Random(5)
    for i in range(40):
        x = (rnd.randint(0, W) + math.sin(t + i) * 6) % W
        y = (rnd.randint(0, H) + t * 30) % H
        R(d, x, y, x + 1, y + 1, P["white"])
    thermometer(d, 14, 40, 0.3, "#3a8ad0", "16°")
    ptext(d, 130, 50, "= 0° МСК", 10, "#bfe6ff", anchor="mm", shadow=O)
    sx, sy = shake(t, 2, 50)
    b = plagin_bust("tired", t=t)
    paste(img, b, 52 + sx, 120 + sy)
    tint = Image.new("RGBA", img.size, (90, 140, 255, 40))
    img.alpha_composite(tint)
    return img


def sc_toilet_think(t, f, dur):
    img = base()
    d = drw(img)
    skyline(d, 0, 0, W - 1, 170, t, seed=12)
    R(d, 0, 170, W - 1, H - 1, "#5a5a64")
    for x in range(0, W, 8):
        R(d, x, 176, x + 2, 210, "#9a9ca8")
    toilet(d, 72, 216)
    paste(img, plagin_mini(0, "tired", walking=False).crop((0, 0, 24, 36)), 66, 150, 2)
    d = drw(img)
    for (x, y, r) in ((112, 140, 3), (120, 128, 5)):
        E(d, x - r, y - r, x + r, y + r, P["white"], O)
    E(d, 110, 70, 176, 120, P["white"], O)
    ptext(d, 143, 95, "НАХ*Я?", 10, O, anchor="mm")
    return img


# ================================================================ часть 2
def sc_city_tour(t, f, dur):
    img = base()
    d = drw(img)
    city_day(d, t, tall=True)
    ground(d)
    x = int(lerp(10, 70, ease(t / dur)))
    paste(img, plagin_mini(f // 4, "normal"), x, 220, 2)
    d = drw(img)
    R(d, x + 44, 190, x + 45, 236, "#5a3424")
    d.polygon([(x + 45, 190), (x + 64, 196), (x + 45, 202)], fill=P["red"], outline=O)
    return img


def sc_ad_tv(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#3a2a3a")
    R(d, 10, 50, 170, 180, "#1a1a20")
    R(d, 16, 56, 164, 174, "#7ac8f0")
    dd = d
    for x0 in range(16, 164, 16):
        h = 40 + (x0 * 7) % 60
        R(dd, x0, 174 - h, x0 + 12, 174, "#5a7898")
    for k in range(6):
        ph = (t * 2 + k / 6) % 1
        ptext(d, 26 + k * 24, 70 + int(ph * 10), "✦", 9, "#fff2b0")
    R(d, 60, 180, 120, 190, "#1a1a20")
    ptext(d, 90, 30, "РЕКЛАМА", 12, "#ffe680", anchor="mm", shadow=O)
    ptext(d, 90, 210, "*в реальности", 8, "#c8c8d0", anchor="mm")
    ptext(d, 90, 222, "больше людей", 8, "#c8c8d0", anchor="mm")
    return img


def crowd_draw(img, t, f, n=40, seed=6):
    d = drw(img)
    rnd = random.Random(seed)
    items = []
    for i in range(n):
        x = rnd.randint(-10, W - 10)
        y = rnd.randint(130, 290)
        items.append((y, x, i))
    for y, x, i in sorted(items):
        p = PEOPLE[i % len(PEOPLE)]
        paste(img, person_mini(f // 4 + i, **p), x + int(math.sin(t * 2 + i) * 3), y - 56, 1)


def sc_crowd(t, f, dur, tuesday=False):
    img = base()
    d = drw(img)
    city_day(d, t, 140)
    R(d, 0, 140, W - 1, H - 1, "#a8a8b0")
    crowd_draw(img, t, f)
    d = drw(img)
    sx, sy = shake(t, 1, 30)
    paste(img, plagin_mini(0, "o", walking=False), 80 + sx, 200 + sy, 2)
    d = drw(img)
    if tuesday:
        R(d, 110, 20, 170, 70, P["white"])
        R(d, 110, 20, 170, 32, P["red"])
        d.rectangle([110, 20, 170, 70], outline=O)
        ptext(d, 140, 26, "ОБЫЧНЫЙ", 6, P["white"], anchor="mm")
        ptext(d, 140, 50, "ВТОРНИК", 8, O, anchor="mm")
    else:
        ptext(d, 120, 190, "!!!", 14, P["red"], shadow=O)
    return img


def sc_crowd_tuesday(t, f, dur):
    return sc_crowd(t, f, dur, tuesday=True)


def street_bg(img, t):
    d = drw(img)
    city_day(d, t, 140)
    R(d, 0, 140, W - 1, H - 1, "#5a5a64")
    for y in (180, 240):
        for x in range(-int(t * 40) % 24 - 24, W, 24):
            R(d, x, y, x + 12, y + 1, P["white"])
    return d


def sc_mopeds(t, f, dur, n=6, swarm=False):
    img = base()
    street_bg(img, t)
    rnd = random.Random(9)
    cols = ["#e8473a", "#3a6ad0", "#2a8a3a", "#e8a020", "#8a4ad0", "#f2f2f2"]
    for i in range(n if not swarm else 16):
        y = 150 + rnd.randint(0, 130)
        sp = rnd.uniform(40, 110) * (1 if i % 2 else -1)
        x = (rnd.randint(0, 300) + t * sp) % 260 - 40
        m = moped(t, cols[i % 6], dict(top=cols[(i + 2) % 6], helmet=cols[(i + 3) % 6]))
        if sp < 0:
            m = m.transpose(Image.FLIP_LEFT_RIGHT)
        paste(img, m, x, y - 30 + int(math.sin(t * 7 + i) * 4))
    d = drw(img)
    if swarm:
        R(d, 120, 40, 172, 90, P["white"])
        d.rectangle([120, 40, 172, 90], outline=O)
        ptext(d, 146, 54, "у нас:", 7, O, anchor="mm")
        R(d, 140, 64, 142, 84, "#2a2a30")
        R(d, 136, 64, 150, 66, "#2a2a30")
        E(d, 136, 82, 142, 88, "#2a2a30")
        E(d, 146, 82, 152, 88, "#2a2a30")
        ptext(d, 70, 60, "тут:", 10, P["white"], anchor="mm", shadow=O)
    return img


def sc_mopeds_swarm(t, f, dur):
    return sc_mopeds(t, f, dur, swarm=True)


def sc_traffic_rules(t, f, dur):
    img = base()
    street_bg(img, t)
    d = drw(img)
    for i, (x, title, lines) in enumerate(((8, "ДЛЯ КИТАЙЦЕВ", ["едь как хочешь", "красный = совет", "тротуар = дорога"]),
                                           (94, "ДЛЯ ОСТАЛЬНЫХ", ["стой", "жди", "молись"]))):
        R(d, x + 36, 110, x + 40, 160, "#5a5a64")
        paper(d, x, 30, x + 78, 112, None, bg="#f4f1e6")
        R(d, x + 1, 31, x + 77, 44, "#2a5a8a" if i == 0 else P["red"])
        ptext(d, x + 39, 38, title, 6, P["white"], anchor="mm")
        for k, s in enumerate(lines):
            ptext(d, x + 6, 52 + k * 18, s, 7, O)
    m = moped(t, "#e8473a", dict(top="#3a6ad0"))
    paste(img, m, (t * 90) % 240 - 40, 200)
    return img


def sc_moped_foot(t, f, dur):
    img = base()
    street_bg(img, t)
    d = drw(img)
    hit = t > dur * 0.55
    paste(img, plagin_mini(0, "o" if hit else "normal", walking=False), 60, 160, 2)
    k = min(1.0, t / (dur * 0.55))
    m = moped(t, "#3a6ad0", dict(top="#c0303a"))
    paste(img, m, lerp(-50, 60, k) if not hit else 60 + (t - dur * 0.55) * 120, 236)
    d = drw(img)
    if not hit:
        ptext(d, 30, 200, "...", 12, P["white"], shadow=O)
        ptext(d, 120, 140, "тихо", 8, P["white"], shadow=O)
    else:
        star_burst(d, 84, 262, 14)
        ptext(d, 84, 262, "АЙ", 7, O, anchor="mm")
    return img


def sc_beach_clean(t, f, dur):
    img = base()
    beach_bg(img, t)
    d = drw(img)
    for k in range(5):
        ph = (t * 1.5 + k / 5) % 1
        ptext(d, 20 + k * 34, 230 - int(ph * 10), "✦", 9, P["white"])
    paste(img, plagin_mini(f // 4, "normal"), int(lerp(20, 110, ease(t / dur))), 220, 2)
    return img


def sc_beach_soup(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#f2d090")
    E(d, 6, 110, 174, 260, "#f4f4f8", O)
    E(d, 16, 120, 164, 200, "#e8a040")
    for k in range(4):
        ph = (t + k / 4) % 1
        x = 40 + k * 30
        d.arc([x, 80 - int(ph * 20), x + 10, 110 - int(ph * 20)], 90, 270, fill=P["white"], width=2)
    paste(img, plagin_bust("happy", t=t).crop((0, 0, 76, 56)), 52, 108)
    d = drw(img)
    E(d, 16, 150, 164, 200, "#e8a040")
    R(d, 120, 40, 124, 170, "#c8a070")
    R(d, 132, 40, 136, 170, "#c8a070")
    return img


def sc_beach_empty(t, f, dur):
    img = base()
    beach_bg(img, t, morning=True)
    paste(img, plagin_mini(0, "normal", walking=False), 76, 210, 2)
    d = drw(img)
    ptext(d, 90, 40, "7:00", 14, P["white"], anchor="mm", shadow=O)
    hearts(d, t, 90, 200, 3)
    return img


def sc_beach_jump(t, f, dur):
    img = base()
    beach_bg(img, t)
    for i in range(4):
        hop = int(abs(math.sin(t * 5 + i)) * 26)
        pm = person_mini(0, walking=False, arm_up=True, **PEOPLE[i])
        paste(img, pm, 10 + i * 42, 210 - hop, 1)
    d = drw(img)
    phone(d, 120, 230, 40, 70)
    E(d, 132, 256, 148, 272, "#2a2a34", O)
    if int(t * 4) % 3 == 0:
        star_burst(d, 140, 228, 10, P["white"])
    return img


def sc_beach_covered(t, f, dur):
    img = base()
    beach_bg(img, t)
    d = drw(img)
    # зонт
    d.chord([40, 120, 140, 180], 180, 360, fill="#e8473a", outline=O)
    R(d, 89, 150, 91, 240, "#5a3424")
    pm = person_mini(0, walking=False, hair="#141418", top="#5a5a8a", pants="#2a2a44")
    paste(img, pm, 60, 168, 2)
    d = drw(img)
    # шляпа + маска
    d.chord([56, 166, 112, 186], 180, 360, fill="#e8d8a0", outline=O)
    R(d, 74, 186, 94, 194, P["white"])
    # пчёлы
    for k in range(3):
        a = t * 3 + k * 2
        x = 90 + 50 * math.cos(a)
        y = 200 + 20 * math.sin(a * 1.3)
        E(d, x - 3, y - 2, x + 3, y + 2, "#ffd25a", O)
        R(d, x - 1, y - 2, x, y + 2, O)
    ptext(d, 90, 100, "ПАСЕКА?", 10, P["white"], anchor="mm", shadow=O)
    return img


def jelly(d, x, y, t, c="#ff8ad8"):
    d.chord([x - 16, y - 14, x + 16, y + 10], 180, 360, fill=c, outline=O)
    for k in range(5):
        xx = x - 12 + k * 6
        wob = int(math.sin(t * 6 + k) * 2)
        R(d, xx + wob, y - 2, xx + wob + 1, y + 16, c)
    R(d, x - 6, y - 8, x - 4, y - 6, O)
    R(d, x + 4, y - 8, x + 6, y - 6, O)


def sc_jellyfish(t, f, dur):
    img = base()
    d = drw(img)
    for y in range(H):
        R(d, 0, y, W - 1, y, blend("#2a6ac0", "#0a2a5a", y / H))
    jelly(d, 90 + int(math.sin(t * 2) * 30), 150 + int(math.sin(t * 3) * 10), t)
    paste(img, person_mini(0, walking=False, expr="o", **PEOPLE[1]), 70, 220, 2)
    d = drw(img)
    ptext(d, 120, 90, "!!!", 14, P["red"], shadow=O)
    return img


def sc_jelly_no(t, f, dur):
    img = base()
    beach_bg(img, t)
    d = drw(img)
    E(d, 40, 60, 140, 160, P["white"], O)
    jelly(d, 90, 112, t)
    d.ellipse([40, 60, 140, 160], outline=P["red"], width=6)
    d.line([(56, 76), (124, 144)], fill=P["red"], width=6)
    if t > dur * 0.5:
        R(d, 66, 190, 114, 230, "#3a8ad0")
        d.polygon([(66, 190), (114, 190), (114, 214), (90, 236), (66, 214)], fill="#3a8ad0", outline=O)
        ptext(d, 90, 208, "✓", 14, P["white"], anchor="mm")
    return img


# ================================================================ часть 3
def sc_hk_border(t, f, dur):
    img = base()
    d = drw(img)
    sky_day(d, 0, 230)
    ground(d, 230, "#a8a8b0")
    R(d, 20, 90, 160, 230, "#d8d8e0")
    d.rectangle([20, 90, 160, 230], outline=O)
    R(d, 20, 70, 160, 92, "#2a5a8a")
    ptext(d, 90, 81, "ГРАНИЦА", 10, P["white"], anchor="mm")
    for k in range(3):
        R(d, 36 + k * 40, 130, 64 + k * 40, 230, "#8a9ab0")
    flag_cn(d, 4, 40)
    R(d, 152, 40, 176, 56, "#de2910")
    E(d, 159, 43, 169, 53, P["white"])
    paste(img, plagin_mini(f // 4, "normal"), int(lerp(0, 90, ease(t / dur))), 220, 2)
    return img


def sc_hk_skyline(t, f, dur, love=True):
    img = base()
    hk_night(img, t)
    d = drw(img)
    paste(img, plagin_mini(0, "normal", walking=False), 76, 210, 2)
    d = drw(img)
    if love:
        hearts(d, t, 90, 200, 6)
    ptext(d, 90, 270, "ГОНКОНГ", 12, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_hk_skyline2(t, f, dur):
    return sc_hk_skyline(t, f, dur, love=True)


def sc_hk_cockroach(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#3a3a44")
    R(d, 0, 210, W - 1, H - 1, "#5a5a64")
    phone(d, 30, 110, 50, 100)
    x = 100 + int(math.sin(t * 3) * 6)
    E(d, x, 120, x + 50, 210, "#6a3a1a", O)
    E(d, x + 14, 104, x + 36, 124, "#5a2a14", O)
    d.line([(x + 25, 124), (x + 25, 206)], fill="#3a1a0a")
    for k in range(3):
        y = 140 + k * 22
        wig = int(math.sin(t * 20 + k) * 3)
        d.line([(x, y), (x - 14, y - 6 + wig)], fill=O, width=2)
        d.line([(x + 50, y), (x + 64, y - 6 - wig)], fill=O, width=2)
    d.line([(x + 18, 106), (x + 4, 80)], fill=O, width=1)
    d.line([(x + 32, 106), (x + 46, 80)], fill=O, width=1)
    ptext(d, 90, 50, "1 : 1", 18, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_hk_people(t, f, dur):
    img = base()
    hk_night(img, t)
    pm = person_mini(0, walking=False, hair="#2a1a14", top="#2a2f55", pants="#23233a")
    paste(img, pm, 30, 190, 2)
    d = drw(img)
    R(d, 52, 228, 54, 246, P["red"])
    bubble(d, 70, 150, 100, 30, "HELLO! HOW ARE U?", 7)
    return img


def sc_phone_translate(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#2a2a3a")
    phone(d, 36, 30, 108, 220)
    R(d, 40, 38, 140, 58, "#3a8ad0")
    ptext(d, 90, 48, "ПЕРЕВОДЧИК", 8, P["white"], anchor="mm")
    R(d, 46, 70, 134, 110, "#e8e8f0")
    ptext(d, 90, 80, "где туалет?", 8, O, anchor="mm")
    n = min(3, int(t * 3))
    ptext(d, 90, 98, "→ " + "...".ljust(3)[:n], 8, "#3a8ad0", anchor="mm")
    R(d, 46, 120, 134, 160, "#d8f0c8")
    ptext(d, 90, 132, "HELLO", 12, "#2a8a3a", anchor="mm")
    ptext(d, 90, 150, "(весь англ.)", 7, "#555", anchor="mm")
    E(d, 76, 200, 104, 228, P["red"], O)
    R(d, 88, 206, 92, 218, P["white"])
    return img


def sc_smalltalk(t, f, dur):
    img = base()
    hk_night(img, t)
    paste(img, plagin_mini(0, "normal", walking=False), 20, 200, 2)
    paste(img, person_mini(0, walking=False, hair="#2a1a14", top="#8a3a3a"), 112, 200, 2)
    d = drw(img)
    if int(t * 1.5) % 2 == 0:
        bubble(d, 10, 160, 70, 22, "NICE WEATHER!", 6)
    else:
        bubble(d, 100, 160, 70, 22, "YEAH, MATE!", 6)
    return img


def sc_menu_point(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#5a3a2a")
    paper(d, 14, 30, 166, 230, "МЕНЮ", title_bg="#c0303a")
    for i in range(4):
        y = 56 + i * 42
        E(d, 24, y, 60, y + 32, "#f4f4f8", O)
        E(d, 30, y + 6, 54, y + 26, ["#e8a040", "#c04a3a", "#5ad068", "#e8d080"][i])
        R(d, 70, y + 8, 150, y + 10, "#8a8070")
        R(d, 70, y + 18, 130, y + 20, "#8a8070")
    k = (t * 0.8) % 1
    fy = 70 + int(k * 3) * 42
    E(d, 100, fy, 120, fy + 20, P["skin"], O)
    R(d, 84, fy + 6, 100, fy + 10, P["skin"])
    d.rectangle([84, fy + 6, 100, fy + 10], outline=O)
    if t > dur * 0.6:
        ptext(d, 150, 250, "*кивок*", 9, "#ffe680", anchor="mm", shadow=O)
    return img


def wallet(d, x, y, t, cry=True):
    R(d, x, y, x + 60, y + 40, "#6a3a1a")
    d.rectangle([x, y, x + 60, y + 40], outline=O)
    R(d, x + 40, y + 14, x + 60, y + 26, "#8a5a2a")
    R(d, x + 14, y + 12, x + 18, y + 16, O)
    R(d, x + 28, y + 12, x + 32, y + 16, O)
    if cry:
        for k in range(2):
            ph = (t * 2 + k * 0.5) % 1
            R(d, x + 15 + k * 14, y + 18 + int(ph * 30), x + 16 + k * 14, y + 21 + int(ph * 30), "#9fd3ff")
        d.arc([x + 14, y + 24, x + 32, y + 34], 200, 340, fill=O)


def sc_hk_expensive(t, f, dur):
    img = base()
    hk_night(img, t)
    d = drw(img)
    wallet(d, 60, 140, t)
    for k in range(5):
        ph = (t + k / 5) % 1
        x = 70 + int(math.sin(k * 2 + t) * 30)
        y = 140 - int(ph * 100)
        R(d, x, y, x + 12, y + 6, "#7ac070")
        d.rectangle([x, y, x + 12, y + 6], outline=O)
    ptext(d, 90, 40, "$$$", 18, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_water_price(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, 89, H - 1, "#c0303a")
    R(d, 90, 0, W - 1, H - 1, "#2a2a4a")
    ptext(d, 45, 40, "КИТАЙ", 10, P["white"], anchor="mm", shadow=O)
    ptext(d, 135, 40, "ГОНКОНГ", 10, P["white"], anchor="mm", shadow=O)
    bottle(d, 38, 90, 50)
    bottle(d, 128, 90, 50)
    price_tag(d, 20, 160, "¥2")
    if t > dur * 0.4:
        price_tag(d, 102, 160, "HK$25", "#ff8a8a")
        star_burst(d, 160, 150, 8)
    return img


def sc_noodles_vs_water(t, f, dur):
    img = base()
    sunburst(img, t, "#c0303a", "#e0503a")
    d = drw(img)
    E(d, 10, 130, 90, 180, "#f4f4f8", O)
    E(d, 16, 134, 84, 160, "#e8a040")
    for k in range(5):
        d.arc([20 + k * 10, 128, 34 + k * 10, 150], 180, 360, fill="#f2d080")
    R(d, 60, 90, 62, 150, "#c8a070")
    R(d, 68, 90, 70, 150, "#c8a070")
    ptext(d, 50, 196, "обед", 9, P["white"], anchor="mm", shadow=O)
    ptext(d, 90, 150, "=", 18, "#ffe680", anchor="mm", shadow=O)
    bottle(d, 124, 120, 50)
    ptext(d, 131, 196, "вода", 9, P["white"], anchor="mm", shadow=O)
    ptext(d, 90, 60, "×10", 22, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_wallet_cry(t, f, dur):
    img = base()
    sunburst(img, t, "#3a5aa0", "#4a6ac0")
    d = drw(img)
    wallet(d, 20, 160, t, cry=t > dur * 0.5)
    paste(img, plagin_mini(0, "normal", walking=False), 110, 160, 2)
    d = drw(img)
    thumbs(d, 150, 190)
    return img


def sc_spa_enter(t, f, dur):
    img = base()
    spa_bg(img, t)
    d = drw(img)
    R(d, 30, 90, 150, 230, "#7a4428")
    d.rectangle([30, 90, 150, 230], outline=O)
    R(d, 36, 100, 144, 230, "#ffd9a0")
    R(d, 40, 80, 140, 98, "#c0303a")
    ptext(d, 90, 89, "SPA 24 ЧАСА", 8, "#ffe680", anchor="mm")
    paste(img, plagin_mini(f // 4, "normal"), int(lerp(-10, 70, ease(t / dur))), 222, 2)
    return img


def sc_spa_price(t, f, dur):
    img = base()
    spa_bg(img, t)
    d = drw(img)
    R(d, 24, 100, 156, 190, "#ffd25a")
    d.rectangle([24, 100, 156, 190], outline=O)
    for y in range(104, 188, 8):
        E(d, 20, y, 28, y + 4, "#3a2a2a")
        E(d, 152, y, 160, y + 4, "#3a2a2a")
    ptext(d, 90, 116, "БИЛЕТ", 9, O, anchor="mm")
    ptext(d, 90, 142, "¥300", 18, P["red"], anchor="mm")
    ptext(d, 90, 170, "24 ЧАСА", 10, O, anchor="mm")
    return img


def sc_massage(t, f, dur, sleep=False):
    img = base()
    spa_bg(img, t)
    d = drw(img)
    R(d, 14, 200, 166, 212, "#f4f1ea")
    R(d, 20, 212, 26, 260, "#5a3424")
    R(d, 154, 212, 160, 260, "#5a3424")
    b = plagin_bust("sleep" if sleep or t > dur * 0.5 else "happy", "nodrool", t)
    b = b.rotate(90, resample=Image.NEAREST, expand=True)
    paste(img, b, 20, 130)
    d = drw(img)
    R(d, 14, 200, 166, 212, "#f4f1ea")
    R(d, 60, 190, 166, 204, "#f4f1ea")
    # руки массажиста
    for k in range(2):
        y = 180 + int(abs(math.sin(t * 6 + k)) * 6)
        E(d, 90 + k * 30, y, 106 + k * 30, y + 12, "#e0a882", O)
    if sleep:
        zzz(d, 60, 150, t)
        ptext(d, 90, 60, "ЛУЧШИЙ СОН", 10, "#ffe680", anchor="mm", shadow=O)
        ptext(d, 90, 76, "ЗА СЕМЕСТР", 10, "#ffe680", anchor="mm", shadow=O)
    else:
        ptext(d, 90, 70, "90 МИН", 14, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_spa_sleep(t, f, dur):
    return sc_massage(t, f, dur, sleep=True)


def sc_spa_fun(t, f, dur):
    img = base()
    spa_bg(img, t)
    d = drw(img)
    # бильярд
    R(d, 6, 196, 96, 240, "#2a7a3a")
    d.rectangle([6, 196, 96, 240], outline="#5a3424", width=3)
    for k, c in enumerate(("#ffd25a", P["red"], "#3a6ad0", P["white"])):
        E(d, 30 + k * 12, 214 + (k % 2) * 6, 36 + k * 12, 220 + (k % 2) * 6, c)
    # аркада
    R(d, 116, 120, 166, 240, "#4a2a8a")
    d.rectangle([116, 120, 166, 240], outline=O)
    c = ["#5ad0ff", "#ff5a8a", "#7aff8a"][int(t * 4) % 3]
    R(d, 122, 130, 160, 170, c)
    ptext(d, 141, 150, "GAME", 7, O, anchor="mm")
    R(d, 130, 186, 132, 196, "#1a1a20")
    E(d, 128, 182, 134, 188, P["red"])
    # шведский стол
    for k in range(4):
        E(d, 10 + k * 26, 100, 32 + k * 26, 112, "#f4f4f8", O)
        E(d, 14 + k * 26, 102, 28 + k * 26, 108, ["#e8a040", "#c04a3a", "#5ad068", "#e8d080"][k])
    ptext(d, 56, 88, "ШВЕДСКИЙ СТОЛ", 7, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_spa_home(t, f, dur):
    img = base()
    spa_bg(img, t)
    d = drw(img)
    R(d, 50, 80, 130, 100, P["white"])
    d.rectangle([50, 80, 130, 100], outline=O)
    ptext(d, 90, 90, "МОЙ ДОМ", 10, P["red"], anchor="mm")
    x = int(lerp(-20, 60, ease(t / dur)))
    paste(img, person_mini(f // 4, hair=P["hair"], top="#f4f4f8", pants="#f4f4f8"), x, 180, 2)
    d = drw(img)
    R(d, x + 44, 216, x + 70, 236, "#c09060")
    d.rectangle([x + 44, 216, x + 70, 236], outline=O)
    ptext(d, x + 57, 226, "вещи", 6, O, anchor="mm")
    return img


# ================================================================ заставки
def sc_outro_china(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#121220")
    im, a = agent(40, "happy", f, arms="up")
    paste(img, im, 62, 70 + int(abs(math.sin(t * 4)) * 4))
    d = drw(img)
    ptext(d, 90, 140, "Plaginstory", 16, P["white"], anchor="mm", shadow="#ff4a6a")
    R(d, 20, 170, 160, 188, P["white"])
    d.rectangle([20, 170, 160, 188], outline="#3ad0e0")
    n = min(len(HANDLE), int(t * 8))
    ptext(d, 28, 179, HANDLE[:n] + ("|" if int(t * 3) % 2 else ""), 9, "#222", anchor="lm")
    ptext(d, 90, 214, "ПОДПИШИСЬ ↓", 10, P["ag_lt"], anchor="mm")
    return img


def _tbc(n):
    def fn(t, f, dur):
        img = base()
        sunburst(img, t, "#1a1a2e", "#26264a")
        d = drw(img)
        pop = ease(t / 0.25)
        ptext(d, 90, 70, "ПРОДОЛЖЕНИЕ", int(lerp(8, 15, pop)), P["white"], anchor="mm", shadow="#ff4a6a")
        ptext(d, 90, 96, f"В ЧАСТИ {n}", 13, P["ag_lt"], anchor="mm", shadow=O)
        ptext(d, 90 + int(math.sin(t * 8) * 6), 124, "→", 22, "#ffe680", anchor="mm", shadow=O)
        paste(img, plagin_mini(0, "o", walking=False), 68, 146, 2)
        d = drw(img)
        R(d, 30, 268, 150, 284, P["white"])
        d.rectangle([30, 268, 150, 284], outline="#3ad0e0")
        ptext(d, 38, 276, HANDLE, 9, "#222", anchor="lm")
        return img
    return fn


def _ptitle(n, sub):
    def fn(t, f, dur):
        img = base()
        sunburst(img, t * 2, "#e8662a", "#ff9a4a")
        d = drw(img)
        k = ease(t / 0.3)
        ptext(d, 90, 74, "ЧАСТЬ", 16, P["white"], anchor="mm", shadow=O)
        ptext(d, 90, 112, str(n), int(lerp(20, 48, k)), "#ffe680", anchor="mm", shadow=O)
        ptext(d, 90, 150, sub, 11, P["white"], anchor="mm", shadow=O)
        paste(img, plagin_mini(0, "normal", walking=False), 68, 170, 2)
        return img
    return fn


sc_tbc2 = _tbc(2)
sc_tbc3 = _tbc(3)
sc_ptitle2 = _ptitle(2, "ГОРОД И МОРЕ")
sc_ptitle3 = _ptitle(3, "ГОНКОНГ И СПА")

SCENE_FUNCS = {k[3:]: v for k, v in globals().items() if k.startswith("sc_")}
art.SCENE_FUNCS.update(SCENE_FUNCS)
