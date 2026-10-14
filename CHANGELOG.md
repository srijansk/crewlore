# Changelog

## Unreleased

### Changed

- **One compile per store at a time.** `lore compile`, `lore watch`, `lore render` and the hooks take an exclusive non-blocking lock on `.lore/cache/compile.lock` (`flock` on POSIX, `msvcrt.locking` on Windows). A second compile prints "another compile is running on this store; nothing written" and exits 0 instead of running. Only a lock call that fails because another process holds the lock (`EAGAIN`, `EWOULDBLOCK`, `EACCES`) means that; on a filesystem that cannot lock at all (`ENOLCK` on some network mounts) the compile warns once on stderr and runs unguarded, as it does on a platform with no lock module, instead of being skipped forever behind a misleading line. The lock file is never deleted. Serving never takes the lock (see Fixed below). What the lock does for a rebase is described under `lore hook install`.
- **Store writes are atomic.** Every file the store writes — claims, conflicts, usage, sessions, the extraction cache, the config, the gitignore and the rendered book — goes to a sibling temp file that then replaces the target, so a reader that overlaps a writer sees the old file or the new one, never a truncated `claims.jsonl` that the next compile would persist as empty.
- **`capture.settle_minutes` (default 10).** A transcript modified more recently than this is still being written by a running session and is left for a later pass; `lore compile` says how many it left and why. A session is captured once, so capturing it mid-way — a post-commit hook fires while the agent is still working, or `lore watch` ticks during a session — would have kept only its first half for good. Set it to 0 to capture immediately. `--settle MINUTES` on `lore compile` and `lore watch` overrides it for one run, so `lore compile --settle 0` compiles a session you have just finished without waiting or editing the config. A `settle_minutes` that is not a number of minutes, 0 or more (`null`, `abc`, a negative), is a clear config error instead of a traceback. Pull-request imports are complete files and take no settle time.
- **Study tables relabelled.** The headline poisoning numbers (44.7%, 47.6%, 30.1%, 17.5%) are the mean share of a declined PR's claims that state the rejected approach as current, as `studies/palm/analyze.py` computes them, not the share of declined PRs with at least one such claim, which the README and the study README had said. Both metrics are now shown (47, 45, 35 and 25 of 60 declined PRs), and the "0 of 867 statements" figure, which mixed declined-only and control arms, is replaced by 0 of 658 statements from declined PRs (0 of 1,060 counting the merged controls). No analysis code changed.

### Added

