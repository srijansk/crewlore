# Changelog

## 0.1.0 (unreleased)

First working vertical slice — capture → compile → serve → actuate → measure, built test-first.

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

Live end-to-end on public-safe data (Haiku): 6 transcripts ingested, 2 secrets redacted, 7 compiled claims (decisions/gotchas/procedures), a rendered team-knowledge book, and a 67% preventable-rediscovery rate (2/3 held-out sessions).

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
- **8 distinct scope groupings** spanning UI adapters, decorator introspection, durable-execution threat modeling, toolsets, tests, and version policy
- **100% per-session canonical fidelity** — every anchor verified against its session's content under the explicit contract
- **0 conflicts** (sessions disjoint in scope)
- Provenance documents five real-data bugs the capture process found and fixed before publication.
