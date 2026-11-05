# -*- coding: utf-8 -*-
"""Плагин v2 (по новому фото): лохматые рыжевато-русые волосы, рыжая борода,
серо-голубые глаза, румяные щёки, белая футболка.

Импорт этого модуля ПОДМЕНЯЕТ art.plagin_bust / art.plagin_mini.
Импортировать до art2/art3, чтобы они подхватили новый спрайт.
"""
import random

from PIL import Image

import art
from art import P, R, E, drw

O = P["out"]
HAIR = "#d39a5c"
HAIR_DK = "#a8703a"
HAIR_LT = "#f2c98e"
BEARD = "#c27c44"
BEARD_DK = "#9a5a2e"
SKIN = "#f2c2a8"
SKIN_SH = "#dc9a84"
RED = "#e89488"
IRIS = "#7f9cb4"
TEE = "#f6f5f2"
TEE_SH = "#d4d2da"


def _messy_hair(d, cx, ty, t, fringe=True):
    rnd = random.Random(7)
    # объём
    d.chord([cx - 20, ty - 2, cx + 20, ty + 32], 180, 360, fill=O)
    d.chord([cx - 19, ty - 1, cx + 19, ty + 31], 180, 360, fill=HAIR)
    # торчащие пряди сверху
    for i in range(9):
        x = cx - 16 + i * 4
        h = rnd.randint(3, 8)
        sway = 1 if (i + int(t * 2)) % 4 == 0 else 0
        d.polygon([(x - 2, ty + 4), (x + 2, ty + 4), (x + 1 + sway, ty - h), (x - 1 + sway, ty - h + 1)], fill=HAIR)
        d.point((x + sway, ty - h), fill=HAIR_LT)
    # пряди-текстура
    for _ in range(60):
        x = rnd.randint(cx - 17, cx + 17)
        y = rnd.randint(ty, ty + 13)
        if ((x - cx) / 18.5) ** 2 + ((y - (ty + 15)) / 15.5) ** 2 < 1:
            d.line([(x, y), (x + rnd.choice((-2, 2)), y + 2)], fill=HAIR_DK if rnd.random() < 0.5 else HAIR_LT)
    # бока
    R(d, cx - 19, ty + 14, cx - 15, ty + 26, HAIR)
    R(d, cx + 15, ty + 14, cx + 19, ty + 24, HAIR)
    if fringe:
        # чёлка набок: падает на лоб слева направо
        d.polygon([(cx - 16, ty + 14), (cx + 8, ty + 12), (cx + 4, ty + 20), (cx - 2, ty + 18),
                   (cx - 8, ty + 23), (cx - 13, ty + 20)], fill=HAIR)
        d.line([(cx - 10, ty + 16), (cx - 6, ty + 22)], fill=HAIR_DK)
        d.line([(cx - 2, ty + 15), (cx, ty + 19)], fill=HAIR_DK)
        d.line([(cx + 3, ty + 14), (cx + 5, ty + 17)], fill=HAIR_LT)