- **`lore render`** rebuilds the book and the conflict list from the claims already compiled, with no model call and no API key: the command for a fresh clone, or after a merge or pull. It reads the stored claims only — not captured sessions, not this machine's extraction cache — so a render adds no claim that `lore compile` has not committed and cannot bring back a claim a teammate removed in review. It reports how many claim lines changed (normally 0), is byte-stable across repeats, and leaves a store with no claims file untouched instead of creating empty files. Captured sessions that have never been extracted are counted and left for `lore compile`. `--expect-head SHA` (also on `lore compile`) writes nothing git tracks unless, when the work is done, HEAD is still that commit or a descendant of it on which the committed `claims.jsonl` is the same blob (missing at both counts as the same): a commit that merely follows the one compiled for is accepted; a branch switch, an amend, or a `claims.jsonl` committed meanwhile is not, and the message says when it was the claims file. The captured sessions and the extraction cache, both gitignored, are kept either way, so the next compile costs nothing. "Nothing git tracks" includes `.lore/.gitignore`: a store from an older version has its shorter ignore list refreshed with the claims write, after the check, not by the session and cache writes before it, which ask only for the two lines every version has had.
- **`lore hook install`** adds a marked block to the repository's `post-commit`, `post-merge` and `post-rewrite` hooks: `lore compile` runs in the background after each commit and once after a rebase, `lore render` after each merge, all logging to `.lore/cache/hook.log` (truncated once it passes 1 MiB). The hook hands git's stdout and stderr back before the compile starts, so a commit from a GUI client, `gh`, CI or any script capturing git's output returns at once while the model call runs. The interpreter is pinned at install time (shell-quoted) with `lore` on PATH as the fallback, so GUI git clients and CI runners without the `lore` launcher on PATH still work and a committed `core.hooksPath` works for teammates; the model key must be in the git client's environment, since only the interpreter is pinned. The interpreter runs with the current directory off `sys.path` (a `-c` entry rather than `-m lore.cli`, which puts the directory first) and `--repo` naming the repository, so no `lore/` package in the repository, at the top level or planted under `.lore/cache/`, can stand in for the installed one; a committed `.lore/config.yaml` steers an automatic compile, so its `model.base_url` deserves the review code gets. The hook records the commit it fired on (`git rev-parse --verify -q HEAD`: empty, not the word `HEAD`, when there is none) and passes it as `--expect-head`, so a compile that outlives a `git checkout` writes nothing git tracks. A rebase fires post-commit once per replayed commit while HEAD is still moving, so the post-commit block steps aside while `rebase-merge/` or `rebase-apply/rebasing` exists and the post-rewrite hook compiles once when the rebase, or `git pull --rebase`, has finished with HEAD settled; `git commit --amend` compiles through post-commit alone; a multi-commit `cherry-pick` has no closing hook, so its first commit starts the compile, the others are skipped by the lock, and that compile lands when it finishes since the later commits follow the first with the claims file unchanged; an `--amend` made while a compile runs replaces the commit instead of following it, so that compile ends in "HEAD moved" and the layer catches up on the next commit. `core.hooksPath` is honoured, and install notes when the hooks directory is tracked by git. A hook that is a symlink is edited through the link: install says which file the block went into, gives the shared-hook note when that file is tracked by git, and refuses a link to a file that does not exist; uninstall writes the remaining text back through the link instead of deleting the link and leaving the block in its target. The block is placed before the first command that ends the hook, found by reading the hook as the shell does: `exit` or `exec` after `;`, `&&`, `||` or `|`, behind `then`, `else` or `do`, inside the body of an `if`, `for`, `while` or `case`, a `case` arm, a function or a `{ }` group (the block goes before the outermost statement), behind a variable assignment or a redirection (`exec 2>&1 cmd`), or on a continued line; comments, heredoc bodies, quoted strings, `$( )` substitutions and `( )` subshells are seen through, and a redirection-only `exec >log 2>&1` does not count. A hook that ends inside an unterminated heredoc or quote is refused rather than given a block it would never run. A hook whose shebang is not `sh`, `bash`, `dash`, `ksh` or `zsh` is refused untouched; a hook with CRLF line endings is refused with instructions to convert it to LF, since git cannot exec it and the block would be a shell syntax error in it; a damaged or duplicated block is refused with "fix by hand" by install and uninstall alike; install says when it re-enabled a hook's executable bit. `LORE_SKIP_HOOK` set to any non-empty value skips a run. `lore hook uninstall` removes exactly the bytes install added; a hook whose last line had no newline keeps the one install added (install says so). `lore hook status` reports installed (naming the pinned interpreter when it is not the current one), outdated, missing, or `broken (<reason>)` — not executable, CRLF line endings, a shell syntax error, exits before the block (an `exit` inside a function body does not count, for status or for leaving an existing block in place: the body runs only where the function is called, which `--probe` follows), holds the block inside a heredoc, pinned interpreter missing with no `lore` on PATH, or an interpreter that cannot import `lore.cli` (probed from an empty directory with the current directory off `sys.path`, so a `lore/` package in the working directory cannot stand in) — and prints the last line of `hook.log`. `lore hook status --probe` runs each hook with `LORE_HOOK_PROBE` set, which makes the block touch a file and exit instead of compiling, and reports `broken (block is never reached)` when the hook ends before the block in a way no static read can see (`set -e` and a failing command, say); it runs the hook's other commands too, which is why it is a flag, and without it a hook with other commands before the block reads `installed (not probed: …)`. The post-merge render dirties the tree when the committed book lags the merged claims; that is the point, commit it.
- **An original score for the launch video**, `docs/launch-video/audio/`: `score.json` lists a sound event for every moment on screen and one chord per bar; `score.py` synthesises it deterministically (numpy, scipy) and masters it with ffmpeg to -14 LUFS / -1 dBTP; `render.py mux` puts it onto the rendered video. The embedded copies in the README and the Welcome discussion carry the score.

### Fixed

