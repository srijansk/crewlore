# agent-lore

> An open, local-first, harness-agnostic **compiler** that turns a team's AI-coding-agent sessions into a high-quality, versioned, plaintext tribal-knowledge layer living in the team's own git repo — and serves it back into any agent at the start of every session.

**Status:** v0.1, alpha. Building in the open. CLI command is `lore`.

## Why

Knowledge discovered inside an agent session is private by default and lost by default. The next engineer — and every future agent run — re-derives the same context, re-learns the same gotcha, re-makes a decision the team already made. `lore` captures sessions, *compiles* them (dedup, conflict-resolution, authority/recency scoring, distillation) into a shared plaintext artifact in your repo, and serves the relevant slice back to any agent. Nothing leaves your infrastructure.

The compilation quality — not the plumbing — is the product. And a knowledge layer's value is an **actuation** property, not a storage property: `lore` is built around a usage-driven loop so the knowledge layer drives better sessions instead of becoming a dumpyard of unused claims.

## Architecture

```
ingest+scrub (thin adapters) -> compile (the moat) -> serve (plaintext + MCP)
   transcripts -> NSF             NSF -> claims          .lore/ in your repo
                                        |
                                 actuation loop  <-  usage from serve
                          (decay unused / reinforce used / retire overridden)

        `lore watch` runs ingest -> compile -> prune automatically, on an interval
```

The intelligence is in **compile**. Capture and serve are deliberately thin so adding a harness is a small adapter contribution. Compilation is **automatic** (`lore watch`): it reads existing transcripts, scrubs secrets, compiles incrementally, and prunes — no human trigger. The **actuation loop** closes the cycle: usage recorded at serve time drives a usage-based lifecycle so the store *churns* instead of growing into a dumpyard of unused claims.

## Try the demo (no API key)

```bash
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
python scripts/demo.py
```

It runs the whole loop on synthetic, public-safe sessions and prints the compiled knowledge book plus the two success-criteria numbers:

- **Fidelity** — every claim's anchor resolves verbatim against its source (a claim without a verifiable anchor is a defect, dropped at extraction).
- **Preventable-rediscovery rate** — replay the post-cutoff sessions and count how many re-derived something a prior claim already knew. This measures *actuation* (did the knowledge change a session), not quiz-passing. Run it on a public repo's session history and the headline writes itself.

It also surfaces a recorded **conflict** (two decisions disagree → kept with both provenances, never silently merged).

## Quickstart (target DX)

```bash
pipx install agent-lore          # or: uvx --from agent-lore lore
cd my-team-repo
lore init                        # creates .lore/ in the repo
lore watch                       # AUTOMATIC: ingest transcripts, scrub secrets, compile, prune
                                 #   (lore watch --once for cron/CI; lore compile for a manual pass)
lore serve                       # MCP server for query-time retrieval
git add .lore/knowledge .lore/claims && git commit
```

Compilation is **automatic by default** — `lore watch` reads the coding agent's existing on-disk transcripts on an interval, so nobody has to remember to compile. Secrets are scrubbed at ingest before anything is stored or sent to the model.

## Known limitations (v0.1)

- **Conflict detection is bottlenecked by alignment, not the rule.** Conflicts are found among claims sharing `(scope, kind, topic)` by *exact lexical match*. The rule is correct and unit-tested, but real models phrase those coordinates inconsistently across sessions (observed live: one ledger decision landed at scope `ledger service` / topic `ledger_storage`, the contradicting one at scope `ledger storage` / topic `database_selection`), so genuine disagreements can fail to group. The intended fix is **semantic, not more lexical rules**: cluster claims by embedding similarity within a kind ("same question?"), then have the model adjudicate ("do they disagree?"), and tune that. v0.1 ships a cheap prior — feeding the existing topic vocabulary back to the extractor for reuse; grounding `scope` in the files a session touched is an optional signal. Deferred.
- **Live extraction validated on Anthropic Haiku;** the deterministic stages are fully tested, extraction is exercised through an injected `complete()` seam plus a live smoke test. Quality of extracted claims tracks the model used.
- **Human review gate is partial.** A secret-scrubber runs at ingest (API keys, AWS keys, private-key blocks, secret assignments redacted before anything is stored or sent to the model) — the automated half of the leakage gate. The *quality* half (a human approving claims before they're served, so noisy sessions don't yield junk claims — observed live: a debug dump produced a muddled claim) is still pending; for now lean on git PR-review of the `.lore/claims` diff. See the design review's C3/C4.

## License

MIT. See `LICENSE`.
