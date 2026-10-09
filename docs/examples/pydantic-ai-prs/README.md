# Example: `crewlore` compiled from [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) pull requests

A current-format snapshot (crewlore 0.4.0, 2026-10-09): `lore import-prs pydantic/pydantic-ai --limit 100` on a repo nobody had run an agent in locally. The last 100 closed pull requests were scanned; 24 were detected as written by a coding agent (6 closed, 18 merged); they compiled into **130 claims**, 15 of them marked **not adopted**.

The point of this example is that every anchor can be followed. The scrubbed source threads are committed in [`sessions/`](sessions/), so a ref like `pr_pydantic__pydantic-ai__9988#event-12` is the thirteenth line of `sessions/pr_pydantic__pydantic-ai__9988.jsonl`, and a `path:line` ref is where an inline review comment sat in the pull request.

## Files

| File | What it is |
|---|---|
| [`book.md`](book.md) | The rendered knowledge book, exactly as `lore` wrote it to `.lore/knowledge/README.md`. |
| [`claims.jsonl`](claims.jsonl) | The structured claims, one per line: kind, scope, action, adoption, provenance, anchors. |
| [`sessions/`](sessions/) | The 24 scrubbed session files the anchors point into. |
| [`provenance.md`](provenance.md) | Command, model, counts, what the fidelity gate dropped, cost estimate, per-PR table. |
| [`stats.json`](stats.json) | The same numbers, machine-readable. |

## What to check

1. Pick any claim in `book.md`, open the session file its anchor names, and read the quoted event. The quote must appear there (whitespace, case and Markdown decoration aside; see [`docs/anchors.md`](../../anchors.md)).
2. Pick a claim marked `· not adopted` and read the pull request it came from on GitHub. It should be a declined approach, and the *Instead* action should match what the reviewers asked for.
3. Read `provenance.md` for how many proposals the gate dropped. That is the honest measure of extraction quality; the store itself is clean by construction.

## What this example does not show

- A real cross-PR disagreement. The one conflict recorded (end of `book.md`) is three claims that *agree* about the `.github/` maintainer-only rule, grouped as a disagreement because the lexical conflict detector saw the same scope, kind and topic with different statements. It is left in as an honest example of that mechanism's current weakness.
- Anything about transcripts: this snapshot is pull requests only. The older [`pydantic-ai/`](../pydantic-ai/) snapshot is the session-based one, compiled with 0.1.0.
- Long-horizon lifecycle behaviour; the claims were minutes old when committed.
