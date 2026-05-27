# Candidate sessions on `pydantic/pydantic-ai`

Curated open issues to pick from when capturing the real demo sessions. Selected to (a) span gotchas / decisions / procedures so the compiled book is varied, (b) include a **paired conflict moment** for the demo's "disagreement is knowledge" beat, and (c) each fit in a single ~30–60 min focused Claude Code session.

> **Repo:** [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) · 17.3k ⭐ · MIT · 556 open issues · last commit yesterday. Cloned at `~/demos/pydantic-ai` (shallow). `git fetch --unshallow` if you need full history during a session.

## Setup (one-time)

```bash
cd ~/demos/pydantic-ai
lore init                                       # creates .lore/ in the repo
ls ~/.claude/projects/ | grep pydantic-ai       # confirm Claude Code transcripts will land here
```

If the project directory doesn't exist in `~/.claude/projects/` yet, open Claude Code once in `~/demos/pydantic-ai` so it registers, then come back.

## The recommended 7

### Gotchas — concrete data-loss / silent-drop bugs

These produce sharp `[gotcha]` claims with crisp anchors.

| # | Issue | Likely scope | Why this is good demo data |
|---|---|---|---|
| G1 | [#5679 — Vercel AI adapter: `TextContent.metadata` silently dropped on round-trip](https://github.com/pydantic/pydantic-ai/issues/5679) | `ui-adapters/vercel` | Crisp data-loss bug; the gotcha names *exactly* what gets dropped — the kind of claim a future agent would want at session start |
| G2 | [#5672 — Bedrock filters `tools` array client-side when `tool_choice` forces a specific tool](https://github.com/pydantic/pydantic-ai/issues/5672) | `models/bedrock` | Provider-quirk gotcha; the kind of thing a *new* engineer would lose hours rediscovering |
| G3 | [#5358 — `takes_run_context()` silently swallows `NameError` on TYPE_CHECKING-hidden `RunContext`](https://github.com/pydantic/pydantic-ai/issues/5358) | `tools/dispatch` | Silent-failure gotcha (the lab's "silent data loss is harder than timeouts" theme) — ideal claim shape |
| G4 | [#5621 — groq: `_map_executed_tool` returns `(None, return_part)` in streaming, breaking call/return pairing](https://github.com/pydantic/pydantic-ai/issues/5621) | `models/groq/streaming` | Provider-streaming gotcha; produces both a gotcha AND a procedure ("when adding a streaming provider, verify the envelope shape") |

### Decisions — design choices with multiple reasonable answers

These produce `[decision]` claims. The pair below is the **conflict moment** — pick D1 *and* hand D2 to a collaborator (or vice versa); make different calls; the demo's conflict beat lands.

| # | Issue | Likely scope | Why this is good demo data |
|---|---|---|---|
| **D1** ⚔ | [#5536 — HITL approval signal is plain `bool` — hardening proposal (narrow vs proper fix)](https://github.com/pydantic/pydantic-ai/issues/5536) | `tools/approval` | Issue *explicitly* frames two options ("narrow" vs "proper"). Excellent design-decision session. |
| **D2** ⚔ | [#5617 — Allow `requires_approval` to accept a callable for conditional per-tool approval](https://github.com/pydantic/pydantic-ai/issues/5617) | `tools/approval` | Same scope (tool approval), different shape of decision (callable vs static). Independent calls here disagree naturally with D1's outcome — *that's the conflict the demo will surface*. |

### Procedure — recurring maintenance pattern

| # | Issue | Likely scope | Why this is good demo data |
|---|---|---|---|
| P1 | [#5663 — xAI: update docs and `KnownModelName` for current Grok 4.3 / 4.20 model names](https://github.com/pydantic/pydantic-ai/issues/5663) | `docs/models` | Boring but high-signal procedure: "when a provider releases new model names, update X / Y / Z." Procedures are underrepresented in agent-coded knowledge layers; getting one helps cover the claim-type matrix. |

## Minimum viable set (if you only have time for 4 sessions)

- **G1 + G3** — two gotchas in different parts of the codebase (UI adapter, dispatch). Different scopes → the book groups well by area.
- **D1 + D2** — the conflict pair. Critical: do them **independently**, no pre-coordination, on different days if possible. Each session decides for itself. *Don't read each other's transcripts before compiling.*

That's 4 sessions, ~3 hours of real focused work, and the book that comes out has:
- 2 gotchas in 2 scopes
- 1 surfaced conflict (the dramatic demo moment)
- 1 or 2 implied procedures from the same sessions

## If a collaborator is available (the strong multi-user moment)

Hand them **D2** (or D1). They work it on their own machine, in their own Claude Code, without seeing your D1 transcript. Their `.jsonl` ships to you (zip + back-channel; never commit). You drop it next to yours in `~/.claude/projects/-Users-<you>-demos-pydantic-ai/` before compiling.

If a collaborator isn't available, you can do both D1 and D2 yourself — the conflict still surfaces if the calls genuinely differ — but the *narrative* "I and N colleagues each picked up a different issue" is weaker. Strong preference for at least one external session if at all possible.

## Capture etiquette (for each session)

- Pick the issue, read it, **then** open Claude Code and work the problem. Don't paste the issue body into the session — let the natural exploration happen.
- Aim for **friction**: a wrong first hypothesis, a correction, a decision between approaches. The signal gate looks for friction.
- Take **one line of notes per session** of "things `lore` should have captured" — we'll cross-check on Day 6.
- When done, the transcript is automatically written to `~/.claude/projects/-Users-<you>-demos-pydantic-ai/<session>.jsonl`. Nothing else to do.

## What's deliberately not on this list

- **Mega-issues** (multi-week features) — won't fit a 60-min session.
- **Bot/CI/meta issues** (anything labelled `pydanty:meta`, `agentic-workflows`, `stale-issues`) — noise, not knowledge.
- **`needs discussion` items** that haven't converged — without a resolution, the session produces vague decisions.

If you want to swap any of these for an issue you find more interesting, that's fine — apply the same shape: concrete, has a reproducer or a forced choice, scoped to one area of the codebase.
