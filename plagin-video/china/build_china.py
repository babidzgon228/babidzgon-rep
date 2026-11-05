# -*- coding: utf-8 -*-
"""Ролик «Жизнь в Китае»: озвучка ElevenLabs (1 или несколько файлов) -> видео.

Отличия от первых роликов:
- пиксель-арт сглаживается xBR (ffmpeg xbr=4) — гладкие края вместо «кубиков»;
- фото пользователя накладываются поверх в полном качестве, с плавным наездом;
- субтитры рисует libass (ASS) уже на финальном разрешении.

    python3 build_china.py --vo a.mp3 b.mp3 --words a.json b.json --outdir out [--parts]
"""
import argparse
import json
import os
import subprocess
import sys
from multiprocessing import Process

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import art  # noqa: E402
import plagin2  # noqa: E402,F401  (новый внешний вид Плагина — до art2/art3)
import art2  # noqa: E402,F401
import art3  # noqa: E402,F401
import audio  # noqa: E402
import build_long  # noqa: E402
from script_china import PART_SPLITS, SCENES  # noqa: E402

FPS = 30
OW, OH = 1080, 1920
GAP = 0.35  # пауза между файлами озвучки
PHOTO_DIR = os.path.join(HERE, "photos")
# сцена -> (файл, x, y, w, h) в пикселях финального кадра (без белой рамки 12px)
PHOTOS = {
    "photo_campus": ("1_campus.jpg", 28, 330, 1000, 562),
    "photo_skyscrapers": ("2_skyscrapers.jpg", 78, 260, 900, 720),
    "photo_temples": ("3_temples.jpg", 78, 260, 900, 720),
    "photo_sea": ("4_sea.jpg", 118, 170, 820, 1084),
}
CAP_Y = 1530
FONT_DIR = "/usr/share/fonts/opentype/inter"


