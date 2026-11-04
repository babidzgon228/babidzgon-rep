# -*- coding: utf-8 -*-
"""Длинная версия ролика под готовую озвучку (ElevenLabs).

    python3 build_long.py --vo voice.mp3 --words words.json --out out/plagin_long.mp4

words.json — распознанные слова с таймингами (Vosk, см. asr.py):
[{"word": "...", "start": 1.05, "end": 1.29, "conf": 1.0}, ...]
"""
import argparse
import difflib
import json
import os
import re

import numpy as np

import art
import art2  # noqa: F401  (регистрирует новые сцены)
import audio
import build
from script_long import SCENES

CENSOR = {
    "блядь": "бл*дь", "блять": "бл*ть", "сука": "с*ка", "нихуя": "них*я",
    "охуенные": "ох*енные", "пиздец": "п*здец",
}
MAX_CHUNK = 30  # символов в одном субтитре


def norm(w):
    w = w.lower().replace("ё", "е")
    return re.sub(r"[^а-яa-z0-9]", "", w)


def tokenize(text):
    """-> список слов; слово = dict(pieces=[(текст, подсветка)], align=[токены для выравнивания])."""
    words = []
    hl = False
    for raw in text.split():
        pieces, buf = [], ""
        for ch in raw:
            if ch in "[]":
                if buf:
                    pieces.append((buf, hl))
                    buf = ""
                hl = ch == "["
            else:
                buf += ch
        if buf:
            pieces.append((buf, hl))
        plain = "".join(p for p, _ in pieces)
        toks = [norm(x) for x in re.split(r"[-—]", plain)]
        toks = [x for x in toks if x]
        if pieces:
            words.append(dict(pieces=pieces, align=toks, plain=plain))
    return words


def censor_piece(p):
    m = re.match(r"^([«(\"]*)(.*?)([.,!?:;»)\"…]*)$", p)
    pre, core, post = m.groups()
    low = core.lower()
    if low in CENSOR:
        rep = CENSOR[low]
        core = rep.upper() if core.isupper() else (rep[0].upper() + rep[1:] if core[:1].isupper() else rep)
    return pre + core + post


def align(entries, asr):
    """Сопоставляет слова сценария с распознанными словами -> время начала каждого слова."""
    mine = []  # (индекс записи, индекс слова)
    toks = []
    for ei, (_, words) in enumerate(entries):
        for wi, w in enumerate(words):
            for tk in w["align"] or ["_"]:
                mine.append((ei, wi))
                toks.append(tk)
    theirs = [norm(x["word"]) for x in asr]
    sm = difflib.SequenceMatcher(None, toks, theirs, autojunk=False)
    tmap = [None] * len(toks)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("equal", "replace"):
            for k in range(i2 - i1):
                j = j1 + int(k * (j2 - j1) / (i2 - i1))
                tmap[i1 + k] = (asr[j]["start"], asr[min(j, len(asr) - 1)]["end"])
    # интерполяция пропусков
    known = [i for i, v in enumerate(tmap) if v]
    for i, v in enumerate(tmap):
        if v is None:
            prev = max([k for k in known if k < i], default=None)
            nxt = min([k for k in known if k > i], default=None)
            if prev is not None and nxt is not None:
                a = tmap[prev][1]
                b = tmap[nxt][0]
                fr = (i - prev) / (nxt - prev)
                tmap[i] = (a + (b - a) * fr, a + (b - a) * fr)
            elif prev is not None:
                tmap[i] = tmap[prev]
            else:
                tmap[i] = tmap[nxt]
    starts = {}
    ends = {}
    for (ei, wi), (s, e) in zip(mine, tmap):
        starts.setdefault((ei, wi), s)
        ends[(ei, wi)] = e
    ratio = sm.ratio()
    return starts, ends, ratio


def chunk_words(words):
    """Режет слова записи на короткие субтитры (≤ MAX_CHUNK символов, по знакам препинания)."""
    chunks, cur, ln = [], [], 0
    for wi, w in enumerate(words):
        L = len(w["plain"])
        if cur and ln + 1 + L > MAX_CHUNK:
            chunks.append(cur)
            cur, ln = [], 0
        cur.append(wi)
        ln += (1 if ln else 0) + L
        if re.search(r"[.!?…:»]$", w["plain"]) and ln >= 12:
            chunks.append(cur)
            cur, ln = [], 0
    if cur:
        if chunks and ln < 8 and len(" ".join(words[i]["plain"] for i in chunks[-1])) + ln < MAX_CHUNK + 8:
            chunks[-1] += cur
        else:
            chunks.append(cur)
    return chunks


