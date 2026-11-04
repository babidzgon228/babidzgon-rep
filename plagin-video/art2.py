# -*- coding: utf-8 -*-
"""Новые сцены и персонажи для длинной версии ролика."""
import math
import random

from PIL import Image, ImageDraw

import art
from art import (P, W, H, R, E, drw, ptext, paste, lerp, ease, checker, glow, light_cone, zzz, bubble,
                 hearts, sunburst, agent, plagin_bust, plagin_mini, room_night, lecture_bg, bedroom_bg,
                 corridor_bg, uni_building, monitor, keyboard, mug, window_frame, fish, base)

O = P["out"]


# ================================================================ helpers
def paper(d, x0, y0, x1, y1, title=None, title_bg="#2a5a8a", bg="#f4f1e6"):
    R(d, x0 + 2, y0 + 2, x1 + 2, y1 + 2, "#00000055")
    R(d, x0, y0, x1, y1, bg)
    d.rectangle([x0, y0, x1, y1], outline=O)
    if title:
        R(d, x0 + 1, y0 + 1, x1 - 1, y0 + 16, title_bg)
        ptext(d, (x0 + x1) // 2, y0 + 9, title, 9, P["white"], anchor="mm")


def stamp(img, text, x, y, t_in, t, color=None, angle=12, size=12, w=None):
    """Печать, которая «падает» на бумагу."""
    if t < t_in:
        return
    color = color or P["red"]
    k = ease((t - t_in) / 0.15)
    w = w or (len(text) * size * 0.72 + 14)
    st = Image.new("RGBA", (int(w) + 6, size + 16), (0, 0, 0, 0))
    sd = drw(st)
    sd.rectangle([2, 2, st.width - 3, st.height - 3], outline=color, width=2)
    ptext(sd, st.width // 2, st.height // 2, text, size, color, anchor="mm")
    st = st.rotate(angle, resample=Image.NEAREST, expand=True)
    if k < 1:
        sc = 1.6 - 0.6 * k
        st = st.resize((max(1, int(st.width * sc)), max(1, int(st.height * sc))), Image.NEAREST)
    paste(img, st, x - st.width // 2, y - st.height // 2)


def floor_and_wall(img, wall="#5a4a6a", floor="#4a3a3e", fy=230):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, wall)
    R(d, 0, fy, W - 1, H - 1, floor)
    R(d, 0, fy, W - 1, fy + 2, "#2a1e24")
    return d


def desk_front(d, y=212):
    R(d, 0, y, W - 1, y + 5, P["wood_lt"])
    R(d, 0, y + 6, W - 1, H - 1, P["wood"])
    for yy in range(y + 14, H, 9):
        R(d, 0, yy, W - 1, yy, P["wood_dk"])


def shake(t, amp=2, speed=40):
    return int(math.sin(t * speed) * amp), int(math.cos(t * speed * 1.3) * amp)


def confetti(d, t, n=30, seed=4):
    rnd = random.Random(seed)
    cols = ["#ff5a5a", "#ffd25a", "#5ad0ff", "#7aff8a", "#ff8ad8", "#ffffff"]
    for i in range(n):
        x0 = rnd.randint(0, W)
        sp = rnd.uniform(30, 70)
        y = (rnd.randint(0, H) + t * sp) % (H + 20) - 10
        x = x0 + math.sin(t * 3 + i) * 6
        c = cols[i % len(cols)]
        if (int(t * 8) + i) % 2:
            R(d, x, y, x + 2, y + 1, c)
        else:
            R(d, x, y, x + 1, y + 2, c)


def star_burst(d, x, y, r, c="#ffe680"):
    pts = []
    for i in range(16):
        a = i * math.pi / 8
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
    d.polygon(pts, fill=c, outline=O)


def night_overlay(img, a=110):
    img.alpha_composite(Image.new("RGBA", img.size, (10, 12, 50, a)))


def chalkboard(d, x0, y0, x1, y1):
    R(d, x0 - 3, y0 - 3, x1 + 3, y1 + 3, P["wood_dk"])
    R(d, x0, y0, x1, y1, P["board"])
    R(d, x0 + 1, y0 + 1, x1 - 1, y0 + 4, "#33644f")


# ================================================================ sprites
def person_mini(frame=0, hair="#1c1c22", top="#c03a3a", pants="#2a355c", glasses=False, expr="normal",
                walking=True, scarf=None, skin=None, arm_up=False, backpack=None):
    im = Image.new("RGBA", (24, 56), (0, 0, 0, 0))
    d = drw(im)
    skin = skin or P["skin"]
    ph = frame % 4 if walking else 0
    y = 1 if ph in (1, 3) else 0
    legs = {0: (-2, 2), 1: (0, 0), 2: (2, -2), 3: (0, 0)}[ph]
    for i, dx in enumerate(legs):
        lx = 7 + i * 6 + dx
        R(d, lx, 34 + y, lx + 4, 48, pants)
        R(d, lx - 1, 49, lx + 5, 51, "#e8e8ee")
    if backpack:
        R(d, 2, 19 + y, 6, 31 + y, backpack)
    R(d, 5, 18 + y, 18, 35 + y, top)
    R(d, 15, 18 + y, 18, 35 + y, art.blend(top, "#000000", 0.25))
    sw = {0: 2, 1: 0, 2: -2, 3: 0}[ph]
    R(d, 3, 19 + y, 5, 30 + y + sw // 2, top)
    R(d, 3, 31 + y + sw // 2, 5, 33 + y + sw // 2, skin)
    if arm_up:
        R(d, 18, 6 + y, 20, 20 + y, top)
        R(d, 18, 3 + y, 20, 6 + y, skin)
    else:
        R(d, 18, 19 + y, 20, 30 + y - sw // 2, top)
        R(d, 18, 31 + y - sw // 2, 20, 33 + y - sw // 2, skin)
    E(d, 5, 3 + y, 18, 17 + y, skin, O)
    if scarf:
        d.chord([3, 0 + y, 20, 18 + y], 180, 360, fill=scarf)
        R(d, 3, 9 + y, 5, 16 + y, scarf)
        R(d, 18, 9 + y, 20, 16 + y, scarf)
        for k in range(3):
            d.point((7 + k * 4, 4 + y), fill=P["white"])
    else:
        d.chord([4, 1 + y, 19, 15 + y], 180, 360, fill=hair)
        R(d, 4, 7 + y, 5, 11 + y, hair)
        R(d, 18, 7 + y, 19, 11 + y, hair)
    if glasses:
        d.rectangle([7, 8 + y, 10, 11 + y], outline=O)
        d.rectangle([13, 8 + y, 16, 11 + y], outline=O)
        R(d, 11, 9 + y, 12, 9 + y, O)
    if expr == "sleep":
        R(d, 8, 10 + y, 10, 10 + y, O)
        R(d, 13, 10 + y, 15, 10 + y, O)
    elif expr == "o":
        R(d, 8, 9 + y, 9, 10 + y, O)
        R(d, 14, 9 + y, 15, 10 + y, O)
        E(d, 10, 12 + y, 13, 15 + y, P["mouth"])
    else:
        R(d, 9, 9 + y, 9, 10 + y, O)
        R(d, 14, 9 + y, 14, 10 + y, O)
        R(d, 10, 14 + y, 13, 14 + y, P["skin_sh"])
    return im


def man_bust(expr="neutral", t=0.0, hair="#c8c8d0", bald=True, glasses=True, mustache=True,
             suit="#6a4a34", tie="#9a2a2a", skin=None):
    """Пожилой мужчина (препод/декан) по пояс, 76x100."""
    im = Image.new("RGBA", (76, 100), (0, 0, 0, 0))
    d = drw(im)
    cx, ty = 38, 6
    skin = skin or "#e8b898"
    sy = ty + 50
    E(d, cx - 34, sy, cx + 34, sy + 74, O)
    E(d, cx - 33, sy + 1, cx + 33, sy + 73, suit)
    d.polygon([(cx - 9, sy), (cx + 9, sy), (cx + 5, 99), (cx - 5, 99)], fill="#f2f0ea")
    d.polygon([(cx - 3, sy + 4), (cx + 3, sy + 4), (cx + 4, sy + 34), (cx, sy + 40), (cx - 4, sy + 34)], fill=tie)
    R(d, cx - 6, ty + 40, cx + 6, sy + 4, "#c99a7e")
    # уши
    E(d, cx - 20, ty + 20, cx - 13, ty + 32, "#d9a486", O)
    E(d, cx + 13, ty + 20, cx + 20, ty + 32, "#d9a486", O)
    E(d, cx - 16, ty + 2, cx + 16, ty + 44, "#d9a486", O)
    E(d, cx - 16, ty + 2, cx + 13, ty + 42, skin)
    if bald:
        R(d, cx - 6, ty + 5, cx - 2, ty + 7, "#f6d4bc")  # блик на лысине
        for sx in (-1, 1):
            x0 = cx - 17 if sx < 0 else cx + 12
            R(d, x0, ty + 14, x0 + 5, ty + 24, hair)
    else:
        d.chord([cx - 17, ty, cx + 17, ty + 30], 180, 360, fill=hair)
    # брови
    by = ty + 18
    if expr == "squint":
        d.line([(cx - 12, by - 2), (cx - 4, by)], fill="#8a8a90", width=2)
        R(d, cx + 4, by + 1, cx + 12, by + 2, "#8a8a90")
    else:
        R(d, cx - 12, by - (2 if expr == "laugh" else 0), cx - 4, by + 1 - (2 if expr == "laugh" else 0), "#9a9aa0")
        R(d, cx + 4, by - (2 if expr == "laugh" else 0), cx + 12, by + 1 - (2 if expr == "laugh" else 0), "#9a9aa0")
    ey = ty + 23
    for x0 in (cx - 11, cx + 4):
        if expr == "laugh" or expr == "sleep":
            d.line([(x0, ey + 3), (x0 + 3, ey + 1 if expr == "laugh" else ey + 4), (x0 + 6, ey + 3)], fill=O)
        elif expr == "squint" and x0 < cx:
            R(d, x0, ey + 2, x0 + 6, ey + 3, O)
        else:
            R(d, x0 + 1, ey + 1, x0 + 5, ey + 4, P["white"])
            R(d, x0 + 2, ey + 2, x0 + 4, ey + 4, P["pupil"])
    if glasses:
        d.rectangle([cx - 13, ey - 1, cx - 2, ey + 6], outline="#2a2a30")
        d.rectangle([cx + 2, ey - 1, cx + 13, ey + 6], outline="#2a2a30")
        R(d, cx - 2, ey + 1, cx + 2, ey + 1, "#2a2a30")
        if int(t * 2) % 3 == 0:
            R(d, cx - 11, ey, cx - 9, ey, P["white"])
    R(d, cx + 1, ty + 28, cx + 2, ty + 33, "#c99a7e")
    my = ty + 36
    if mustache:
        d.polygon([(cx - 9, my + 1), (cx, my - 2), (cx + 9, my + 1), (cx + 7, my + 3), (cx, my + 1), (cx - 7, my + 3)],
                  fill="#b8b8c0", outline="#8a8a90")
    if expr == "laugh":
        E(d, cx - 6, my + 3, cx + 6, my + 9, P["mouth"], O)
        R(d, cx - 4, my + 3, cx + 4, my + 4, P["white"])
    elif expr == "sleep":
        E(d, cx - 2, my + 3, cx + 2, my + 6, P["mouth"])
    else:
        R(d, cx - 4, my + 5, cx + 4, my + 5, O)
    return im


def dean_mini(frame=0, walking=True):
    im = Image.new("RGBA", (26, 60), (0, 0, 0, 0))
    d = drw(im)
    ph = frame % 4 if walking else 0
    y = 1 if ph in (1, 3) else 0
    legs = {0: (-2, 2), 1: (0, 0), 2: (2, -2), 3: (0, 0)}[ph]
    for i, dx in enumerate(legs):
        lx = 8 + i * 6 + dx
        R(d, lx, 38 + y, lx + 4, 53, "#23233a")
        R(d, lx - 1, 54, lx + 5, 56, "#111")
    R(d, 4, 20 + y, 21, 39 + y, "#2a2f55")
    R(d, 10, 20 + y, 15, 30 + y, "#f2f0ea")
    R(d, 12, 21 + y, 13, 33 + y, P["red"])
    E(d, 2, 33 + y, 23, 42 + y, "#2a2f55")  # животик
    R(d, 2, 21 + y, 4, 34 + y, "#2a2f55")
    R(d, 21, 21 + y, 23, 34 + y, "#2a2f55")
    E(d, 6, 3 + y, 19, 19 + y, "#e8b898", O)
    R(d, 5, 9 + y, 7, 13 + y, "#c8c8d0")
    R(d, 18, 9 + y, 20, 13 + y, "#c8c8d0")
    d.point((10, 5 + y), fill="#fbe0cc")
    R(d, 9, 10 + y, 10, 11 + y, O)
    R(d, 15, 10 + y, 16, 11 + y, O)
    R(d, 8, 14 + y, 17, 15 + y, "#b8b8c0")
    return im


def vacuum(t=0.0, acc=(), s=1.0):
    """Робот-пылесос (вид сбоку-сверху) с аксессуарами: cap, scarf, bag, diploma."""
    im = Image.new("RGBA", (60, 50), (0, 0, 0, 0))
    d = drw(im)
    bob = int(abs(math.sin(t * 8)) * 1)
    y0 = 24 - bob
    E(d, 6, y0 + 4, 54, y0 + 22, "#1c1c22", O)
    E(d, 6, y0, 54, y0 + 16, "#3a3a46", O)
    E(d, 12, y0 + 2, 48, y0 + 12, "#55556a")
    E(d, 22, y0 + 3, 38, y0 + 9, "#6a6a80")
    # «глаза»-светодиоды
    blink = int(t * 2) % 7 == 0
    for ex in (20, 36):
        if blink:
            R(d, ex, y0 + 12, ex + 3, y0 + 12, "#5ad0ff")
        else:
            R(d, ex, y0 + 11, ex + 3, y0 + 13, "#5ad0ff")
    # щёточка
    ang = t * 20
    for k in range(3):
        a = ang + k * 2.1
        d.line([(8, y0 + 18), (8 + 6 * math.cos(a), y0 + 18 + 3 * math.sin(a))], fill="#9a9aa8")
    if "scarf" in acc:
        d.chord([10, y0 - 10, 50, y0 + 14], 180, 360, fill="#c0304a")
        for k in range(5):
            d.point((16 + k * 7, y0 - 3 + (k % 2) * 2), fill=P["white"])
        d.polygon([(46, y0 + 2), (54, y0 + 8), (48, y0 + 9)], fill="#c0304a", outline=O)
        d.rectangle([17, y0 + 9, 25, y0 + 15], outline=O)
        d.rectangle([33, y0 + 9, 41, y0 + 15], outline=O)
        R(d, 26, y0 + 11, 32, y0 + 11, O)
    if "cap" in acc:
        d.polygon([(14, y0 - 6), (30, y0 - 12), (46, y0 - 6), (30, y0)], fill="#1a1a22", outline=O)
        R(d, 24, y0 - 6, 36, y0 + 1, "#1a1a22")
        R(d, 44, y0 - 6, 45, y0 + 6, "#ffd25a")
        R(d, 43, y0 + 6, 46, y0 + 8, "#ffd25a")
    return im


def cat(t=0.0, pose="sit", c="#f0a050", glasses=False):
    im = Image.new("RGBA", (34, 30), (0, 0, 0, 0))
    d = drw(im)
    dk = art.blend(c, "#000000", 0.3)
    if pose == "sleep":
        E(d, 2, 14, 32, 28, c, O)
        E(d, 20, 10, 32, 22, c, O)
        d.polygon([(21, 12), (23, 6), (26, 11)], fill=c, outline=O)
        d.polygon([(27, 11), (30, 6), (31, 12)], fill=c, outline=O)
        R(d, 23, 16, 25, 16, O)
        R(d, 28, 16, 30, 16, O)
        for k in range(3):
            R(d, 6 + k * 5, 16, 7 + k * 5, 24, dk)
        d.arc([0, 12, 14, 30], 90, 270, fill=dk, width=2)
        return im
    # сидит
    E(d, 6, 12, 28, 29, c, O)
    E(d, 8, 2, 26, 18, c, O)
    d.polygon([(9, 6), (10, -1), (15, 4)], fill=c, outline=O)
    d.polygon([(19, 4), (24, -1), (25, 6)], fill=c, outline=O)
    R(d, 11, 9, 12, 11, O)
    R(d, 21, 9, 22, 11, O)
    d.point((16, 13), fill="#e87a8a")
    R(d, 2, 12, 8, 12, "#ffffff80")
    R(d, 26, 12, 32, 12, "#ffffff80")
    if glasses:
        d.rectangle([9, 8, 14, 12], outline=O)
        d.rectangle([19, 8, 24, 12], outline=O)
    for k in range(3):
        R(d, 10 + k * 5, 18, 11 + k * 5, 24, dk)
    tail = int(math.sin(t * 4) * 3)
    d.line([(27, 26), (32, 20 + tail)], fill=c, width=3)
    if pose == "paw":
        R(d, 24, 4, 28, 14, c)
        E(d, 23, 1, 29, 6, c, O)
    return im


def alarm_char(t=0.0, s=44, tie=True, mustache=True, ringing=False, expr="normal", frame=0, walk=False):
    """Будильник-персонаж."""
    im = Image.new("RGBA", (s + 24, s + 30), (0, 0, 0, 0))
    d = drw(im)
    cx = im.width // 2
    sx, sy = (int(math.sin(t * 60) * 2), 0) if ringing else (0, 0)
    top = 10
    r = s // 2
    # ножки
    ph = frame % 4 if walk else 0
    fl = -2 if ph == 1 else 0
    fr = -2 if ph == 3 else 0
    R(d, cx - r // 2 - 2 + sx, top + s - 2 + fl, cx - r // 2 + 2 + sx, top + s + 8 + fl, "#3a2a2a")
    R(d, cx + r // 2 - 2 + sx, top + s - 2 + fr, cx + r // 2 + 2 + sx, top + s + 8 + fr, "#3a2a2a")
    # колокольчики
    tilt = int(math.sin(t * 50) * 3) if ringing else 0
    for bx in (cx - r + 4, cx + r - 4):
        E(d, bx - 7 + sx + tilt, top - 6, bx + 7 + sx + tilt, top + 6, "#e8c040", O)
    R(d, cx - 1 + sx, top - 8, cx + 1 + sx, top, "#3a2a2a")
    E(d, cx - r + sx, top, cx + r + sx, top + s, "#d8443a", O)
    E(d, cx - r + 5 + sx, top + 5, cx + r - 5 + sx, top + s - 5, "#fbf6ea")
    for k in range(12):
        a = k * math.pi / 6
        px = cx + sx + (r - 8) * math.cos(a)
        py = top + r + (r - 8) * math.sin(a)
        d.point((px, py), fill="#555")
    # стрелки
    a1 = t * 2
    d.line([(cx + sx, top + r), (cx + sx + (r - 12) * math.cos(a1), top + r + (r - 12) * math.sin(a1))], fill="#333")
    # лицо
    ey = top + r - 6
    if expr == "sleep":
        R(d, cx - 9 + sx, ey + 2, cx - 4 + sx, ey + 2, O)
        R(d, cx + 4 + sx, ey + 2, cx + 9 + sx, ey + 2, O)
    elif expr == "dizzy":
        for ex in (cx - 7, cx + 7):
            d.line([(ex - 2 + sx, ey), (ex + 2 + sx, ey + 4)], fill=O)
            d.line([(ex + 2 + sx, ey), (ex - 2 + sx, ey + 4)], fill=O)
    else:
        R(d, cx - 8 + sx, ey, cx - 6 + sx, ey + 4, O)
        R(d, cx + 6 + sx, ey, cx + 8 + sx, ey + 4, O)
        if expr == "proud":
            R(d, cx - 10 + sx, ey - 3, cx - 4 + sx, ey - 3, O)
            R(d, cx + 4 + sx, ey - 3, cx + 10 + sx, ey - 3, O)
    if mustache:
        d.polygon([(cx - 10 + sx, ey + 9), (cx + sx, ey + 6), (cx + 10 + sx, ey + 9), (cx + 6 + sx, ey + 11),
                   (cx + sx, ey + 9), (cx - 6 + sx, ey + 11)], fill="#3a2a22")
    if ringing or expr == "yell":
        E(d, cx - 4 + sx, ey + 11, cx + 4 + sx, ey + 17, P["mouth"], O)
    if tie:
        d.polygon([(cx - 3 + sx, top + s - 4), (cx + 3 + sx, top + s - 4), (cx + 5 + sx, top + s + 8),
                   (cx + sx, top + s + 11), (cx - 5 + sx, top + s + 8)], fill="#2a4ea0", outline=O)
    if ringing:
        for k in range(3):
            a = -math.pi / 2 + (k - 1) * 0.7
            d.line([(cx + 20 * math.cos(a) * 1.4, top + 4 + 20 * math.sin(a)),
                    (cx + 26 * math.cos(a) * 1.4, top + 4 + 26 * math.sin(a))], fill="#ffe680", width=2)
    return im


def sash(d, box, text, c="#c0304a"):
    x0, y0, x1, y1 = box
    d.polygon([(x0, y0), (x0 + 7, y0), (x1, y1 - 7), (x1, y1)], fill=c, outline=O)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    ptext(d, cx, cy, text, 5, "#ffe680", anchor="mm")


def crown(d, x, y, w=16):
    d.polygon([(x, y + 8), (x, y), (x + w // 4, y + 5), (x + w // 2, y - 2), (x + 3 * w // 4, y + 5), (x + w, y),
               (x + w, y + 8)], fill="#ffd25a", outline=O)
    d.point((x + w // 2, y + 3), fill=P["red"])


def thumbs(d, x, y):
    E(d, x, y, x + 10, y + 10, P["skin"], O)
    R(d, x + 3, y - 7, x + 6, y, P["skin"])
    d.rectangle([x + 3, y - 8, x + 6, y], outline=O)
    R(d, x + 4, y - 7, x + 5, y, P["skin"])


def speed_lines(d, t, c="#ffffff", n=14, cx=W // 2, cy=150):
    rnd = random.Random(int(t * 12))
    for i in range(n):
        a = rnd.uniform(0, 2 * math.pi)
        r0 = rnd.uniform(70, 100)
        r1 = r0 + rnd.uniform(30, 80)
        d.line([(cx + r0 * math.cos(a), cy + r0 * math.sin(a)), (cx + r1 * math.cos(a), cy + r1 * math.sin(a))],
               fill=c, width=1)


def office_bg(img, t, wall="#4a5a6a"):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, wall)
    for x in range(0, W, 30):
        R(d, x, 0, x, 230, art.blend(wall, "#000000", 0.15))
    R(d, 110, 30, 168, 100, "#9fd3ff")
    window_frame(d, 108, 28, 170, 102, 2)
    R(d, 0, 230, W - 1, H - 1, "#3a3440")
    return d


def classroom_front(img, t, rows=((78, 6, 18), (124, 5, 24), (176, 4, 32)), arms_up=False, seed=9, board_text=None):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#6b4a52")
    R(d, 30, 10, 150, 60, P["board"])
    d.rectangle([30, 10, 150, 60], outline=P["wood_dk"])
    if board_text:
        ptext(d, 90, 34, board_text, 8, P["chalk"], anchor="mm")
    rnd = random.Random(seed)
    for ri, (yy, n, s) in enumerate(rows):
        step = W // n
        for i in range(n):
            hx = i * step + (step - s) // 2
            skin = rnd.choice(["#f4c7aa", "#e0a882", "#c98e6a", "#f6d2bc"])
            hair = rnd.choice(["#3a2a20", "#1c1c22", "#7a4a2a", "#c08a50", "#a03a2a"])
            shirt = rnd.choice(["#3b5a8a", "#8a3a3a", "#3a7a5a", "#5a4a8a", "#7a6a3a"])
            if arms_up:
                wave = int(math.sin(t * 8 + i + ri) * 2)
                R(d, hx + s - 2 + wave, yy - s // 2, hx + s + 2 + wave, yy + s, shirt)
                E(d, hx + s - 3 + wave, yy - s // 2 - 4, hx + s + 3 + wave, yy - s // 2 + 1, skin)
            R(d, hx - 2, yy + s - 2, hx + s + 2, yy + s * 2, shirt)
            E(d, hx, yy, hx + s, yy + int(s * 1.1), skin, O)
            d.chord([hx - 1, yy - 2, hx + s + 1, yy + int(s * 0.8)], 180, 360, fill=hair)
            ew = max(2, s // 6)
            for ex in (hx + s // 4, hx + s - s // 4 - ew):
                R(d, ex, yy + s // 2, ex + ew - 1, yy + s // 2 + ew - 1, P["black"])
        R(d, 0, yy + s * 2 - 6, W - 1, yy + s * 2, P["wood_lt"])
        R(d, 0, yy + s * 2, W - 1, yy + s * 2 + 4, P["wood"])
    return d


# ================================================================ scenes
def sc_uni_china(t, f, dur):
    img = base()
    d = drw(img)
    uni_building(d, t)
    # красные фонарики
    for i, lx in enumerate((22, 62, 118, 158)):
        sw = int(math.sin(t * 2 + i) * 2)
        R(d, lx, 0, lx, 16, "#3a2018")
        E(d, lx - 8 + sw, 16, lx + 8 + sw, 30, "#e0302a", O)
        R(d, lx - 5 + sw, 14, lx + 5 + sw, 16, "#ffd25a")
        R(d, lx - 5 + sw, 30, lx + 5 + sw, 32, "#ffd25a")
        R(d, lx - 1 + sw, 32, lx + 1 + sw, 38, "#e0302a")
        for k in range(2):
            R(d, lx - 7 + sw, 20 + k * 5, lx + 7 + sw, 20 + k * 5, "#b02020")
    glow(img, 90, 30, 60, (255, 90, 60), 30)
    x = int(lerp(20, 80, ease(t / dur)))
    paste(img, plagin_mini(f // 4, "tired"), x, 210, 2)
    return img


def sc_books_pile(t, f, dur):
    img = base()
    room_night(img, t)
    paste(img, plagin_bust("tired", t=t), 52, 116)
    d = drw(img)
    keyboard(d, 64, 212, 40)
    cols = ["#c0392b", "#2a6ad0", "#2f8f4c", "#8e44ad", "#e67e22", "#16a085", "#d35400", "#34495e"]
    n = min(14, int(t * 7) + 2)
    for i in range(n):
        side = i % 2
        k = i // 2
        bw = 34 + (i * 7) % 10
        bx = (8 if side == 0 else W - 8 - bw) + (i * 3) % 6
        by = 206 - k * 9
        drop = 0
        age = t - (i - 2) / 7
        if age < 0.15:
            drop = int((1 - age / 0.15) * 30)
        R(d, bx, by - drop, bx + bw, by + 7 - drop, cols[i % len(cols)])
        R(d, bx + 2, by + 2 - drop, bx + bw - 2, by + 2 - drop, "#f2efe4")
        d.rectangle([bx, by - drop, bx + bw, by + 7 - drop], outline=O)
    return img


def sc_pie_chart(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#1e2238")
    for x in range(0, W, 12):
        R(d, x, 0, x, H - 1, "#242a44")
    for y in range(0, H, 12):
        R(d, 0, y, W - 1, y, "#242a44")
    ptext(d, 90, 30, "МОЙ ДЕНЬ", 14, P["white"], anchor="mm", shadow=O)
    cx, cy, r = 90, 120, 60
    k = ease(t / 1.2)
    d.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill=O)
    d.pieslice([cx - r, cy - r, cx + r, cy + r], -90, -90 + 180 * k, fill="#3f71c9")
    d.pieslice([cx - r, cy - r, cx + r, cy + r], -90 + 180 * k, -90 + 359 * k, fill="#8e5ad0")
    if k > 0.95:
        d.pieslice([cx - r, cy - r, cx + r, cy + r], 268, 270, fill=P["red"])
    ptext(d, cx - 30, cy, "УЧЁБА", 8, P["white"], anchor="mm")
    ptext(d, cx + 30, cy, "СОН", 8, P["white"], anchor="mm")
    for i, (c, s) in enumerate((("#3f71c9", "Учёба — 50%"), ("#8e5ad0", "Сон — 50%"), (P["red"], "Жизнь — 0%"))):
        yy = 200 + i * 14
        R(d, 30, yy, 38, yy + 8, c)
        ptext(d, 44, yy, s, 8, P["white"])
    if t > dur * 0.55:
        R(d, 20, 238, 160, 240, P["red"])
    return img


def sc_canteen_sleep(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#e6eef2")
    for y in range(0, 200, 10):
        for x in range(0, W, 10):
            d.rectangle([x, y, x + 10, y + 10], outline="#b8c8d0")
    R(d, 0, 120, W - 1, 124, "#3a7a9a")
    ptext(d, 90, 30, "СТОЛОВАЯ", 11, "#3a7a9a", anchor="mm")
    R(d, 120, 60, 170, 100, "#f2c46a")
    d.rectangle([120, 60, 170, 100], outline=O)
    ptext(d, 145, 68, "МЕНЮ", 7, O, anchor="mm")
    for k in range(3):
        R(d, 126, 78 + k * 7, 164, 78 + k * 7, "#7a5a3a")
    b = plagin_bust("sleep", t=t).rotate(-35, resample=Image.NEAREST, expand=True)
    paste(img, b, 30, 118)
    d = drw(img)
    R(d, 0, 214, W - 1, H - 1, "#c8a070")
    R(d, 0, 214, W - 1, 218, "#e0b888")
    # поднос + тарелка
    R(d, 70, 200, 170, 226, "#8a8a98")
    E(d, 84, 198, 130, 216, "#ffffff", O)
    E(d, 90, 201, 124, 212, "#e8a040")
    R(d, 138, 204, 162, 206, "#c8c8d0")
    zzz(d, 120, 150, t)
    return img


def sc_bed_dream(t, f, dur):
    img = base()
    d = bedroom_bg(img, t)
    night_overlay(img, 120)
    d = drw(img)
    E(d, 14, 190, 110, 226, "#f4f1ea", O)
    b = plagin_bust("sleep", "nodrool", t).rotate(70, resample=Image.NEAREST, expand=True)
    paste(img, b, 6, 168)
    d = drw(img)
    d.polygon([(0, 236), (W - 1, 216), (W - 1, H - 1), (0, H - 1)], fill="#3f6fc4")
    # облако сна
    for (x, y, r) in ((70, 150, 3), (80, 136, 5)):
        E(d, x - r, y - r, x + r, y + r, P["white"], O)
    for (x, y, r) in ((70, 80, 26), (100, 70, 30), (130, 84, 24), (96, 100, 26), (60, 98, 18)):
        E(d, x - r - 1, y - r - 1, x + r + 1, y + r + 1, O)
    for (x, y, r) in ((70, 80, 26), (100, 70, 30), (130, 84, 24), (96, 100, 26), (60, 98, 18)):
        E(d, x - r, y - r, x + r, y + r, P["white"])
    # во сне — он снова спит
    R(d, 66, 92, 130, 104, "#3f6fc4")
    E(d, 66, 84, 80, 96, P["skin"], O)
    d.chord([66, 82, 80, 94], 180, 360, fill=P["hair"])
    R(d, 69, 90, 71, 90, O)
    R(d, 74, 90, 76, 90, O)
    zzz(d, 84, 76, t * 1.3, "#3a4aa0")
    zzz(d, 120, 160, t, "#ffffff")
    return img


def sc_zones(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, P["wood"])
    for y in range(0, H, 9):
        R(d, 0, y, W - 1, y, P["wood_dk"])
    # линия раздела
    k = ease(t / 1.0)
    yy = int(20 + 280 * k)
    for y in range(20, yy, 8):
        R(d, 86, y, 94, y + 4, "#ffd25a")
        R(d, 86, y + 4, 94, y + 7, "#1a1a1a")
    im1, _ = agent(34, "angry", f, arms="side")
    im2, _ = agent(34, "angry", f, arms="side", color="#e8663a")
    hop = int(abs(math.sin(t * 6)) * 3)
    paste(img, im1, 18, 150 - hop)
    paste(img, im2.transpose(Image.FLIP_LEFT_RIGHT), 112, 150 - (3 - hop))
    d = drw(img)
    for x, s in ((40, "МОЁ"), (138, "МОЁ")):
        R(d, x - 16, 110, x + 16, 126, P["white"])
        d.rectangle([x - 16, 110, x + 16, 126], outline=O)
        ptext(d, x, 118, s, 8, P["red"], anchor="mm")
        R(d, x, 126, x + 1, 146, "#6a3e24")
    # вещи
    R(d, 20, 220, 60, 240, "#f4f1e6")
    R(d, 120, 218, 164, 240, "#2a2a34")
    R(d, 124, 222, 160, 236, "#3a6ad0")
    return img


def sc_agent_boss(t, f, dur):
    img = base()
    sunburst(img, t, "#d8a040", "#f2c46a")
    d = drw(img)
    im, a = agent(56, "normal", f, arms="side")
    paste(img, im, 30, 120)
    d = drw(img)
    bx0, by0, bx1, by1 = a["body"]
    crown(d, 30 + (bx0 + bx1) // 2 - 12, 120 + by0 - 10, 24)
    # планшет с посещаемостью
    R(d, 110, 120, 166, 200, "#8a5a3a")
    R(d, 114, 128, 162, 196, "#f4f1e6")
    R(d, 130, 116, 146, 124, "#c0c0c8")
    ptext(d, 138, 134, "ПОСЕЩ.", 6, O, anchor="mm")
    n = min(6, int(t * 4))
    for i in range(6):
        yy = 144 + i * 8
        R(d, 118, yy + 4, 150, yy + 4, "#c8c2b0")
        if i < n:
            d.line([(152, yy + 2), (154, yy + 4), (158, yy - 1)], fill="#2a8a3a", width=1)
    return img


def sc_agent_notes_angry(t, f, dur):
    img = base()
    room_night(img, t)
    d = drw(img)
    for i in range(8):
        R(d, 10, 204 - i * 6, 52, 209 - i * 6, ["#f4f1e6", "#e8e2d0"][i % 2])
        d.rectangle([10, 204 - i * 6, 52, 209 - i * 6], outline="#8a8070")
    sx, sy = shake(t, 1, 30)
    im, a = agent(50, "glasses", f, arms="up" if int(t * 3) % 2 else "side")
    paste(img, im, 70 + sx, 150 + sy)
    d = drw(img)
    # пар из ушей
    for k in range(3):
        ph = (t * 1.5 + k / 3) % 1
        x = 68 + int(math.sin(ph * 6) * 3)
        y = 150 - int(ph * 30)
        E(d, x - 4, y - 3, x + 4, y + 3, "#e8e8f0")
        x = 136 - int(math.sin(ph * 6) * 3)
        E(d, x - 4, y - 3, x + 4, y + 3, "#e8e8f0")
    ptext(d, 150, 120, "!!", 16, P["red"], shadow=O)
    return img


def sc_babki(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#d8b090")
    for y in range(0, 240, 8):
        for x in range(-(y // 8 % 2) * 8, W, 16):
            d.rectangle([x, y, x + 16, y + 8], outline="#b88a6a")
    # дверь подъезда
    R(d, 104, 70, 166, 236, "#3a5a3a")
    d.rectangle([104, 70, 166, 236], outline=O)
    R(d, 110, 80, 160, 130, "#2a4a2a")
    R(d, 150, 160, 156, 166, "#c8c8d0")
    R(d, 108, 52, 162, 66, "#2a5a8a")
    ptext(d, 135, 59, "ПОДЪЕЗД 3", 7, P["white"], anchor="mm")
    R(d, 90, 140, 98, 160, "#5a5a6a")  # домофон
    for k in range(3):
        R(d, 92, 144 + k * 5, 96, 146 + k * 5, "#2a2a30")
    # лавка
    R(d, 0, 236, W - 1, H - 1, "#6a6a72")
    R(d, 6, 214, 120, 220, "#7a4428")
    R(d, 10, 220, 14, 240, "#3a2a20")
    R(d, 112, 220, 116, 240, "#3a2a20")
    # шелуха от семечек
    rnd = random.Random(3)
    for _ in range(30):
        x, y = rnd.randint(10, 170), rnd.randint(244, 300)
        R(d, x, y, x + 1, y, "#2a2a2a")
    turn = int(t * 2.2) % 2
    for i, (x, c) in enumerate(((14, P["ag"]), (64, "#e8663a"))):
        talking = (i == turn)
        hop = int(abs(math.sin(t * 10)) * 3) if talking else 0
        im, a = agent(40, "angry" if talking else "normal", f, arms="up" if talking and int(t * 6) % 2 else "side",
                      color=c)
        if i == 1:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        paste(img, im, x, 168 - hop)
        d = drw(img)
        # платочек
        bx0 = x + 8
        by0 = 168 - hop + 8
        scarf = "#c0304a" if i == 0 else "#3a6ad0"
        d.chord([bx0 - 3, by0 - 12, bx0 + 43, by0 + 14], 180, 360, fill=scarf, outline=O)
        for k in range(5):
            d.point((bx0 + 4 + k * 8, by0 - 4 + (k % 2) * 2), fill=P["white"])
        d.polygon([(bx0 + 18, by0 + 1), (bx0 + 22, by0 + 8), (bx0 + 26, by0 + 1)], fill=scarf, outline=O)
        if talking:
            bubble(d, x + (0 if i == 0 else -10), 120, 58, 18, "Я ВАЖНЕЕ!", 7)
    return img


def sc_plagin_thumbs(t, f, dur):
    img = base()
    room_night(img, t)
    paste(img, plagin_bust("happy", t=t), 52, 116)
    d = drw(img)
    bob = int(abs(math.sin(t * 6)) * 3)
    thumbs(d, 34, 180 - bob)
    thumbs(d, 134, 180 - bob)
    desk_front(d, 208)
    return img


def sc_agents_nelez(t, f, dur):
    img = base()
    room_night(img, t)
    im1, _ = agent(40, "angry", f, arms="side")
    im2, _ = agent(40, "angry", f, arms="side", color="#e8663a")
    paste(img, im1, 14, 160)
    paste(img, im2, 100, 160)
    d = drw(img)
    if t > 0.5:
        bubble(d, 40, 100, 100, 26, "НЕ ЛЕЗЬ!", 12)
    return img


def sc_chat_blocked(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#2a2030")
    # телефон
    R(d, 26, 10, 154, 300, "#111")
    R(d, 30, 22, 150, 288, "#e8e4dc")
    R(d, 30, 22, 150, 44, "#3a8aa0")
    E(d, 34, 26, 50, 40, P["ag"])
    ptext(d, 56, 28, "Агенты (2)", 8, P["white"])
    ptext(d, 56, 37, "печатают...", 6, "#d8f0ff")
    msgs = ["ребят?", "ау", "ну вы чё", "я же ваш хозяин"]
    n = min(len(msgs), int(t * 3) + 1)
    for i in range(n):
        y = 60 + i * 22
        w = len(msgs[i]) * 6 + 10
        R(d, 144 - w, y, 144, y + 14, "#c8f0a8")
        ptext(d, 144 - w + 5, y + 3, msgs[i], 8, "#222")
        ptext(d, 140, y + 15, "✓", 6, "#888", anchor="ra")
    if t > dur * 0.55:
        R(d, 36, 200, 144, 222, "#ffd8d8")
        ptext(d, 90, 211, "Вы удалены из чата", 7, P["red"], anchor="mm")
    return img


def sc_job_interview(t, f, dur):
    img = base()
    office_bg(img, t)
    d = drw(img)
    R(d, 14, 40, 96, 60, P["white"])
    d.rectangle([14, 40, 96, 60], outline=O)
    ptext(d, 55, 50, "СОБЕСЕДОВАНИЕ", 6, O, anchor="mm")
    paste(img, man_bust_plagin(t), 96, 126)
    d = drw(img)
    desk_front(d, 214)
    R(d, 20, 170, 60, 214, "#3a2a2a")  # пустой стул
    R(d, 16, 190, 64, 196, "#5a3a3a")
    if int(t * 3) % 2 == 0 and t < dur * 0.8:
        ptext(d, 40, 140, "ТУК-ТУК", 9, "#ffe680", anchor="mm", shadow=O)
    return img


def man_bust_plagin(t):
    return plagin_bust("neutral", t=t)


def sc_alarm_pro(t, f, dur):
    img = base()
    office_bg(img, t, "#5a4a6a")
    d = drw(img)
    x = int(lerp(-60, 50, ease(t / 1.2)))
    paste(img, alarm_char(t, 60, expr="proud", frame=f // 4, walk=t < 1.2), x, 140)
    d = drw(img)
    # портфель
    R(d, x + 76, 210, x + 96, 226, "#5a3424")
    R(d, x + 82, 206, x + 90, 210, "#3a2016")
    if t > 1.2:
        for i in range(3):
            ph = (t * 2 + i / 3) % 1
            ptext(d, x + 10 + i * 30, 130 - int(ph * 10), "✦", 9, "#fff2b0")
    return img


def sc_resume(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#3a2a34")
    paper(d, 14, 24, 166, 250, "РЕЗЮМЕ")
    paste(img, alarm_char(t, 30, ringing=False), 20, 44)
    d = drw(img)
    ptext(d, 76, 54, "Будильник", 9, O)
    ptext(d, 76, 66, "Иванович", 9, O)
    rows = [("Должность:", "побудчик"), ("Стаж:", "10 лет"), ("Навыки:", "громкий"), ("Достижение:", "")]
    for i, (a, b) in enumerate(rows):
        if t > 0.3 + i * dur * 0.15:
            yy = 104 + i * 22
            ptext(d, 22, yy, a, 8, "#555")
            ptext(d, 158, yy, b, 8, O, anchor="ra")
            R(d, 22, yy + 14, 158, yy + 14, "#d8d2c0")
    if t > dur * 0.6:
        ptext(d, 22, 196, "поднял декана", 8, "#2a5a8a")
        ptext(d, 22, 208, "после корпоратива", 8, "#2a5a8a")
        ptext(d, 158, 230, "★★★★★", 9, "#e8a020", anchor="ra")
    return img


def sc_plagin_happy(t, f, dur):
    img = base()
    sunburst(img, t, "#ffb040", "#ffd27a")
    d = drw(img)
    b = int(abs(math.sin(t * 8)) * 4)
    paste(img, plagin_bust("happy", t=t), 52, 120 - b)
    d = drw(img)
    confetti(d, t)
    return img


def sc_bed_yell(t, f, dur):
    img = base()
    bedroom_bg(img, t)
    night_overlay(img, 130)
    d = drw(img)
    sx, sy = shake(t, 2, 35)
    paste(img, plagin_bust("yell", t=t), 20 + sx, 120 + sy)
    d = drw(img)
    d.polygon([(0, 214), (W - 1, 204), (W - 1, H - 1), (0, H - 1)], fill="#3f6fc4")
    checker(d, (0, 204, W - 1, H - 1), 6, "#3f6fc4", "#4f80d6", mask=lambda x, y: y >= 214 - x * 10 / 180)
    paste(img, alarm_char(t, 40, ringing=True), 112, 150)
    d = drw(img)
    R(d, 108, 204, 170, 210, "#5a3424")
    txt = "ОТВАЛИ!" if (t % 1.2) < 0.6 else "5 МИНУТ!"
    if t > dur * 0.45:
        bubble(d, 20, 70, 76, 22, txt, 10)
    return img


def sc_slipper_throw(t, f, dur):
    img = base()
    bedroom_bg(img, t)
    night_overlay(img, 120)
    hit = t > 0.6
    paste(img, alarm_char(t, 50, expr="dizzy" if hit else "normal", ringing=not hit), 96, 140)
    d = drw(img)
    R(d, 90, 210, 172, 216, "#5a3424")
    for i in range(2):
        k = min(1.0, max(0.0, (t - i * 0.25) / 0.45))
        x = lerp(-10, 108, k)
        y = 200 - math.sin(k * math.pi) * 70 + k * (-20)
        rot = k * 600
        sl = Image.new("RGBA", (22, 12), (0, 0, 0, 0))
        sd = drw(sl)
        E(sd, 0, 2, 21, 11, "#f28ab0", O)
        E(sd, 2, 0, 12, 8, "#ffb0d0")
        sl = sl.rotate(rot, resample=Image.NEAREST, expand=True)
        if k < 1:
            paste(img, sl, x, y)
    d = drw(img)
    if hit:
        star_burst(d, 120, 150, 16)
        ptext(d, 120, 150, "БАМ", 7, O, anchor="mm")
        for k in range(3):
            a = t * 6 + k * 2.1
            ptext(d, 124 + 14 * math.cos(a), 134 + 5 * math.sin(a), "★", 7, "#ffe680")
        # тапки на полу
        E(d, 100, 228, 122, 238, "#f28ab0", O)
        E(d, 128, 230, 150, 240, "#f28ab0", O)
    return img


def sc_alarm_leave(t, f, dur):
    img = base()
    office_bg(img, t, "#4a3a4a")
    d = drw(img)
    R(d, 134, 70, 176, 230, "#5a3424")
    R(d, 138, 74, 172, 230, "#1a1420")
    x = int(lerp(30, 120, ease(t / dur)))
    paste(img, alarm_char(t, 50, expr="proud", frame=f // 4, walk=True), x, 150)
    d = drw(img)
    R(d, x - 6, 196, x + 16, 214, "#c09060")
    R(d, x - 6, 196, x + 16, 198, "#a07040")
    E(d, x - 2, 186, x + 8, 196, "#f28ab0", O)
    ptext(d, x + 34, 120, "ХМФ!", 9, P["white"], anchor="mm", shadow=O)
    return img


def startup_bg(img, t):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#2a2a3a")
    R(d, 0, 230, W - 1, H - 1, "#5a4a3a")
    for x in range(0, W, 14):
        R(d, x, 230, x, H - 1, "#4a3a2a")
    R(d, 30, 30, 150, 60, "#14141c")
    glow_c = "#ff5ad0" if int(t * 3) % 5 else "#ff9ae8"
    ptext(d, 90, 45, "STARTUP", 14, glow_c, anchor="mm")
    glow(img, 90, 45, 50, (255, 90, 210), 30)
    d = drw(img)
    R(d, 12, 120, 40, 160, "#2f6f3c")
    E(d, 8, 100, 44, 130, "#3f8f4c", O)
    R(d, 150, 140, 176, 200, "#3a3a4a")
    R(d, 154, 144, 172, 160, "#5ad0ff")
    return d


def sc_startup_cats(t, f, dur, dean=False):
    img = base()
    startup_bg(img, t)
    d = drw(img)
    # кресла-мешки и коты
    for i, (x, c) in enumerate(((10, "#c04a8a"), (70, "#4a8ac0"), (124, "#8ac04a"))):
        E(d, x, 216, x + 50, 250, c, O)
        awake = (t > dur * 0.5) and i % 2 == 0
        paste(img, cat(t, "sit" if awake else "sleep", ["#f0a050", "#8a8a9a", "#3a3a3a"][i]), x + 8, 196)
        d = drw(img)
        if not awake:
            zzz(d, x + 30, 196, t + i)
        else:
            ptext(d, x + 24, 180, "!", 12, P["red"], shadow=O)
    if dean:
        paste(img, man_bust("sleep", t, bald=True, glasses=False, suit="#2a2f55", tie=P["red"]), 52, 96)
        d = drw(img)
        R(d, 40, 192, 140, 198, "#7a4428")
    paste(img, alarm_char(t, 40, ringing=True), 120 if dean else 60, 100 if dean else 110)
    return img


def sc_startup_cats2(t, f, dur):
    return sc_startup_cats(t, f, dur, dean=True)


def sc_agent_starosta(t, f, dur):
    img = base()
    sunburst(img, t, "#d8a040", "#ffe08a")
    im, a = agent(70, "shades", f, arms="side")
    b = int(abs(math.sin(t * 4)) * 3)
    paste(img, im, 46, 120 - b)
    d = drw(img)
    bx0, by0, bx1, by1 = a["body"]
    sash(d, (46 + bx0 + 2, 120 - b + by0 + 20, 46 + bx1 - 2, 120 - b + by1 - 4), "СТАРОСТА")
    crown(d, 46 + (bx0 + bx1) // 2 - 14, 120 - b + by0 - 12, 28)
    for i in range(4):
        ph = (t * 1.5 + i / 4) % 1
        ptext(d, 30 + i * 36, 110 - int(ph * 20), "✦", 9, P["white"])
    return img


def sc_plagin_shock(t, f, dur):
    img = base()
    sunburst(img, t * 4, "#c0302a", "#e8603a")
    sx, sy = shake(t, 3, 45)
    b = plagin_bust("o", t=t, blink=False)
    paste(img, b, -14 + sx, 100 + sy, 2)
    d = drw(img)
    ptext(d, 150, 80, "!!!", 18, "#ffe680", shadow=O)
    return img


def sc_agent_pointer(t, f, dur):
    img = base()
    d = lecture_bg(img, t, front=True)
    ptext(d, 64, 50, "КТО НЕ ПИШЕТ?", 8, P["chalk"], anchor="mm")
    im, a = agent(40, "glasses", f, arms="side")
    paste(img, im, 14, 150)
    d = drw(img)
    bx0, by0, bx1, by1 = a["body"]
    hx, hy = 14 + a["rh"][0], 150 + a["rh"][1]
    wob = int(math.sin(t * 8) * 3)
    d.line([(hx, hy), (128, 150 + wob)], fill="#c8a070", width=2)
    sash(d, (14 + bx0 + 2, 150 + by0 + 12, 14 + bx1 - 2, 150 + by1 - 2), "СТАРОСТА")
    paste(img, plagin_bust("o", t=t), 104, 150)
    d = drw(img)
    desk_front(d, 230)
    if int(t * 4) % 2:
        ptext(d, 150, 130, "!", 18, P["red"], shadow=O)
    return img


def sc_plagin_yell(t, f, dur, bg="class"):
    img = base()
    if bg == "class":
        lecture_bg(img, t)
    else:
        room_night(img, t)
    d = drw(img)
    speed_lines(d, t, "#ffffff")
    sx, sy = shake(t, 2, 40)
    paste(img, plagin_bust("yell", "finger", t), 52 + sx, 116 + sy)
    d = drw(img)
    desk_front(d, 212)
    return img


def sc_plagin_yell2(t, f, dur):
    return sc_plagin_yell(t, f, dur, bg="room")


def sc_agent_form(t, f, dur):
    img = base()
    lecture_bg(img, t, front=True)
    im, a = agent(50, "shades", f, arms="side")
    paste(img, im, 24, 150)
    d = drw(img)
    bx0, by0, bx1, by1 = a["body"]
    sash(d, (24 + bx0 + 2, 150 + by0 + 14, 24 + bx1 - 2, 150 + by1 - 2), "СТАРОСТА")
    desk_front(d, 220)
    if t > dur * 0.5:
        k = ease((t - dur * 0.5) / 0.6)
        w = int(lerp(30, 110, k))
        h = int(w * 1.3)
        x0 = int(lerp(90, 60, k))
        y0 = int(lerp(170, 120, k))
        paper(d, x0, y0, x0 + w, y0 + h)
        if k > 0.8:
            ptext(d, x0 + w // 2, y0 + 12, "БЛАНК", 9, O, anchor="mm")
            ptext(d, x0 + w // 2, y0 + 24, "ПЕРЕСДАЧИ", 8, P["red"], anchor="mm")
            for k2 in range(5):
                R(d, x0 + 8, y0 + 40 + k2 * 12, x0 + w - 8, y0 + 40 + k2 * 12, "#c8c2b0")
    else:
        ptext(d, 130, 140, "ПРИОРИТЕТЫ", 7, P["white"], anchor="mm", shadow=O)
        for i, s in enumerate(("1. группа", "2. девчонки", "3. ты — нет")):
            ptext(d, 106, 154 + i * 12, s, 7, "#ffe680", shadow=O)
    return img


def sc_traitor(t, f, dur):
    img = base()
    sunburst(img, t, "#5a0a14", "#8a1a24")
    d = drw(img)
    im, a = agent(70, "shades", f, arms="side")
    paste(img, im, 46, 120)
    d = drw(img)
    # блик очков
    k = (t * 1.5) % 1
    bx0, by0, bx1, by1 = a["body"]
    ex1, ex2, ey = a["eyes"]
    if k < 0.3:
        x = 46 + ex1 - 3 + int(k / 0.3 * (ex2 - ex1 + 6))
        R(d, x, 120 + ey, x + 1, 120 + ey + 3, P["white"])
    # дождь
    rnd = random.Random(2)
    for i in range(30):
        x = rnd.randint(0, W)
        y = (rnd.randint(0, H) + t * 200) % H
        R(d, x, y, x, y + 4, "#c06070")
    return img


def sc_interrogation(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#0e0c14")
    sw = math.sin(t * 2.2) * 24
    lx = 90 + sw
    R(d, 89, 0, 90, 40, "#3a3a44")
    d.line([(90, 40), (lx, 60)], fill="#3a3a44")
    d.polygon([(lx - 10, 60), (lx + 10, 60), (lx + 6, 52), (lx - 6, 52)], fill="#5a5a6a")
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.polygon([(lx - 8, 60), (lx + 8, 60), (lx + 70, 260), (lx - 70, 260)], fill=(255, 240, 180, 60))
    img.alpha_composite(ov)
    paste(img, plagin_bust("tired", t=t), 52, 130)
    d = drw(img)
    # пот
    for k in range(2):
        ph = (t * 1.2 + k * 0.5) % 1
        R(d, 66 + k * 44, 150 + int(ph * 20), 67 + k * 44, 152 + int(ph * 20), "#9fd3ff")
    R(d, 20, 226, 160, 232, "#3a3a44")
    R(d, 26, 232, 30, 300, "#2a2a34")
    R(d, 150, 232, 154, 300, "#2a2a34")
    return img


def sc_prof_squint(t, f, dur):
    img = base()
    d = lecture_bg(img, t, front=True)
    ptext(d, 64, 50, "ПЕРЕСДАЧА", 9, P["chalk"], anchor="mm")
    paste(img, man_bust("squint", t), 52, 116)
    d = drw(img)
    desk_front(d, 212)
    R(d, 30, 204, 70, 212, "#f4f1e6")
    return img


def sc_exam_ticket(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, P["wood"])
    for y in range(0, H, 9):
        R(d, 0, y, W - 1, y, P["wood_dk"])
    paper(d, 14, 40, 166, 230, "БИЛЕТ №13", title_bg="#8a2a2a")
    qs = [("1.", "Как работает", "нейросеть?"), ("2.", "Почему она", "работает?"), ("3.", "Почему не", "у вас?")]
    for i, (n, a, b) in enumerate(qs):
        if t > 0.2 + i * dur * 0.22:
            yy = 70 + i * 50
            ptext(d, 22, yy, n, 10, P["red"])
            ptext(d, 40, yy, a, 9, O)
            ptext(d, 40, yy + 14, b, 9, O)
    return img


def sc_prof_laugh(t, f, dur):
    img = base()
    d = lecture_bg(img, t, front=True)
    sx, sy = shake(t, 2, 25)
    paste(img, man_bust("laugh", t), 52 + sx, 116 + sy)
    d = drw(img)
    desk_front(d, 212)
    for k in range(3):
        ph = (t * 2 + k / 3) % 1
        ptext(d, 40 + k * 50, 110 - int(ph * 20), "ХА", 8, "#ffe680", shadow=O)
    if t > dur * 0.4:
        k = ease((t - dur * 0.4) / 0.15)
        sz = int(lerp(60, 34, k))
        ptext(d, 150, 160, "2", sz, P["red"], anchor="mm", shadow=O)
    return img


def sc_agent_money(t, f, dur):
    img = base()
    sunburst(img, t, "#3a8a4a", "#5ab06a")
    d = drw(img)
    rnd = random.Random(7)
    for i in range(18):
        x = rnd.randint(0, W)
        y = (rnd.randint(0, H) + t * 80) % (H + 20) - 10
        E(d, x, y, x + 8, y + 8, "#ffd25a", O)
        ptext(d, x + 4, y + 4, "¥", 6, "#a07010", anchor="mm")
    im, a = agent(56, "shades", f, arms="up")
    paste(img, im, 40, 130)
    d = drw(img)
    # мешок
    E(d, 108, 170, 160, 226, "#c8a060", O)
    R(d, 126, 162, 142, 172, "#a08040")
    ptext(d, 134, 200, "¥", 14, "#5a3a10", anchor="mm")
    ptext(d, 90, 250, "СТИПЕНДИЯ", 10, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_meme_burst(t, f, dur):
    img = base()
    cols = [("#ff4a8a", "#ffd25a"), ("#4ad0ff", "#a04aff"), ("#7aff6a", "#ff7a4a")]
    c1, c2 = cols[int(t * 6) % 3]
    sunburst(img, t * 6, c1, c2)
    d = drw(img)
    sx, sy = shake(t, 3, 30)
    paste(img, plagin_mini(0, "o", walking=False), 57 + sx, 112 + sy, 3)
    d = drw(img)
    star_burst(d, 30, 60, 18, "#ffffff")
    star_burst(d, 150, 260, 14, "#ffffff")
    return img


def sc_dean_vacuum(t, f, dur):
    img = base()
    corridor_bg(img, t, off=0)
    d = drw(img)
    x = int(lerp(-40, 70, ease(t / (dur * 0.8))))
    vx = x + 60
    paste(img, dean_mini(f // 4, walking=t < dur * 0.8), x, 170, 2)
    paste(img, vacuum(t), vx, 250)
    d = drw(img)
    # поводок
    d.line([(x + 44, 236), (vx + 30, 268)], fill=P["red"], width=1)
    R(d, x + 4, 150, x + 48, 162, "#2a5a8a")
    ptext(d, x + 26, 156, "ДЕКАН", 7, P["white"], anchor="mm")
    return img


def sc_vacuum_grad(t, f, dur):
    img = base()
    sunburst(img, t, "#2a4a8a", "#3a6ac0")
    d = drw(img)
    b = int(abs(math.sin(t * 4)) * 4)
    paste(img, vacuum(t, ("cap",)), 30, 100 - b, 2)
    d = drw(img)
    if t > dur * 0.35:
        R(d, 50, 210, 130, 250, "#f4f1e6")
        d.rectangle([50, 210, 130, 250], outline=O)
        ptext(d, 90, 220, "ДИПЛОМ", 8, "#2a5a8a", anchor="mm")
        ptext(d, 90, 232, "магистр", 7, O, anchor="mm")
        ptext(d, 90, 242, "клининга", 7, O, anchor="mm")
        R(d, 116, 240, 126, 252, P["red"])
    confetti(d, t, 16)
    return img


def sc_vacuum_vahter(t, f, dur):
    img = base()
    floor_and_wall(img, "#6b4a52", "#4a3a3e", 220)
    d = drw(img)
    R(d, 20, 40, 160, 100, P["board"])
    d.rectangle([20, 40, 160, 100], outline=P["wood_dk"])
    paste(img, plagin_mini(0, "tired", walking=False), 110, 140, 2)
    vx = int(lerp(-50, 40, ease(t / (dur * 0.7))))
    paste(img, vacuum(t, ("scarf",)), vx, 214, 1)
    d = drw(img)
    if t > dur * 0.7:
        bubble(d, vx + 10, 180, 44, 16, "КХМ.", 8)
    return img


def sc_stand_sleep(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#141420")
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.polygon([(80, 0), (100, 0), (150, 290), (30, 290)], fill=(255, 240, 200, 45))
    img.alpha_composite(ov)
    d = drw(img)
    E(d, 30, 270, 150, 300, "#2a2a3a")
    sway = math.sin(t * 2) * 4
    m = person_mini(0, walking=False, expr="sleep", hair=P["hair"], top=P["chk_a"], pants=P["jeans"])
    m = plagin_mini(0, "tired", walking=False).rotate(sway, resample=Image.NEAREST, expand=True)
    paste(img, m, 54, 120, 3)
    d = drw(img)
    zzz(d, 112, 110, t)
    paste(img, vacuum(t, ("scarf",)), 4, 262, 1)
    return img


def sc_blacklist(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#3a1a1a")
    paper(d, 16, 30, 164, 250, None, bg="#141414")
    ptext(d, 90, 50, "ЧЁРНЫЙ СПИСОК", 10, P["white"], anchor="mm")
    R(d, 26, 62, 154, 63, P["red"])
    items = ["1. Плагин", "2. Агент-будильник", "3. Кот из стартапа"]
    for i, s in enumerate(items):
        if t > 0.4 + i * dur * 0.2:
            ptext(d, 28, 84 + i * 30, s, 9, "#f0f0f0")
    if t > dur * 0.3:
        paste(img, vacuum(t, ("scarf",)), 110, 196)
    return img


def astral_bg(img, t):
    d = drw(img)
    for y in range(H):
        R(d, 0, y, W - 1, y, art.blend("#1a0a3a", "#6a2a8a", y / H))
    rnd = random.Random(11)
    for i in range(60):
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        if (int(t * 4) + i) % 6:
            d.point((x, y), fill="#e8d8ff")
        else:
            R(d, x - 1, y, x + 1, y, "#ffffff")
            R(d, x, y - 1, x, y + 1, "#ffffff")
    glow(img, 90, 160, 90, (200, 120, 255), 40)
    return drw(img)


def sc_astral(t, f, dur):
    img = base()
    astral_bg(img, t)
    fl = int(math.sin(t * 2) * 6)
    glow(img, 90, 160 + fl, 60, (255, 230, 150), 60)
    paste(img, plagin_bust("sleep", "nodrool", t), 52, 110 + fl)
    d = drw(img)
    d.ellipse([60, 96 + fl, 120, 106 + fl], outline="#fff2b0")
    return img


def sc_vacuum_smenka(t, f, dur):
    img = base()
    astral_bg(img, t)
    fl = int(math.sin(t * 2.5) * 6)
    paste(img, vacuum(t, ("scarf",)), 30, 120 + fl, 2)
    d = drw(img)
    # мешок для сменки
    R(d, 112, 120 + fl, 150, 160 + fl, "#3a6ad0")
    d.rectangle([112, 120 + fl, 150, 160 + fl], outline=O)
    d.line([(112, 120 + fl), (131, 106 + fl), (150, 120 + fl)], fill=O)
    ptext(d, 131, 140 + fl, "СМЕНКА", 6, P["white"], anchor="mm")
    return img


def sc_exchange_student(t, f, dur):
    img = base()
    floor_and_wall(img, "#6b4a52", "#4a3a3e", 230)
    d = drw(img)
    # шкаф
    R(d, 8, 60, 70, 232, "#6a3e28")
    d.rectangle([8, 60, 70, 232], outline=O)
    R(d, 38, 62, 40, 230, O)
    op = ease((t - 0.2) / 0.6)
    R(d, 40, 62, 40 + int(30 * (1 - op)), 230, "#7a4428")
    x = int(lerp(30, 76, op))
    paste(img, person_mini(f // 4, hair="#141418", top="#c0303a", glasses=True, backpack="#3a3a4a",
                           walking=op < 1), x, 120, 2)
    d = drw(img)
    if t > dur * 0.35:
        bubble(d, 98, 90, 74, 22, "НИ ХАО, БРАТ!", 7)
    return img


def sc_coursework_price(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#2a2a3a")
    paper(d, 24, 40, 156, 236)
    ptext(d, 90, 70, "КУРСОВАЯ", 12, O, anchor="mm")
    ptext(d, 90, 86, "РАБОТА", 9, O, anchor="mm")
    for k in range(8):
        R(d, 34, 104 + k * 10, 146 - (k * 13) % 30, 104 + k * 10, "#c8c2b0")
    if t > dur * 0.3:
        d.polygon([(120, 170), (166, 170), (176, 186), (166, 202), (120, 202)], fill="#ffd25a", outline=O)
        E(d, 166, 183, 170, 187, O)
        ptext(d, 144, 186, "¥300", 10, O, anchor="mm")
    stamp(img, "ОРИГИНАЛ", 80, 210, dur * 0.7, t, angle=-10, size=10)
    return img


def sc_agent_blush(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#4a2a34")
    # календарь
    R(d, 112, 30, 168, 90, P["white"])
    R(d, 112, 30, 168, 44, P["red"])
    ptext(d, 140, 37, "ДЕДЛАЙН", 6, P["white"], anchor="mm")
    ptext(d, 140, 66, "!", 22, P["red"], anchor="mm")
    k = ease(t / (dur * 0.6))
    col = art.blend(P["ag"], "#e02a2a", k)
    im, a = agent(66, "normal", f, arms="side", color=col)
    paste(img, im, 40, 140)
    d = drw(img)
    bx0, by0, bx1, by1 = a["body"]
    ex1, ex2, ey = a["eyes"]
    for ex in (ex1, ex2):
        R(d, 40 + ex - 5, 140 + ey + 14, 40 + ex + 6, 140 + ey + 16, "#ff8aa8")
    sash(d, (40 + bx0 + 2, 140 + by0 + 22, 40 + bx1 - 2, 140 + by1 - 4), "СТАРОСТА")
    for k2 in range(2):
        ph = (t * 1.5 + k2 * 0.5) % 1
        E(d, 40 + bx1 - 4 + k2 * 6, 140 + by0 + 6 + int(ph * 16), 40 + bx1 + 1 + k2 * 6, 140 + by0 + 12 + int(ph * 16),
          "#9fd3ff", O)
    return img


def sc_rebrand(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#1e1e2a")
    R(d, 10, 30, 170, 140, "#f4f4f8")
    d.rectangle([10, 30, 170, 140], outline=O)
    ptext(d, 90, 44, "РЕБРЕНДИНГ", 11, "#2a5a8a", anchor="mm")
    R(d, 20, 70, 74, 120, "#e8e8f0")
    ptext(d, 47, 90, "курсовая", 7, O, anchor="mm")
    ptext(d, 90, 95, "→", 14, P["red"], anchor="mm")
    R(d, 106, 70, 160, 120, "#ffd25a")
    ptext(d, 133, 86, "курсовая", 7, O, anchor="mm")
    ptext(d, 133, 100, "2.0", 12, P["red"], anchor="mm")
    im, a = agent(50, "shades", f, arms="side")
    paste(img, im, 60, 170)
    d = drw(img)
    hx, hy = 60 + a["rh"][0], 170 + a["rh"][1]
    d.line([(hx, hy), (150, 112 + int(math.sin(t * 5) * 3))], fill="#c8a070", width=2)
    return img


def court_bg(img, t):
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#5a3424")
    for x in range(0, W, 20):
        R(d, x, 0, x + 1, 200, "#4a2818")
    R(d, 60, 20, 120, 60, "#ffd25a")
    d.rectangle([60, 20, 120, 60], outline=O)
    ptext(d, 90, 40, "СУД", 12, O, anchor="mm")
    R(d, 30, 120, 150, 200, "#7a4428")
    R(d, 26, 116, 154, 122, "#9a5c36")
    R(d, 0, 200, W - 1, H - 1, "#3a2418")
    return d


def sc_court(t, f, dur):
    img = base()
    court_bg(img, t)
    paste(img, man_bust("neutral", t, bald=False, hair="#e8e8f0", glasses=True, mustache=False, suit="#141418",
                        tie="#141418"), 52, 40)
    d = drw(img)
    R(d, 30, 120, 150, 200, "#7a4428")
    R(d, 26, 116, 154, 122, "#9a5c36")
    paste(img, person_mini(0, hair="#141418", top="#c0303a", glasses=True, walking=False), 10, 200, 2)
    im, a = agent(22, "glasses", f, arms="side", color="#4a7ad0")
    paste(img, im, 130, 262)
    d = drw(img)
    R(d, 160, 266, 172, 280, "#8a5a3a")
    return img


def sc_lawyer_agent(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#1a1a2a")
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).polygon([(80, 0), (100, 0), (150, 260), (30, 260)], fill=(255, 240, 200, 50))
    img.alpha_composite(ov)
    d = drw(img)
    E(d, 40, 240, 140, 262, "#2a2a3a")
    b = int(abs(math.sin(t * 5)) * 2)
    im, a = agent(44, "glasses", f, arms="side", color="#4a7ad0")
    paste(img, im, 60, 196 - b)
    d = drw(img)
    R(d, 112, 222 - b, 140, 244 - b, "#a06a3a")
    d.rectangle([112, 222 - b, 140, 244 - b], outline=O)
    R(d, 120, 218 - b, 132, 222 - b, "#a06a3a")
    # галстук-бабочка
    cx = 60 + (a["body"][0] + a["body"][2]) // 2
    cy = 196 - b + a["body"][1] + 28
    d.polygon([(cx - 6, cy - 3), (cx, cy), (cx - 6, cy + 3)], fill=P["red"], outline=O)
    d.polygon([(cx + 6, cy - 3), (cx, cy), (cx + 6, cy + 3)], fill=P["red"], outline=O)
    ptext(d, 90, 120, "АДВОКАТ", 9, "#ffe680", anchor="mm", shadow=O)
    return img


def sc_cat_meme(t, f, dur):
    img = base()
    court_bg(img, t)
    d = drw(img)
    # открытая папка
    op = ease(t / 0.8)
    R(d, 14, 70, 166, 250, "#a06a3a")
    d.rectangle([14, 70, 166, 250], outline=O)
    if op > 0.5:
        R(d, 26, 84, 154, 236, P["white"])
        d.rectangle([26, 84, 154, 236], outline=O)
        R(d, 34, 100, 146, 210, "#9ab0c8")
        paste(img, cat(t, "sit", "#f0a050", glasses=False), 56, 120, 2)
        d = drw(img)
        ptext(d, 90, 96, "КОГДА ПРОСНУЛСЯ", 6, P["white"], anchor="mm", shadow=O)
        ptext(d, 90, 218, "А УЖЕ СЕССИЯ", 7, O, anchor="mm")
    return img


def sc_gavel(t, f, dur):
    img = base()
    court_bg(img, t)
    d = drw(img)
    R(d, 40, 222, 110, 236, "#5a3020")
    d.rectangle([40, 222, 110, 236], outline=O)
    ph = (t * 1.6) % 1
    down = min(1.0, ph / 0.2)
    th = math.radians(235 - 55 * down)  # поднят -> опущен
    px, py = 150, 206
    L = 70
    hx, hy = px + L * math.cos(th), py + L * math.sin(th)
    d.line([(px, py), (hx, hy)], fill="#8a5a3a", width=5)
    ux, uy = math.cos(th), math.sin(th)
    vx, vy = -uy, ux
    corners = [(hx + ux * 9 + vx * 16, hy + uy * 9 + vy * 16), (hx + ux * 9 - vx * 16, hy + uy * 9 - vy * 16),
               (hx - ux * 9 - vx * 16, hy - uy * 9 - vy * 16), (hx - ux * 9 + vx * 16, hy - uy * 9 + vy * 16)]
    d.polygon(corners, fill="#6a3e28", outline=O)
    if 0.2 < ph < 0.4:
        star_burst(d, 70, 218, 14)
    stamp(img, "ПРОИГРАНО", 90, 110, dur * 0.25, t, size=13, angle=-8)
    return img


def sc_agent_vacation(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, 150, "#7ac8f0")
    E(d, 120, 20, 160, 60, "#fff2a0")
    for y in range(150, 210):
        R(d, 0, y, W - 1, y, "#2a8ac0" if (y + int(t * 10)) % 6 else "#5ab0e0")
    R(d, 0, 210, W - 1, H - 1, "#f2d090")
    # пальма
    R(d, 20, 100, 26, 230, "#8a5a2a")
    for a in range(5):
        ang = a * 0.8 - 1.6 + math.sin(t) * 0.1
        d.polygon([(23, 100), (23 + 40 * math.cos(ang), 100 + 20 * math.sin(ang) - 6),
                   (23 + 34 * math.cos(ang), 100 + 20 * math.sin(ang) + 4)], fill="#3f8f4c", outline=O)
    im, a = agent(56, "shades", f, arms="up", color="#d0602a")
    paste(img, im, 60, 186)
    d = drw(img)
    R(d, 140, 230, 170, 256, "#c03a3a")
    R(d, 150, 224, 160, 230, "#5a2a2a")
    return img


def sc_agent_teacher(t, f, dur, ask=False):
    img = base()
    d = lecture_bg(img, t, front=True)
    ptext(d, 64, 50, "ПРЕПОД", 10, P["chalk"], anchor="mm")
    im, a = agent(56, "glasses", f, arms="up" if ask and int(t * 3) % 2 else "side")
    paste(img, im, 56, 140)
    d = drw(img)
    bx0, by0, bx1, by1 = a["body"]
    cx = 56 + (bx0 + bx1) // 2
    # усы и галстук
    my = 140 + a["eyes"][2] + 16
    d.polygon([(cx - 10, my), (cx, my - 3), (cx + 10, my), (cx + 7, my + 3), (cx, my + 1), (cx - 7, my + 3)],
              fill="#3a2a22")
    d.polygon([(cx - 3, 140 + by0 + 32), (cx + 3, 140 + by0 + 32), (cx + 5, 140 + by1 - 4), (cx, 140 + by1),
               (cx - 5, 140 + by1 - 4)], fill="#2a4ea0", outline=O)
    desk_front(d, 214)
    if ask:
        bubble(d, 100, 100, 74, 24, "ПЕРЕСДАТЬ?", 8)
    return img


def sc_agent_teacher2(t, f, dur):
    return sc_agent_teacher(t, f, dur, ask=True)


def sc_board_topic(t, f, dur):
    img = base()
    d = drw(img)
    R(d, 0, 0, W - 1, H - 1, "#5a3a44")
    chalkboard(d, 8, 30, 172, 220)
    lines = ["ТЕМА:", "Как не", "выспаться", "и стать", "старостой"]
    total = sum(len(s) for s in lines)
    n = int(ease(t / (dur * 0.85)) * total)
    yy = 50
    last = (20, 50)
    for s in lines:
        k = min(len(s), n)
        if k > 0:
            ptext(d, 20, yy, s[:k], 13 if s == "ТЕМА:" else 12, P["chalk"])
            last = (20 + int(k * 9), yy + 6)
        n -= k
        yy += 30
    # мел
    R(d, last[0] + 4, last[1], last[0] + 10, last[1] + 3, P["white"])
    R(d, 0, 222, W - 1, 226, P["wood_lt"])
    return img


def sc_hands_up(t, f, dur):
    img = base()
    classroom_front(img, t, arms_up=True, board_text="КТО ПЕРЕСДАЁТ?")
    d = drw(img)
    paste(img, vacuum(t, ()), 6, 238)
    d = drw(img)
    R(d, 30, 236, 32, 252, "#9a9aa8")
    R(d, 28, 232, 34, 236, "#9a9aa8")
    if t > dur * 0.5:
        paste(img, person_mini(0, walking=False, scarf="#c0304a", top="#5a3a6a", pants="#3a3a44", glasses=True,
                               arm_up=True, skin="#e8b898"), 130, 220, 2)
    return img


def sc_cat_class(t, f, dur):
    img = base()
    d = lecture_bg(img, t, front=True)
    ptext(d, 64, 50, "ПЕРЕСДАЧА", 9, P["chalk"], anchor="mm")
    paste(img, cat(t, "paw", "#3a3a3a", glasses=True), 52, 140, 2)
    d = drw(img)
    desk_front(d, 196)
    R(d, 50, 188, 90, 196, "#f4f1e6")
    R(d, 96, 190, 130, 196, "#3a6ad0")
    return img


def sc_meeting(t, f, dur):
    img = base()
    office_bg(img, t, "#3a4a5a")
    d = drw(img)
    R(d, 10, 30, 90, 90, P["white"])
    d.rectangle([10, 30, 90, 90], outline=O)
    pts = [(16, 80), (32, 60), (48, 70), (64, 44), (84, 50)]
    d.line(pts, fill=P["red"], width=2)
    paste(img, man_bust("sleep", t, bald=True, glasses=False, suit="#2a2f55", tie=P["red"]), 52, 110)
    d = drw(img)
    zzz(d, 100, 110, t)
    R(d, 0, 200, W - 1, 210, "#7a4428")
    R(d, 0, 210, W - 1, H - 1, "#5a3020")
    paste(img, alarm_char(t, 44, ringing=True, expr="yell"), 104, 150)
    d = drw(img)
    if t > dur * 0.45:
        bubble(d, 10, 96, 90, 22, "ВСТАВАЙТЕ!!", 9)
    return img


def sc_circus(t, f, dur):
    img = base()
    d = drw(img)
    n = 16
    rot = t * 0.4
    cx, cy = W // 2, 40
    R(d, 0, 0, W - 1, H - 1, "#f4f1e6")
    for i in range(n):
        if i % 2 == 0:
            a0 = rot + i * math.pi / (n / 2)
            a1 = a0 + math.pi / n * 2 * 0.5
            d.polygon([(cx, cy), (cx + 400 * math.cos(a0), cy + 400 * math.sin(a0)),
                       (cx + 400 * math.cos(a1), cy + 400 * math.sin(a1))], fill="#d8302a")
    # участники цирка прыгают
    actors = [
        (agent(30, "happy", f, arms="up")[0], 10, 200),
        (alarm_char(t, 30, tie=True), 50, 190),
        (cat(t, "paw"), 104, 214),
        (vacuum(t, ("scarf",)), 120, 240),
    ]
    for i, (im, x, y) in enumerate(actors):
        hop = int(abs(math.sin(t * 6 + i)) * 10)
        paste(img, im, x, y - hop)
    d = drw(img)
    confetti(d, t, 40)
    stamp(img, "АВТОМАТ", 90, 120, dur * 0.2, t, color="#2a8a3a", size=16, angle=-8)
    return img


SCENE_FUNCS = {k[3:]: v for k, v in globals().items() if k.startswith("sc_")}
art.SCENE_FUNCS.update(SCENE_FUNCS)