def plagin_bust(expr="neutral", pose="rest", t=0.0, blink=True):
    im = Image.new("RGBA", (76, 100), (0, 0, 0, 0))
    d = drw(im)
    cx, ty = 38, 4
    sy = ty + 52
    # футболка
    E(d, cx - 33, sy, cx + 33, sy + 70, O)
    E(d, cx - 32, sy + 1, cx + 32, sy + 69, TEE)
    E(d, cx + 8, sy + 6, cx + 32, sy + 69, TEE_SH)
    E(d, cx - 32, sy + 1, cx + 24, sy + 69, TEE)
    # шея + ворот
    R(d, cx - 7, ty + 40, cx + 7, sy + 4, SKIN_SH)
    E(d, cx - 10, sy - 3, cx + 10, sy + 7, "#e2e0e6")
    E(d, cx - 8, sy - 3, cx + 8, sy + 4, SKIN_SH)
    # уши
    E(d, cx - 20, ty + 22, cx - 13, ty + 33, SKIN_SH, O)
    E(d, cx + 13, ty + 22, cx + 20, ty + 33, SKIN_SH, O)
    # лицо (шире, с тенью справа)
    E(d, cx - 17, ty + 6, cx + 17, ty + 47, SKIN_SH, O)
    E(d, cx - 17, ty + 6, cx + 14, ty + 45, SKIN)
    # борода по контуру челюсти + подбородок
    d.chord([cx - 17, ty + 14, cx + 17, ty + 48], 10, 170, fill=BEARD)
    E(d, cx - 12, ty + 30, cx + 12, ty + 42, SKIN)
    rnd = random.Random(3)
    for _ in range(40):
        x = rnd.randint(cx - 15, cx + 15)
        y = rnd.randint(ty + 34, ty + 47)
        if im.getpixel((x, y))[:3] == tuple(int(BEARD[i:i + 2], 16) for i in (1, 3, 5)):
            d.point((x, y), fill=BEARD_DK)
    # усы
    d.polygon([(cx - 7, ty + 37), (cx, ty + 35), (cx + 7, ty + 37), (cx + 6, ty + 39), (cx, ty + 37),
               (cx - 6, ty + 39)], fill=BEARD)
    # волосы
    _messy_hair(d, cx, ty, t)
    blink_now = blink and expr not in ("sleep", "happy") and (t % 3.1) > 2.95
    # брови (рыжие, светлые)
    by = ty + 21
    if expr in ("o", "yell"):
        by -= 3
    if expr == "tired":
        by += 1
    if expr == "angry":
        d.line([(cx - 11, by), (cx - 5, by + 2)], fill=BEARD, width=2)
        d.line([(cx + 5, by + 2), (cx + 11, by)], fill=BEARD, width=2)
    elif expr == "smirk":
        R(d, cx - 11, by + 1, cx - 5, by + 2, BEARD)
        R(d, cx + 5, by - 1, cx + 11, by, BEARD)
    else:
        R(d, cx - 11, by, cx - 5, by + 1, BEARD)
        R(d, cx + 5, by, cx + 11, by + 1, BEARD)
    # глаза
    ey = ty + 25
    for sx in (-1, 1):
        x0 = cx - 11 if sx < 0 else cx + 4
        if expr == "sleep" or blink_now:
            d.line([(x0, ey + 3), (x0 + 1, ey + 4), (x0 + 5, ey + 4), (x0 + 6, ey + 3)], fill=O)
        elif expr == "happy":
            d.line([(x0, ey + 4), (x0 + 1, ey + 2), (x0 + 5, ey + 2), (x0 + 6, ey + 4)], fill=O)
        elif expr == "tired":
            R(d, x0, ey + 2, x0 + 6, ey + 5, P["eye_w"])
            R(d, x0, ey + 1, x0 + 6, ey + 2, SKIN_SH)
            R(d, x0, ey + 2, x0 + 6, ey + 2, O)
            R(d, x0 + 2, ey + 3, x0 + 4, ey + 5, IRIS)
            d.point((x0 + 3, ey + 4), fill=P["pupil"])
            R(d, x0, ey + 7, x0 + 6, ey + 7, "#d49aa4")
        elif expr in ("o", "yell"):
            R(d, x0 - 1, ey - 1, x0 + 7, ey + 6, P["eye_w"])
            R(d, x0 - 1, ey - 2, x0 + 7, ey - 2, O)
            R(d, x0 + 2, ey + 1, x0 + 4, ey + 4, IRIS)
            R(d, x0 + 3, ey + 2, x0 + 3, ey + 3, P["pupil"])
        else:
            R(d, x0, ey, x0 + 6, ey + 4, P["eye_w"])
            R(d, x0, ey - 1, x0 + 6, ey - 1, O)
            R(d, x0 + 2, ey + 1, x0 + 5, ey + 4, IRIS)
            R(d, x0 + 3, ey + 2, x0 + 4, ey + 3, P["pupil"])
            d.point((x0 + 2, ey + 1), fill=P["white"])
    # нос (крупнее, румяный)
    R(d, cx + 1, ty + 28, cx + 2, ty + 33, SKIN_SH)
    E(d, cx - 3, ty + 31, cx + 4, ty + 35, "#eaa898")
    # румянец
    R(d, cx - 15, ty + 30, cx - 9, ty + 34, RED)
    R(d, cx + 8, ty + 30, cx + 12, ty + 34, RED)
    # рот
    my = ty + 40
    if expr == "o":
        E(d, cx - 4, my - 3, cx + 4, my + 5, P["lip"])
        E(d, cx - 2, my - 1, cx + 2, my + 3, P["mouth"])
    elif expr == "yell":
        E(d, cx - 6, my - 3, cx + 6, my + 6, P["mouth"], O)
        R(d, cx - 3, my + 3, cx + 3, my + 5, P["tongue"])
        R(d, cx - 4, my - 2, cx + 4, my - 2, P["white"])
    elif expr == "happy":
        d.line([(cx - 6, my - 1), (cx - 4, my + 2), (cx + 4, my + 2), (cx + 6, my - 1)], fill=O)
        R(d, cx - 3, my + 1, cx + 3, my + 1, P["mouth"])
    elif expr == "smirk":
        d.line([(cx - 4, my + 1), (cx + 3, my + 1), (cx + 6, my - 1)], fill=O)
    elif expr == "sleep":
        E(d, cx - 2, my, cx + 2, my + 3, P["mouth"])
        if pose != "nodrool":
            dl = int((t * 3) % 4)
            R(d, cx + 2, my + 3, cx + 2, my + 4 + dl, "#bfe6ff")
    elif expr == "tired":
        d.line([(cx - 4, my + 1), (cx + 4, my)], fill=O)
    else:  # нейтрально: пухлые губы
        R(d, cx - 4, my, cx + 4, my + 1, "#e08a8a")
        R(d, cx - 4, my, cx + 4, my, "#b05a5a")
    if pose == "finger":
        hx, hy = cx + 24, ty + 46
        d.polygon([(cx + 22, sy + 20), (cx + 30, sy + 22), (hx + 6, hy + 4), (hx - 2, hy + 4)], fill=TEE, outline=O)
        E(d, hx - 3, hy - 4, hx + 6, hy + 6, SKIN, O)
        R(d, hx + 1, hy - 16, hx + 3, hy - 4, SKIN)
        R(d, hx, hy - 16, hx, hy - 4, O)
        R(d, hx + 4, hy - 16, hx + 4, hy - 4, O)
        R(d, hx + 1, hy - 17, hx + 3, hy - 17, O)
    elif pose == "hands":
        for hx in (cx - 22, cx + 14):
            E(d, hx - 1, 90, hx + 9, 99, SKIN, O)
    return im


