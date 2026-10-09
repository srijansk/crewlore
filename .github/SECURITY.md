# Security policy

`crewlore` is an early-stage open-source project. It runs locally and hosts no service — there is no server to attack — but it processes session transcripts and pull-request threads that may contain sensitive content, and it ships a secret scrubber that other people will rely on.

## Reporting a vulnerability

Please **do not file a public issue** for anything on this list. Use GitHub's private reporting instead: open the repository's **Security** tab and choose **Report a vulnerability**. Reports go only to the maintainer, who will respond within 72 hours.

- A secret-scrub bypass (a real-world secret format that `lore.scrub` passes through un-redacted)
- A way for `crewlore` to read or leak data from outside the directories it is told to read (this repo's `.lore/`, the configured transcript directory, the pull-request export it fetched)
- A way for `lore serve` / the MCP server to expose more than the user intended
- A dependency-chain vulnerability with practical exploitability against `crewlore`'s usage

For ordinary bugs and feature requests, please open a GitHub issue.

## Scope

In scope:

- `crewlore`'s own code (`src/lore/`)
- Documented behavior of `lore init`, `lore compile`, `lore watch`, `lore import-prs`, `lore query`, `lore feedback`, `lore status`, `lore serve`
- The secret-scrubber pattern set in `src/lore/scrub.py` (see `docs/scrub.md` for the documented coverage contract)

Out of scope:

- Vulnerabilities in a model provider's API (Anthropic, OpenAI) or in a local model server you run (Ollama, LM Studio, vLLM)
- Issues that require physical or local access to the developer's machine
- Theoretical or non-exploitable patterns

## Disclosure preference

Once a fix is shipped, reporters are credited in the release notes unless they ask not to be. Coordinated disclosure window: 7–14 days from a fix landing, depending on severity.
