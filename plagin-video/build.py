# -*- coding: utf-8 -*-
"""Сборка ролика: озвучка → музыка/эффекты → кадры → mp4.

    python3 build.py --voice /path/ru_RU-ruslan-medium.onnx --out out/plagin.mp4
"""
import argparse
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import art
import audio
from script import DEFAULT_LS, SCENES

FPS = 30
OW, OH = 1080, 1920
K = OW // art.W  # 6
CAP_FONT = "/usr/share/fonts/opentype/inter/Inter-Black.otf"
CAP_SIZE = 66
CAP_Y = 1530
HL = (255, 98, 60)


# ---------------------------------------------------------------- captions
def parse_caption(cap):
    """-> список слов; слово = список кусков (текст, подсветка)."""
    words = []
    hl = False
    for raw in cap.split():
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
        if pieces:
            words.append(pieces)
    return words


_cap_cache = {}


def render_caption(cap):
    if cap in _cap_cache:
        return _cap_cache[cap]
    f = ImageFont.truetype(CAP_FONT, CAP_SIZE)
    words = parse_caption(cap)
    space = f.getlength(" ") + 14
    maxw = 960
    lines, cur, curw = [], [], 0
    for pieces in words:
        ww = sum(f.getlength(t) for t, _ in pieces)
        if cur and curw + space + ww > maxw:
            lines.append((cur, curw))
            cur, curw = [], 0
        curw = curw + (space if cur else 0) + ww
        cur.append((pieces, ww))
    if cur:
        lines.append((cur, curw))
    lh = int(CAP_SIZE * 1.12)
    im = Image.new("RGBA", (OW, lh * len(lines) + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for li, (ws, lw) in enumerate(lines):
        x = (OW - lw) / 2
        y = 16 + li * lh
        for pieces, ww in ws:
            for t, h in pieces:
                d.text((x + 4, y + 7), t, font=f, fill=(20, 8, 16, 200), stroke_width=8,
                       stroke_fill=(20, 8, 16, 200))
                x += f.getlength(t)
            x -= ww
            for t, h in pieces:
                d.text((x, y), t, font=f, fill=HL if h else (255, 255, 255), stroke_width=8,
                       stroke_fill=(24, 12, 20))
                x += f.getlength(t)
            x += space
    _cap_cache[cap] = im
    return im


# ---------------------------------------------------------------- timeline
def build_timeline(voice):
    lead = 0.15
    t = 0.0
    timeline = []
    clips = []
    for si, (name, segs) in enumerate(SCENES):
        st = t
        t += lead if si == 0 else 0.0
        caps = []
        for seg in segs:
            a = voice.say(seg["say"], length_scale=seg.get("ls", DEFAULT_LS))
            d = len(a) / audio.SR
            clips.append((t, a))
            if seg["cap"]:
                caps.append((t - st, t - st + d + seg.get("gap", 0.15), seg["cap"]))
            t += d + seg.get("gap", 0.15)
            print(f"  [{name}] {d:5.2f}s  {seg['say']}", flush=True)
        timeline.append(dict(name=name, start=st, end=t, caps=caps))
    return timeline, clips, t


def mix_audio(timeline, clips, total, path):
    n = int((total + 0.5) * audio.SR)
    voice = np.zeros(n, np.float32)
    for t0, a in clips:
        s = int(t0 * audio.SR)
        voice[s:s + len(a)] += a[: n - s] * 0.9
    print("  music...", flush=True)
    music = audio.lofi_music(total + 0.5)
    music = music[:n] if len(music) >= n else np.pad(music, (0, n - len(music)))
    # дакинг музыки под голосом
    env = np.abs(voice)
    win = int(0.25 * audio.SR)
    env = np.convolve(env, np.ones(win) / win, mode="same")
    duck = 1.0 - 0.6 * np.clip(env / 0.04, 0, 1)
    music = music * 0.2 * duck
    sfx = np.zeros(n, np.float32)
    rng = np.random.default_rng(1)
    for sc in timeline[1:]:
        w = audio.whoosh(rng, 0.2, 0.06)
        s = max(0, int((sc["start"] - 0.08) * audio.SR))
        sfx[s:s + len(w)] += w[: n - s]
    out = timeline[-1]
    for i in range(7):  # клавиши в аутро
        b = audio.blip(1200 + i * 40, 0.04, 0.03)
        s = int((out["start"] + 0.12 + i / 8) * audio.SR)
        sfx[s:s + len(b)] += b[: n - s]
    audio.write_wav(path + ".voice.wav", voice)
    audio.write_wav(path + ".bed.wav", music + sfx)


def master_audio(path):
    """Голос: эквалайзер, лёгкая компрессия и комната; плюс музыкальная подложка."""
    vf = ("highpass=f=75,equalizer=f=180:t=q:w=1.2:g=2,equalizer=f=3200:t=q:w=1.5:g=2.5,"
          "acompressor=threshold=-20dB:ratio=3:attack=4:release=90:makeup=2,"
          "aecho=0.85:0.6:18|31:0.10|0.06")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", path + ".voice.wav", "-i", path + ".bed.wav",
           "-filter_complex",
           f"[0:a]{vf}[v];[v][1:a]amix=inputs=2:duration=longest:normalize=0,"
           "loudnorm=I=-14:TP=-1.5:LRA=9,aresample=44100[a]",
           "-map", "[a]", "-ac", "2", path]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------- render
def render_video(timeline, total, wav, out):
    nframes = int(total * FPS) + 1
    ff = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}",
         "-r", str(FPS), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out],
        stdin=subprocess.PIPE)
    si = 0
    for fi in range(nframes):
        T = fi / FPS
        while si < len(timeline) - 1 and T >= timeline[si]["end"]:
            si += 1
        sc = timeline[si]
        t = T - sc["start"]
        dur = sc["end"] - sc["start"]
        local_f = int(t * FPS)
        small = art.SCENE_FUNCS[sc["name"]](t, local_f, dur).convert("RGB")
        frame = small.resize((OW, OH), Image.NEAREST)
        # «панч»-зум на склейке
        if si > 0 and local_f < 5:
            s = 1.0 + 0.06 * (1 - local_f / 5)
            cw, ch = int(OW / s), int(OH / s)
            x0, y0 = (OW - cw) // 2, (OH - ch) // 2
            frame = frame.crop((x0, y0, x0 + cw, y0 + ch)).resize((OW, OH), Image.NEAREST)
        # субтитр
        for (c0, c1, cap) in sc["caps"]:
            if c0 <= t < c1:
                cim = render_caption(cap)
                age = t - c0
                if age < 0.1:
                    sc_ = 0.86 + 0.14 * (age / 0.1) + 0.04 * np.sin(age / 0.1 * np.pi)
                    cim = cim.resize((int(cim.width * sc_), int(cim.height * sc_)), Image.BILINEAR)
                fr = frame.convert("RGBA")
                fr.alpha_composite(cim, ((OW - cim.width) // 2, CAP_Y - cim.height // 2))
                frame = fr.convert("RGB")
                break
        ff.stdin.write(frame.tobytes())
        if fi % 150 == 0:
            print(f"  frame {fi}/{nframes}", flush=True)
    ff.stdin.close()
    ff.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", required=True, help="Piper .onnx model (ru_RU)")
    ap.add_argument("--out", default="out/plagin.mp4")
    ap.add_argument("--audio-only", action="store_true")
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    print("TTS...", flush=True)
    v = audio.Voice(args.voice)
    timeline, clips, total = build_timeline(v)
    total += 0.1
    print(f"total {total:.2f}s", flush=True)
    wav = os.path.splitext(args.out)[0] + ".wav"
    mix_audio(timeline, clips, total, wav)
    master_audio(wav)
    if args.audio_only:
        return
    print("render...", flush=True)
    render_video(timeline, total, wav, args.out)
    print("done:", args.out)


if __name__ == "__main__":
    main()
