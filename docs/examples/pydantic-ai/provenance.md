# Provenance

Full reproducibility detail for the `pydantic-ai` example.

## Target repo

| | |
|---|---|
| Repository | [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) |
| License | MIT |
| Commit at time of capture | [`7a5bec6`](https://github.com/pydantic/pydantic-ai/commit/7a5bec6) (`main`) |
| Clone form used | `--depth 1` (shallow) into `~/demos/pydantic-ai/` |

## Sessions captured

Both sessions ran in Claude Code in the cloned target repo directory.

### Session 1 — Issue #5679

| | |
|---|---|
| Issue | [#5679 — \[roundtrip-sweep\] Vercel AI adapter: TextContent.metadata silently dropped on round-trip](https://github.com/pydantic/pydantic-ai/issues/5679) |
| Session id (Claude Code) | `a8fa3beb-ec13-4ba2-8f68-9c745eecfaa2` |
| Captured | 2026-05-28 |
| Wall-clock duration | ~35 minutes |
| NSF events extracted | 179 (1 user_message, 38 agent_message, 67 tool_call, 67 tool_result, others gated) |
| Signal-gate reasons fired | `correction · error · gotcha · convention` |
| Claims contributed | 6 |

### Session 2 — Issue #5358

| | |
|---|---|
| Issue | [#5358 — takes_run_context() silently swallows NameError on TYPE_CHECKING-hidden RunContext, causing silent dispatch failure](https://github.com/pydantic/pydantic-ai/issues/5358) |
| Session id (Claude Code) | `870cdc5a-4983-446e-a0fe-c26507b40cd4` |
| Captured | 2026-05-30 |
| Wall-clock duration | ~similar |
| Claims contributed | 3 |

## Compilation

| | |
|---|---|
| `agent-lore` version | `0.1.0`, commit `97dcc78` |
| Model | `claude-sonnet-4-6` via Anthropic API |
| Temperature | `0` (deterministic structured-output extraction) |
| Max tokens | `8192` |
| Compile command | equivalent to `lore compile --repo ~/demos/pydantic-ai --transcripts ~/.claude/projects/-Users-srijansaket-demos-pydantic-ai` |
| Compile cost | ~$0.40 (combined input + output for both sessions) |
| Scrub redactions | 0 (no secrets in either session) |

## Result stats

- **9 active claims** across **4 scopes** and **3 topics**.
- **100% fidelity** — every anchor's quote resolves verbatim against its session's transcript content (the fidelity gate enforces this at extraction time; defects are dropped before the claim is admitted).
- **0 conflicts** — the two sessions cover disjoint scopes (`_utils.py` introspection vs UI adapter round-tripping), so no `(scope, kind, topic)` group has claims from ≥2 sessions disagreeing.

## Reproducibility notes

You cannot exactly reproduce these 9 claims — Claude Code sessions are non-deterministic by their nature, and your investigation will go down different code paths than ours did. What you CAN reproduce:

1. **The pipeline mechanism.** Install `agent-lore`, do your own real Claude Code sessions on pydantic-ai (or any repo), and run `lore compile`. The output shape (claims with verbatim anchors, scope-grouped book, deterministic claim IDs) will be the same.
2. **Anchor verification of *this* example.** Every line-numbered anchor in `book.md` (e.g. `ag_ui/_adapter.py:181-182`) refers to pydantic-ai at commit `7a5bec6`. You can `git checkout 7a5bec6` in your clone and find each cited line.
3. **The Day-2 inheritance behavior.** After your own compile, queries via `lore query "..."` will retrieve relevant claims from your session(s), demonstrating the same cross-session inheritance pattern.

## What was deliberately not done

- No conflict was manufactured. Both sessions covered legitimately different scopes; we let the data speak.
- No claims were edited post-extraction. The book is the raw output, including phrasing quirks from the model.
- No anchors were rewritten or "tightened." If a verbatim quote feels long, that's the model's choice — `lore`'s only job is to keep it honest, and it does.

## Lineage

- The capture process and per-issue session briefs that drove these sessions live in [`docs/demo/capture-playbook.md`](../../demo/capture-playbook.md) and [`docs/demo/session-briefs.md`](../../demo/session-briefs.md).
- Real-data findings that surfaced during this work — four bugs in `agent-lore` itself caught and fixed before producing this example — are in commit [`a62be7f`](https://github.com/srijansk/agent-lore/commit/a62be7f).
