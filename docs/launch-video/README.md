# Launch video source

The 56-second crewlore launch video embedded in the top-level README is rendered from the two files in this directory. Nothing in it is a screen recording: every frame is drawn by `launch.html`, a single self-contained page where every scene is a pure function of time, and `render.py` steps through that time one frame at a time, captures each frame through the locally installed Google Chrome, and hands the frames to ffmpeg.

The rendered MP4 is not committed (`docs/assets/*.mp4` is gitignored); the README embeds a copy uploaded to GitHub's attachment storage so that clones stay small. The score is composed from `audio/score.json` by `audio/score.py` (see below).

## Rendering

Requirements: Google Chrome, ffmpeg, and [uv](https://docs.astral.sh/uv/), which fetches Playwright on the fly. No Playwright browser download is needed because the script drives the Chrome you already have.

```bash
# from the repo root: a few stills, for checking a scene (prints the PNG paths)
uv run --with playwright python docs/launch-video/render.py stills 5.2 34 55.5

# the full video -> docs/assets/crewlore-launch-16x9.mp4 (about three minutes on a laptop)
uv run --with playwright python docs/launch-video/render.py video
```

## Editing

Open `launch.html` in a browser and call `seek(34)` in the console to jump to any second. The `scenes` array at the bottom of the file holds each scene's start and end time and an `update(t, $)` function that positions every element for local time `t`; timings are plain numbers, so moving a caption earlier or holding a scene longer is a one-number change. Scene content is ordinary HTML, so wording changes are text edits.

The terminal scenes show real output: the install scene mirrors pipx, and the import, query and MCP scenes reproduce what `lore` printed for the committed pull-request example in `docs/examples/pydantic-ai-prs/` (24 agent-authored pull requests, 130 claims, 173 anchors). The agent conversation in the MCP scene is illustrative. If the example is re-run, update the numbers in the import and compile scenes to match `stats.json`.

Fonts are resolved by name, because headless Chrome does not map the generic `system-ui` and `ui-monospace` families on macOS: headlines use `BlinkMacSystemFont` (SF Pro) with Helvetica Neue as the fallback, and terminals use Menlo. On Linux, swap in Inter and a monospace font you have installed.

## Sound

`audio/score.json` is the score: tempo, sections with one chord per bar and an energy level, and a hit list, one sound event per on-screen moment (a card popping in, a line of output, a number landing, the wordmark). `audio/score.py` synthesises everything deterministically with numpy and scipy, places each event at its exact sample, and masters the mix with ffmpeg's loudnorm to -14 LUFS integrated and -1 dBTP, then prints the measured result.

```bash
uv run --with numpy,scipy python docs/launch-video/audio/score.py      # -> docs/assets/crewlore-launch-score.wav
uv run --with playwright python docs/launch-video/render.py mux          # put it onto the rendered MP4
```

When a scene's timing changes in `launch.html`, move the matching `t` values in `score.json` and re-run both. The score is verified by measurement, not by ear: listen on speakers and on a laptop before publishing.
