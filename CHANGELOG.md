# Changelog

## 0.2.0

Every claim now says whether the team adopted it; pull-request threads are a second capture source; and a decay bug that emptied the knowledge layer on any historical import is fixed. This is the first release since 0.1.1, so it also carries the CI fix that had `main` red since July.

### Added — adoption polarity

- **`adoption: current | not_adopted` on every claim.** A schema that can only say "X" turns "we tried X and declined it" into a confident assertion of X: the compiled claim reads fluently, cites a real line, and is wrong about the world. Measured on agent-authored pull requests that were closed without merging (see [`studies/palm/`](studies/palm/)), crewlore's own extractor stored the declined approach as current practice in roughly half of those threads, and so did a schema-free summarizer, so this is not one prompt's fault. Stating the outcome in the transcript helps; giving the schema a field for it, plus an instruction to use it, is what makes the extractor actually *record* the rejection in the claim's text. Across every arm without such a field it never once did. The field is excluded from the content-addressed id, like `topic`, and defaults to `current`, so existing `claims.jsonl` files load unchanged.
- **The extractor is instructed to use it.** When a session shows an approach was declined, reverted or not accepted, the statement records that it was tried and not adopted and `action` says what to do instead. An unrecognised value is never coerced to `current` (that would be the exact inversion the field prevents); the claim is dropped.
- **Declined claims are visible everywhere a claim is shown.** The book and `lore query` tag them `[kind · not adopted]` and label the action *Instead*; the MCP tool returns the field.

- **Existing stores:** claims compiled before this release load with `adoption: current`. Extraction is cached per session, so run `lore compile --rebuild` once to re-extract existing sessions under the new schema.

### Tooling

- CI runs on Python 3.10 through 3.14.
- Tag-driven releases: pushing `vX.Y.Z` builds the distribution, publishes to PyPI through trusted publishing, and creates the GitHub release from this file's matching section.
- `CITATION.cff` for citing the software; `studies/` for the measurement studies behind product decisions, each with its reproduction recipe.

### Added

- **`lore import-prs OWNER/REPO`** — compile a GitHub repository's pull-request threads into knowledge. Coding agents now author much of the reasoning text in PR threads: an agent-written PR body states the intent, the alternatives weighed and the constraint hit, which human authors historically never wrote down. This means a repo you have never run an agent in still has a usable knowledge layer — no local transcript directory, no waiting for sessions to accumulate.
- **GitHub PR adapter** (`github-pr`) — one pull request is one session. Two properties make PR threads a better fit for the session format than transcripts: merge/close and approval/change-request are ground-truth outcomes, so the `accept`/`reject` event kinds finally carry real verdicts; and inline review comments already name a `path` and `line`, so anchor provenance arrives rather than being reconstructed.
- **Multi-method agent attribution** — author login, commit trailers, and PR-body markers, with the deciding signal recorded on each record so a disagreement can be audited. Author metadata alone is not enough: agents that commit under a human account are invisible to it. Projects that mandate AI-assistance disclosure are also detected (reported as `unspecified`, since the wording names the practice and not the product), and `extra_markers` accepts repo-specific conventions. An unrecognised author is reported as human — under-claiming shrinks the corpus rather than contaminating it.

### Fixed

- **Claims compiled from historical sessions were archived before they could ever be served.** The unused-decay lifecycle measured staleness from `observed_at` (when the knowledge was seen in the source) instead of from when the claim entered the store. Those two clocks coincide for transcripts compiled as they happen, which is why this shipped, and diverge completely for any imported or backfilled corpus — where every claim aged out on the very first compile pass, leaving a store full of claims with an empty book and empty retrieval. Claims now carry a separate `compiled_at`, set once by the store on first persist, and decay is measured against it; `observed_at` keeps its existing role in conflict recency. A claim with no entry stamp (written by an earlier version) is left alone rather than retired on a clock we do not have.
- **Anchor refs are now derived from where the quote resolved, instead of being copied from the model.** The fidelity gate proves a quote was really said, not *where* — and the ref was whatever the model claimed, which in real runs came out as `agent/agent_message` or a PR-body section heading. Those read as provenance while pointing nowhere a reader can navigate to. Refs are now computed from the matching event: a `path:line` the event already carries is preferred (an inline review comment is the most precise pointer a source gives us), otherwise `<session>#event-<n>`, which resolves against the stored session. A quote spanning several events — legal, since the gate matches the joined transcript — degrades to the session id rather than inventing a pointer.
- **An invalid API key reported a successful run that compiled nothing.** The compiler deliberately swallows per-session extraction errors so one oversized context or transient 429 cannot abort a whole pass — but rejected credentials fail identically on *every* session, so a bad key silently skipped all of them and printed `0 active claims` with no error. Provider auth rejections (401/403) are now raised as a fatal `CredentialsError` that stops the run with an actionable message and a non-zero exit, while rate limits and server errors stay retryable. Sessions skipped by genuinely transient failures are now counted and reported instead of hidden.
- `discover` no longer auto-paginates a repository's entire pull-request history before applying `--limit`; on a large repo that was thousands of API calls to fetch the first page's worth, and it hung rather than erroring.
- Changed-file lists are read at PR level, because the commits endpoint omits per-commit files — previously every `diff` event was captured with no file refs at all.

### Changed

- Add `[project.urls]` (Homepage / Repository / Issues / Changelog) so the PyPI project page links back to the repo.

## 0.1.1

Docs-only release. No code or behavior changes — the package is identical to 0.1.0.

- README install instruction is `pipx install crewlore`, and the hero image plus all in-README links are absolute GitHub URLs so the PyPI project page renders correctly (relative links 404 on PyPI). The 0.1.0 page was published before this fix and is immutable; 0.1.1 carries the corrected page.

## 0.1.0

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
