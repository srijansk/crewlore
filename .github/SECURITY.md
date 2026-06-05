# Security policy

`crewlore` is an early-stage open-source project. It runs locally and does not host any service on the maintainer's infrastructure — there is no server to attack — but it does process session transcripts that may contain sensitive content, and it ships a secret-scrubber that other people will rely on.

## Reporting a vulnerability

If you find anything in the following list, **please do not file a public issue**. Email **srijan@pavoai.com** with the details and I'll respond within 72 hours:

- A secret-scrub bypass (a real-world secret format that `lore.scrub` passes through un-redacted)
- A way for `crewlore` to read or leak data from outside its working directory
- A way for `lore serve` / the MCP server to expose more than the user intended
- A dependency-chain vulnerability with practical exploitability against `crewlore`'s usage

For ordinary bugs and feature requests, please open a GitHub issue.

## Scope

In scope:

- `crewlore`'s own code (`src/lore/`)
- Documented behavior of `lore init`, `lore compile`, `lore query`, `lore status`, `lore watch`, `lore serve`
- The secret-scrubber pattern set in `src/lore/scrub.py` (see also `docs/scrub.md` for the documented coverage contract)

Out of scope:

- Vulnerabilities in the model provider's API (Anthropic / OpenAI)
- Issues that require physical/local access to the developer's machine
- Theoretical or non-exploitable patterns

## Disclosure preference

Once a fix is shipped, I will credit reporters in the release notes unless asked not to. Coordinated disclosure window: 7–14 days from a fix landing, depending on severity.
