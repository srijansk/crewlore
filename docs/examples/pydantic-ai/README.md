# Example: `crewlore` compiled on [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai)

Real-data evidence of `crewlore` working on a public codebase. Every claim in `book.md` cites session content from a Claude Code investigation of a real open issue in pydantic-ai; the cited code lines live in pydantic-ai's public repo and you can verify each one.

## Headline numbers

| | |
|---|---|
| **Target repo** | [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) (17.3k ⭐, MIT) |
| **Sessions captured** | 3 Claude Code sessions on real open issues ([#5679](https://github.com/pydantic/pydantic-ai/issues/5679), [#5358](https://github.com/pydantic/pydantic-ai/issues/5358), [#5536](https://github.com/pydantic/pydantic-ai/issues/5536)) |
| **Compiled claims** | **18** (7 gotchas · 7 decisions · 3 procedures · 1 style) |
| **Distinct scopes** | **8 groupings** spanning UI adapters, decorator introspection, durable execution, toolsets, tests, and the version policy |
| **Fidelity** | **100%** — every anchor's quote canonically resolves against its session's content. See [`docs/anchors.md`](../../anchors.md) for the canonical-form spec. |
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
pipx install --python python3.13 git+https://github.com/srijansk/crewlore.git

# 2. Clone the same target
gh repo clone pydantic/pydantic-ai ~/demos/pydantic-ai
cd ~/demos/pydantic-ai && lore init

# 3. Do your own Claude Code session(s) on real issues
# 4. Compile
export ANTHROPIC_API_KEY=...
lore compile

# 5. Browse .lore/knowledge/README.md
```

You can also verify *this* example by reading each anchor in `book.md` and checking it represents the source's content faithfully — the canonical form in `docs/anchors.md` defines what "verbatim" tolerates (Markdown decoration, whitespace, case) and what it rejects (content drift, fabrication, paraphrase).

## What this example does and doesn't prove

**Proves:**
- The compile pipeline produces well-formed, scope-tagged, citation-bearing claims on a real public codebase across three sessions.
- 100% fidelity is achievable on real-data extraction — every claim's anchor canonically resolves against its source session.
- Topic-reuse and dedup work — three sessions on different scopes produced disjoint topic clusters.
- The trivial parts of a session are gated out; only friction/resolution events were compiled.
- Day-2 inheritance works: querying for themes from one session retrieves the relevant slice without crossing into unrelated areas. See the validation queries in the provenance doc.

**Does NOT prove yet:**
- Behavior at scale (10+ sessions, multiple authors). On the roadmap.
- Real cross-session conflicts — the three sessions in this example cover different scopes, so no contradiction surfaced. The conflict mechanism is unit-tested; a real-data conflict example will land when two captured sessions reach different conclusions on the same scope+topic.
- Long-horizon actuation behavior (claim decay, lifecycle pruning) — these claims are days old; meaningful only over weeks.

## How this was captured

See [`provenance.md`](provenance.md) for the full procedural detail and [`docs/evaluating-on-your-codebase.md`](../../evaluating-on-your-codebase.md) for the general capture methodology.
