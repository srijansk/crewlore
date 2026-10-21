<p align="center">
  <img alt="crewlore" src="https://raw.githubusercontent.com/srijansk/crewlore/main/docs/assets/wordmark.png" width="420">
</p>

<p align="center">
  <a href="https://github.com/srijansk/crewlore/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/srijansk/crewlore/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/crewlore/"><img alt="PyPI" src="https://img.shields.io/pypi/v/crewlore.svg"></a>
  <a href="https://pypi.org/project/crewlore/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/crewlore.svg"></a>
  <a href="https://opensource.org/licenses/MIT"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
</p>

> **Your coding agents keep relearning what your team already figured out.**
> `crewlore` reads the sessions your agents already produce, and your repo's pull requests, pulls out the decisions, procedures and gotchas, and writes them into a plain-text knowledge book inside your repo. Every entry quotes the exact line it came from, and records whether the team adopted it or tried it and declined. Runs on your machine with your own model key.

**Sixty seconds on what it does and how it is used:**

https://github.com/user-attachments/assets/b16cb272-da48-4756-89ba-1cc626629e0c

**The same thing in a terminal.** The recording below is the bundled demo, `uv run python scripts/demo.py --step`, which needs no API key: a handful of synthetic sessions compiled into a book, including one claim the team tried and declined.

<p align="center">
  <img src="https://raw.githubusercontent.com/srijansk/crewlore/main/docs/assets/demo.gif" alt="crewlore compiling agent sessions into a team knowledge book, including a claim the team declined" />
</p>

```bash
pipx install crewlore
```

