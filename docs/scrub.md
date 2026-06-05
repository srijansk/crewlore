# Secret scrubbing — coverage contract

Anchors are verbatim transcript excerpts and the store is committed plaintext, so any secret that lands in a session must be redacted before the session is written. This doc enumerates exactly what the scrubber catches and what it doesn't — so you can make an informed call about whether you also want a human review step before pushing `.lore/`.

The scrubbing runs **at ingest**, before storage, before the LLM call, before anchors are written. See `lore.scrub.scrub_text` for the implementation.

## What gets redacted

Each pattern is high-precision (anchored by a distinctive prefix or shape) to keep false positives low. The replacement is a labelled token so a reader can see *what* was redacted, not just that something was.

| # | Secret class | Recognizer | Replacement |
|---|---|---|---|
| 1 | RSA / EC / OpenSSH **private-key blocks** | `-----BEGIN ... PRIVATE KEY----- … -----END ... PRIVATE KEY-----` | `[REDACTED:private-key]` |
| 2 | **OpenAI / Anthropic / generic `sk-*` API keys** | `sk-[A-Za-z0-9_-]{16,}` | `[REDACTED:api-key]` |
| 3 | **AWS Access Key ID** | `AKIA[0-9A-Z]{16}` | `[REDACTED:aws-key]` |
| 4 | **GitHub classic PAT** | `ghp_[A-Za-z0-9]{20,}` | `[REDACTED:github-token]` |
| 5 | **GitHub fine-grained PAT** | `github_pat_[A-Za-z0-9_]{22,}` | `[REDACTED:github-token]` |
| 6 | **Google API key** | `AIza[A-Za-z0-9_-]{35}` | `[REDACTED:google-api-key]` |
| 7 | **Slack tokens** (bot, user, app, refresh, app-level) | `xox[abprs]-[A-Za-z0-9-]{10,}` | `[REDACTED:slack-token]` |
| 8 | **HuggingFace user-access tokens** | `hf_[A-Za-z0-9]{30,}` | `[REDACTED:hf-token]` |
| 9 | **JWTs** (3 base64url segments, starting with `eyJ`) | `eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+` | `[REDACTED:jwt]` |
| 10 | **Connection-string passwords** (`postgres://`, `mongodb://`, `mysql://`, `redis://`, `amqp(s)://`, `mssql://`) | password group between `user:` and `@host` | `[REDACTED:uri-password]` (scheme + user + host preserved) |
| 11 | **Generic `password=` / `secret=` / `token=` / `api_key=` assignment shapes** | `(?i)(?:password\|secret\|token\|api[_-]?key)\s*[:=]\s*['"]?[^\s'"]{6,}` | `[REDACTED:secret]` |

Patterns are tested individually in `tests/unit/test_scrub.py` (one test per class above, plus a negative test that ordinary prose survives untouched).

## What is *not* redacted

The scrubber is **not a DLP system**. It raises the floor on what reaches the model and the store; it is not a substitute for a security review when sensitive content is in play. Specifically:

- **Custom or in-house token formats** (e.g. an internal service that issues opaque tokens with no distinctive prefix). If your team has one, add a pattern to `src/lore/scrub.py` and a test in `tests/unit/test_scrub.py`.
- **Free-form prose containing the secret value** without one of the recognized markers (e.g. someone literally types `the password is hunter2` — the generic assignment pattern catches `password = …` but not free prose).
- **Already-base64'd or otherwise encoded secrets** the model received as opaque blobs.
- **PII** (emails, phone numbers, names) — out of scope for this module; if you need PII handling, layer a separate pass.

If you want a quick visual audit before sharing `.lore/` with anyone, `grep -RE 'REDACTED' .lore/` shows everything the scrubber caught (good sign that it *is* catching things), and `git diff .lore/` shows exactly what changed since your last commit (manual review surface).

## Raw transcripts are gitignored by default

`crewlore`'s default `.gitignore` excludes `.lore/sessions/` — your captured transcripts never leave your machine. Only the *compiled claims* (`.lore/claims/`) and the *rendered book* (`.lore/knowledge/`) are committed by default, and those go through the scrubber first.

## Extending coverage

The recipe is small:

1. Add a pattern + replacement to `_PATTERNS` in `src/lore/scrub.py`. Put it before the generic-assignment pattern (which is last) so a more specific shape claims its match first.
2. Add a positive test (`test_redacts_<thing>`) and verify a non-secret string isn't false-positive-redacted.
3. Update this doc (add a row to the table above).

If your pattern is rare / domain-specific (e.g. an internal-only token shape), keep it local; if it's a widespread public format that anyone running `crewlore` would benefit from, open a PR.

## Roadmap

- **Approve-before-push gate** — a `lore review` command that surfaces the diff in `.lore/claims/` since the last commit and asks the developer to acknowledge before staging. Tracked as the strong complement to automated scrubbing; not in v0.1 scope.
- **Pattern-coverage badge** — a small CI job that fuzzes random strings against the pattern set and reports any new secret shapes that snuck through.
- **Pluggable scrubbers** — projects with their own DLP tooling could chain `crewlore`'s scrubber with theirs.

If you find a real-world secret shape that bypasses the current set, [report it as a security issue](../.github/SECURITY.md) rather than filing a public bug — give me a chance to ship the pattern before it's on Hacker News.
