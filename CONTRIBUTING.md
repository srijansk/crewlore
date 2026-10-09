# Contributing to crewlore

Thanks for considering a contribution. `crewlore` is small, alpha, and intentionally focused — the best way to help right now is to try it on a real repo, open a [discussion](https://github.com/srijansk/crewlore/discussions) about what worked and what didn't, and (if you're up for it) ship a small, well-scoped PR.

Before substantial changes, please open a discussion or an issue so we can agree on the shape before you write code. A 5-minute conversation usually saves an hour of rework.

## The highest-leverage contribution

**Add a capture adapter for another coding agent.** The architecture is deliberately split: all the intelligence is in compile, and capture is a thin mapping from one coding agent's session artifacts into a shared event format. A new adapter is one self-contained module that maps a harness's session artifacts into the Normalized Session Format (NSF). Look at `src/lore/capture/adapters/claude_code.py` (transcripts) and `src/lore/capture/adapters/github_pr.py` (pull-request threads), with their tests in `tests/unit/`, for the shape — that's the entire surface area. If your source needs fetching rather than reading files off disk, keep the fetch in `src/lore/capture/sources/` and the mapping in the adapter, as the GitHub source does, so the adapter stays testable without a network.

## Local setup

```bash
git clone https://github.com/srijansk/crewlore.git
cd crewlore
uv sync --all-extras
uv run pytest
```

You should see all tests green. If anything's off, that's a bug — please open an issue.

## Running the tests

```bash
uv run pytest                   # full suite
uv run pytest tests/unit        # fast feedback loop
uv run pytest tests/integration # store/compile orchestration
uv run pytest tests/e2e         # the whole vertical, deterministic
```

The suite is fully deterministic. **No real API calls happen during `pytest`** — LLM extraction is exercised behind an injected `complete(prompt) -> str` callable so tests are fast, hermetic, and free. To exercise the live extraction path, set `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) and run `lore compile` against a real repo's transcripts.

## Code style

- Linting: `uv run ruff check .` (what CI runs) and `uv run ruff check --fix .` for autofixes. Line length 100.
- Type hints throughout (`from __future__ import annotations` at the top of every module).
- Pydantic models for any data that crosses a module boundary.

## Test-driven development

The project was built test-first and that's the discipline for contributions. Concretely: write the failing test that captures the desired behavior, verify it fails for the expected reason, then write the smallest implementation that makes it pass. The schema and pipeline tests in `tests/unit/` are good models for the shape.

If you're fixing a bug, please include a regression test that fails on `main` and passes with your fix.

## Pull requests

- Branch from `main`; keep PRs focused on one thing.
- Include the test that proves the change works (red → green in the same PR).
- Run `uv run pytest` and `uv run ruff check .` before pushing.
- Reference the issue or discussion the PR addresses.

## Reporting issues

For bugs: please include the command you ran, the observed output, the expected output, and your Python version + OS. If the bug involves real transcripts, **don't paste their contents** — describe the shape (kinds of events, rough size) instead.

For security issues, use the private reporting path in [SECURITY.md](.github/SECURITY.md) rather than filing publicly.

## Code of conduct

Be excellent to each other. Discussions and reviews are technical and direct, but always respectful — disagree about the work, never about the person.

## License

By contributing you agree your contributions are licensed under the same MIT license that covers the project.