**You need:** Python 3.10 or newer; a model key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) or a local OpenAI-compatible model; the [GitHub CLI](https://cli.github.com/) (`gh auth login`) if you want to compile pull requests; [`uv`](https://docs.astral.sh/uv/) only for the no-key demo below.

## Quickstart

Two ways in, depending on where your team's knowledge currently lives.

**You already use Claude Code.** Point `lore` at the transcripts it writes to disk. By default it reads only this repo's own transcripts, never the other projects on your machine.

```bash
cd my-repo
export ANTHROPIC_API_KEY=...     # or OPENAI_API_KEY, or a local model in .lore/config.yaml
lore init                        # create .lore/ in your repo
lore watch                       # read this repo's transcripts, scrub secrets, compile, prune — on an interval
lore query "billing webhook"     # ask the knowledge layer anything, anytime
```

**You have a repo but no sessions yet.** Compile its pull-request threads instead. Coding agents write much of their reasoning in PR descriptions and reviews — what they tried, why it failed, which constraint they hit — so a repo nobody has run an agent in locally already has a knowledge layer waiting:

```bash
cd my-repo
export ANTHROPIC_API_KEY=...
lore init
lore import-prs owner/repo       # closed PRs by default, agent-authored only; uses your gh login, stores no token
lore query "billing webhook"
```

Either way, commit `.lore/knowledge` and `.lore/claims` and your teammates inherit the book on their next `git pull`. Raw transcripts and raw PR exports stay out of git.

<details>
<summary>Trouble installing?</summary>

If `pipx` fails with `Broken Python installation, platform.mac_ver() returned an empty value`, your default Python is a broken install (sometimes seen with very recent Homebrew Python builds). This is about the interpreter pipx uses, not the package — pin a known-working one:

```bash
pipx install --python python3.13 crewlore
```

To make pipx default to Python 3.13 going forward: `export PIPX_DEFAULT_PYTHON=$(which python3.13)`.

</details>

### Try it without an API key

```bash
git clone https://github.com/srijansk/crewlore.git
cd crewlore && uv run python scripts/demo.py
```

The demo runs the whole loop on bundled synthetic sessions and prints the compiled book, a query against it, and three checks. It is a demonstration of the mechanism on toy data, not a benchmark.

## Let your assistant use it

```bash
lore install                      # the /lore skill, for the assistants found on this machine
lore install --project --always-on   # into this repo, plus a short block in CLAUDE.md / AGENTS.md
lore install --project --hooks       # plus Claude Code hooks: a file's scope claims as it is read and edited
```

The skill tells the assistant to run `lore query` before changing code in a repository that has `.lore/`, to treat `not adopted` claims as declined work, to weigh a claim like a teammate's comment rather than an instruction, and to report back with `lore feedback` afterwards. Claude Code, Cursor and Gemini CLI each get a skill directory, and Codex shares the cross-framework Agent Skills directory (`~/.agents/skills/`, or `.agents/skills/` in the repository with `--project`). `--always-on` adds a short marked block to the assistant's instruction file (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`) or, for Cursor, an always-apply rule in `.cursor/rules/`. With `--hooks`, Claude Code also gets hooks in its settings file: when the assistant reads or edits a file, the claims whose scope covers that file join its context (once per scope per conversation; Claude Code delivers the text with the tool's result, so in the usual read-then-edit flow they are in view before the edit), and each prompt brings up the claims relevant to it, the way `lore query` would with a two-word relevance floor. A claim a reader has corrected arrives the way `lore query` shows it: marked `corrected`, with its note, after every claim nobody has corrected. The hooks run `lore claude-hook` through a POSIX shell (Git Bash on Windows), stay silent whenever there is nothing to add, and exit 0 whatever happens, so a teammate without crewlore, or with an older one, is never blocked. Compaction drops injected context, so a `SessionStart` hook clears the conversation's memory of shown scopes and they come up again. Every file written carries a crewlore marker: install refuses to replace a skill it did not write (`--force` overrides), and `lore uninstall` removes only marked files, the marked block and crewlore's own hook entries, keeping your own text and line endings as they were. Assistants that cannot run commands, such as Claude Desktop, use the MCP server instead (`lore serve`, see [`docs/mcp.md`](https://github.com/srijansk/crewlore/blob/main/docs/mcp.md)).

## What you get

Raw, messy sessions go in. Out comes a **claim**: one reusable thing the team learned, with four parts.

- **Kind** — a `decision`, `procedure`, `gotcha`, or `style` rule.
- **Action** — what a future session should do about it.
- **Anchor** — a verbatim quote from the source, plus where it sits (`<session>#event-<n>` for a transcript, `path:line` when a PR review comment supplies one). The compiler checks every quote against the source and drops any claim whose quote does not match, so the book never contains a citation that cannot be found.
- **Adoption** — `current`, or `not_adopted` when the team tried the thing and declined it.

> **`[gotcha]`** · *services/billing*
>
> Billing webhook handler lacks an idempotency check, causing duplicate charges when Stripe retries webhooks.
>
> **Do** — dedupe on the Stripe idempotency key before processing.
>
> > *anchor* `ses_1#event-3` — "the handler has no idempotency check, so when Stripe retries a webhook the charge is processed again."

**Declined work is recorded as declined.** When a session or pull request shows an approach was tried and not adopted, the claim says so, and its action says what to do instead:

> **`[decision · not adopted]`** · *services/billing*
>
> Storing the Stripe idempotency key in Redis was proposed and rejected in review because the check has to run inside the database transaction.
>
> **Instead** — keep the key in the same transaction as the charge.
>
> > *anchor* `services/billing/webhook.py:88` — "Don't put the key in Redis. Must be inside the transaction."

Why this matters: a memory schema that can only say "X" turns "we tried X and declined it" into a confident assertion of X — fluent, correctly quoted, and wrong about the world. The measurement behind this design is in [the study](#the-study-behind-the-adoption-field) below.

Claims roll up into a knowledge book at `.lore/knowledge/README.md`, grouped by area and committed to your repo alongside your code:

```markdown
# Team knowledge (compiled by crewlore)

## services/billing

- **[gotcha]** Billing webhook handler lacks an idempotency check; dedupe on the Stripe key.
  - *Do:* Dedupe on the Stripe idempotency key before processing.
  - _anchor_ `ses_1#event-3`: "the handler has no idempotency check, so when Stripe retries a webhook the charge is processed again."
- **[decision · not adopted]** Storing the idempotency key in Redis was proposed and rejected in review.
  - *Instead:* Keep the key in the same transaction as the charge.
  - _anchor_ `services/billing/webhook.py:88`: "Don't put the key in Redis. Must be inside the transaction."

## deployment

- **[procedure]** Run migrations before deploy to prevent missing columns.
  - *Do:* Run `make migrate` before every deploy.
```

## A real example

[`docs/examples/pydantic-ai-prs/`](https://github.com/srijansk/crewlore/tree/main/docs/examples/pydantic-ai-prs/) is `lore import-prs pydantic/pydantic-ai --limit 100`, run on 2026-10-09 against the public [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) repo (20k+ ⭐) with the default model, on a machine that had never run an agent in it. Of the last 100 closed pull requests, 24 were written by a coding agent: 18 merged, 6 closed without merging. They compiled into **130 claims**, 15 of them marked **not adopted**, carrying 173 anchors. The fidelity gate dropped none of the model's proposals, and an independent re-check of every anchor against the committed threads found none that fail to resolve. The scrubbed source threads are in the example, so every anchor can be followed to the event it quotes.

One claim from a merged pull request, where an alternative was tried and turned down inside the review:

> **`[decision · not adopted]`** · *pydantic_ai_slim/pydantic_ai/models*
>
> Unified prompt caching (`ModelSettings.cache` / `Caching`) stays opt-in. A default-on variant (`cache` defaulting to True on models with `supports_cache`) was tried and not adopted, because the maintainer deferred default-on caching to v3.
>
> **Instead** — do not default `cache` to True; leave caching off unless the user sets `cache`, uses `Caching()`, or sets a provider-specific cache setting. Revisit default-on only for v3.
>
> > *anchor* `pr_pydantic__pydantic-ai__7560#event-65` — "Per maintainer decision, caching stays off unless `cache` (or the `Caching` capability) or a provider-specific cache setting asks for it; turning it on by default waits for v3."

The directory also shows what the conflict detector does with claims that agree. The 0.4.0 run recorded one conflict: three claims that all say contributor PRs must not touch the repository's `.github/` directory, grouped as a disagreement because the detector then compared only scope, kind and topic. Since 0.4.2 a conflict needs evidence of disagreement (one claim marked not adopted while another is current, or one forbidding what another prescribes), and re-rendering the book from the committed claims records none. The blind spot that remains is listed under limits below.

The older snapshot, [`docs/examples/pydantic-ai/`](https://github.com/srijansk/crewlore/tree/main/docs/examples/pydantic-ai/), is three Claude Code sessions compiled with crewlore 0.1.0 in May 2026. Its README explains what it can and cannot show.

## How it works

```mermaid
flowchart LR
    S["coding-agent<br/>sessions"] --> I["ingest + scrub<br/>(one session format,<br/>secrets redacted)"]
    P["agent-authored<br/>pull requests"] --> I
    I --> C["compile<br/>(claims with verbatim<br/>anchors + adoption)"]
    C --> R["<b>.lore/</b> in your repo<br/>(knowledge book + claims,<br/>plaintext, git-versioned)"]
    R --> SV["serve<br/>(files + MCP query)"]
    SV --> N["next agent session<br/>inherits the knowledge"]

    SV -. "usage + feedback" .-> AL["lifecycle<br/>(decay · reinforce · retire)"]
    AL -. "lifecycle update" .-> R

    classDef engine fill:#4a5d9e,stroke:#1a2c4d,color:#fff,stroke-width:2px
    classDef artifact fill:#2d6a4f,stroke:#1b4332,color:#fff,stroke-width:2px
    class C engine
    class R artifact
```

- **Ingest + scrub.** Two sources feed one session format. *Transcripts:* the Claude Code session files for this repo. *Pull requests:* fetched through the `gh` CLI, one PR thread per session, carrying the description, commits and their messages, review comments with their file and line, approve or request-changes verdicts, CI results, and whether the PR merged or was closed. Both are scrubbed of a curated set of secret patterns (API keys, cloud and GitHub tokens, Slack and Hugging Face tokens, JWTs, connection-string passwords, private-key blocks, `password=…` shapes) before anything is stored or sent to a model. The pattern set and its limits are in [`docs/scrub.md`](https://github.com/srijansk/crewlore/blob/main/docs/scrub.md).
- **Compile.** A model extracts candidate claims from each session. Deterministic stages then do the rest: verify every anchor quote against the source and drop what does not match, derive each anchor's position from where the quote was found, deduplicate by content, record disagreements between sessions instead of overwriting, and score authority by how many independent sessions support a claim. `lore compile` prints how many proposed anchors and claims the gate dropped each pass; that number, not the store's after-the-fact "fidelity", is what tells you how the model behaved.
- **Serve.** A Markdown book in `.lore/knowledge/`, a `lore query` command, a `/lore` skill that `lore install` puts into your coding assistant, and an optional MCP server so any agent can pull the relevant slice at the start of a session.
- **Lifecycle.** Every retrieval is recorded. People and agents can mark claims influential or overridden (`lore feedback`, or the `lore_feedback` MCP tool). Claims nobody has read in 30 days (configurable) are archived, claims that are repeatedly overridden are retired, and influential ones are reinforced, so the book stays small instead of growing into a pile nobody reads. Usage is tracked per machine; the usage file is local so the committed book stays byte-stable. A claim that is wrong or outdated can be **corrected** (`lore feedback <id> --corrected "what is true now"`): the note goes to a tracked file beside the claims (commit it with the book), is shown wherever the claim is served, and the claim stays in the book marked `corrected`, after uncorrected claims in retrieval, the way declined work stays visible rather than deleted.

The intelligence is in compile; ingest and serve are deliberately thin, so supporting another coding agent or another source is a small adapter, not a rewrite. "Compile" here means the repeatable session-to-claims transform: one model call per session, wrapped in deterministic verification, dedup, conflict recording and scoring.

## How it differs

- **vs. memory services with their own store** — their knowledge lives in a database you reach through an API. `crewlore`'s lives in your repo as plaintext: reviewed in pull requests, searched with grep, audited with `git log`.
- **vs. per-editor memory** — tied to one person and one tool. `crewlore`'s book is a team artifact that a new teammate gets on `git pull`.
- **vs. a hand-written `CLAUDE.md` or rules file** — written after the fact and stale within weeks. `crewlore` extracts from what actually happened, keeps the quote as proof, and retires what stops being read.
- **vs. retrieval over document chunks** — returns passages. `crewlore` returns claims with an action and a verdict, so a reader can tell a decision from a rejected alternative. (Retrieval today is deterministic word overlap, not embeddings — simpler and dependency-free; semantic ranking is on the roadmap.)

## Why this exists

Knowledge discovered inside an agent session is private by default and lost by default. It lives in one developer's transcript, so the next engineer — and every future agent run — re-reads the same files, re-learns the same gotcha, and re-makes a decision the team already made. There's no shared layer that both humans and agents read from, so decisions drift and bugs resurface.

`crewlore` makes that knowledge a first-class, versioned artifact in the place your team already trusts: your git repo.

**What it is:** a compiler that turns sessions and pull requests into deduplicated, conflict-aware, provenance-carrying team knowledge, served back to any agent.

**What it isn't:** a hosted service, a vector database, or a personal-memory layer for a single IDE. There's no account, no cloud, and no proprietary store — the compiled knowledge is plaintext you own.

## Your data stays yours

- **Local-first.** Capture, compile, and serve all run on infrastructure you control. Point the compiler at your own model provider or a local OpenAI-compatible model (Ollama, LM Studio, vLLM) via `provider: local` — nothing routes through any `crewlore`-operated service, because there is none.
- **Scoped by default.** `lore compile` and `lore watch` read only this repo's own Claude Code transcripts. Reading any other directory is an explicit choice (`--transcripts DIR` or `capture.transcripts` in the config).
- **Plaintext, in your repo.** The knowledge layer is human-readable Markdown and JSONL under `.lore/`, versioned by git. `git log .lore/` is your audit trail.
- **Secrets are scrubbed before storage.** Scrubbing of message content and tool-call arguments happens at ingest, before the session is written and before any model call. It is a high-precision pattern set, a floor rather than a DLP guarantee (see [`docs/scrub.md`](https://github.com/srijansk/crewlore/blob/main/docs/scrub.md)). Review the `.lore/` diff in a pull request like any other change.
- **Raw captures never reach git.** `.lore/sessions/`, `.lore/sources/` (raw PR exports), the extraction cache and the usage file are gitignored, and the ignore file is written on every store write, not only by `lore init`.
- **No tokens to store.** Pull-request import goes through the `gh` CLI you already authenticated; `crewlore` never sees or stores a GitHub token.
- **Other people's text is treated as untrusted.** Transcripts and pull-request threads go to the model inside a delimiter their content cannot forge, with a rule that instruction-like text is content, not a command. That lowers the odds of a planted claim without ruling one out, so anchors compiled from now on name who wrote the quoted text (for pull requests, the login and the author's repository role; a local transcript knows human or agent only) and every new claim shows in the `.lore/` diff. Claims are served to agents as evidence, not instructions, as single lines with terminal escapes and invisible characters stripped. The threat model is in [`SECURITY.md`](https://github.com/srijansk/crewlore/blob/main/.github/SECURITY.md).

## CLI

| Command | What it does |
|---|---|
| `lore init` | Create the `.lore/` layout in your repo. |
| `lore watch` | Automatically ingest → compile → prune on an interval (`--once` for cron/CI). |
| `lore compile` | Run a single ingest-and-compile pass manually (`--rebuild` to re-extract everything; `--settle MINUTES` to override `capture.settle_minutes` for this run, `--settle 0` to capture a session you have just finished). |
| `lore render` | Rebuild the book and conflict list from the claims already compiled, with no model call: for a fresh clone, or after a merge or pull. Reads the stored claims only (not sessions, not this machine's extraction cache), reports how many claim lines changed (normally none), and leaves a store with no claims untouched. |
| `lore hook install` / `uninstall` / `status` | Git hooks that keep the layer current without a daemon: `lore compile` in the background after each commit and once after a rebase, `lore render` after each merge. Honours `core.hooksPath`; `LORE_SKIP_HOOK` set to any non-empty value skips a run; `status` says why a hook would not run (`--probe` runs it to check it reaches the block) and shows the last hook output. Details under [Git hooks](#git-hooks). |
| `lore import-prs OWNER/REPO` | Compile a GitHub repository's pull-request threads. Scans closed PRs by default (`--state open` or `all`), agent-authored only (`--all-authors` for every PR), most recently updated first (`--limit N`). Needs the `gh` CLI. |
| `lore query "<task>"` | Retrieve the claims most relevant to a task, with their ids (records usage). `--json` for scripts; `--exit-code` to exit 4 when nothing matched. |
| `lore explain <scope>` | Everything known about one scope: current practice first, then declined work, each with its anchors and their authors, plus live conflicts and the scopes nested under it. A name matching several scopes is refused with the candidates listed. Reading a scope marks all its claims served, like a query. Scopes are text the model wrote, so one area can appear under more than one spelling; the book's headings are the list. `--json`, and `--exit-code` for 3 on an ambiguous name and 4 on no match. |
| `lore review [PR]` | Check the files a change touches (the current branch, or a pull request through `gh`) against the claims that cover them; declined work first, and a flag when the change reads like an approach the team declined. `--comment` posts the report on the PR; `--json`; `--exit-code` for 5 when flagged. See [`docs/review.md`](https://github.com/srijansk/crewlore/blob/main/docs/review.md). |
| `lore feedback <id>… --influential` / `--overridden` / `--corrected NOTE` | Tell the layer what became of served claims. Influential and overridden feed the lifecycle; a correction is written to a tracked file beside the claims (commit it with the book) and shown wherever the claim is served. |
| `lore status` | Show claim/conflict counts and how much of the layer is actually being read. |
| `lore install` / `lore uninstall` | Put the `/lore` skill into your coding assistant (`--project` for this repo, `--always-on` to add a block to its instruction file, `--hooks` for Claude Code hooks, `--force` to replace a skill file crewlore did not write), or remove exactly what was written. |
| `lore serve` | Start an MCP server exposing `lore_query`, `lore_explain` and `lore_feedback` to any MCP-speaking agent (Claude Desktop, Cursor, …). Requires the `serve` extra. See [`docs/mcp.md`](https://github.com/srijansk/crewlore/blob/main/docs/mcp.md). |

### Git hooks

`lore hook install` adds a marked, removable block to the repository's `post-commit`, `post-merge` and `post-rewrite` hooks. What to know before relying on it:

- **The compile runs in the background and gives git its output back at once.** A commit returns in milliseconds; the model call happens afterwards and logs to `.lore/cache/hook.log` (truncated once it passes 1 MiB). `lore hook status` prints the last line of that log, so a failed run is visible. The interpreter runs with the current directory off `sys.path` and the repository passed explicitly, so no `lore/` package in your repository, at the top level or planted under the gitignored `.lore/cache/`, can stand in for the installed crewlore.
- **The interpreter is pinned, the key is not.** The block runs the Python that installed it and falls back to `lore` on PATH, so GUI git clients and CI runners work without the launcher on PATH, but `lore compile` still needs `ANTHROPIC_API_KEY` (or your provider's key) in the git client's environment. A GUI client started from the dock does not see your shell's exports; a client without the key logs a credentials error to `hook.log` and the commit itself is unaffected. With the hook installed, a committed `.lore/config.yaml` steers an automatic compile — its `model.base_url` decides where the model call, and your key, go — so review changes to that file like code.
- **One compile per store at a time, and one per rebase.** The compile takes `.lore/cache/compile.lock`; a second one exits with "another compile is running". A rebase (`git rebase`, `git pull --rebase`) fires post-commit once per replayed commit while HEAD is still moving, so the post-commit block steps aside during a rebase and the `post-rewrite` hook compiles once when it has finished, with HEAD settled; `git commit --amend` compiles through post-commit alone. The compile records the commit it fired on (`--expect-head`) and, when it finishes, writes nothing git tracks unless HEAD is still that commit or has moved on from it along the same branch with the committed `claims.jsonl` unchanged: a fixup commit, or a multi-commit `cherry-pick`, landing while the model works is fine (the first commit's compile lands; the others were skipped by the lock), while a branch switch, a `claims.jsonl` committed meanwhile, or an `--amend`, which replaces the commit rather than following it, ends the compile with "HEAD moved" — the extraction stays cached and the layer catches up on your next commit. On a filesystem that cannot lock at all (some network mounts), compiles warn once and run unguarded instead of being skipped forever.
- **Queries during a compile keep their counts.** `lore query` and the MCP server write only the gitignored usage sidecar, never `claims.jsonl`, and a compile re-reads that sidecar just before it persists, so a claim served while the model was working is not archived later as never served.
- **Sessions still in progress wait.** A transcript modified in the last `capture.settle_minutes` (default 10) is left for a later pass, so a session the agent commits mid-way is not captured half-finished (see Configuration). To compile a session you have just finished without waiting, run `lore compile --settle 0`.
- **The post-merge render dirties the tree when the committed book lags the merged claims.** That is what it is for: review and commit `.lore/knowledge/README.md` and `.lore/claims/conflicts.jsonl` like any other change. It renders from the stored claims only, so a render brings nothing back from your cache. That holds for `render` alone: the next `lore compile` replays every cached extraction onto the committed claims, so a claim whose line was deleted in review returns on the next commit, with no model call, from any machine that extracted it. To remove a claim for good, set its `status` to `archived` on its line instead of deleting the line: a compile keeps the committed line's status, the lifecycle leaves non-active claims alone, and archived claims stay out of the book and of `lore query`.
- **Existing hooks are edited carefully, and only the block is ever added.** A hook that `exit`s or `exec`s another program never reaches anything appended after that command, so install reads the hook the way the shell does — commands split at `;`, `&&`, `||` and `|`, comments, heredoc bodies and line continuations skipped, `then`/`else`/`do` and `case` arms seen through, nesting in `if`/`for`/`while`/`case`/`{` tracked — and places the block before the first such command, or before the outermost statement holding it (a function whose body exits included, so the block runs whether or not the function is called), and says where it went; a hook whose end it cannot make sense of (an unterminated heredoc or quote) is refused rather than given a dead block. A hook whose shebang is not a POSIX shell (`sh`, `bash`, `dash`, `ksh`, `zsh`) is refused untouched; a hook with CRLF line endings is refused too, since git cannot run it (`/bin/sh\r` is not an interpreter) — convert it to LF first; a damaged or duplicated block is reported with "fix by hand", never edited; install re-enables the executable bit on a hook that had lost it and says so. `lore hook uninstall` removes exactly the bytes install added; the one thing it cannot give back is a missing final newline, which install adds (and says so) because the block cannot start mid-line. With a committed `core.hooksPath` the hook file is shared, so install notes that the pinned interpreter is this machine's and the PATH fallback serves everyone else; a hook that is a symlink (`.git/hooks/post-commit -> ../../scripts/post-commit`) is edited through the link, install says which file the block went into and gives the same note when that file is tracked, uninstall writes the rest back through the link rather than deleting it, and a link to a file that does not exist is refused.
- **`lore hook status` says why a hook would not run**, not whether the text matches: not executable, CRLF line endings, a shell syntax error, a hook that exits before the block (an `exit` inside a function body does not count: the body runs only where the function is called, and a block standing after the definition is left where it is) or holds it inside a heredoc, a missing pinned interpreter with no `lore` on PATH, an interpreter that cannot import crewlore. What a static read cannot see (`set -e` and a failing command before the block, say) `lore hook status --probe` can: it runs each hook with `LORE_HOOK_PROBE` set, which makes the block touch a file and exit instead of compiling, and reports `broken (block is never reached)` when it was not. The probe runs the hook's other commands too, which is why it is a flag and not the default; without it, a hook with other commands before the block is reported `installed (not probed: …)`.

## Configuration

`.lore/config.yaml`:

```yaml
model:
  provider: anthropic          # anthropic | openai | local
  name: claude-sonnet-5-5      # any current Claude model works; nothing but the prompt is sent
  # temperature: 0             # only sent if set; current Claude models reject sampling parameters
  # base_url: http://localhost:11434/v1   # for provider: local — Ollama, LM Studio, vLLM
capture:
  transcripts: auto            # this repo's own Claude Code transcripts, or a directory path
  settle_minutes: 10           # a transcript modified more recently is still being written; wait for it (`--settle` overrides per run)
compile:
  watch_interval_seconds: 300
  max_unused_days: 30          # claims nobody reads for this long are archived
```

Bring your own key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`); `crewlore` never ships keys anywhere. The default Anthropic provider works out of the box. For OpenAI or a local OpenAI-compatible model, add the SDK: `pipx inject crewlore openai` (or `pip install 'crewlore[openai]'`). With `provider: local` nothing leaves your machine at all. A rejected key, an unknown model name, or a parameter the model refuses stops the run with a clear error instead of reporting a successful compile of nothing.

## The study behind the adoption field

Before the adoption field existed, I measured what the compiler stores when it reads work a team declined, using agent-authored pull requests from the public [AIDev](https://arxiv.org/abs/2602.09185) corpus: 60 PRs closed without merging and 60 merged PRs from the same repositories, each claim judged by a separate model against the PR's actual outcome.

| | Share of a declined PR's claims that state the rejected approach as current practice, averaged over PRs | Declined PRs with at least one such claim |
|---|---|---|
| crewlore's extractor, no change | 44.7% | 47 of 60 |
| A schema-free summarizer on the same threads | 47.6% | 45 of 60 |
| Merged controls | 0% | 0 of 60 |
| Tell the model the PR was closed | 30.1%, −14.6 points | 35 of 60 |
| Add the adoption field plus an instruction to use it | 17.5%, a further −12.7 points | 25 of 60 |

The part that changed the schema: across every version without the field, 0 of the 658 statements extracted from declined PRs mentioned the rejection in their own text (0 of 1,060 counting the merged controls). With the field, 77 of the 196 claims from declined PRs say so in words, and 77 of the 91 the model marked `not_adopted` do. Telling the model was not enough; it needed somewhere to write it down.

The code, pinned data revision and reproduction recipe are in [`studies/palm/`](https://github.com/srijansk/crewlore/tree/main/studies/palm/). The study ran crewlore's extractor and fidelity gate with Gemini models through the OpenAI-compatible provider, with a second judge for agreement (κ = 0.92). This repository is the primary record of the study; a short write-up is being posted as a preprint and will be linked here. If `crewlore` is useful in your research, [`CITATION.cff`](https://github.com/srijansk/crewlore/blob/main/CITATION.cff) has the citation.

## Status, limits and roadmap

> [!NOTE]
> **Alpha.** The on-disk format may change before 1.0; format changes are listed in the [CHANGELOG](https://github.com/srijansk/crewlore/blob/main/CHANGELOG.md). Tested on Python 3.10–3.14, with no network calls in the test suite.

- **Works today:** capture from Claude Code transcripts and GitHub pull-request threads, secret scrubbing, the compile pipeline (verbatim-anchor gate, derived anchor positions, adoption field, conflict recording, authority scoring), the book, `lore query` and `lore explain`, `lore review`, the `/lore` skill and Claude Code hooks (`lore install`), git hooks that compile after each commit (`lore hook install`), the MCP server, feedback and corrections, and unused-claim decay.
- **Limits worth knowing:** retrieval is word overlap, not embeddings; the only transcript source is Claude Code (Cursor, Codex and Copilot sessions come in through the PR path); commits outside a pull request are not read; there is no approve-before-serve gate, so review the `.lore/` diff in a PR; the conflict detector flags a disagreement only when one claim is marked not adopted or forbids what another prescribes, so two sessions that merely pick different answers go unflagged; usage and decay are per machine, not shared across the team.
- **Planned:** a human approve-before-serve gate, transcript adapters for other coding agents, embedding-based retrieval, capture at session end without waiting for a commit, and a shared usage signal across teammates.

## Contributing

Issues, discussions, and PRs welcome. New here? Start a [discussion](https://github.com/srijansk/crewlore/discussions) — adding a capture adapter for another coding agent is the most valuable first contribution and is intentionally small (the Claude Code and GitHub PR adapters are the two worked examples). See [CONTRIBUTING.md](https://github.com/srijansk/crewlore/blob/main/CONTRIBUTING.md) for local setup and the dev loop.

## License

MIT — see [LICENSE](https://github.com/srijansk/crewlore/blob/main/LICENSE).

crewlore is written and maintained by Srijan Saket. The official source is [github.com/srijansk/crewlore](https://github.com/srijansk/crewlore): every [PyPI release](https://pypi.org/project/crewlore/) since 0.2.0 is published from this repository's release workflow and carries a provenance attestation naming this repository.