# ---------------------------------------------------------------- субтитры (ASS)
def ass_time(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def ass_text(cap):
    out, hl = "", False
    for ch in cap:
        if ch == "[":
            out += "{\\c&H3C62FF&}"
        elif ch == "]":
            out += "{\\c&HFFFFFF&}"
        elif ch in "{}":
            continue
        else:
            out += ch
    return out


def write_ass(timeline, path):
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {OW}", f"PlayResY: {OH}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        "Style: Cap,Inter Black,68,&H00FFFFFF,&H00FFFFFF,&H00140C18,&H64100810,0,0,0,0,100,100,1,0,1,7,6,5,"
        "80,80,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for sc in timeline:
        for c0, c1, cap in sc["caps"]:
            a, b = sc["start"] + c0, sc["start"] + c1
            pop = "{\\pos(540,%d)\\fscx84\\fscy84\\t(0,110,\\fscx100\\fscy100)}" % CAP_Y
            lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Cap,,0,0,0,,{pop}{ass_text(cap)}")
    open(path, "w").write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- рендер
def render(timeline, voice, out):
    total = timeline[-1]["end"]
    base = os.path.splitext(out)[0]
    wav = base + ".wav"
    build_long.mix(timeline, total, voice, wav)
    ass = base + ".ass"
    write_ass(timeline, ass)

    photo_scenes = [sc for sc in timeline if sc["name"] in PHOTOS]
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{art.W}x{art.H}",
           "-r", str(FPS), "-i", "-", "-i", wav]
    for sc in photo_scenes:
        cmd += ["-i", os.path.join(PHOTO_DIR, PHOTOS[sc["name"]][0])]
    fc = [f"[0:v]xbr=4,scale={OW}:{OH}:flags=lanczos[v0]"]
    for k, sc in enumerate(photo_scenes):
        _, x, y, w, h = PHOTOS[sc["name"]]
        s, e = sc["start"], sc["end"]
        n = int((e - s) * FPS) + 2
        fc.append(
            f"[{k + 2}:v]scale={2 * w}:{2 * h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={2 * w}:{2 * h},unsharp=5:5:0.6,"
            f"zoompan=z='1+0.0005*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={w}x{h}:fps={FPS},"
            f"pad={w + 24}:{h + 24}:12:12:white,setpts=PTS-STARTPTS+{s:.3f}/TB[p{k}]")
        fc.append(f"[v{k}][p{k}]overlay={x - 12}:{y - 12}:enable='between(t,{s:.3f},{e:.3f})'"
                  f":eof_action=pass[v{k + 1}]")
    last = f"v{len(photo_scenes)}"
    fc.append(f"[{last}]ass={ass}:fontsdir={FONT_DIR}[vout]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    nframes = int(total * FPS) + 1
    si = 0
    for fi in range(nframes):
        T = fi / FPS
        while si < len(timeline) - 1 and T >= timeline[si]["end"]:
            si += 1
        sc = timeline[si]
        t = T - sc["start"]
        im = art.SCENE_FUNCS[sc["name"]](t, int(t * FPS), sc["end"] - sc["start"]).convert("RGB")
        ff.stdin.write(im.tobytes())
        if fi % 300 == 0:
            print(f"  {os.path.basename(out)}: {fi}/{nframes}", flush=True)
    ff.stdin.close()
    ff.wait()
    print("готово:", out, f"{total:.1f}s", flush=True)


# ---------------------------------------------------------------- части
def split_parts(timeline, voice):
    sr = audio.SR
    cuts = [next(sc["start"] for sc in timeline if sc["name"] == n) for n in PART_SPLITS]
    bounds = [0.0] + cuts + [None]
    parts = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        last = b is None
        scs = [sc for sc in timeline if sc["start"] >= a - 1e-6 and (last or sc["start"] < b - 1e-6)]
        off = 0.0
        tl = []
        if i > 0:
            off = 1.8
            tl.append(dict(name=f"ptitle{i + 1}", start=0.0, end=off, caps=[]))
        tl += [dict(sc, start=sc["start"] - a + off, end=sc["end"] - a + off) for sc in scs]
        v = voice[int(a * sr): (int(b * sr) if not last else len(voice))]
        v = np.concatenate([np.zeros(int(off * sr), np.float32), v])
        if not last:
            end = tl[-1]["end"]
            tl.append(dict(name=f"tbc{i + 2}", start=end, end=end + 2.6, caps=[]))
        parts.append((tl, v))
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vo", nargs="+", required=True)
    ap.add_argument("--words", nargs="+", required=True)
    ap.add_argument("--outdir", default=os.path.join(HERE, "out"))
    ap.add_argument("--parts", action="store_true", help="ещё и части по ≤ 3 мин")
    ap.add_argument("--plan-only", action="store_true")
    args = ap.parse_args()
    voices, words, off = [], [], 0.0
    for vp, wp in zip(args.vo, args.words):
        v = audio.load_audio(vp)
        for w in json.load(open(wp)):
            words.append(dict(w, start=w["start"] + off, end=w["end"] + off))
        voices.append(v)
        voices.append(np.zeros(int(GAP * audio.SR), np.float32))
        off += len(v) / audio.SR + GAP
    voice = np.concatenate(voices[:-1])
    timeline, total = build_long.build_timeline(len(voice) / audio.SR, words, scenes=SCENES)
    timeline[-1]["name"] = "outro_china"
    for sc in timeline:
        print(f"{sc['start']:6.1f}-{sc['end']:6.1f} ({sc['end'] - sc['start']:4.1f}s) {sc['name']}")
    print(f"всего {total:.1f}s")
    if args.plan_only:
        return
    os.makedirs(args.outdir, exist_ok=True)
    jobs = [(timeline, voice, os.path.join(args.outdir, "plagin_china_full.mp4"))]
    if args.parts:
        for i, (tl, v) in enumerate(split_parts(timeline, voice), 1):
            print(f"часть {i}: {tl[-1]['end']:.1f}s")
            jobs.append((tl, v, os.path.join(args.outdir, f"plagin_china_part{i}.mp4")))
    procs = [Process(target=render, args=j) for j in jobs]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
