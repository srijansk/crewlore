#!/usr/bin/env python3
"""Original score for the launch video, composed to its timeline.

score.json holds the tempo, the sections (energy and one chord per bar) and a hit list: a
sound event for each moment on screen (a card popping in, a line of output, a number landing),
placed at the exact sample. Everything is synthesised here with numpy and scipy, deterministic
seeds throughout, then mastered with ffmpeg's loudnorm to the streaming norm (-14 LUFS
integrated, true peak at or below -1 dBTP) and measured back.

  uv run --with numpy,scipy python docs/launch-video/audio/score.py

Writes docs/assets/crewlore-launch-score.wav (gitignored). The method (a beat grid, chord per
bar, events on the picture's own moments, a loudness-normalised master) follows the approach
in Anannya Mishra's launch-film skill; the code is this file's own.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 48_000
TAU = 2 * np.pi
F32 = np.float32
HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "score.json").read_text())
OUT = (HERE / CFG["out"]).resolve()
DUR = float(CFG["duration"])
BPM = float(CFG.get("bpm", 120))
BEAT = 60.0 / BPM
BAR = 4 * BEAT
N = int(round(DUR * SR))

NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
QUALITY = {
    "": [0, 4, 7],
    "m": [0, 3, 7],
    "7": [0, 4, 7, 10],
    "maj7": [0, 4, 7, 11],
    "m7": [0, 3, 7, 10],
    "m9": [0, 3, 7, 10, 14],
    "maj9": [0, 4, 7, 11, 14],
    "add9": [0, 4, 7, 14],
    "sus2": [0, 2, 7],
    "sus4": [0, 5, 7],
}


# ----------------------------------------------------------------- primitives
def rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def n_(dur: float) -> int:
    return int(round(dur * SR))


def t_(dur: float) -> np.ndarray:
    return np.arange(n_(dur)) / SR


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def chord(name: str) -> dict:
    m = re.match(r"^([A-G])([#b]?)(.*)$", name)
    if not m or m.group(3) not in QUALITY:
        raise ValueError(f"unknown chord {name!r}")
    pc = NOTE[m.group(1)] + {"#": 1, "b": -1, "": 0}[m.group(2)]
    root = 52 + (pc - 52) % 12  # pad root between E3 and D#4
    intervals = QUALITY[m.group(3)]
    pad = [root + i for i in intervals[:4]]
    if len(pad) == 3:
        pad.append(root + 12)
    return {"pad": pad, "bass": 28 + (pc - 28) % 12, "arp": sorted(set(pad + [pad[0] + 12]))}


def decay(n: int, tau: float, attack: float = 0.0) -> np.ndarray:
    t = np.arange(n) / SR
    env = np.exp(-np.maximum(t - attack, 0.0) / tau)
    if attack > 0:
        env *= np.clip(t / attack, 0.0, 1.0)
    return env.astype(F32)


def adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    a_n, d_n, r_n = max(1, n_(a)), max(1, n_(d)), max(1, n_(r))
    s_n = max(0, n - a_n - d_n - r_n)
    env = np.concatenate(
        [
            0.5 - 0.5 * np.cos(np.linspace(0, np.pi, a_n, endpoint=False)),
            np.linspace(1.0, s, d_n, endpoint=False),
            np.full(s_n, s),
            s * (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, r_n))),
        ]
    )
    return np.pad(env, (0, max(0, n - len(env))))[:n].astype(F32)


def edge(x: np.ndarray, fi: float = 0.0005, fo: float = 0.008) -> np.ndarray:
    """Raised-cosine fades at both ends so no sound starts or stops on a step."""
    x = np.array(x, dtype=F32)
    a, b = min(len(x), n_(fi)), min(len(x), n_(fo))
    if a:
        x[:a] *= (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, a, endpoint=False))).astype(F32)
    if b:
        x[-b:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, b))).astype(F32)
    return x


def sos(kind: str, fc, order: int = 2):
    nyq = SR * 0.45
    if kind == "band":
        return signal.butter(
            order, [min(fc[0], nyq - 1), min(fc[1], nyq)], "band", fs=SR, output="sos"
        )
    return signal.butter(order, min(fc, nyq), kind, fs=SR, output="sos")


def lp(x, fc, order=2):
    return signal.sosfilt(sos("low", fc, order), x).astype(F32)


def hp(x, fc, order=2):
    return signal.sosfilt(sos("high", fc, order), x).astype(F32)


def bp(x, lo, hi, order=2):
    return signal.sosfilt(sos("band", (lo, hi), order), x).astype(F32)


def sine(freq, n: int, phase0: float = 0.0) -> np.ndarray:
    f = np.broadcast_to(np.asarray(freq, np.float64), (n,))
    ph = phase0 + np.concatenate([[0.0], np.cumsum(f[:-1])]) / SR
    return np.sin(TAU * ph).astype(F32)


def saw(freq: float, n: int, phase0: float = 0.0) -> np.ndarray:
    """Band-limited sawtooth: additive sum of harmonics below the Nyquist limit."""
    t = np.arange(n) / SR
    out = np.zeros(n, np.float64)
    k_max = int(min(60, (SR * 0.45) // freq))
    for k in range(1, k_max + 1):
        out += np.sin(TAU * (k * freq * t + k * phase0)) / k
    return (out * (2 / np.pi)).astype(F32)


def noise(n: int, seed: int) -> np.ndarray:
    return rng(seed).standard_normal(n).astype(F32)


def sweep_noise(dur: float, f_start: float, f_end: float, seed: int, order: int = 2) -> np.ndarray:
    """Noise through a band-pass whose centre glides from f_start to f_end (block-wise)."""
    n = n_(dur)
    x = noise(n, seed)
    out = np.zeros(n, F32)
    block = n_(0.012)
    centres = np.geomspace(f_start, f_end, max(2, n // block + 1))
    for i, c in enumerate(centres):
        a, b = i * block, min(n, (i + 1) * block + block)
        if a >= n:
            break
        seg = bp(x[a:b], c / 1.6, c * 1.6, order)
        out[a:b] += edge(seg, 0.004, 0.004)
    return out


def pan(x: np.ndarray, p: float) -> np.ndarray:
    p = float(np.clip(p, -1, 1))
    left, right = np.cos((p + 1) * np.pi / 4) * np.sqrt(2), np.sin((p + 1) * np.pi / 4) * np.sqrt(2)
    return np.stack([x * left, x * right], 1).astype(F32)


def norm(x: np.ndarray, peak: float = 1.0) -> np.ndarray:
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    return (x * (peak / m)).astype(F32) if m > 0 else x


# ----------------------------------------------------------------- instruments
def pad(notes: list[int], dur: float, bright: float, seed: int, attack: float = 0.5) -> np.ndarray:
    n = n_(dur)
    out = np.zeros(n, np.float64)
    r = rng(seed)
    for i, m in enumerate(notes):
        f = midi_hz(m)
        for cents in (-7.0, 0.0, 7.0):
            out += saw(f * 2 ** (cents / 1200), n, r.random()) * (0.6 if cents else 1.0)
        out += sine(f / 2, n, r.random()) * 0.35 * (i == 0)
    out = lp(out.astype(F32), 380 + 2600 * bright, 4)
    return edge(norm(out, 0.9) * adsr(n, attack, 0.3, 0.85, 0.9), 0.005, 0.02)


def sub(m: int, dur: float, seed: int = 0) -> np.ndarray:
    n = n_(dur)
    f = midi_hz(m)
    x = sine(f, n) + 0.18 * sine(2 * f, n)
    return edge(np.tanh(1.6 * x).astype(F32) * decay(n, dur * 0.55, 0.004))


def heartbeat(m: int) -> np.ndarray:
    n = n_(0.6)
    out = np.zeros(n, F32)
    for at, lvl in ((0.0, 1.0), (0.17, 0.75)):
        s = sub(m, 0.25) * lvl
        i = n_(at)
        out[i : i + len(s)] += s[: n - i]
    return lp(out, 150, 2)


def kick() -> np.ndarray:
    n = n_(0.42)
    t = np.arange(n) / SR
    f = 42 + 130 * np.exp(-t / 0.045)
    body = sine(f, n) * decay(n, 0.13)
    click = hp(noise(n_(0.01), 11), 2500) * decay(n_(0.01), 0.002)
    out = body.copy()
    out[: len(click)] += 0.35 * click
    return edge(np.tanh(1.3 * out).astype(F32))


def clap(seed: int = 3) -> np.ndarray:
    n = n_(0.3)
    out = np.zeros(n, F32)
    for k, at in enumerate((0.0, 0.011, 0.022, 0.034)):
        burst = bp(noise(n_(0.26), seed + k), 900, 4800) * decay(n_(0.26), 0.012 if k < 3 else 0.09)
        i = n_(at)
        out[i : i + len(burst)] += burst[: n - i]
    return edge(norm(out, 0.9))


def snare(seed: int = 5) -> np.ndarray:
    n = n_(0.25)
    tone = sine(185, n) * decay(n, 0.05)
    body = bp(noise(n, seed), 600, 6000) * decay(n, 0.07)
    return edge(norm(0.6 * tone + body, 0.9))


def hat(open_: bool, seed: int) -> np.ndarray:
    n = n_(0.3 if open_ else 0.07)
    return edge(hp(noise(n, seed), 7500, 4) * decay(n, 0.11 if open_ else 0.022))


def pluck(m: int, seed: int) -> np.ndarray:
    n = n_(0.5)
    x = saw(midi_hz(m), n, rng(seed).random())
    x = lp(x, 2200, 2) * decay(n, 0.14, 0.002)
    return edge(norm(x, 0.8))


def bell(m: int, dur: float = 1.6) -> np.ndarray:
    n = n_(dur)
    f = midi_hz(m)
    out = np.zeros(n, F32)
    for ratio, amp, tau in (
        (1.0, 1.0, 0.7),
        (2.76, 0.45, 0.35),
        (5.4, 0.2, 0.18),
        (8.93, 0.08, 0.1),
    ):
        if ratio * f < SR * 0.45:
            out += amp * sine(ratio * f, n) * decay(n, tau, 0.002)
    return edge(norm(out, 0.8))


def tick(f: float = 3200.0, level: float = 1.0, tau: float = 0.004) -> np.ndarray:
    n = n_(0.03)
    return edge(norm(bp(noise(n, int(f)), f / 1.5, f * 1.5, 2) * decay(n, tau), level))


def click() -> np.ndarray:
    n = n_(0.04)
    x = sine(1500, n) * decay(n, 0.005)
    tk = 0.6 * tick(4000, 0.8, 0.0025)
    x[: len(tk)] += tk
    return edge(norm(x, 0.9))


def type_hit() -> np.ndarray:
    n = n_(0.08)
    thump = sine(95, n) * decay(n, 0.03)
    x = 0.7 * thump + 0.5 * np.pad(tick(2600, 1.0, 0.003), (0, n - n_(0.03)))
    return edge(norm(x, 0.8))


def swish(dur: float = 0.35, seed: int = 21) -> np.ndarray:
    n = n_(dur)
    x = sweep_noise(dur, 400, 6000, seed)
    return edge(norm(x * np.sin(np.pi * np.arange(n) / n).astype(F32), 0.7), 0.01, 0.02)


def whoosh(dur: float = 0.6, seed: int = 22) -> np.ndarray:
    n = n_(dur)
    x = sweep_noise(dur, 180, 3500, seed, 2)
    env = np.sin(np.pi * np.arange(n) / n) ** 1.5
    return edge(norm(x * env.astype(F32), 0.75), 0.02, 0.03)


def stamp() -> np.ndarray:
    n = n_(0.28)
    thump = sine(68, n) * decay(n, 0.09)
    burst = bp(noise(n, 31), 500, 2500) * decay(n, 0.025)
    return edge(norm(thump + 0.5 * burst, 0.9))


def thunk() -> np.ndarray:
    n = n_(0.22)
    t = np.arange(n) / SR
    f = 60 + 55 * np.exp(-t / 0.03)
    x = sine(f, n) * decay(n, 0.07) + 0.15 * lp(noise(n, 41), 900) * decay(n, 0.02)
    return edge(norm(x, 0.8))


def impact() -> np.ndarray:
    n = n_(1.2)
    t = np.arange(n) / SR
    boom = sine(48 + 40 * np.exp(-t / 0.05), n) * decay(n, 0.35)
    burst = lp(noise(n, 51), 2200) * decay(n, 0.12)
    tail = bp(noise(n, 52), 200, 1200) * decay(n, 0.5) * 0.25
    return edge(norm(np.tanh(1.4 * (boom + 0.6 * burst + tail)).astype(F32), 0.95))


def riser(dur: float = 1.45, seed: int = 61) -> np.ndarray:
    n = n_(dur)
    t = np.arange(n) / SR
    ramp = (t / dur) ** 2.2
    x = sweep_noise(dur, 250, 7000, seed) * ramp.astype(F32)
    tone = sine(110 * 2 ** (2 * t / dur), n) * ramp.astype(F32) * 0.25
    return edge(norm(x + tone, 0.8), 0.02, 0.004)


def snare_fill(dur: float = 1.5) -> np.ndarray:
    n = n_(dur)
    out = np.zeros(n, F32)
    hits = 12
    for k in range(hits):
        s = snare(seed=70 + k) * (0.35 + 0.65 * k / (hits - 1))
        i = n_(k * dur / hits)
        out[i : i + len(s)] += s[: n - i]
    return edge(norm(out, 0.9))


def shimmer(notes: list[int], dur: float = 4.5) -> np.ndarray:
    n = n_(dur)
    out = np.zeros(n, np.float64)
    for k, m in enumerate(notes):
        out += sine(midi_hz(m + 24), n, 0.1 * k) * adsr(n, 1.4, 0.5, 0.8, 2.4)
    return edge(norm(out.astype(F32), 0.6), 0.01, 0.05)


def logo_sting(notes: list[int]) -> np.ndarray:
    n = n_(4.5)
    out = np.zeros(n, F32)
    for k, m in enumerate(notes + [notes[0] + 12]):
        b = bell(m + 12, 3.2) * (0.9 - 0.12 * k)
        i = n_(0.012 * k)
        out[i : i + len(b)] += b[: n - i]
    boom = impact()
    out[: len(boom)] += 0.7 * boom
    sh = shimmer(notes)
    out[: len(sh)] += 0.5 * sh
    return edge(norm(out, 0.95), 0.001, 0.4)


# ----------------------------------------------------------------- mixing
class Bus:
    def __init__(self) -> None:
        self.x = np.zeros((N, 2), F32)

    def add(self, s: np.ndarray, at: float, gain: float = 1.0, pan_: float = 0.0) -> None:
        if s.ndim == 1:
            s = pan(s, pan_)
        i = int(round(at * SR))
        if i < 0:
            s, i = s[-i:], 0
        if i >= N:
            return
        j = min(N, i + len(s))
        self.x[i:j] += s[: j - i] * gain


BUSES = {k: Bus() for k in ("kick", "drums", "bass", "pad", "arp", "bell", "sfx")}
KICKS: list[float] = []
PLACED: list[tuple[float, str]] = []


def bars(section: dict):
    k, t = 0, section["start"]
    while t < section["end"] - 1e-9:
        yield t, min(BAR, section["end"] - t), chord(section["chords"][k % len(section["chords"])])
        t += BAR
        k += 1


def arrange() -> None:
    drums_out = float(CFG.get("drums_out", DUR))
    for si, sec in enumerate(CFG["sections"]):
        e = sec["energy"]
        bright = {"intro": 0.2, "groove": 0.45, "peak": 0.65, "outro": 0.55}[e]
        for bi, (t0, blen, ch) in enumerate(bars(sec)):
            seed = 1000 * si + bi
            BUSES["pad"].add(
                pad(ch["pad"], blen + 0.9, bright, seed, attack=1.2 if e == "intro" else 0.35),
                t0,
                0.5 if e == "outro" else 0.42,
            )
            if e == "intro":
                BUSES["bass"].add(heartbeat(ch["bass"] + 12), t0, 0.55)
                for b in (1, 3):  # clock ticks on beats 2 and 4
                    BUSES["sfx"].add(
                        tick(2400, 0.35, 0.003), t0 + b * BEAT, 0.5, pan_=0.3 if b == 1 else -0.3
                    )
            if e in ("groove", "peak"):
                for b in range(int(round(blen / BEAT))):
                    tb = t0 + b * BEAT
                    if tb >= drums_out - 1e-9:
                        break
                    BUSES["kick"].add(kick(), tb, 0.95)
                    KICKS.append(tb)
                    if b % 2 == 1:
                        BUSES["drums"].add(clap(seed + b), tb, 0.42)
                    BUSES["drums"].add(hat(True, seed * 7 + b), tb + BEAT / 2, 0.14, pan_=0.25)
                    if e == "peak":
                        for q in (1, 3):
                            BUSES["drums"].add(
                                hat(False, seed * 11 + b * 4 + q),
                                tb + q * BEAT / 4,
                                0.09,
                                pan_=-0.3,
                            )
                for q in range(int(round(blen / (BEAT / 2)))):
                    tq = t0 + q * BEAT / 2
                    if tq >= drums_out - 1e-9:
                        break
                    BUSES["bass"].add(
                        sub(ch["bass"], BEAT / 2, seed), tq, 0.7 if q % 2 == 0 else 0.5
                    )
                if e == "peak":
                    arp = ch["arp"]
                    for q in range(int(round(blen / (BEAT / 2)))):
                        tq = t0 + q * BEAT / 2
                        if tq >= drums_out - 1e-9:
                            break
                        m = arp[(q + bi) % len(arp)]
                        BUSES["arp"].add(
                            pluck(m, seed * 13 + q), tq, 0.2, pan_=-0.4 + 0.8 * ((q + bi) % 2)
                        )
            if e == "outro":
                for k, m in enumerate(ch["pad"]):
                    BUSES["bell"].add(
                        bell(m + 12, 1.8), t0 + k * BEAT / 2 + 0.25, 0.14, pan_=-0.3 + 0.2 * k
                    )


HIT_GAIN = {
    "tick": 0.5,
    "soft-tick": 0.3,
    "tick-rise": 0.45,
    "type-hit": 0.5,
    "click": 0.5,
    "swish": 0.4,
    "whoosh": 0.5,
    "stamp": 0.7,
    "thunk": 0.6,
    "bell": 0.45,
    "impact": 0.9,
    "riser": 0.6,
    "drop": 1.0,
    "snare-fill": 0.55,
    "logo-sting": 0.9,
}


def place_hits() -> None:
    outro_chord = chord(CFG["sections"][-1]["chords"][0])
    rises = 0
    for h in sorted(CFG["hits"], key=lambda h: h["t"]):
        t, kind = float(h["t"]), h["kind"]
        gain = HIT_GAIN.get(kind)
        if gain is None:
            raise ValueError(f"unknown hit kind {kind!r}")
        if kind == "tick":
            s = tick()
        elif kind == "soft-tick":
            s = tick(2000, 0.6)
        elif kind == "tick-rise":
            s = tick(2200 * 2 ** (rises / 6), 0.9)
            rises += 1
        elif kind == "type-hit":
            s = type_hit()
        elif kind == "click":
            s = click()
        elif kind == "swish":
            s = swish(seed=int(t * 100))
        elif kind == "whoosh":
            s = whoosh(seed=int(t * 100))
        elif kind == "stamp":
            s = stamp()
        elif kind == "thunk":
            s = thunk()
        elif kind == "bell":
            s = bell(81 if rises == 0 else 84)
        elif kind == "impact":
            s = impact()
        elif kind == "riser":
            s = riser()
        elif kind == "drop":
            s = impact()
        elif kind == "snare-fill":
            s = snare_fill()
        else:  # logo-sting
            s = logo_sting(outro_chord["pad"])
        BUSES["sfx"].add(s, t, gain)
        PLACED.append((t, kind))


def mixdown() -> np.ndarray:
    # Side-chain: everything tonal ducks under each kick so the groove breathes.
    duck = np.ones(N, F32)
    env = decay(n_(0.3), 0.09)
    for tk in KICKS:
        i = n_(tk)
        j = min(N, i + len(env))
        duck[i:j] = np.minimum(duck[i:j], 1.0 - 0.55 * env[: j - i])
    gains = {
        "kick": 1.0,
        "drums": 1.0,
        "bass": 0.9,
        "pad": 1.0,
        "arp": 1.0,
        "bell": 1.0,
        "sfx": 1.0,
    }
    mix = np.zeros((N, 2), F32)
    for name, bus in BUSES.items():
        x = bus.x * gains[name]
        if name in ("pad", "bass", "arp"):
            x = x * duck[:, None]
        mix += x
    for a, b in CFG.get("silence", []):
        mix[n_(a) : n_(b)] = 0.0
    fade_from = float(CFG.get("fade_out", DUR - 0.5))
    k = n_(fade_from)
    if k < N:
        mix[k:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, N - k)))[:, None].astype(F32)
    mix = hp(mix, 28, 2)
    return norm(np.tanh(1.1 * mix).astype(F32), 0.7)


def master(mix: np.ndarray) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lufs, tp = float(CFG.get("lufs", -14.0)), float(CFG.get("true_peak", -1.0))
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "mix.wav"
        wavfile.write(raw, SR, mix)
        base = f"loudnorm=I={lufs}:TP={tp}:LRA=11"
        tone = "bass=g=2.5:f=230:w=0.7,treble=g=-2.5:f=4200"
        first = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(raw),
                "-af",
                f"{tone},{base}:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stderr
        m = json.loads(first[first.rindex("{") : first.rindex("}") + 1])
        measured = (
            f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
            f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(raw),
                "-af",
                f"{tone},{base}{measured}",
                "-ar",
                str(SR),
                "-c:a",
                "pcm_s24le",
                str(OUT),
            ],
            check=True,
        )
    report = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(OUT),
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    tail = report[report.rindex("Integrated loudness") :]
    integrated = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    peak = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB, {DUR:.1f} s)")
    print(f"integrated loudness {integrated.group(1) if integrated else '?'} LUFS (target {lufs})")
    print(f"true peak {peak.group(1) if peak else '?'} dBTP (limit {tp})")
    print(
        f"{len(PLACED)} hits placed sample-exactly, {len(KICKS)} kicks, sections: "
        + ", ".join(f"{s['energy']} {s['start']}-{s['end']}" for s in CFG["sections"])
    )


def main() -> None:
    arrange()
    place_hits()
    master(mixdown())


if __name__ == "__main__":
    sys.exit(main())