def plagin_mini(frame=0, expr="tired", walking=True):
    im = Image.new("RGBA", (22, 56), (0, 0, 0, 0))
    d = drw(im)
    ph = frame % 4 if walking else 0
    y = 1 if ph in (1, 3) else 0
    legs = {0: (-2, 2), 1: (0, 0), 2: (2, -2), 3: (0, 0)}[ph]
    for i, dx in enumerate(legs):
        lx = 6 + i * 6 + dx
        R(d, lx, 34 + y, lx + 4, 48, P["jeans"])
        R(d, lx, 34 + y, lx, 48, P["jeans_dk"])
        R(d, lx - 1, 49, lx + 5, 51, P["shoe"])
        R(d, lx - 1, 51, lx + 5, 51, "#9aa0b0")
    R(d, 4, 18 + y, 17, 35 + y, TEE)
    R(d, 14, 18 + y, 17, 35 + y, TEE_SH)
    sw = {0: 2, 1: 0, 2: -2, 3: 0}[ph]
    for side, s in ((2, sw), (18, -sw)):
        R(d, side - 1, 19 + y, side + 1, 24 + y, TEE)
        R(d, side - 1, 25 + y, side + 1, 32 + y + s // 2, SKIN)
    # голова: лицо, борода, лохматые волосы
    E(d, 4, 4 + y, 17, 17 + y, SKIN, O)
    d.chord([4, 6 + y, 17, 18 + y], 10, 170, fill=BEARD)
    R(d, 8, 12 + y, 13, 13 + y, SKIN)
    d.chord([3, 0 + y, 18, 14 + y], 180, 360, fill=HAIR)
    for i in range(5):
        x = 4 + i * 3
        R(d, x, -1 + y + (i % 2), x + 1, 1 + y, HAIR)
    R(d, 5, 6 + y, 11, 7 + y, HAIR)  # чёлка набок
    d.point((7, 3 + y), fill=HAIR_LT)
    d.point((12, 2 + y), fill=HAIR_DK)
    if expr == "tired":
        R(d, 7, 10 + y, 9, 10 + y, O)
        R(d, 12, 10 + y, 14, 10 + y, O)
    elif expr == "o":
        R(d, 7, 9 + y, 8, 10 + y, O)
        R(d, 12, 9 + y, 13, 10 + y, O)
        E(d, 9, 12 + y, 11, 15 + y, P["mouth"])
    else:
        R(d, 8, 9 + y, 8, 10 + y, O)
        R(d, 13, 9 + y, 13, 10 + y, O)
    return im


art.plagin_bust = plagin_bust
art.plagin_mini = plagin_mini