- **A query answered during a compile lost its usage count.** `lore query`, `lore feedback` and the MCP tools rewrote both `claims.jsonl` and the usage sidecar from their own snapshot, and a compile rewrote both from the snapshot it loaded when it started, so a claim served while the model was working (`lore watch`, or a hook compile, with an agent querying at the same time) had its `times_served` bump overwritten when the compile finished, and the lifecycle later archived it as never served; a query could also revert `claims.jsonl` to the pre-compile set. Serving now writes only the usage sidecar (`LoreStore.write_usage`), leaving `claims.jsonl` untouched rather than rewritten with the same bytes, and a compile re-reads the sidecar just before it persists, so the counters bumped during it survive.
- **Crash leftovers of atomic writes are gitignored and swept.** A writer that died between writing `.<name>.<pid>.tmp` and replacing the target left it behind as an untracked file. `.lore/.gitignore` now covers `.*.tmp`, and the next write to the same path removes such siblings once they are older than ten minutes (a live write holds its temp file for milliseconds).

## 0.4.2 — 2026-10-09

### Changed

- **The conflict detector needs evidence of disagreement.** It used to record a conflict whenever claims from different sessions shared a scope, kind and topic, without reading what they said, so three claims that agreed about one rule were reported as a disagreement (the `.github/` maintainer-only conflict in `docs/examples/pydantic-ai-prs/`, until now disclosed as a known weakness). A conflict is now recorded only for a cross-session pair on one topic that carries a marker the detector can read offline: one claim marked `not_adopted` while the other is `current`, or one claim's action forbidding what the other's prescribes — a sentence opening with *do not*, *don't*, *never*, *avoid*, *must not*, *should not* or *no longer* whose content overlaps the other claim's prescription more closely than the two agree, so "do not X; do Y" and "do Y" count as agreement. The same-kind and cross-session requirements are unchanged, and the recorded reason now names the evidence and the claims. Two decisions that merely pick different answers, with neither marker, are no longer flagged: telling a different answer from a different wording needs a model, and guessing it from text is what over-flagged. Lexical similarity was evaluated and rejected — on the example corpus the agreeing claims are the low-similarity ones (pairwise Jaccard 0.11–0.23) and the disagreeing test pair the high one (0.50). The deterministic stages still make no model call.
- **`docs/examples/pydantic-ai-prs/` re-rendered with the new detector.** `book.md`, `stats.json` and `provenance.md` now record 0 conflicts; `claims.jsonl` is byte-identical, since re-deriving conflicts and the book from committed claims needs no model call. The README no longer lists the false positive as a known weakness and names the remaining blind spot under limits.

### Added

- **Launch video source**, `docs/launch-video/`: a 56-second product video drawn frame by frame from one HTML file and rendered through the locally installed Chrome (`render.py`, Playwright, ffmpeg). The MP4 stays out of git; the README and the Welcome discussion embed a copy uploaded to GitHub.
- **Wordmark and social-card sources**, `docs/brand/`: the README header now uses the wordmark on its own dark card (`docs/assets/wordmark.png`, so it reads the same in every theme), and the repository's social preview card is rendered from the same file.

### Fixed

- **GitHub releases now carry their CHANGELOG section as notes.** The release workflow matched the version heading only without its date suffix, so every release until now said "See CHANGELOG.md."; the earlier releases were backfilled by hand.

## 0.4.1 — 2026-10-09

### Fixed

- **`lore serve` broke on a fresh install of the `serve` extra.** The `mcp` library's 2.x release renamed the server class crewlore imports, and the extra's range allowed it. The extra now pins `mcp>=1.0,<2`; an incompatible install is reported as such instead of as "extra not installed". Support for `mcp` 2.x is planned.
- Lockfile refreshed to patched transitive versions (`pyjwt`, `cryptography`, `anyio`, `starlette`, `python-multipart`).

## 0.4.0 — 2026-10-09

### Changed

- **Default model is `claude-sonnet-5-5`.** With no sampling parameters sent (0.3.0), current Claude models work; the newer Sonnet is cheaper than the 4.6 generation and was validated on the new example below. Set `model.name` to keep an older model.

### Added

- **A current-format example compiled from public pull requests**, `docs/examples/pydantic-ai-prs/`: `lore import-prs pydantic/pydantic-ai --limit 100` found 24 agent-authored threads among the last 100 closed PRs (18 merged, 6 declined) and compiled them into 130 claims, 15 marked not adopted, with 173 anchors; the gate dropped none of the model's proposals and an independent re-check resolves every anchor. The scrubbed source threads are committed next to the claims, so every anchor can be followed to the event it quotes. The older session-based snapshot stays as `docs/examples/pydantic-ai/`, labelled as the 0.1.0 artifact it is.

