# Changelog

## 0.1.0 (unreleased)

First working vertical slice — capture → compile → serve → actuate → measure, built test-first.

### Pre-launch hardening

A full adversarial audit before going public surfaced a cluster of fixes, all landed here:

- **Incremental compile cost.** `lore watch` now caches extraction per session (sessions are immutable, so the id is a safe key) — each interval only LLM-extracts newly-ingested sessions instead of re-running the whole corpus against your key. `--rebuild` ignores the cache. The watch loop is now incremental in *cost*, not just idempotent in *output*.
- **First-run works out of the box.** `anthropic` (the default provider) is now a base dependency, and SDK imports are guarded with an actionable message instead of a raw `ModuleNotFoundError`. `pipx install crewlore` → `lore compile` just works with a key.
- **Local models are real.** `model.provider: local` + `model.base_url` routes to any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM). Previously "local" was advertised but unimplemented and produced a dead-end error.
- **`lore serve --mcp`** — the documented MCP flag now exists (it was missing; the copy-paste `mcp.json` failed to launch).
- **Tool-call arguments are scrubbed.** Secrets passed as tool-call args live in event `meta`, which previously bypassed the scrubber; `meta` is now walked recursively. Coverage broadened (AWS `ASIA`/secret-key assignments, all `xox?-` Slack tokens, quoted multi-word secrets). See [`docs/scrub.md`](docs/scrub.md).
- **Usage stats moved to a gitignored sidecar** so `lore query` no longer rewrites the git-tracked `claims.jsonl` on every call — `git log .lore/` stays clean.
- **Robustness:** timestamps are always timezone-aware (a timestampless transcript no longer crashes the actuation loop); a single failing session no longer aborts the whole compile pass.
- **`lore --version`** flag; one canonical-form definition shared between the fidelity gate and the reported fidelity number; honesty passes on the README (the synthetic rediscovery metric is labelled demo data, the fidelity claim states what the gate does and does not certify, retrieval is described as lexical).
- Corrected the pydantic-ai example counts (9 scope groupings / 6 topics, matching the committed data).

### Added

- **Schemas** — content-addressed `Claim` IDs (idempotent compile, clean merges); `NSFEvent`, `Anchor`, `Provenance`, `Conflict`, `UsageStats`. Actuation fields (`action`, `status`, `usage`) and a conflict-grouping `topic` baked in.
- **Store** — `.lore/` layout; sorted, one-object-per-line JSONL for line-oriented diffs/merges; raw sessions gitignored (secrets safety).
- **Capture** — Claude Code adapter (transcript records → NSF) and a friction/resolution signal gate so trivial one-shot sessions are not compiled.
- **Compiler** — deterministic dedup/merge, conflict-recording (not merging), authority-by-support, latest-observed; LLM extraction behind a `complete(prompt)->str` seam with a verbatim-anchor fidelity gate.
- **Serve** — instrumented task-conditioned retrieval (records usage), influence/override feedback, markdown knowledge book, optional MCP server (`[serve]` extra).
- **Actuation loop** — usage-driven lifecycle: decay unused, retire overridden, reinforce influential.
- **Measurement** — `fidelity_report` and held-out `replay_report` (preventable-rediscovery rate).
- **CLI** — `init`, `compile`, `query`, `status` (surfaces utilization as a dumpyard early-warning), `serve`.
- **Demo** — `scripts/demo.py` runs the full loop on synthetic public-safe data, no API key.

### Provider support

- BYO-key Anthropic and OpenAI; loud `CredentialsError` when no key is configured. Nothing routes through any lore-operated infrastructure.

### Live validation (Anthropic Haiku)

Ran the real extraction path end-to-end and fixed what it surfaced:

