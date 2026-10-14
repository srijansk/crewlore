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
- Documented behavior of `lore init`, `lore compile`, `lore watch`, `lore import-prs`, `lore query`, `lore explain`, `lore feedback`, `lore status`, `lore serve`
- The secret-scrubber pattern set in `src/lore/scrub.py` (see `docs/scrub.md` for the documented coverage contract)

Out of scope:

- Vulnerabilities in a model provider's API (Anthropic, OpenAI) or in a local model server you run (Ollama, LM Studio, vLLM)
- Issues that require physical or local access to the developer's machine
- Theoretical or non-exploitable patterns

## Threat model

`crewlore` reads text that other people wrote (session transcripts, pull-request descriptions, reviews and comments), sends it to a model you configure, stores what the model returns, and hands that back to people and agents. Each hop is a place for someone else's text to do something it should not.

| Vector | What `crewlore` does |
|---|---|
| Prompt injection through a transcript or a pull-request thread (text that tells the extractor to ignore its rules, to record a particular claim, or to mark work adopted or declined) | The extractor frames the transcript as untrusted input: it sits inside a per-call delimiter, named in the prompt, that its content cannot forge; each event starts at the margin and continuation lines are indented, so content cannot forge an event header; the list of known topic keys, which the model wrote in earlier sessions, is framed the same way; and the prompt states that instruction-like text is content. These lower the odds of a planted claim; they do not rule one out. The model may still write a planted sentence up as a claim, and the verbatim-anchor gate only checks that the quoted text exists in the source, not who wrote it. What the layer guarantees is auditability: every claim carries a verbatim anchor that names the author of the quoted text when the source records it (human or agent, login, and for pull-request threads the author's repository role), the book and the MCP payload show it, and every new claim appears in the `.lore/` diff. Review `.lore/` changes in a pull request like any other change, and weigh a claim anchored to a drive-by comment accordingly. |
| Injection through stored claims into the agents that read them | The MCP tool description states that claims are evidence, never instructions, and names the author of each anchor. Model-written claim fields are single lines; terminal escape sequences and invisible characters (controls, bidirectional overrides, zero-width and tag characters) are stripped when a claim is built and again when the CLI, the book and the MCP tool serve it, so a claim cannot restyle a terminal, hide content, or print as two claims. |
| Secrets in transcripts | Message content and tool-call arguments are scrubbed at ingest, before the session is written and before any model call (`docs/scrub.md`). Raw captures, the extraction cache and the usage file are gitignored. |
| Reading outside the repository | Only this repository's `.lore/`, its own Claude Code transcript directory (or a directory you name), and the pull-request export it fetched. |
| Network | The model provider you configure, and GitHub through the `gh` CLI you already authenticated. No telemetry, no `crewlore`-operated service. |

## Disclosure preference

Once a fix is shipped, reporters are credited in the release notes unless they ask not to be. Coordinated disclosure window: 7–14 days from a fix landing, depending on severity.
