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

All three sessions ran in Claude Code, in the cloned target repo directory.

### Session 1 — Issue #5679 (G1)

| | |
|---|---|
| Issue | [#5679 — \[roundtrip-sweep\] Vercel AI adapter: TextContent.metadata silently dropped on round-trip](https://github.com/pydantic/pydantic-ai/issues/5679) |
| Session id (Claude Code) | `a8fa3beb-ec13-4ba2-8f68-9c745eecfaa2` |
| Captured | 2026-05-28 |
| Wall-clock duration | ~35 minutes |
| NSF events extracted | 179 (1 user_message, 38 agent_message, 67 tool_call, 67 tool_result) |
| Signal-gate reasons fired | `correction · error · gotcha · convention` |
| Claims contributed | 8 |

### Session 2 — Issue #5358 (G3)

| | |
|---|---|
| Issue | [#5358 — takes_run_context() silently swallows NameError on TYPE_CHECKING-hidden RunContext, causing silent dispatch failure](https://github.com/pydantic/pydantic-ai/issues/5358) |
| Session id (Claude Code) | `870cdc5a-4983-446e-a0fe-c26507b40cd4` |
| Captured | 2026-05-30 |
| NSF events extracted | 63 (6 user_message, 11 agent_message, 23 tool_call, 23 tool_result) |
| Signal-gate reasons fired | `correction · error · gotcha · convention` |
| Claims contributed | 4 |

### Session 3 — Issue #5536 (D1)

| | |
|---|---|
| Issue | [#5536 — HITL approval signal is a plain `bool` — hardening proposal (narrow vs proper fix)](https://github.com/pydantic/pydantic-ai/issues/5536) |
| Session id (Claude Code) | `409b2ad6-82d0-4ef9-95dd-223ecf0cdc73` |
| Captured | 2026-05-31 |
| Wall-clock duration | ~16 minutes |
| NSF events extracted | 63 (4 user_message, 9 agent_message, 25 tool_call, 25 tool_result) |
| Signal-gate reasons fired | `correction · error · convention` |
| Claims contributed | 6 |

## Compilation

| | |
|---|---|
| `agent-lore` version | `0.1.0` |
| Model | `claude-sonnet-4-6` via Anthropic API |
| Temperature | `0` (deterministic structured-output extraction) |
| Max tokens | `8192` |
| Compile command | equivalent to `lore compile --repo ~/demos/pydantic-ai --transcripts ~/.claude/projects/-Users-srijansaket-demos-pydantic-ai` |
| Compile cost | ~$0.60 (combined input + output across three sessions) |
| Scrub redactions | 0 (no secrets in any of the three sessions) |

## Result stats

- **18 active claims** across **8 scope groupings** and **5 distinct topics**.
- **100% fidelity** under the canonical-form contract defined in [`docs/anchors.md`](../../anchors.md). Every anchor's quote canonically resolves to a substring of its source session's content. The canonical form tolerates whitespace, case, and Markdown decoration; it rejects content drift, fabrication, paraphrase, and out-of-order stitching.
- **0 conflicts** — the three sessions cover disjoint scopes (UI adapter round-tripping, decorator introspection, and durable-execution threat modeling), so no `(scope, kind, topic)` group has claims from ≥2 sessions disagreeing.

## Reproducibility notes

You cannot exactly reproduce these 18 claims — Claude Code sessions are non-deterministic in their content, and your investigation will go down different code paths than ours did. What you CAN reproduce:

1. **The pipeline mechanism.** Install `agent-lore`, do your own real Claude Code sessions on pydantic-ai (or any repo), and run `lore compile`. The output shape (claims with canonically-verified anchors, scope-grouped book, deterministic claim IDs, scrub at ingest) will be the same.
2. **Anchor verification of *this* example.** Every anchor in `book.md` references content from one of the three captured sessions (session ids above). The canonical-form contract in `docs/anchors.md` defines what "verbatim" tolerates and rejects.
3. **The Day-2 inheritance behavior.** After your own compile, queries via `lore query "..."` will retrieve relevant claims from your session(s), demonstrating the same cross-session inheritance pattern.

## What was deliberately not done

- No conflict was manufactured. The three sessions covered legitimately different scopes; we let the data speak.
- No claims were edited post-extraction. The book is the raw output from `lore compile`, including phrasing quirks from the model.
- No anchors were rewritten or "tightened." If a quote feels long or includes the model's framing, that's its choice — `agent-lore`'s job is to keep it honest within the canonical-form contract, and it does.

## Real-data findings during this capture

The capture-and-compile process surfaced bugs and contract gaps in `agent-lore` itself, all addressed before committing this example:

1. **Haiku drift on long contexts** — Haiku model drifted away from structured-output format past ~30k transcript tokens; Sonnet 4.6 doesn't. Tracked, default model switched to Sonnet 4.6.
2. **Non-deterministic LLM output** — extractor needed `temperature=0` for reliable structured extraction. Fixed in commit [`a62be7f`](https://github.com/srijansk/agent-lore/commit/a62be7f).
3. **Fragile JSON parser** — `_safe_json_array` outermost-bracket fallback broke when prose contained brackets. Explicit code-fence regex extraction added. Fixed in `a62be7f`.
4. **Conflict detection over-flagging single-session claims** — multiple complementary findings from one session were flagged as conflicts. Tightened to require claims from ≥2 distinct sessions. Fixed in `a62be7f`.
5. **Fidelity gate's canonical-form contract was implicit** — the gate strictly substring-matched against prompt-rendered transcripts including `[actor/kind]` markers and `tool_call` content. Markdown decoration in source vs decoration-less model quotes also broke matches. The canonical-form contract was made explicit and documented in [`docs/anchors.md`](../../anchors.md); the haystack now excludes `tool_call` events and the canonical form strips Markdown decoration consistently on both sides. Adversarial tests pin down what's still rejected (fabrication, content drift, stitching).

That's the "test on real data before prod" payoff — five real bugs caught and fixed by capturing real sessions before the project went public.

## Lineage

- The capture process and per-issue session briefs that drove these sessions live in [`docs/demo/capture-playbook.md`](../../demo/capture-playbook.md) and [`docs/demo/session-briefs.md`](../../demo/session-briefs.md).