def caption_text(words, idxs):
    out = []
    for i in idxs:
        s = ""
        for p, h in words[i]["pieces"]:
            p = censor_piece(p).upper()
            s += f"[{p}]" if h else p
        out.append(s)
    return " ".join(out)


def build_timeline(vo_dur, asr, outro=2.6):
    entries = [(name, tokenize(text)) for name, text in SCENES]
    starts, ends, ratio = align(entries, asr)
    print(f"совпадение текста с распознанным: {ratio:.0%}")
    timeline = []
    sc_starts = []
    for ei, (name, words) in enumerate(entries):
        s = starts[(ei, 0)] - 0.12
        sc_starts.append(max(0.0, s) if ei else 0.0)
    for ei, (name, words) in enumerate(entries):
        st = sc_starts[ei]
        en = sc_starts[ei + 1] if ei + 1 < len(entries) else vo_dur + 0.25
        caps = []
        chunks = chunk_words(words)
        for ci, idxs in enumerate(chunks):
            c0 = starts[(ei, idxs[0])] - st
            if ci + 1 < len(chunks):
                c1 = starts[(ei, chunks[ci + 1][0])] - st
            else:
                c1 = en - st
            caps.append((max(0.0, c0 - 0.05), c1, caption_text(words, idxs)))
        timeline.append(dict(name=name, start=st, end=en, caps=caps))
    timeline.append(dict(name="outro", start=vo_dur + 0.25, end=vo_dur + 0.25 + outro, caps=[]))
    return timeline, timeline[-1]["end"]


def mix(timeline, total, vo_path, path):
    n = int((total + 0.3) * audio.SR)
    v = audio.load_audio(vo_path)
    voice = np.zeros(n, np.float32)
    voice[: min(n, len(v))] = v[:n]
    print("  музыка...", flush=True)
    music = audio.lofi_music(total + 0.3)
    music = music[:n] if len(music) >= n else np.pad(music, (0, n - len(music)))
    env = np.convolve(np.abs(voice), np.ones(int(0.25 * audio.SR)) / int(0.25 * audio.SR), mode="same")
    duck = 1.0 - 0.6 * np.clip(env / 0.04, 0, 1)
    music = music * 0.2 * duck
    sfx = np.zeros(n, np.float32)
    rng = np.random.default_rng(1)
    for sc in timeline[1:]:
        w = audio.whoosh(rng, 0.18, 0.035)
        s = max(0, int((sc["start"] - 0.07) * audio.SR))
        sfx[s:s + len(w)] += w[: n - s]
    out = timeline[-1]
    for i in range(7):
        b = audio.blip(1200 + i * 40, 0.04, 0.03)
        s = int((out["start"] + 0.12 + i / 8) * audio.SR)
        sfx[s:s + len(b)] += b[: n - s]
    audio.write_wav(path + ".voice.wav", voice)
    audio.write_wav(path + ".bed.wav", music + sfx)
    build.master_audio(path, external=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vo", required=True)
    ap.add_argument("--words", required=True)
    ap.add_argument("--out", default="out/plagin_long.mp4")
    ap.add_argument("--plan-only", action="store_true")
    args = ap.parse_args()
    asr = json.load(open(args.words))
    vo_dur = len(audio.load_audio(args.vo)) / audio.SR
    timeline, total = build_timeline(vo_dur, asr)
    for sc in timeline:
        print(f"{sc['start']:6.1f}-{sc['end']:6.1f} ({sc['end'] - sc['start']:4.1f}s) {sc['name']}")
        for c0, c1, c in sc["caps"]:
            print(f"        {sc['start'] + c0:6.1f}  {c}")
    print(f"всего {total:.1f}s, сцен {len(timeline)}")
    if args.plan_only:
        return
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    wav = os.path.splitext(args.out)[0] + ".wav"
    mix(timeline, total, args.vo, wav)
    print("рендер...", flush=True)
    build.render_video(timeline, total, wav, args.out)
    print("готово:", args.out)


if __name__ == "__main__":
    main()
