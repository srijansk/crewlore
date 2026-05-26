# agent-lore

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-96%20passing-brightgreen.svg)](#development)

> **Your coding agents keep relearning what your team already figured out.**
> `agent-lore` compiles the decisions, gotchas, and conventions discovered inside AI-coding-agent sessions into a versioned, plaintext knowledge layer that lives in your own git repo — and serves the relevant slice back to any agent at the start of a session. Local-first: nothing leaves your machines.

<!-- TODO before public launch: an asciinema/GIF of `lore watch` turning a raw session into a compiled claim. -->

```bash
pipx install agent-lore        # PyPI release pending — until then:
# pipx install git+https://github.com/srijansk/agent-lore.git
```

## Quickstart

```bash
cd my-repo
lore init                      # create .lore/ in your repo
lore watch                     # automatic: read agent transcripts, scrub secrets,
                               #   compile to claims, prune — on an interval
lore query "billing webhook"   # ask the knowledge layer anything, anytime
```

That's it — engineers keep working in whatever agent they use; `lore` keeps the knowledge layer fresh in the background. Commit `.lore/knowledge` and `.lore/claims` and your teammates inherit it on the next `git pull`.

Want to see it work end-to-end with zero setup and no API key?

```bash
uv run python scripts/demo.py
```

## What you get

Raw, messy sessions go in. A clean, citable team-knowledge book comes out — grouped by area, every line backed by a verbatim quote from the session it came from:

```markdown
## billing/webhook
- [gotcha] Billing webhook handler lacks an idempotency check, causing duplicate
  charges when Stripe retries webhooks.
    Do: dedupe on the Stripe idempotency key before processing.
    anchor: "the handler has no idempotency check, so when Stripe retries..."

## deployment
- [procedure] Always run migrations before deploy to prevent missing columns.
    Do: add a pre-deploy check that migrations have run against the target DB.

## .
- [procedure] Write the failing test first; PRs without one are rejected in review.
```

Each entry is a **compiled claim** — a decision, procedure, gotcha, or style norm — carrying its provenance and a verbatim **anchor** so a human can verify it and an agent can trust it. On the bundled demo, every claim's anchor resolves verbatim against its source (100% fidelity), and replaying later sessions shows two of three re-deriving something the layer already knew.

## How it works

```
ingest + scrub  ──▶  compile (the engine)  ──▶  serve (files + MCP)
 transcripts→NSF       NSF → compiled claims      .lore/ in your repo
                              │
                       actuation loop  ◀──  usage from serve
                 (decay unused · reinforce used · retire overridden)

   `lore watch` runs ingest → compile → prune automatically, on an interval.
```

- **Ingest + scrub** — reads the coding agent's existing on-disk transcripts and redacts secrets (API keys, tokens, private keys) *before* anything is stored or sent to a model.
- **Compile** — extracts atomic claims, deduplicates them, records disagreements instead of silently overwriting, scores authority by how often a claim recurs, and drops any claim whose citation doesn't resolve verbatim.
- **Serve** — writes a human- and agent-readable knowledge book to `.lore/knowledge/`, and exposes a query tool (including an optional MCP server) so any agent can pull the relevant slice on demand.
- **Actuation loop** — every retrieval is recorded, and that usage drives a lifecycle: unused claims decay and archive, contradicted claims are retired, useful claims are reinforced. The store stays small and fresh instead of growing into a pile nobody reads.

The intelligence is in **compile**; ingest and serve are deliberately thin, so supporting another coding agent is a small adapter, not a rewrite.

## Why this exists

Knowledge discovered inside an agent session is private by default and lost by default. It lives in one developer's transcript, so the next engineer — and every future agent run — re-reads the same files, re-learns the same gotcha, and re-makes a decision the team already made. There's no shared layer that both humans and agents read from, so decisions drift and bugs resurface.

`agent-lore` makes that knowledge a first-class, versioned artifact in the place your team already trusts: your git repo.

**What it is:** a compiler that turns sessions into accurate, deduplicated, conflict-aware, provenance-carrying team knowledge, served back to any agent.

**What it isn't:** a hosted service, a vector database, or a personal-memory layer for a single IDE. There's no account, no cloud, and no proprietary store — the compiled knowledge is plaintext you own.

## Your data stays yours

- **Local-first.** Capture, compile, and serve all run on infrastructure you control. Point the compiler at your own model provider or a local model — nothing routes through any `agent-lore`-operated service, because there is none.
- **Plaintext, in your repo.** The knowledge layer is human-readable Markdown and JSONL under `.lore/`, versioned by git. `git log .lore/` is your audit trail.
- **Secrets never travel.** Scrubbing happens at ingest, before storage or any model call. Raw session captures are git-ignored by default.

## CLI

| Command | What it does |
|---|---|
| `lore init` | Create the `.lore/` layout in your repo. |
| `lore watch` | Automatically ingest → compile → prune on an interval (`--once` for cron/CI). |
| `lore compile` | Run a single ingest-and-compile pass manually. |
| `lore query "<task>"` | Retrieve the claims most relevant to a task (records usage). |
| `lore status` | Show claim/conflict counts and how much of the layer is actually being used. |
| `lore serve` | Start an MCP server exposing query-time retrieval to any MCP-speaking agent. |

## Configuration

`.lore/config.yaml`:

```yaml
model:
  provider: anthropic          # anthropic | openai | (local)
  name: claude-haiku-4-5
capture:
  transcripts: ~/.claude/projects
compile:
  cadence: auto                # `lore watch` interval below
  watch_interval_seconds: 300
```

Bring your own key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`); `agent-lore` never ships keys anywhere.

## Status

Alpha, and honest about it. The core is stable and tested end to end; the moving edges are clearly scoped:

- **Stable:** capture, secret scrubbing, the compile pipeline, retrieval, the actuation loop, and the `.lore/` plaintext format.
- **May change before 1.0:** the on-disk schema. Because everything is plaintext and git-versioned, you can always read and migrate it; breaking format changes will ship with migrations.
- **Today's adapter:** Claude Code. The architecture is harness-neutral by design; more adapters land once the core is proven on one.

## Roadmap & limitations

- Cross-session **conflict detection** is improving — disagreements about the same decision are surfaced, not buried, but reliably aligning claims across independently-compiled sessions is an active area of work.
- A **human review gate** is partial: secret-scrubbing is automated; an explicit approve-before-serve step is planned. For now, review the `.lore/claims` diff in your normal PR flow.
- More **capture adapters** (Cursor, Copilot, …) and a real-time capture hook are planned after the Claude Code path is proven.

## Development

```bash
git clone https://github.com/srijansk/agent-lore.git
cd agent-lore
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
pytest
```

96 tests across unit / integration / e2e. The deterministic stages run with no network I/O; LLM extraction is unit-tested behind an injected fake, so `pytest` makes no real API calls. Set `ANTHROPIC_API_KEY` to exercise live compilation.

## Contributing

Issues and PRs welcome — open an issue to discuss substantial changes first. Adding support for another coding agent is the most valuable contribution and is intentionally small: implement one adapter against the normalized session format.

## License

MIT — see [LICENSE](LICENSE).
