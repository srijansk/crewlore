# Examples — `crewlore` on real codebases

Committed snapshots of `crewlore` output on public codebases: the rendered book, the structured claims, and the compile details, so the numbers in the main README point at something you can open.

| Example | Target | Source | Compiled with | Claims | Anchors checkable? |
|---|---|---|---|---|---|
| [`pydantic-ai-prs/`](pydantic-ai-prs/) | [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) (20k+ ⭐) | 24 agent-authored pull requests out of the last 100 closed (18 merged, 6 declined) | crewlore 0.4.0, Sonnet 5.5, 2026-10-09 | 130 (15 not adopted) | Yes — the scrubbed source threads are committed alongside |
| [`pydantic-ai/`](pydantic-ai/) | same repo | 3 Claude Code sessions on open issues | crewlore 0.1.0, Sonnet 4.6, May 2026 | 18 | No — sessions not published; 0.1.0 free-text anchor refs |

Start with `pydantic-ai-prs/`: pick any claim in its `book.md`, open the session file its anchor names, and find the quoted event. Its `provenance.md` records what the fidelity gate dropped, which is the honest measure of extraction quality.

Contribute one: follow [`docs/evaluating-on-your-codebase.md`](../evaluating-on-your-codebase.md), then open a PR adding your `docs/examples/<repo-name>/` snapshot with the same file shape (`book.md`, `claims.jsonl`, `provenance.md`, `README.md`, and `sessions/` when the source is public). For `lore import-prs` snapshots, note the `--limit` and `--state` used.
