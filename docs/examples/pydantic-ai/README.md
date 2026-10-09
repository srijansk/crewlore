# Example: `crewlore` compiled on [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai)

A snapshot of `crewlore` 0.1.0 output on a public codebase, compiled in May 2026. Every claim in `book.md` came from a Claude Code investigation of a real open issue in pydantic-ai. The claims can be checked against the public issues and code; the three source sessions themselves are not published, so the anchor quotes cannot be clicked through to a transcript line, and this snapshot predates the navigable anchor positions and the adoption field that later releases added.

## Headline numbers

| | |
|---|---|
| **Target repo** | [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) (20k+ ⭐, MIT) |
| **Sessions captured** | 3 Claude Code sessions on real open issues ([#5679](https://github.com/pydantic/pydantic-ai/issues/5679), [#5358](https://github.com/pydantic/pydantic-ai/issues/5358), [#5536](https://github.com/pydantic/pydantic-ai/issues/5536)) |
| **Compiled claims** | **18** (7 gotchas · 7 decisions · 3 procedures · 1 style) |
| **Distinct scopes** | **9 groupings** spanning UI adapters, decorator introspection, durable execution, toolsets, tests, and the version policy |
| **Anchor gate** | Every anchor in the snapshot passed the verbatim gate against its session (which is true of every store by construction — the gate drops what fails; the 0.1.0 run did not record how many proposals it dropped). See [`docs/anchors.md`](../../anchors.md) for the contract. |
| **Conflicts** | 0 (the three sessions cover different scopes; no cross-session disagreement to record) |
| **Compile cost** | ~$0.60 with Sonnet 4.6 (deterministic at temperature=0) |

## What's in this directory

| File | What it is |
|---|---|
| [`book.md`](book.md) | The compiled knowledge book, exactly as `lore` rendered it to `.lore/knowledge/README.md`. This is what a teammate would see on `git pull`. |
| [`claims.jsonl`](claims.jsonl) | The raw structured claims, one JSON object per line — schemas, provenance, anchors, and usage stats. Skim for verifiability. |
| [`provenance.md`](provenance.md) | Full reproducibility detail: session IDs, dates, exact commit of pydantic-ai, model, `crewlore` version. |

## How to verify

You can't reproduce the *exact* claims (Claude Code sessions are non-deterministic in their content; even at extractor temperature=0, the input prose varies between sessions). But you can verify the mechanism end-to-end:

```bash
# 1. Install
pipx install crewlore

# 2. Clone the same target
gh repo clone pydantic/pydantic-ai ~/demos/pydantic-ai
cd ~/demos/pydantic-ai && lore init

# 3. Do your own Claude Code session(s) on real issues
# 4. Compile
export ANTHROPIC_API_KEY=...
lore compile

# 5. Browse .lore/knowledge/README.md
```

You can read each claim in `book.md` against the linked issue and the pydantic-ai code at the documented commit and judge whether it is true. What you cannot do with this snapshot is open the quoted transcript line, because the sessions are not published.

## What this example does and doesn't prove

**Proves:**
- The compile pipeline produces well-formed, scope-tagged, citation-bearing claims on a real public codebase across three sessions.
- The verbatim-anchor gate holds on real-data extraction: every claim that reached the store carries a quote that resolved against its session.
- Topic-reuse and dedup work — three sessions on different scopes produced disjoint topic clusters.
- The trivial parts of a session are gated out; only friction/resolution events were compiled.
- Querying for themes from one session retrieves the relevant slice without crossing into unrelated areas (checked by hand at capture time; the queries were not recorded in this snapshot).

**Does NOT prove:**
- Behavior at scale (10+ sessions, multiple authors). On the roadmap.
- Real cross-session conflicts — the three sessions in this example cover different scopes, so no contradiction surfaced. The conflict mechanism is unit-tested; a real-data conflict example will land when two captured sessions reach different conclusions on the same scope+topic.
- Long-horizon lifecycle behavior (claim decay, pruning) — these claims were days old when captured; meaningful only over weeks.
- That the anchor refs are navigable — this snapshot's refs are free-text labels from the 0.1.0 extractor, the defect that 0.2.0 fixed by deriving positions from where the quote resolved.

## How this was captured

See [`provenance.md`](provenance.md) for the full procedural detail and [`docs/evaluating-on-your-codebase.md`](../../evaluating-on-your-codebase.md) for the general capture methodology.
