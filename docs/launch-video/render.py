#!/usr/bin/env python3
"""Render launch.html into stills or the finished launch video.

The page exposes `window.seek(t)` (every frame is a pure function of t, nothing depends
on wall-clock time) and `window.DURATION`. Frames are captured through the locally
installed Google Chrome via Playwright, then encoded with ffmpeg.

Requires: Google Chrome, ffmpeg, and `uv` (which fetches Playwright on the fly).

Usage, from the repo root:
  uv run --with playwright python docs/launch-video/render.py stills 5.2 34
  uv run --with playwright python docs/launch-video/render.py video [--fps 30] [--workers 3]

`video` writes docs/assets/crewlore-launch-16x9.mp4 (gitignored). `stills` writes PNGs
to a temporary directory and prints their paths.
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "launch.html"
DEFAULT_OUTPUT = HERE.parent / "assets" / "crewlore-launch-16x9.mp4"
W, H = 1920, 1080


def _open(p):
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    page.goto(HTML.as_uri())
    page.wait_for_function(
        "typeof window.seek === 'function' && typeof window.DURATION === 'number'"
    )
    page.evaluate("document.fonts.ready")
    return browser, page


def _duration() -> float:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, page = _open(p)
        d = page.evaluate("window.DURATION")
        browser.close()
    return float(d)


def stills(times: list[float]) -> list[Path]:
    from playwright.sync_api import sync_playwright

    outdir = Path(tempfile.mkdtemp(prefix="crewlore-launch-stills-"))
    paths = []
    with sync_playwright() as p:
        browser, page = _open(p)
        for t in times:
            page.evaluate("t => window.seek(t)", t)
            path = outdir / f"t{t:06.2f}.png"
            page.screenshot(path=str(path))
            paths.append(path)
        browser.close()
    return paths


def _render_range(job: tuple[int, int, int, str]) -> int:
    start, end, fps, outdir = job
    from playwright.sync_api import sync_playwright

    out = Path(outdir)
    with sync_playwright() as p:
        browser, page = _open(p)
        for i in range(start, end):
            page.evaluate("t => window.seek(t)", i / fps)
            page.screenshot(path=str(out / f"f{i:05d}.png"))
        browser.close()
    return end - start


def video(fps: int, workers: int, output: Path) -> Path:
    duration = _duration()
    total = int(math.ceil(duration * fps))
    frames = Path(tempfile.mkdtemp(prefix="crewlore-launch-frames-"))
    chunk = int(math.ceil(total / workers))
    jobs = [(s, min(s + chunk, total), fps, str(frames)) for s in range(0, total, chunk)]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        done = sum(ex.map(_render_range, jobs))
    elapsed = time.time() - t0
    print(f"rendered {done} frames ({duration:.1f}s @ {fps}fps) in {elapsed:.0f}s", flush=True)
    if done != total:
        raise SystemExit(f"expected {total} frames, got {done}")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-framerate",
        str(fps),
        "-i",
        str(frames / "f%05d.png"),
        # A silent stereo track: some upload pipelines reject video-only files.
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-shortest",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        str(output),
    ]
    subprocess.run(cmd, check=True)
    shutil.rmtree(frames, ignore_errors=True)
    print(f"wrote {output} ({output.stat().st_size / 1e6:.1f} MB)")
    return output


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stills", help="render PNG stills at the given times (seconds)")
    s.add_argument("times", nargs="+", type=float)
    v = sub.add_parser("video", help="render every frame and encode the MP4")
    v.add_argument("--fps", type=int, default=30)
    v.add_argument("--workers", type=int, default=3, help="parallel Chrome instances")
    v.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args(argv)
    if args.cmd == "stills":
        for path in stills(args.times):
            print(path)
    else:
        video(args.fps, args.workers, args.output)


if __name__ == "__main__":
    main(sys.argv[1:])