## 0.3.0 — 2026-10-09

A launch-readiness release. Two defaults change, one surface is added, and the docs stop claiming more than the code does.

### Changed

- **`lore compile` / `lore watch` read only this repo's own Claude Code transcripts.** The previous default was the whole `~/.claude/projects` tree, which copied every project on the machine into one repo's `.lore/sessions/` and sent all of them to the model. The default is now the one directory Claude Code keeps for this repo (`capture.transcripts: auto`); an existing config that still names the whole tree is treated the same way. Pass `--transcripts DIR` or set a directory in the config to read anything else.
- **No sampling parameters are sent unless configured.** The hard-coded `temperature=0` is gone: current Claude models reject non-default sampling parameters, so any model newer than the 4.6 generation failed on every session, and a fixed temperature never made extraction deterministic anyway. Set `model.temperature` in config to pass one to a provider that accepts it.
- **Requests a model refuses outright are fatal.** A 400 (unsupported parameter) or 404 (unknown model name) now stops the run with a message naming the config to fix, like a rejected key already did, instead of being retried silently on every session.
- **Config keys that nothing read are gone** (`harness`, `scopes`, `compile.cadence`); `compile.watch_interval_seconds` is now actually the `lore watch` default and `compile.max_unused_days` sets the decay window.
- **A recompile never lowers a claim's authority.** A teammate compiling with no local sessions used to reset every inherited claim to base authority, churning the committed `claims.jsonl` on each pull.
- **Claims compiled from pull requests record `harness: github-pr`** instead of `claude-code`.

### Added

- **`lore feedback <id>… --influential|--overridden`** and an MCP tool **`lore_feedback`**, so the influence/override half of the lifecycle is reachable. `lore query` and `lore_query` now return claim ids.
- **`lore import-prs --state closed|open|all`.** The default is still closed PRs, which is now documented.
- **Fidelity-gate statistics.** `lore compile` prints how many proposed anchors and claims the gate dropped each pass — the number that says how the model behaved, since a store's after-the-fact fidelity is 100% by construction.
- **`scripts/demo.py --step`** pauses between sections; the README GIF is re-recorded and `docs/social-video.tape` renders a 1080p explainer.

### Fixed

- **Raw captures could be committed.** `.lore/.gitignore` was written only by `lore init`; a store written to by `lore compile` without a prior init had none. It is now written on every store write, and it also covers `.lore/sources/`, where raw pull-request exports land before scrubbing — that directory was not ignored at all.
- `lore status` and `lore query` outside an initialised repo say so instead of printing zeros; `lore init` twice says "already initialised"; `lore serve` no longer advertises a `--no-mcp` option that did not exist.
- Docs: the example snapshot is labelled as the 0.1.0 artifact it is; the Claude Desktop MCP snippet uses the real config file and passes `--repo` instead of a `cwd` key the client ignores; the PyPI summary and `lore --help` describe the current product; the pydantic-ai star count is current; "not in v0.1 scope" wording removed.

## 0.2.0

Every claim now says whether the team adopted it; pull-request threads are a second capture source; and a decay bug that emptied the knowledge layer on any historical import is fixed. This is the first release since 0.1.1 and includes the fix for a test fixture that had aged past the decay window.

### Added — adoption polarity

- **`adoption: current | not_adopted` on every claim.** A schema that can only say "X" turns "we tried X and declined it" into a confident assertion of X: the compiled claim reads fluently, cites a real line, and is wrong about the world. Measured on agent-authored pull requests that were closed without merging (see [`studies/palm/`](https://github.com/srijansk/crewlore/tree/main/studies/palm/)), crewlore's own extractor stored the declined approach as current practice in roughly half of the claims it extracted from those threads (and left at least one such claim behind in three out of four of them), and so did a schema-free summarizer, so this is not one prompt's fault. Stating the outcome in the transcript helps; giving the schema a field for it, plus an instruction to use it, is what makes the extractor actually *record* the rejection in the claim's text. Across every arm without such a field it never once did. The field is excluded from the content-addressed id, like `topic`, and defaults to `current`, so existing `claims.jsonl` files load unchanged.
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

Confirmed working live: extraction returns well-formed claims, the verbatim-anchor fidelity gate holds at 100%, trivial sessions are gated out, and retrieval returns relevant claims. See the README's limits section for the residual conflict-coordinate-consistency gap.

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