- Tolerate ```` ```json ```` fences and prose around the JSON array (models wrap output).
- Conflicts require matching `kind` (a gotcha and its fix-decision shared a topic and were falsely flagged).
- Feed existing topic vocabulary back to the extractor so it reuses keys across sessions.

Confirmed working live: extraction returns well-formed claims, the verbatim-anchor fidelity gate holds at 100%, trivial sessions are gated out, and retrieval returns relevant claims. See README "Known limitations" for the residual conflict-coordinate-consistency gap.

### Automatic compilation + secret scrubbing

Compilation is now automatic by default — no human has to remember to run it:

- **Secret scrubber** (`lore.scrub`) runs at ingest: API keys, AWS keys, private-key blocks, and secret assignments are redacted before anything is stored or sent to the model.
- **Capture-from-transcripts** (`lore.capture.ingest`): reads the coding agent's existing on-disk transcripts, incrementally (skips already-captured sessions). No live hook needed for MVP.
- **`auto_compile`** = ingest → compile → prune (actuation lifecycle) → re-render the book, in one idempotent pass.
- **`lore watch`** runs that pass on an interval (`--once` for cron/CI); `lore compile` is the manual escape hatch.
- **Signal gate** widened to capture procedures/conventions/team-norms, not only friction (was silently dropping "how we do X" / "the rule is Y" sessions).

Live end-to-end on public-safe data (Haiku): 6 transcripts ingested, 2 secrets redacted, 7 compiled claims (decisions/gotchas/procedures), a rendered team-knowledge book, and 2 of 3 held-out sessions re-deriving known knowledge (illustrative demo data, n=3).

### Fidelity-gate contract made explicit (`_canonical_form`)

The fidelity gate's tolerance shape — what counts as a "verbatim" anchor — is now a documented contract instead of an implicit substring check. Driven by real-data findings from capturing pydantic-ai sessions where agent prose contains Markdown decoration and long replies are split across NSF events by tool calls.

- **New module-level `_canonical_form(text)`** in `lore.compile.extractor`. Three transformations applied in order, each with its own line and rationale: strip Markdown decoration (`` ` ``, `*`, `_`); collapse whitespace; lowercase. Full docstring covering the contract.
- **What's accepted:** Markdown decoration differences, whitespace differences, case differences, quotes that span event boundaries (e.g. a long agent reply split by a tool_call).
- **What's still rejected:** fabricated content, paraphrase, changed meaningful words, out-of-order stitching of disjoint substrings.
- **Five adversarial tests** pin down both halves: `test_fidelity_accepts_*` for tolerated variations, `test_fidelity_rejects_*` for content-drift cases.
- **New spec doc:** [`docs/anchors.md`](docs/anchors.md) — the precise contract, why each transformation exists, what's deliberately preserved, and the v0.2 roadmap item (position-pointer anchors that eliminate the gate entirely).
- **Haystack excludes `tool_call` events** — their `content` is just the tool name (e.g. `"Read"`), not session prose; including it would break quotes that span agent-message events separated by tool calls.

### Real-data evidence: pydantic-ai example expanded

`docs/examples/pydantic-ai/` now reflects three captured sessions (G1 #5679, G3 #5358, D1 #5536):

- **18 active claims** (7 gotchas, 7 decisions, 3 procedures, 1 style)
- **9 distinct scope groupings** spanning UI adapters, decorator introspection, durable-execution threat modeling, toolsets, tests, and version policy
- **100% per-session canonical fidelity** — every anchor verified against its session's content under the explicit contract
- **0 conflicts** (sessions disjoint in scope)
- Provenance documents five real-data bugs the capture process found and fixed before publication.

### Renamed from `agent-lore` to `crewlore`

The original working name `agent-lore` collided on PyPI and on GitHub (taken by an unrelated 2018 project). Renamed to `crewlore` — two familiar words, instant comprehension, with the name free on PyPI and the repo live on GitHub. The importable package, CLI command, and `.lore/` directory layout stay the same; only the distribution and GitHub URL change. (Not yet published to PyPI; install from git until the first release is cut.)

### README hero GIF rework

- **Compiled-book renders as Markdown** in the recording (via `rich.markdown.Markdown`) — headings, bullets, and kind tags are now visibly formatted; previously the GIF showed raw text and the "interesting facts" landed weakly.
- **Architecture diagram is Mermaid**, not ASCII — renders inline on GitHub with the engine + artifact visually emphasized.
- **Higher-contrast theme + larger font** in `docs/recording.tape` (Catppuccin Mocha, 18pt) for legibility at README hero size.
