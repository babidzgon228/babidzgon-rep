# -*- coding: utf-8 -*-
"""Озвучка (Piper TTS, локально), фоновая lo-fi музыка и звуковые эффекты."""
import os
import wave

import numpy as np

SR = 44100


# ---------------------------------------------------------------- TTS
def _resample(x, sr_from, sr_to):
    if sr_from == sr_to:
        return x
    n = int(round(len(x) * sr_to / sr_from))
    t_old = np.linspace(0, 1, len(x), endpoint=False)
    t_new = np.linspace(0, 1, n, endpoint=False)
    return np.interp(t_new, t_old, x).astype(np.float32)


def _trim(x, thr=0.012, pad=int(0.03 * SR)):
    idx = np.where(np.abs(x) > thr)[0]
    if len(idx) == 0:
        return x
    a = max(0, idx[0] - pad)
    b = min(len(x), idx[-1] + pad)
    return x[a:b]


class Voice:
    def __init__(self, model_path):
        from piper import PiperVoice
        self.v = PiperVoice.load(model_path)
        self.sr = self.v.config.sample_rate

    def say(self, text, length_scale=0.93, noise_scale=0.72, noise_w=0.9, sent_gap=0.16):
        from piper.config import SynthesisConfig
        cfg = SynthesisConfig(length_scale=length_scale, noise_scale=noise_scale,
                              noise_w_scale=noise_w, normalize_audio=True)
        parts = []
        for ch in self.v.synthesize(text, syn_config=cfg):
            a = getattr(ch, "audio_float_array", None)
            if a is None:
                a = ch.audio_int16_array.astype(np.float32) / 32768.0
            a = _trim(_resample(np.asarray(a, dtype=np.float32), self.sr, SR))
            parts.append(a)
            parts.append(np.zeros(int(sent_gap * SR), np.float32))
        if parts:
            parts.pop()
        return np.concatenate(parts) if parts else np.zeros(1, np.float32)


# ---------------------------------------------------------------- music
def _note(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _env(n, a=0.01, r=0.2):
    e = np.ones(n, np.float32)
    na, nr = int(a * SR), int(r * SR)
    if na:
        e[:na] = np.linspace(0, 1, na)
    if nr and nr < n:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def lofi_music(duration, bpm=84, seed=7):
    """Тёплый чиптюн-лоуфай: аккорды, арпеджио, бочка/снейр/хэт, винил-шум."""
    rng = np.random.default_rng(seed)
    n = int(duration * SR) + SR
    out = np.zeros(n, np.float32)
    beat = 60.0 / bpm
    bar = 4 * beat
    # Am7 - Fmaj7 - Cmaj7 - G6
    chords = [[57, 60, 64, 67], [53, 57, 60, 64], [48, 55, 59, 64], [55, 59, 62, 64]]
    bass = [45, 41, 48, 43]
    t_bar = 0.0
    i = 0
    while t_bar < duration + bar:
        ch = chords[i % 4]
        s0 = int(t_bar * SR)
        if s0 >= n:
            break
        # pad (triangle)
        L = int(bar * SR)
        tt = np.arange(L) / SR
        pad = np.zeros(L, np.float32)
        for m in ch:
            f = _note(m)
            pad += (2 / np.pi) * np.arcsin(np.sin(2 * np.pi * f * tt + 0.3 * np.sin(2 * np.pi * 0.5 * tt)))
        pad *= 0.035 * _env(L, 0.25, 0.4)
        # bass (sine-ish square)
        fb = _note(bass[i % 4])
        bs = np.tanh(2.0 * np.sin(2 * np.pi * fb * tt)) * 0.09 * _env(L, 0.02, 0.3)
        # arpeggio 8th notes, soft square
        arp = np.zeros(L, np.float32)
        step = beat / 2
        for k in range(8):
            m = ch[[0, 2, 1, 3, 2, 1, 3, 2][k]] + 12
            a0 = int(k * step * SR)
            ln = int(step * SR * 0.9)
            ta = np.arange(ln) / SR
            sq = np.sign(np.sin(2 * np.pi * _note(m) * ta)) * 0.5 + 0.5 * np.sin(2 * np.pi * _note(m) * ta)
            arp[a0:a0 + ln] += sq * 0.022 * np.exp(-ta * 9)
        seg = pad + bs + arp
        e = min(n, s0 + L)
        out[s0:e] += seg[:e - s0]
        # drums
        for b in range(4):
            tb = s0 + int(b * beat * SR)
            if b in (0, 2):  # kick
                ln = int(0.25 * SR)
                tk = np.arange(ln) / SR
                f = 110 * np.exp(-tk * 18) + 45
                k = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tk * 12) * 0.32
                e = min(n, tb + ln)
                if e > tb:
                    out[tb:e] += k[:e - tb]
            if b in (1, 3):  # snare
                ln = int(0.18 * SR)
                ts = np.arange(ln) / SR
                sn = rng.normal(0, 1, ln) * np.exp(-ts * 22) * 0.07
                sn += np.sin(2 * np.pi * 190 * ts) * np.exp(-ts * 30) * 0.06
                e = min(n, tb + ln)
                if e > tb:
                    out[tb:e] += sn[:e - tb]
            for hh in (0, 0.5):  # hats
                th = tb + int(hh * beat * SR) + int(rng.normal(0, 0.006) * SR)
                ln = int(0.05 * SR)
                h = np.diff(rng.normal(0, 1, ln + 1)) * np.exp(-np.arange(ln) / SR * 70) * 0.025
                if 0 <= th and th + ln < n:
                    out[th:th + ln] += h
        t_bar += bar
        i += 1
    # vinyl crackle + hiss
    out += rng.normal(0, 0.003, n).astype(np.float32)
    pops = rng.integers(0, n, int(duration * 6))
    out[pops] += rng.normal(0, 0.15, len(pops))
    # gentle lowpass (one-pole) for lo-fi warmth
    y = np.zeros_like(out)
    a = 0.35
    acc = 0.0
    for j in range(0, n, 4096):
        blk = out[j:j + 4096]
        res = np.empty_like(blk)
        for q in range(len(blk)):
            acc += a * (blk[q] - acc)
            res[q] = acc
        y[j:j + 4096] = res
    return y[: int(duration * SR)]


def whoosh(rng, dur=0.22, vol=0.05):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = rng.normal(0, 1, n).astype(np.float32)
    # moving band via simple resonator sweep
    f = np.linspace(2500, 400, n)
    y = np.zeros(n, np.float32)
    s1 = s2 = 0.0
    for i in range(n):
        w = 2 * np.pi * f[i] / SR
        r = 0.97
        y0 = x[i] + 2 * r * np.cos(w) * s1 - r * r * s2
        s2, s1 = s1, y0
        y[i] = y0
    y /= np.max(np.abs(y)) + 1e-9
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    return y * env * vol


def blip(freq=880, dur=0.07, vol=0.05):
    n = int(dur * SR)
    t = np.arange(n) / SR
    return (np.sign(np.sin(2 * np.pi * freq * t)) * np.exp(-t * 40) * vol).astype(np.float32)


def write_wav(path, x):
    x = np.clip(x, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
