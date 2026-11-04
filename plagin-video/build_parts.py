# -*- coding: utf-8 -*-
"""Длинный ролик -> 2 части по ≤ 3 минуты (для Reels / Shorts).

    python3 build_parts.py --vo voice.mp3 --words words.json --split agent_pointer --outdir out
"""
import argparse
import json
import os
from multiprocessing import Process

import numpy as np

import audio
import build
import build_long

END_CARD = 2.6    # «Продолжение в части 2»
TITLE_CARD = 1.8  # «Часть 2»


def shift(sc, dt):
    return dict(sc, start=sc["start"] + dt, end=sc["end"] + dt)


def make_parts(timeline, voice, split_name):
    idx = next(i for i, sc in enumerate(timeline) if sc["name"] == split_name)
    cut = timeline[idx]["start"]
    sr = audio.SR
    # часть 1: начало -> карточка «продолжение»
    p1 = timeline[:idx] + [dict(name="to_be_continued", start=cut, end=cut + END_CARD, caps=[])]
    v1 = voice[: int(cut * sr)]
    # часть 2: карточка «часть 2» -> остаток (с аутро)
    p2 = [dict(name="part2_title", start=0.0, end=TITLE_CARD, caps=[])]
    p2 += [shift(sc, TITLE_CARD - cut) for sc in timeline[idx:]]
    v2 = np.concatenate([np.zeros(int(TITLE_CARD * sr), np.float32), voice[int(cut * sr):]])
    return [(p1, v1), (p2, v2)]


def render_part(tl, v, out):
    total = tl[-1]["end"]
    wav = os.path.splitext(out)[0] + ".wav"
    build_long.mix(tl, total, v, wav)
    build.render_video(tl, total, wav, out)
    print("готово:", out, f"{total:.1f}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vo", required=True)
    ap.add_argument("--words", required=True)
    ap.add_argument("--split", default="agent_pointer", help="сцена, с которой начинается 2-я часть")
    ap.add_argument("--outdir", default="out")
    args = ap.parse_args()
    asr = json.load(open(args.words))
    voice = audio.load_audio(args.vo)
    timeline, _ = build_long.build_timeline(len(voice) / audio.SR, asr)
    parts = make_parts(timeline, voice, args.split)
    os.makedirs(args.outdir, exist_ok=True)
    procs = []
    for i, (tl, v) in enumerate(parts, 1):
        print(f"часть {i}: {tl[-1]['end']:.1f}s, сцен {len(tl)}", flush=True)
        p = Process(target=render_part, args=(tl, v, os.path.join(args.outdir, f"plagin_part{i}.mp4")))
        p.start()
        procs.append(p)
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
