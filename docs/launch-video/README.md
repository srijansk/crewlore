# Launch video source

The 56-second crewlore launch video embedded in the top-level README is rendered from the two files in this directory. Nothing in it is a screen recording: every frame is drawn by `launch.html`, a single self-contained page where every scene is a pure function of time, and `render.py` steps through that time one frame at a time, captures each frame through the locally installed Google Chrome, and hands the frames to ffmpeg.

The rendered MP4 is not committed (`docs/assets/*.mp4` is gitignored); the README embeds a copy uploaded to GitHub's attachment storage so that clones stay small.

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
