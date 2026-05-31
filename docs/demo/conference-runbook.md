# Conference demo runbook — 6 minutes

Live demo of `agent-lore` for an AI dev-tools audience. The arc is built so that the live, on-stage moments are **deterministic** (file open, query, status check) and the LLM-dependent steps are **pre-staged**. Default target audience and slot: **AI Tinkerers — AI Dev Tools Track, Seattle, June 8, 2026 (~5–7 min live demo + Q&A).** Adjust timings if your slot differs.

## Demo target repo

[`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) — 17.3k ⭐, MIT, active. The audience can clone it and verify everything you show on stage. See [`candidate-tasks.md`](candidate-tasks.md) for the curated session list (and the issue pair that produces the conflict moment).

## Setup checklist (before stepping on stage)

- [ ] **Terminal**: dark theme, font size ≥ 18pt, full-screen. Clean prompt.
- [ ] **Pre-staged state**: `.lore/` already compiled on the demo repo. Don't recompile live (LLM latency risk).
- [ ] **Two windows visible**: terminal + `.lore/knowledge/README.md` open in your editor side-by-side.
- [ ] **API key set**: `ANTHROPIC_API_KEY` exported — only for the *one* live `lore query` near the end.
- [ ] **Network OK**: at least one query needs to round-trip. Test on conference Wi-Fi 10 min before.
- [ ] **Backup**: `docs/assets/demo.gif` (the asciinema) playable in a browser tab in case of any failure.
- [ ] **Reset script**: `make demo-reset` (or the equivalent) restores `.lore/` between rehearsals.
- [ ] **Water within reach**.

## The 6-minute arc

> Time targets per scene; total ≈ 6:00, hard cap 7:00.

### Scene 1 — The Hook (0:30)

*(no slides; just speak; eye contact)*

> "Show of hands: in the last week, your AI agent re-derived something a teammate's agent already figured out the day before. [pause for hands] Right. Every session is born yesterday. We're going to fix that, in your own git repo, in 5 minutes."

**Beats:** name the pain in the audience's voice; promise concrete time-bound payoff.

### Scene 2 — Setup (0:45)

*(switch to terminal; show the demo repo cloned)*

```bash
$ cd ~/pydantic-ai
$ ls ~/.claude/projects/-Users-you-pydantic-ai/
ses-1234.jsonl  ses-2345.jsonl  ses-3456.jsonl  ...  (N sessions, M authors)
```

> "This is `pydantic-ai`, ⭐ 17k, real codebase you'll recognize. Over the last week, I and [collaborator(s)] each picked up a different open issue. Different problems, different sessions, didn't coordinate. N transcripts now sit on disk — that's *one developer-week of distributed thinking* with nowhere to go."

**Beats:** establish that the input is real and reproducible.

### Scene 3 — The Compile (1:00)

*(open `.lore/knowledge/README.md` in editor — it's already populated; do NOT recompile live)*

> "`agent-lore` already ate those transcripts and produced this. Decisions, procedures, gotchas. Plaintext, in our repo, grouped by area of the codebase."

*(scroll through the book; pause on a couple of compelling claims)*

> "Each entry is what we'd want a new teammate — or a fresh agent session — to know on day one. Not a vector index; a book."

**Beats:** show the artifact; emphasize plaintext + in-repo + readable.

### Scene 4 — Verify (1:00)

*(pick one claim; click into its anchor)*

> "Every claim carries a **verbatim anchor** — a citation back to the moment it was learned. Watch."

*(open the source transcript at the cited turn; show the exact words)*

> "That's not paraphrased. Not a summary. The words the agent (or the human) actually said, with provenance. A claim without a verifiable anchor is a defect — `lore` drops them at extract time."

**Beats:** citation > hallucination. The audience can verify *every* line.

### Scene 5 — The team moment (1:00)

*(switch to a fresh terminal — pretend to be a new engineer joining)*

```bash
$ lore query "structured output with nested models retry"
```

*(it returns 3 claims; read the most relevant aloud)*

> "Day one on the team. The knowledge layer just told me what we already figured out about retry semantics for nested schemas. Now I open a session…"

*(paste the claim into a new Claude Code session prompt; show the agent's first response)*

> "…and the agent's first message is already the right answer. The context-window cold-start is gone."

**Beats:** show the payoff in real time. This is the *only* live LLM moment — keep it short.

### Scene 6 — Trust beats (1:00)

*(quick triplet — ~20s each — no time for explanation, just point)*

**(a) Scrubbing.** Open one transcript:

```bash
$ rg "REDACTED" ~/.claude/projects/.../ses-*.jsonl | head -1
"...we were debugging with ANTHROPIC_[REDACTED:secret]..."
```

> "One of these transcripts had a leaked API key. `lore` redacted it at ingest, before any model call. Secrets never travel."

**(b) Conflict.** Open the book at the Conflicts section:

> "Two of us made different calls about retry strategy. `lore` kept BOTH, with provenance. Disagreement is knowledge — we surface it, we don't bury it."

**(c) Actuation.** Run:

```bash
$ lore status
claims: 47 (38 active, 9 archived)
utilization: 62% of active claims have been served
```

> "Claims nobody touches fade out. No dumpyard. The store stays small and fresh, automatically."

**Beats:** three credibility moments in one minute. Don't over-explain.

### Scene 7 — Close (0:30)

*(speak to the audience, repo URL on screen)*

> "It's alpha. Claude Code adapter today — more next. Format may change before 1.0; migrations will ship. Everything you saw is local-first; nothing leaves your machines. **github.com/srijansk/agent-lore.** Discussions tab is open. Come build with us."

## Q&A prep

The full positioning Q&A — *"why `lore` and not [changelog / `CLAUDE.md` / vector DB / memory framework / built-in memory / etc.]"* — lives in [`q-and-a.md`](q-and-a.md), with deep dives, on-stage one-liners, and honest concessions per question. **Drill the top three before the talk:** the changelog question, the `CLAUDE.md` question, and the cost question.

The shortest top-of-mind table for stage:

| Question | Answer |
|---|---|
| **Why not just keep a changelog / agent log?** | "A changelog is what you *write*; `lore` is what's *compiled*. Changelogs accumulate, compile dedupes. Anchors verify; freeform changelogs don't. The compile step is the product." |
| Why not put it all in `CLAUDE.md`? | "`CLAUDE.md` holds the rules you already know. `lore` holds the gotchas you'd never think to write down. They compose." |
| Cursor / Copilot / Aider / Codex? | "Adapter contribution — small. Architecture is harness-neutral; one module + a manifest." |
| How do you handle secrets? | "Scrubbed at ingest before anything is stored or sent to a model. Plus you git-PR-review the `.lore/claims` diff." |
| Doesn't this just grow forever? | "No — actuation loop. Unused claims decay; contradicted claims retire. Healthy `.lore/` plateaus." |
| Cost? | "BYO key. ~$0.20 per session with Sonnet 4.6. Incremental — you only pay for new sessions." |
| Why not RAG / a vector DB? | "RAG searches *code*; `lore` captures *what your team learned working on the code*. Different unit: chunks vs claims." |
| What if the LLM extracts a wrong claim? | "Verbatim anchors verify every line; the actuation loop retires claims overridden in real use. Explicit review gate ships next." |

## Backup plan

If anything in scenes 3–5 fails on stage:

1. **First fallback** — show `docs/assets/demo.gif` (the asciinema). It covers the same beats and reaches the punchline in under a minute.
2. **Second fallback** — switch to the offline demo: `uv run python scripts/demo.py`. Bundled public-safe data, no network, no API key. Reads as "here's what the loop produces" rather than "here's a real codebase," but still proves the mechanism.
3. **Total failure** — read the closing slide ("alpha; format may change; repo URL"); promise a follow-up demo at the next meetup. Don't try to debug live.

## Rehearsal checklist

- [ ] Run end-to-end at least **three times** the day before. Each run < 7:00.
- [ ] Practice the *transitions* — terminal ↔ editor ↔ Claude Code window. The reps that look smooth on stage felt clumsy the first three times.
- [ ] Time each scene. If Scene 3 (the book) keeps over-running, pre-pick the two claims you'll point at and ignore the rest.
- [ ] Practice with conference Wi-Fi mentally — assume any single API call could take 8 seconds. Don't over-narrate while waiting; let it happen.
- [ ] Sound check: read Scene 1 out loud. Does it sound like *you* or like a script?

## What this demo deliberately does NOT do

- No competitor comparison (per project rule).
- No benchmark numbers we don't have first-hand (no synthetic eval).
- No architecture diagrams (the audience didn't come for boxes-and-arrows; they came to see it work).
- No "five more features" after the close. End on the URL.
