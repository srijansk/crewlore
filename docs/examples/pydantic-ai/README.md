# Example: `agent-lore` compiled on [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai)

Real-data evidence of `agent-lore` working on a public codebase. Every claim in `book.md` cites a verbatim quote from a Claude Code session investigating a real open issue in pydantic-ai; the cited code lines live in pydantic-ai's public repo and you can verify each one.

## Headline numbers

| | |
|---|---|
| **Target repo** | [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) (17.3k ⭐, MIT) |
| **Sessions captured** | 2 Claude Code sessions on real open issues ([#5679](https://github.com/pydantic/pydantic-ai/issues/5679) and [#5358](https://github.com/pydantic/pydantic-ai/issues/5358)) |
| **Total session time** | ~80 minutes |
| **Compiled claims** | **9** (4 gotchas · 3 decisions · 1 procedure · 1 style) |
| **Distinct scopes** | **4** (`_utils.py` · `ag_ui/_adapter.py` · `vercel_ai/_adapter.py` · `docs/version-policy.md`) |
| **Fidelity** | **100%** — every anchor verbatim-resolves against its source transcript |
| **Conflicts** | 0 (the two sessions cover different scopes; no cross-session disagreement to record) |
| **Compile cost** | ~$0.40 with Sonnet 4.6 |

## What's in this directory

| File | What it is |
|---|---|
| [`book.md`](book.md) | The compiled knowledge book, exactly as `lore` rendered it to `.lore/knowledge/README.md`. This is what a teammate would see on `git pull`. |
| [`claims.jsonl`](claims.jsonl) | The raw structured claims, one JSON object per line — schemas, provenance, anchors, and usage stats. Skim for verifiability. |
| [`provenance.md`](provenance.md) | Full reproducibility detail: session IDs, dates, exact commit of pydantic-ai, model, `lore` version. |

## How to verify

You can't reproduce the *exact* claims (Claude Code sessions are non-deterministic by nature), but you can verify the mechanism end-to-end:

```bash
# 1. Install
pipx install --python python3.13 git+https://github.com/srijansk/agent-lore.git

# 2. Clone the same target
gh repo clone pydantic/pydantic-ai ~/demos/pydantic-ai
cd ~/demos/pydantic-ai && lore init

# 3. Do your own Claude Code session(s) investigating real issues
# 4. Compile
export ANTHROPIC_API_KEY=...
lore compile

# 5. Browse .lore/knowledge/README.md
```

You can also verify *this* example by checking each anchor in `book.md` against pydantic-ai's source at the commit listed in `provenance.md`. Every line-quoted anchor (e.g. `ag_ui/_adapter.py:181-182`) points at real code.

## What this example does and doesn't prove

**Proves:**
- The compile pipeline produces well-formed, scope-tagged, verbatim-cited claims on a real public codebase.
- 100% fidelity is achievable on real-data extraction (every anchor we emit resolves against its source).
- Topic-reuse and dedup work — two sessions on different scopes produced disjoint topic clusters.
- The trivial parts of a session are gated out; only friction/resolution events were compiled.
- Day-2 inheritance works: querying for themes from one session retrieves the relevant slice without crossing into unrelated areas (see [the validation queries in our notes](#)).

**Does NOT prove yet:**
- Behavior at scale (10+ sessions, multiple authors). On the roadmap.
- Real cross-session conflicts — both sessions in this example cover different scopes, so no contradiction surfaced. The conflict mechanism is unit-tested; a real-data conflict example will land with the next capture round.
- Long-horizon actuation behavior (claim decay, lifecycle pruning) — both these claims are days old; meaningful only over weeks.

## How this was captured

See [`provenance.md`](provenance.md) for the full procedural detail and [`docs/demo/capture-playbook.md`](../../demo/capture-playbook.md) for the methodology we used.
