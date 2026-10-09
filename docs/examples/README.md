# Examples — `crewlore` on real codebases

Committed snapshots of `crewlore` output on public codebases: the rendered book, the structured claims, and the compile details, so the numbers in the main README point at something you can open.

| Example | Target | Source | Compiled with | Claims |
|---|---|---|---|---|
| [`pydantic-ai/`](pydantic-ai/) | [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) (20k+ ⭐) | 3 Claude Code sessions on open issues | crewlore 0.1.0, May 2026 | 18 |

**What a snapshot does and does not let you check.** The claims can be read against the public issues and code they describe. The source sessions are not published, so the anchor quotes cannot be clicked through to a transcript line; and this snapshot predates the navigable `<session>#event-<n>` anchor positions (0.2.0) and the adoption field, so its anchor refs are the free-text labels the 0.1.0 extractor produced. A current-format example built with `lore import-prs` from public pull-request threads, with the source threads included so every anchor can be checked, is the next addition planned here.

Contribute one: follow [`docs/evaluating-on-your-codebase.md`](../evaluating-on-your-codebase.md), then open a PR adding your `docs/examples/<repo-name>/` snapshot with the same file shape (`book.md`, `claims.jsonl`, `provenance.md`, `README.md`). Snapshots compiled with `lore import-prs` are welcome too — note the source and the `--limit` and `--state` used in `provenance.md`, and include the exported threads if the repository is public.
