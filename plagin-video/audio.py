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


# ---------------------------------------------------------------- внешняя озвучка (ElevenLabs и т.п.)
def load_audio(path):
    """Любой аудиофайл -> float32 mono 44.1 кГц (через ffmpeg)."""
    import subprocess
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def _speech_runs(x, frame=0.01, min_sil=0.12):
    """-> (энергия по кадрам, список пауз (начало, конец) в секундах)."""
    hop = int(frame * SR)
    n = len(x) // hop
    e = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(e / (e.max() + 1e-9))
    sil = db < -38
    runs, i = [], 0
    while i < n:
        if sil[i]:
            j = i
            while j < n and sil[j]:
                j += 1
            if (j - i) * frame >= min_sil:
                runs.append((i * frame, j * frame))
            i = j
        else:
            i += 1
    return db, runs


def split_by_pauses(x, weights, frame=0.01):
    """Режет один длинный файл на len(weights) кусков по паузам.

    Позиция каждой границы оценивается по «чистому» времени речи (без пауз)
    пропорционально количеству букв, затем динамическим программированием
    выбираются паузы, лучше всего совпадающие с этими оценками (по порядку).
    """
    x = _trim(x, thr=0.01, pad=0)
    total = len(x) / SR
    db, runs = _speech_runs(x, frame)
    speech = (db >= -38).astype(float)
    S = np.concatenate([[0.0], np.cumsum(speech) * frame])  # время речи до кадра i
    tot_sp = S[-1]
    cands = [((a + b) / 2, b - a, S[min(int(a / frame), len(S) - 1)]) for a, b in runs]
    nb = len(weights) - 1
    cum = np.cumsum(weights)[:-1] / np.sum(weights)
    exp_sp = cum * tot_sp
    if len(cands) < nb:
        cuts = list(np.interp(exp_sp, S, np.arange(len(S)) * frame))
    else:
        C = len(cands)
        cost = np.array([[((exp_sp[i] - cands[j][2]) / 0.6) ** 2 - 1.5 * min(cands[j][1], 0.8)
                          for j in range(C)] for i in range(nb)])
        dp = np.full((nb, C), np.inf)
        bk = np.zeros((nb, C), int)
        dp[0] = cost[0]
        for i in range(1, nb):
            best, arg = np.inf, -1
            for j in range(C):
                if j > 0 and dp[i - 1][j - 1] < best:
                    best, arg = dp[i - 1][j - 1], j - 1
                if arg >= 0:
                    dp[i][j] = best + cost[i][j]
                    bk[i][j] = arg
        j = int(np.argmin(dp[-1]))
        sel = [j]
        for i in range(nb - 1, 0, -1):
            j = bk[i][j]
            sel.append(j)
        cuts = [cands[j][0] for j in reversed(sel)]
    expect = np.interp(exp_sp, S, np.arange(len(S)) * frame)
    edges = [0.0] + list(cuts) + [total]
    parts = [_trim(x[int(a * SR): int(b * SR)]) for a, b in zip(edges[:-1], edges[1:])]
    return parts, cuts, expect


class ExternalVoice:
    """Готовая озвучка: папка с файлами 01.mp3, 02.mp3 ... (по одному на реплику)
    или один общий файл, который режется по паузам."""

    def __init__(self, path, texts):
        self.parts = []
        if os.path.isdir(path):
            files = sorted(f for f in os.listdir(path)
                           if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg", ".flac")))
            if len(files) != len(texts):
                raise SystemExit(f"в папке {len(files)} файлов, а реплик {len(texts)}")
            self.parts = [_trim(load_audio(os.path.join(path, f))) for f in files]
            self.cuts = None
        else:
            w = [max(1, sum(ch.isalpha() for ch in t)) for t in texts]
            self.parts, self.cuts, self.expect = split_by_pauses(load_audio(path), w)


def moving_avg(x, win):
    """Скользящее среднее за O(N) (np.convolve на длинных треках слишком медленный)."""
    c = np.concatenate([[0.0], np.cumsum(x, dtype=np.float64)])
    h = win // 2
    idx = np.arange(len(x))
    a = np.clip(idx - h, 0, len(x))
    b = np.clip(idx + h + 1, 0, len(x))
    return ((c[b] - c[a]) / (b - a)).astype(np.float32)
