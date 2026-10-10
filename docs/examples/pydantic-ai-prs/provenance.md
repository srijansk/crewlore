# Provenance

How `docs/examples/pydantic-ai-prs/` was produced, with enough detail to repeat it.

## Command

```bash
cd fresh-repo && lore init
lore import-prs pydantic/pydantic-ai --limit 100      # closed PRs, most recently updated first, agent-authored only
```

| | |
|---|---|
| Date | 2026-10-09 |
| crewlore version | 0.4.0 for extraction (the pipeline is the 0.3.0 one; 0.4.0 changed only the default model); book and conflicts re-derived with 0.4.2, see below |
| Model | `claude-sonnet-5-5` via the Anthropic API, no sampling parameters sent |
| Pull requests scanned | 100 most recently updated closed PRs |
| Detected as agent-authored | 24 (all Claude Code; detection by body marker) — 76 skipped as human-authored |
| Outcomes among the 24 | 6 closed, 18 merged |
| Sessions compiled | 24 (24 yielded at least one claim) |
| Wall-clock | 12 min 29 s, of which roughly seven minutes was the GitHub export |
| Estimated cost | about $0.79–$2.29 (144,603 input tokens estimated from session text; output and thinking tokens not metered by the CLI) |
| Secret-scrub redactions | see the run log line in the README |

## What the fidelity gate did

The model proposed 130 claims carrying 173 anchors. The gate dropped 0 anchors whose quote did not resolve verbatim against the source thread, and 0 claims that were left with no verified anchor or failed validation. 130 claims entered the store. This is the number to look at: a store's after-the-fact anchor check is 100% by construction, because the gate removes anything that would fail it.

An independent re-check of every anchor in `claims.jsonl` against the committed `sessions/` files (not the extractor's own check) found 0 that do not resolve.

## Output

| | |
|---|---|
| Active claims | 130 (61 gotcha · 45 decision · 12 procedure · 12 style) |
| Adoption | 115 current · 15 not adopted |
| Scopes | 88 |
| Conflicts recorded | 0 (the 0.4.0 detector recorded 1; see below) |
| Anchors | 173 — refs: 60 path:line, 113 session#event |

## Re-rendered with 0.4.2

On 2026-10-09, after the conflict detector was changed to require evidence of disagreement (crewlore 0.4.2), `book.md` and the conflict list were re-derived from the committed `claims.jsonl` with no model call: a store holding only these claims and no sessions was recompiled (`lore.compile.run.run_compile` with no sessions — the path `lore compile` takes for a teammate who has no local transcripts). `claims.jsonl` came out byte-identical. The one conflict the 0.4.0 detector had recorded — `clm_75189e4ed6c0`, `clm_8705a01acfb0` and `clm_8f6fc780f2dc`, three gotchas from PRs 9988, 9986 and 9899 that all say contributor PRs must not touch `.github/` — is no longer recorded, because the three carry no marker of disagreement: all are `current`, and all three actions forbid the same thing. The conflict count above and in `stats.json` reflects the re-render; every other number is from the original run.

## Per pull request

| PR | Agent | Detected by | Outcome | Events in session | Claims |
|---|---|---|---|---|---|
| [#4843](https://github.com/pydantic/pydantic-ai/pull/4843) | claude-code | commit-trailer | closed | 200 | 7 |
| [#6537](https://github.com/pydantic/pydantic-ai/pull/6537) | claude-code | body-marker | merged | 209 | 11 |
| [#7560](https://github.com/pydantic/pydantic-ai/pull/7560) | claude-code | body-marker | merged | 167 | 11 |
| [#8745](https://github.com/pydantic/pydantic-ai/pull/8745) | claude-code | body-marker | merged | 116 | 13 |
| [#9414](https://github.com/pydantic/pydantic-ai/pull/9414) | claude-code | body-marker | merged | 57 | 3 |
| [#9541](https://github.com/pydantic/pydantic-ai/pull/9541) | claude-code | body-marker | merged | 84 | 8 |
| [#9544](https://github.com/pydantic/pydantic-ai/pull/9544) | claude-code | body-marker | merged | 37 | 4 |
| [#9612](https://github.com/pydantic/pydantic-ai/pull/9612) | claude-code | body-marker | merged | 119 | 9 |
| [#9701](https://github.com/pydantic/pydantic-ai/pull/9701) | claude-code | commit-trailer | merged | 78 | 9 |
| [#9848](https://github.com/pydantic/pydantic-ai/pull/9848) | claude-code | body-marker | merged | 50 | 4 |
| [#9861](https://github.com/pydantic/pydantic-ai/pull/9861) | claude-code | body-marker | merged | 47 | 2 |
| [#9862](https://github.com/pydantic/pydantic-ai/pull/9862) | claude-code | body-marker | merged | 56 | 3 |
| [#9899](https://github.com/pydantic/pydantic-ai/pull/9899) | claude-code | body-marker | merged | 51 | 7 |
| [#9923](https://github.com/pydantic/pydantic-ai/pull/9923) | claude-code | commit-trailer | merged | 36 | 3 |
| [#9934](https://github.com/pydantic/pydantic-ai/pull/9934) | claude-code | body-marker | merged | 37 | 5 |
| [#9938](https://github.com/pydantic/pydantic-ai/pull/9938) | claude-code | body-marker | closed | 38 | 1 |
| [#9953](https://github.com/pydantic/pydantic-ai/pull/9953) | claude-code | body-marker | closed | 40 | 3 |
| [#9986](https://github.com/pydantic/pydantic-ai/pull/9986) | claude-code | body-marker | closed | 42 | 4 |
| [#9988](https://github.com/pydantic/pydantic-ai/pull/9988) | claude-code | body-marker | closed | 39 | 4 |
| [#9989](https://github.com/pydantic/pydantic-ai/pull/9989) | claude-code | body-marker | closed | 38 | 2 |
| [#10007](https://github.com/pydantic/pydantic-ai/pull/10007) | claude-code | body-marker | merged | 61 | 5 |
| [#10038](https://github.com/pydantic/pydantic-ai/pull/10038) | claude-code | body-marker | merged | 36 | 3 |
| [#10039](https://github.com/pydantic/pydantic-ai/pull/10039) | claude-code | body-marker | merged | 53 | 5 |
| [#10042](https://github.com/pydantic/pydantic-ai/pull/10042) | claude-code | body-marker | merged | 40 | 4 |

## What is committed here

- `sessions/*.jsonl` — the scrubbed, normalized session for each pull request: one event per line (`user_message`, `agent_message`, `diff` for commits, `tool_result` for CI checks, `accept`/`reject` for review verdicts and the merge or close). Anchor refs of the form `pr_<owner>__<repo>__<n>#event-<i>` index into these files (zero-based line number), and `path:line` refs come from inline review comments.
- `claims.jsonl` — the compiled claims exactly as written to `.lore/claims/claims.jsonl`, usage stats excluded.
- `book.md` — the rendered `.lore/knowledge/README.md`.
- `stats.json` — the numbers above, as produced by the build script.

Not committed: the raw pre-scrub exports under `.lore/sources/github/` (gitignored by design) and the extraction cache.

## What was deliberately not done

- No claims were edited, removed or re-ordered after extraction. The book is the raw output, including any phrasing the model chose.
- No pull request was hand-picked. The sample is the most recently updated closed PRs at the time of the run, filtered only by the agent-detection rule the tool applies to every repo.
- The run was not repeated to get a nicer result. The numbers above are from the single run that produced these files.
