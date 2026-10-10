# Team knowledge (compiled by crewlore)

## .github workflows / contribution process

- **[procedure]** A PR that closes an issue not assigned to the PR author is closed automatically by a guard check. Contributors must wait to be assigned to the issue before opening a PR, to avoid duplicate effort. Here the Gemini voice_activity PR (closing #9034) was closed for this reason.
  - *Do:* Before opening a PR for an issue, make sure the issue is assigned to you (comment on the issue to request assignment); do not open a PR for an unassigned issue.
  - _anchor_ `pr_pydantic__pydantic-ai__9989#event-4`: "To avoid duplicate effort, please wait to be assigned before opening a PR."
  - _anchor_ `pr_pydantic__pydantic-ai__9989#event-4`: "This PR has been closed automatically because [issue #9034](https://github.com/pydantic/pydantic-ai/issues/9034) is not assigned to you."

## .github/

- **[gotcha]** Changes under `.github/` are maintainer-only, and a `.github Directory Guard` CI check enforces this. Non-maintainer PRs must leave `.github/` files such as the runner lock untouched and flag the needed refresh for a maintainer.
  - *Do:* Do not edit anything under `.github/` in a contributor PR. Note in the PR description that a maintainer needs to refresh the runner lock.
  - _anchor_ `pr_pydantic__pydantic-ai__9988#event-4`: "`.github/` changes are maintainer-only, so `.github/scripts/pydantic-ai-runner.lock` still mirrors the old `anthropic` cutoff."
- **[gotcha]** Pull requests from non-maintainers that touch any file under `.github/` (including `.github/scripts/pydantic-ai-runner.lock`) fail the automatic '.github Directory Guard' check. Only maintainers may change that directory, because it runs with the repo's credentials. The contributor has to revert the `.github/` changes on the branch and ask a maintainer to carry them in a separate PR.
  - *Do:* Do not edit anything under `.github/` in a contributor PR. If a change there is needed, run `git checkout origin/main -- .github`, push, and ask a maintainer in a comment to make the `.github/` change separately.
  - _anchor_ `pr_pydantic__pydantic-ai__9986#event-9`: "it changes files under `.github/`, which we can only accept from maintainers."
  - _anchor_ `pr_pydantic__pydantic-ai__9986#event-9`: "everything under `.github/` runs with this repository's credentials, so changes to it are a supply-chain boundary"
- **[gotcha]** The .github Directory Guard only accepts changes under .github/ from maintainers. A contributor PR that touches workflows is blocked, so the CI job was dropped from the diff and kept in a separate commit for a maintainer to cherry-pick into their own PR.
  - *Do:* Do not include .github/ workflow changes in a contributor PR. Keep them in a separate commit and tell maintainers to carry them forward in their own PR.
  - _anchor_ `pr_pydantic__pydantic-ai__9899#event-9`: "The .github Directory Guard only accepts .github/ changes from maintainers."

## .github/scripts/pydantic-ai-runner.lock

- **[procedure]** The `anthropic` exclude-newer cutoff is mirrored in `.github/scripts/pydantic-ai-runner.lock`. Any change to the cutoff in `pyproject.toml` needs that lock refreshed in the same change with `uv lock --script .github/scripts/pydantic-ai-runner`.
  - *Do:* When adding, changing, or removing the anthropic cutoff, run `uv lock --script .github/scripts/pydantic-ai-runner` in the same change (a maintainer must do this if the contributor cannot touch `.github/`).
  - _anchor_ `pr_pydantic__pydantic-ai__9988#event-0`: "The same entry is mirrored in `.github/scripts/pydantic-ai-runner.lock`, so refresh that with `uv lock --script .github/scripts/pydantic-ai-runner` in the same change."

## .github/workflows

- **[gotcha]** Adding a label that doesn't exist via the issue labels API creates it (default colour `ededed`, no description), so failure labels need no separate provisioning. This is how the repo's `agentic-workflows` label was made.
  - *Do:* Don't add label-provisioning steps for labels applied through the issue labels API.
  - _anchor_ `.github/workflows/pydantic-ai-pr-review.md:391`: "adding a label that doesn't exist yet through the issue labels API creates it. The repo's `agentic-workflows` label was made that way, with the default colour `ededed` and no description."

## .github/workflows (agentic workflows, gh-aw)

- **[gotcha]** In gh-aw workflows that define their own safe-output jobs, the short `missing-tool: false` form is ignored. Use the explicit form (`create-issue: false` for `missing-tool`, `missing-data` and `report-incomplete`, and `noop.report-as-issue: false`) in every agentic workflow so these reports don't file issues.
  - *Do:* When adding or editing an agentic workflow, set `create-issue: false` explicitly for missing-tool, missing-data and report-incomplete, plus `noop.report-as-issue: false`. Do not use the bare `missing-tool: false` form.
  - _anchor_ `pr_pydantic__pydantic-ai__9541#event-17`: "The bare `false` form was dropped by gh-aw in workflows with custom safe-output
jobs, so the explicit `create-issue: false` form is used everywhere."

## .github/workflows, .github/scripts/agent_spend_report.py

- **[decision]** Agentic workflow failures are no longer reported as `[aw]` issues or public No-Op comments. Failed reviews are signalled by the PR labels `ci-review-failed` / `ui-security-review-failed`, and scheduled failures show up in the `failed` column of the weekly `agent-spend-report` Slack report.
  - *Do:* Do not re-enable failure-report issues or public noop comments. Use the failure labels for PR reviews and the spend report `failed` column for scheduled sweeps.
  - _anchor_ `pr_pydantic__pydantic-ai__9541#event-12`: "`agent-spend-report` already posts every agentic workflow's runs to Slack weekly, so it gains a `failed` column instead."

## .github/workflows/*.lock.yml

- **[procedure]** Changing agentic workflow safe-output secrets requires recompiling lock files with `gh aw compile --approve` (gh-aw's safe-update check), and `agentic_workflow_guard.py check --base-ref origin/main` should pass.
  - *Do:* After editing agentic workflow .md files, recompile with gh-aw and use `--approve` when adding new secret use. Run `agentic_workflow_guard.py check --base-ref origin/main`.
  - _anchor_ `pr_pydantic__pydantic-ai__9541#event-1`: "The new secret use needed `gh aw compile --approve` (gh-aw's safe-update check)"
  - _anchor_ `pr_pydantic__pydantic-ai__9541#event-1`: "`agentic_workflow_guard.py check --base-ref origin/main` passes"

## .github/workflows/pydantic-ai-pr-review.md

- **[gotcha]** The CI Review failure-label job must only change the label when the run's `head_sha` is still the PR's current head, because runs for different SHAs use different concurrency groups and could otherwise overwrite each other's label. The head SHA must be read in its own assignment so a failed `gh api` call fails the step under `bash -e`. UI Security Review doesn't need the guard because it uses one concurrency group per PR with cancel-in-progress.
  - *Do:* When touching the failure-label job, keep the current-head check and read the head SHA in a standalone assignment (not inside a conditional or pipe) so API failures fail the job.
  - _anchor_ `.github/workflows/pydantic-ai-pr-review.md:393`: "Fixed in a0cce0ca7: the job now does nothing unless `head_sha` is still the PR's head."
  - _anchor_ `.github/workflows/pydantic-ai-pr-review.md:388`: "the head SHA is now read in its own assignment, so a failed `gh api` call fails the step (`bash -e`) instead of silently exiting 0."

## .github/workflows/pydantic-ai-pr-review.md, pydantic-ai-ui-security-review.md

- **[gotcha]** In the review workflows, a run counts as successful only if `output_types` includes `submit_pull_request_review` or `noop`. Non-empty `output_types` alone isn't enough, since `missing_tool`, `missing_data` or `report_incomplete` outputs mean no review was posted. A skipped `safe_outputs` job (threat detection failed) also counts as no review and must keep the failure label.
  - *Do:* When changing the failure-label logic, treat success as `submit_pull_request_review` or `noop` in `output_types`, and treat a skipped `safe_outputs` as failure.
  - _anchor_ `.github/workflows/pydantic-ai-pr-review.md:385`: "both review workflows now count a run as successful only if `output_types` includes `submit_pull_request_review` or `noop`, the two ways their prompts end a run."
  - _anchor_ `pr_pydantic__pydantic-ai__9541#event-12`: "`flag_failed_review` now treats a skipped `safe_outputs` job (threat detection failed) as no review, instead of clearing the label."

## .github/workflows/shared/security-findings.md

- **[decision]** Security problems found in released code by agentic workflows must go to the private triage Slack channel via the `report_security_finding` output (imported from `shared/security-findings.md`, using `PYDANTIC_AI_TRIAGE_SLACK_WEBHOOK_URL`). They must never be described in an issue, comment, review or noop. Problems a PR itself introduces remain ordinary review comments. This is enforced only by a prompt instruction.
  - *Do:* Import `shared/security-findings.md` in any agentic workflow that files bugs or reviews security. Never publish vulnerability details for released code in public issues or comments.
  - _anchor_ `pr_pydantic__pydantic-ai__9541#event-1`: "New `shared/security-findings.md`, imported by the seven bug-filing workflows and the UI Security Review, gives the agent a `report_security_finding` output that posts to the triage channel via `PYDANTIC_AI_TRIAGE_SLACK_WEBHOOK_URL`, and tells it never to describe such a finding in an issue, comment, review or noop."

## clai2/builtin_plugins/compaction.py

- **[decision]** clai2 `/compact` commits the compacted result only when it has fewer estimated tokens than the input. Otherwise it keeps the history and reports 'Nothing to compact: compacting would not make the conversation smaller.' This replaced the older 'last 50,000 tokens are always kept' message and the previous behavior of committing any differing result with negative savings clamped to 0.
  - *Do:* Do not commit a compaction result unless its estimated tokens are smaller than the input. Do not clamp negative savings to 0. Report savings as 'about X of TOTAL tokens saved'.
  - _anchor_ `pr_pydantic__pydantic-ai__9923#event-1`: "`/compact` commits the result only when it has fewer estimated tokens. Otherwise it keeps the history and says `Nothing to compact: compacting would not make the conversation smaller.`"
- **[decision]** clai2 `/compact` protects min(protected_tokens, half the history's estimated tokens), not the full protected_tokens (default 50,000). Otherwise a history just over the protected tail gets its cut at message 1, and SummarizingCompaction replaces only the first message while keeping the first user prompt, which makes the history larger. Automatic compaction still keeps the full protected_tokens tail.
  - *Do:* When changing `/compact` or compaction chains, keep the manual `/compact` tail capped at half the history's estimated tokens. Leave the automatic compaction trigger and its full protected_tokens tail unchanged.
  - _anchor_ `pr_pydantic__pydantic-ai__9923#event-1`: "`/compact` protects `min(protected_tokens, half the history's estimated tokens)`, so it always has an older half to summarize or drop."

## docs/

- **[style]** Provider-specific configuration and features belong on `docs/models/{provider}.md` pages. General docs such as the Caching page stay provider-agnostic and link out, with each fact kept in one place. Per-provider paragraphs and duplicate mapping columns were trimmed in review because they drift.
  - *Do:* Put provider mechanics, settings, and numbers on the provider page. Link to them from general pages instead of restating them.
  - _anchor_ `docs/prompt-caching.md:26`: "provider-specific config/features should live on `docs/models/{provider}.md` pages, with general docs staying provider-agnostic and linking out."

## docs/**/*.md

- **[style]** Docs must use reference-style mkdocstrings links for API elements, such as provider settings fields. Span attributes and enum-like string values have no mkdocstrings target, so they stay as code literals and link to the canonical Logfire section instead. Internal links should also target section anchors, not page roots.
  - *Do:* Write `[`name`][pydantic_ai...]` links for API objects and `page.md#section` links for internal references. Leave span attribute names as plain code spans.
  - _anchor_ `docs/prompt-caching.md:45`: "they are span attributes, not API objects, so there is no mkdocstrings target for them"
  - _anchor_ `docs/prompt-caching.md:24`: "API elements in `docs/**/*.md` must use reference-style links."

## docs/, CI docs-assets

- **[gotcha]** Docs must not link forward to pages or anchors that don't exist on `main` yet. CI's `docs-assets` gate runs lychee offline with fragment checking and resolves relative doc links as filesystem paths, so such a link turns CI red. Cross-links to a new page are added in a follow-up once it merges, or in the PR that adds the page.
  - *Do:* Only link to doc pages and fragments that exist on main or in the same PR. Defer cross-links to not-yet-merged pages.
  - _anchor_ `pr_pydantic__pydantic-ai__6537#event-73`: "CI's `docs-assets` gate runs lychee with `--offline --include-fragments`, which resolves relative doc links as filesystem paths."

## docs/, tests/test_examples.py

- **[procedure]** `mkdocs.yml` no longer exists on main. New docs pages are registered in `docs/navigation.yml` and need description front matter. New runnable docs examples need mock responses in `tests/test_examples.py`.
  - *Do:* Add new pages to `docs/navigation.yml` with description front matter. Add mock model responses in `tests/test_examples.py` for any new runnable examples.
  - _anchor_ `pr_pydantic__pydantic-ai__6537#event-78`: "registered in docs/navigation.yml (Core Concepts, next to Messages and Persistence)"
  - _anchor_ `pr_pydantic__pydantic-ai__6537#event-6`: "`tests/test_examples.py` gets mock responses for the new runnable examples."

## docs/capabilities/caching.md, docs/agent.md, building-pydantic-ai-agents skill

- **[decision]** The docs recommend adding `Caching()` to every agent (agents page tip, basic agent examples, and the building-pydantic-ai-agents skill). Caching can't be on by default because cache writes cost more than uncached input. Agents making one-off requests should use `messages=False`.
  - *Do:* Include `Caching()` in basic agent examples and agent docs. Use `Caching(messages=False)` for agents that make one-off requests.
  - _anchor_ `pr_pydantic__pydantic-ai__6537#event-6`: "It tells users to add `Caching()` to their agents. Caching can't be on by default, because cache writes cost more than uncached input"

## docs/capabilities/caching.md, pydantic_ai_slim/pydantic_ai/settings.py

- **[gotcha]** When explicit CachePoints exceed the provider's breakpoint limit, the "drop the oldest message breakpoints" rule only holds where Pydantic AI trims client-side (Anthropic, Bedrock, OpenRouter). OpenAI does no client-side trimming. Its server drops the earliest breakpoints first, starting with the instruction breakpoint, so instructions can silently lose caching.
  - *Do:* Don't describe breakpoint trimming as a provider-general rule. Note the OpenAI exception and link to the OpenAI prompt caching section.
  - _anchor_ `docs/capabilities/caching.md:127`: "The page now says OpenAI's server drops the earliest breakpoints first, starting with the instruction breakpoint"

## docs/examples/

- **[gotcha]** Docs pages under docs/examples/ include example files via `snippet`, so example changes propagate to docs without separate edits.
  - *Do:* Don't separately edit docs/examples/ pages when changing example source files that are snippet-included.
  - _anchor_ `pr_pydantic__pydantic-ai__10038#event-1`: "The docs pages under `docs/examples/` include these files via `snippet`, so they pick the change up without edits."

## docs/harness/

- **[style]** Harness docs must show installs as a single `pip/uv-add` line in its own bash fence, not a hand-written `pip install` or `uv add` command. tests/harness/test_docs_installation.py enforces this.
  - *Do:* Write install instructions in harness docs with the `pip/uv-add` shorthand, one line per bash fence.
  - _anchor_ `pr_pydantic__pydantic-ai__9899#event-18`: "is one `pip/uv-add` line in its own bash fence rather than a hand-written
`pip install` or `uv add` command."

## docs/models/google.md, docs/capabilities/caching.md

- **[gotcha]** Google's model ignores inline `CachePoint` markers and caches via the explicit `google_cached_content` setting. Cache tables and docs must not imply Google behaves like Anthropic, OpenAI, or OpenRouter regarding CachePoint.
  - *Do:* When documenting caching for Google, point to `google_cached_content` and state that CachePoint is unsupported.
  - _anchor_ `docs/prompt-caching.md:13`: "notes that `CachePoint` markers are not supported, and lists `google_cached_content` as the explicit-caching configuration"

## docs/models/openai.md, docs/capabilities/caching.md

- **[gotcha]** For GPT-5.6 and later, `openai_prompt_cache_retention` is deprecated in favor of `openai_prompt_cache_options.ttl`, but it is not ignored. The two fields are independent: retention is a maximum policy and `ttl` is a minimum lifetime. The 1,024-token minimum is stated by OpenAI only for GPT-5.6+, and earlier models' minimum varies with request settings.
  - *Do:* Don't write that GPT-5.6+ ignores `prompt_cache_retention`. Keep the 1,024-token qualifier scoped to GPT-5.6 and later.
  - _anchor_ `docs/models/openai.md:185`: "The guide doesn't say GPT-5.6+ ignores `prompt_cache_retention`."
  - _anchor_ `docs/capabilities/caching.md:96`: "The minimum cacheable prompt length is 1,024 tokens for GPT-5.6 and later"

## docs/models/openai.md, pydantic_ai_slim/pydantic_ai/models/openai.py

- **[gotcha]** OpenAI's prompt caching guide anchors changed. Use `#how-caching-works` for `openai_prompt_cache_key`/`openai_prompt_cache_retention` and `#choose-a-caching-mode` for the GPT-5.6 profile comment and `docs/models/openai.md`. The old `#how-it-works` and `#prompt-cache-breakpoints` anchors no longer exist.
  - *Do:* Link to the current OpenAI prompt caching guide anchors, not the removed `#how-it-works` / `#prompt-cache-breakpoints` ones.
  - _anchor_ `pr_pydantic__pydantic-ai__10007#event-1`: "the old `#how-it-works` and `#prompt-cache-breakpoints` anchors no longer exist"

## examples/pydantic_ai_examples/

- **[decision]** Example apps in examples/pydantic_ai_examples/ model prompt caching: every agent that makes regular model requests gets `capabilities=[Caching()]`. Caching is opt-in until v3, but is what users should reach for by default.
  - *Do:* When adding or editing an example agent that makes regular model requests, add `capabilities=[Caching()]`.
  - _anchor_ `pr_pydantic__pydantic-ai__10038#event-1`: "every agent in `examples/pydantic_ai_examples/` that makes regular model requests gets `capabilities=[Caching()]`"
- **[gotcha]** Agents that only drive a realtime session (realtime_voice.py, realtime_text_to_audio.py, realtime_webrtc/app.py, the voice agent in realtime_handoff.py, the camera assistant in realtime_camera/app.py) are deliberately not given Caching(), since the `cache` model setting doesn't apply to realtime models. Regular agents in those files (handoff triage agent, camera diagram drawer) do get it.
  - *Do:* Do not add Caching() to realtime-session-only agents; add it to regular (non-realtime) agents even in realtime example files.
  - _anchor_ `pr_pydantic__pydantic-ai__10038#event-1`: "since the `cache` model setting doesn't apply to realtime models"

## pull request descriptions

- **[procedure]** A PR that has a permitted compatibility impact must carry a `> [!WARNING]` block in its description. The block gives the **Compatibility impact**, **Why this can ship in a minor release** and **Migration** sections, as well as the label, release note and API-check waiver from the checklist.
  - *Do:* For behavior changes with user-visible compatibility impact, add the WARNING block with impact, why-minor and migration. Make sure the PR has the compatibility label.
  - _anchor_ `pr_pydantic__pydantic-ai__9612#event-18`: "- [x] Any permitted **compatibility impact** has a label, warning, migration, release note, and exact API-check waiver."

## pydantic/pydantic-ai GitHub workflow

- **[gotcha]** A PR opened for a GitHub issue that is not assigned to the PR author is closed automatically by a bot, which asks contributors to wait to be assigned before opening a PR. This PR (#9953 for issue #9487) was closed for that reason, even though the fix was complete, tested and had passed CI.
  - *Do:* Before opening a PR for an issue, check that the issue is assigned to you. If it is not, comment on the issue to request assignment and wait for a maintainer to assign it.
  - _anchor_ `pr_pydantic__pydantic-ai__9953#event-4`: "This PR has been closed automatically because [issue #9487](https://github.com/pydantic/pydantic-ai/issues/9487) is not assigned to you."

## pydantic/pydantic-ai PR workflow

- **[gotcha]** Every PR must reference an existing issue with a closing keyword (e.g. `Fixes #1234`) in its description, or it is closed automatically. If GitHub has not yet resolved the issue reference when the guard runs, the PR is closed anyway. It cannot be reopened once its head branch has been deleted, so a replacement PR is needed.
  - *Do:* Make sure an issue exists and is confirmed by a maintainer. Put the closing keyword in the PR body when the PR is opened, and do not delete the head branch after an automatic closure.
  - _anchor_ `pr_pydantic__pydantic-ai__9899#event-14`: "we ask that every PR references an existing issue with a closing keyword (e.g. `Fixes #1234`) in its description, so this PR has been closed automatically."
  - _anchor_ `pr_pydantic__pydantic-ai__9899#event-13`: "the issue-link guard closed it before GitHub had resolved the issue reference, and it can no longer be reopened because its head branch was deleted"

## pydantic/pydantic-ai pull requests

- **[procedure]** A PR that declares a compatibility impact and ticks the compatibility checkbox must carry the `compatibility impact` label, so the release notes pick it up. The checklist expects a label, warning, migration, release note and exact API-check waiver.
  - *Do:* When opening a PR with a permitted compatibility impact, add the `compatibility impact` label along with the warning, migration note, and release note.
  - _anchor_ `pr_pydantic__pydantic-ai__9701#event-13`: "the PR is missing the `compatibility impact` label that the PR template asks for"

## pydantic/pydantic-ai repo contribution workflow

- **[procedure]** Pull requests to pydantic-ai are closed automatically if they don't reference an existing issue with a closing keyword (e.g. `Fixes #1234`) in the description. The Duplicate & Issue-Link Guard enforces this. In this session the PR was opened before its issue existed, so the guard closed it, even though the body said "Closes #9939". Only documentation-only fixes are exempt.
  - *Do:* Before opening a PR, make sure an issue exists and a maintainer has confirmed it. Then reference it with a closing keyword (Fixes #N) in the PR description. If the PR was auto-closed, update the description to reference the issue and reopen it. Do not open a code PR first and file the issue afterwards.
  - _anchor_ `pr_pydantic__pydantic-ai__9938#event-9`: "we ask that every PR references an existing issue with a closing keyword (e.g. `Fixes #1234`) in its description, so this PR has been closed automatically."
  - _anchor_ `pr_pydantic__pydantic-ai__9938#event-9`: "please open one first (e.g. a bug report with a reproducible example), wait for a maintainer to confirm it, then update this PR's description to reference it and reopen the PR."

## pydantic_ai profiles/anthropic, providers/anthropic, providers/bedrock

- **[decision]** Haiku 5.5 (`claude-haiku-5-5`) gets Sonnet 5's capability profile with two flag changes: `anthropic_binds_thinking_blocks` and `anthropic_disallows_top_effort_when_thinking_disabled`. Unlike the other 5.5 models it keeps `anthropic_supports_forced_tool_choice` on. Bedrock structured output stays off for it, so it is listed in `bedrock_structured_output_unsupported`. These flags follow Anthropic's docs only and were not checked against the live API.
  - *Do:* When adding or changing Haiku 5.5 handling, start from Sonnet 5's profile plus those two flag changes. Keep forced tool_choice enabled and keep Bedrock structured output off until AWS lists support. Probe the live API when a key is available.
  - _anchor_ `pr_pydantic__pydantic-ai__9986#event-3`: "Unlike the other 5.5 models it accepts forced `tool_choice`, so `anthropic_supports_forced_tool_choice` stays on."
  - _anchor_ `pr_pydantic__pydantic-ai__9986#event-3`: "the id joins `bedrock_structured_output_unsupported` (keeping today's behavior) and gets no Bedrock literals"

## pydantic_ai realtime Google/Gemini adapter and profile

- **[decision · not adopted]** Emitting input speech events on Gemini 3.x Live (mapping voice_activity ACTIVITY_START/END to RealtimeInputSpeechStart/EndEvent and setting emits_input_speech_events=True for 3.x) was tried in a PR that was closed and not adopted. The issue states the change alters session turn handling, audio retention and barge-in paths, and should land only after the realtime session redesign (#8801) and be tested against it.
  - *Instead:* Do not flip emits_input_speech_events for Gemini 3.x or map voice_activity messages until the realtime session redesign (#8801) has landed; implement and test against that redesign, and only after being assigned the issue (#9034).
  - _anchor_ `pr_pydantic__pydantic-ai__9989#event-0`: "Speech-start events drive the session's turn handling, audio retention and barge-in paths, so flipping the flag changes behavior there, not just the event stream. This should land after the in-progress realtime session redesign (see #8801), and be tested against it."

## pydantic_ai/mcp.py

- **[decision]** MCPToolset.get_tools() hides MCP Apps (SEP-1865) tools whose `_meta.ui.visibility` list does not contain "model" (e.g. ["app"], [], ["app", "app"]). Tools with ["app", "model"] or no visibility are still offered. The check is membership-based, not an exact-list match, and guarded with isinstance(visibility, list) so a malformed non-list value does not make get_tools() raise. direct_call_tool can still call hidden tools.
  - *Do:* When touching MCPToolset.get_tools(), keep the `isinstance(visibility, list) and 'model' not in visibility` skip; do not reintroduce exact-list matching like ['app'] / [].
  - _anchor_ `pydantic_ai_slim/pydantic_ai/mcp.py:1761`: "The check is now `'model' not in visibility` as you suggested, with an `isinstance(visibility, list)` guard added: without it, a malformed non-list `visibility` (an int, say) would make `get_tools()` raise."
  - _anchor_ `pr_pydantic__pydantic-ai__9862#event-5`: "`MCPToolset.get_tools()` now skips tools whose `visibility` list leaves out `"model"`, such as `["app"]`."
- **[decision]** Hiding app-only MCP tools by default (rather than opt-in) was justified under docs/version-policy.md: bug fixes that only break code relying on undocumented behavior are allowed, and exposing app-only tools to the model was never documented. Making it opt-in is left as a possible follow-up if maintainers prefer.
  - *Do:* Treat hiding as the default behavior; only add an opt-in switch if maintainers explicitly request it.
  - _anchor_ `pr_pydantic__pydantic-ai__9862#event-5`: "This PR hides by default because the server has explicitly said these tools are not for the model, and `docs/version-policy.md` allows bug fixes that only break code relying on undocumented behavior."

## pydantic_ai_slim/pydantic_ai

- **[style]** Repo style: private bookkeeping state that must be shared across instances (e.g. the DBOS per-step run-count registry) is kept as module-level state and helpers, not as a class attribute or `ClassVar`.
  - *Do:* Prefer module-level private state and helpers over class attributes for private shared bookkeeping.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/durable_exec/dbos/_durability.py:32`: "this repo prefers module-level state and helpers over class attributes for this kind of private bookkeeping"

## pydantic_ai_slim/pydantic_ai (CacheConfig.messages docstring), docs/capabilities/caching.md

- **[gotcha]** Docs for the prefix-only cache behaviour must state the CachePoint exception. When a `CachePoint` is present, the request stays `mode='explicit'` and caches only through that point, so the fallback does not apply. The `CacheConfig.messages` docstring overgeneralized this and was flagged for it.
  - *Do:* When documenting the `messages=False` fallback, say it applies only when the mapped request has no breakpoint at all, so an explicit CachePoint keeps explicit mode. Keep the API docstring consistent with docs/capabilities/caching.md.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/settings.py:62`: "only flips to `mode='implicit'` when the mapped request carries *no* breakpoint anywhere."

## pydantic_ai_slim/pydantic_ai/_agent_graph.py

- **[decision · not adopted]** `per_request_input_tokens_limit` is deliberately checked only against the response the agent acts on, not against each rejected fallback attempt. Attempts count only toward the cumulative token and cost limits. A review finding asking to enforce it per failed attempt was declined, and the maintainer confirmed this behavior.
  - *Instead:* Do not apply `per_request_input_tokens_limit` to individual rejected attempts. Keep it as a check on the request the agent acts on.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/_agent_graph.py:2168`: "`per_request_input_tokens_limit` stays a check on the request the agent acts on. Rejected attempts count towards the cumulative token and cost limits."
- **[decision]** When every FallbackModel attempt fails on the non-streaming path, the graph records the attempts' usage and runs `check_tokens` and `check_cost`. A limit that is exceeded is raised as `UsageLimitExceeded` with the `FallbackExceptionGroup` as its `__cause__`. An earlier decision to skip this check, to avoid replacing the group, was explicitly corrected after a maintainer decision and a reproduction.
  - *Do:* When touching the all-models-failed path, keep recording attempt usage and enforcing token and cost limits, chaining the group as `__cause__`.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/_agent_graph.py:1622`: "the maintainer's decision is that attempt usage counts towards the token and cost limits."
  - _anchor_ `pydantic_ai_slim/pydantic_ai/_agent_graph.py:1622`: "a limit it exceeds is raised as `UsageLimitExceeded` with the `FallbackExceptionGroup` as its `__cause__`"
- **[gotcha]** Before issuing a continuation, the usage-limit check (`_check_continuation_usage`) must include the turn's `failed_attempts` usage in the total it checks. This applies to both the non-streaming chain and a resumed seed. Otherwise rejected cost can slip under the cost limit and trigger extra billed continuations. On a streamed turn the attempts carry no usage.
  - *Do:* When changing continuation or limit guards, include `failed_attempts` usage in provisional totals, not only `response.usage`.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/fallback.py:308`: "`_check_continuation_usage` now adds the turn's `failed_attempts` usage to the total it checks, on both the non-streaming chain and a resumed seed."

## pydantic_ai_slim/pydantic_ai/_cache_health.py

- **[gotcha]** The 'caching not enabled' health report (`pydantic_ai.cache.not_enabled` / `CacheNotEnabledWarning`) must not fire for OpenAI models, which cache implicitly, even on GPT-5.6 where `supports_cache` is True. `OpenAIChatModel` and `OpenAIResponsesModel` override `_caching_not_enabled` to return False. OpenRouter's Anthropic routes (which inherit from `OpenAIChatModel`) are still reported, but its Gemini routes are not, since Gemini 2.5+ caches implicitly. A warning that is wrong for one provider teaches users to filter it out.
  - *Do:* Don't equate `supports_cache` with 'caches nothing unless configured'. When touching the not-enabled report, keep implicitly-caching models (OpenAI, OpenRouter Gemini) excluded and keep the docs wording consistent.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/__init__.py:605`: "`OpenAIChatModel` and `OpenAIResponsesModel` override `_caching_not_enabled` to return `False`, since unconfigured isn't uncached on a model that caches implicitly"
  - _anchor_ `pr_pydantic__pydantic-ai__7560#event-95`: "Gemini 2.5+ caches implicitly on OpenRouter."

## pydantic_ai_slim/pydantic_ai/_cache_health.py, capabilities/instrumentation.py, harness warn_on_cache_busts

- **[decision]** Core's cache-health instrumentation and the harness `WarnOnCacheBusts` share one collapse detector in `pydantic_ai._cache_health`. A collapse is a read-back more than 5% and at least 2,000 tokens short of the established prefix. Reasons are snake_case (`ttl_expired`, `compacted`, etc.), the missed amount is `missed_tokens`, and only unexpected/unknown collapses warn. Cache marks are keyed per conversation, provider, model, and provider_url.
  - *Do:* Change collapse thresholds or classification in the shared `_cache_health` module only. Don't add a separate implementation. Use snake_case reasons and `missed_tokens`.
  - _anchor_ `pr_pydantic__pydantic-ai__6537#event-98`: "A collapse is now a read-back more than 5% and at least 2,000 tokens short of the"
  - _anchor_ `pr_pydantic__pydantic-ai__6537#event-97`: "pydantic_ai._cache_health now holds the state machine, the collapse definition and the"

## pydantic_ai_slim/pydantic_ai/_model_request_attempts.py, models/fallback.py

- **[style]** Time model request attempts with a monotonic clock. `ModelRequestAttempt.duration` is measured with `perf_counter_ns()` via `AttemptStart` and `elapsed()` in `_model_request_attempts.py`, and a wall-clock timestamp is kept only for the record's start. The duration ends when the attempt fails, meaning when the exception is caught or the response returns, before any `fallback_on` handler or continuation cancel runs. The span ends at start plus duration.
  - *Do:* Use `AttemptStart`/`elapsed()` for new attempt paths. Do not compute durations from two `time_ns()` readings, and don't include handler time in the duration.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/fallback.py:291`: "A new `AttemptStart` in `_model_request_attempts.py` takes a wall-clock `timestamp` for the record together with a `perf_counter_ns()` reading, and `elapsed()` measures `duration` against the monotonic one."
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/fallback.py:280`: "The duration now ends when the attempt fails, meaning when the exception is caught or the response comes back, before any `fallback_on` handler or continuation cancel runs."

## pydantic_ai_slim/pydantic_ai/capabilities

- **[gotcha]** `WrapperCapability` must forward the private default-id hooks (`_default_run_id` and `_default_conversation_id`). Otherwise a durability capability wrapped in it contributes no defaults and its runs keep random UUID7 ids. A wrapped `TemporalDurability` then reaches `workflow.patched()`, so tests that fake `in_workflow` must also fake `workflow.patched`.
  - *Do:* When adding a new hook to the capability base, forward it in `WrapperCapability` and add a test with a wrapped durability capability.
  - _anchor_ `pr_pydantic__pydantic-ai__9701#event-9`: "A durability capability wrapped in a `WrapperCapability` otherwise
contributed no defaults, so its runs kept random ids."

## pydantic_ai_slim/pydantic_ai/durable_exec

- **[gotcha]** Durable execution wrappers (Temporal, DBOS, Prefect) run `request()` inside an activity, step or task, which is a different context. A ContextVar-backed WebSocket connection opened outside is therefore not visible there, and requests silently fall back to HTTP. `connect()` on a durable-wrapped model should raise a `UserError` instead of falling back silently.
  - *Do:* When adding connection or session state held in a ContextVar, make the durable wrappers reject it explicitly rather than letting requests fall back to another transport.
  - _anchor_ `pr_pydantic__pydantic-ai__4843#event-30`: "the durable wrappers run `request()` inside an activity/step/task — a different context — so the connection isn't visible there and requests silently fall back to HTTP."
- **[gotcha]** The deprecated `TemporalAgent`/`DBOSAgent`/`PrefectAgent` wrappers do not go through the durability capability and still mint UUID7 default ids. Third-party engines (Restate, Kitaru, Airflow, Lambda, Absurd) cannot supply replay-stable defaults because the hooks are private. A stable `(ctx.run_id, ctx.run_step)` is now usable as an idempotency key on the three built-in engines.
  - *Do:* Don't expect replay-stable default ids from the deprecated wrappers or third-party engines. Supporting them would require a public backend builder hook.
  - _anchor_ `pr_pydantic__pydantic-ai__9701#event-4`: "The deprecated `TemporalAgent`/`DBOSAgent`/`PrefectAgent` wrappers don't go through the durability capability. They still mint UUID7s"
- **[decision]** Under the built-in durable engines (TemporalDurability, DBOSDurability, PrefectDurability), every agent run without explicit ids gets a replay-stable default `run_id` from the engine's `_default_run_id` hook, not only runs with a workspace. The default `conversation_id` is a UUID5 derived from that run id. Inside a workflow or flow the `run_id` is an engine-derived string, not a UUID7. Engines built on the public `BaseDurabilityCapability` still get UUID7 defaults.
  - *Do:* When touching default id resolution for durable execution, keep the engine hooks `_default_run_id` and `_default_conversation_id` as the source of the defaults. Don't assume the defaults are UUID7 inside a durable workflow. Tell callers to pass `run_id=` / `conversation_id=` explicitly if they need a specific format.
  - _anchor_ `pr_pydantic__pydantic-ai__9701#event-3`: "Inside a durable workflow or flow, the default `run_id` is no longer a UUID7 but an engine-derived string"
  - _anchor_ `pr_pydantic__pydantic-ai__9701#event-4`: "Each engine already had a replay-stable recipe, so the bug was only the `_has_get_workspace` gate in `CombinedCapability`."

## pydantic_ai_slim/pydantic_ai/durable_exec/_base.py

- **[decision · not adopted]** Deriving the default `conversation_id` inside `BaseDurabilityCapability` for all engines was tried and not adopted. Third-party engines built on the public base cannot supply a replay-stable `run_id`, so the derivation only changed the id format (UUID7 to UUID5 of a random id) without making it stable. The derivation is now a module-level `conversation_id_from_run_id()` that only the Temporal, DBOS and Prefect durability capabilities call from their own `_default_conversation_id`. The base returns `None`.
  - *Instead:* Do not put the UUID5 conversation_id derivation on `BaseDurabilityCapability`. Have only engines that supply a replay-stable run_id call `conversation_id_from_run_id()` from their own `_default_conversation_id` override.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/durable_exec/_base.py:883`: "the derivation is now a module-level `conversation_id_from_run_id()`, and only `TemporalDurability`, `DBOSDurability` and `PrefectDurability` call it, from their own `_default_conversation_id`. The base returns `None`"

## pydantic_ai_slim/pydantic_ai/durable_exec/dbos/_durability.py

- **[gotcha]** On DBOS, defaulting `run_id` to `workflow_id:function_id+1` collides when two agent runs in the same workflow start concurrently (e.g. `asyncio.gather`), because both resolve ids before either starts a step. DBOSDurability counts runs per step position per workflow execution. The first run at a position keeps the old format and later ones get a `:<n>` suffix, so in-flight workflows recover with the same ids.
  - *Do:* Keep the per-step-position run counter when changing DBOS default run_id logic. Keep the first run's id format unchanged.
  - _anchor_ `pr_pydantic__pydantic-ai__9701#event-4`: "`workflow_id:function_id+1` collides when two agent runs in one workflow are started with `asyncio.gather`"

## pydantic_ai_slim/pydantic_ai/durable_exec/temporal

- **[gotcha]** Temporal replay matches commands by command type and activity id/type, not by activity input payloads. Activity inputs such as `run_id` or `conversation_id` that differ on replay do not cause non-determinism errors. A workflow can replay with different `run_id`s in its activity inputs and still complete.
  - *Do:* Don't treat changed activity input payloads (like ids) as a replay non-determinism risk. Focus on command sequence and RNG draws.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_durability.py:514`: "Temporal matches replayed commands by command type and activity id/type, not by activity input payloads."

## pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_durability.py

- **[gotcha]** On Temporal, any new `workflow.uuid4()` draw in workflow code shifts the workflow's random sequence for histories recorded before the change. The stable default run-id draw is therefore gated behind `workflow.patched('pydantic_ai:stable_default_run_id')`. The unpatched path applies only when the root capability supplies workspaces and `TemporalDurability` is a direct child of the root, which is exactly where the old code drew. Replay tests should check the absent patch marker in the history and that the next `workflow.uuid4()` draw matches the recorded one.
  - *Do:* When adding any workflow RNG draw (`workflow.uuid4()`/`random()`) to Temporal agent code, put it behind `workflow.patched(...)` and add a replay test with a history recorded without the marker.
  - _anchor_ `pr_pydantic__pydantic-ai__9701#event-4`: "Adding that draw to histories that never made it would shift every later `workflow.random()`/`uuid4()` value in user code on replay."
  - _anchor_ `pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_durability.py:503`: "The unpatched path now requires the root to supply workspaces *and* this capability to be a direct child of the root"

## pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_model.py

- **[gotcha]** In Temporal wrappers, methods that delegate to the wrapped model must resolve the model selected via `using_model()` through `self._current_model()`, not `self.wrapped`. Otherwise guards and delegation apply to the default model instead of the selected one. Raw model-id strings should raise a registration-directed `UserError` rather than being inferred in workflow code.
  - *Do:* Use `self._current_model()` in new TemporalModel delegations. Handle the string case with a clear error asking the user to register the model via `models=`.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_model.py:160`: "`TemporalModel.connect()` now resolves `_current_model()` and applies the guard/delegation to the selected registered model."

## pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_run_context.py

- **[gotcha]** Review feedback on the tracer-restoring approach: `_restore_tracer` resolves only `agent.root_capability`, which does not include per-run `Instrumentation` passed via `agent.run(..., capabilities=[...])`. Activity-side spans for such runs therefore go to the agent-level tracer or the no-op tracer. The reviewer suggested passing the effective run instrumentation into activity context restoration, or rejecting that mode for activity-side tracing.
  - *Do:* When restoring the tracer in Temporal activities, account for per-run `Instrumentation` supplied via `agent.run(capabilities=...)`. Either pass the effective run instrumentation through, or explicitly document or reject that case.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/durable_exec/temporal/_run_context.py:314`: "`_restore_tracer` resolves only `agent.root_capability`, which does not include the per-run override; pass the effective run instrumentation into activity context restoration or reject this mode for activity-side tracing."
- **[decision]** Inside Temporal activities, `TemporalRunContext` guards fields that were not serialized across the activity boundary and raises a UserError when they are read. `tracer` was one of them, so any tool body calling `ctx.tracer.start_as_current_span` (the `Memory` tools, and potentially harness code in guardrails, spend and compaction) failed. The attempted fix stopped guarding `tracer`. Instead, `deserialize_run_context` re-attaches a tracer resolved from the worker agent: an `Instrumentation` capability, else the agent's `instrument=` settings, else a no-op tracer. That PR was closed for lack of issue assignment, not because of a code rejection.
  - *Do:* To fix tools reading `ctx.tracer` inside Temporal activities, restore the tracer from the worker agent in `deserialize_run_context` (Instrumentation capability, then `instrument=`, then no-op). Do not add per-harness fallback tracers. Add a Temporal integration test under tests/harness/memory/.
  - _anchor_ `pr_pydantic__pydantic-ai__9953#event-3`: "`deserialize_run_context` resolves the tracer from the worker's agent the way the workflow resolved the run's instrumentation: an `Instrumentation` capability on the agent, else its `instrument=` settings, else the no-op tracer."

## pydantic_ai_slim/pydantic_ai/exceptions.py

- **[gotcha]** `FallbackExceptionGroup` does not carry `attempts` over to groups derived by `except*`, `split()` or `subgroup()`. Derived groups get the class-default empty `attempts`, because attempts don't split along the exceptions (rejected responses are grouped into a single `ResponseRejected`). Code that needs the records must catch `FallbackExceptionGroup` itself.
  - *Do:* Catch `FallbackExceptionGroup` directly to read `.attempts`. Don't add a `derive()` override that copies the attempts.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/exceptions.py:607`: "Code that needs the records should catch `FallbackExceptionGroup` itself, where `attempts` is complete."

## pydantic_ai_slim/pydantic_ai/messages.py

- **[style]** Newly added public serializable record classes such as `ModelRequestAttempt` should be `frozen=True`, matching `WorkspaceRef`. Freezing can be relaxed later without a break, but freezing after users may mutate instances would break them.
  - *Do:* Make new leaf record dataclasses frozen unless mutation is needed.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/messages.py:2812`: "Freezing it, since that's the direction that can't be taken later without a break, while unfreezing could be."

## pydantic_ai_slim/pydantic_ai/models

- **[decision · not adopted]** Warnings for a `CachePoint` dropped by providers that ignore it (Cohere, Groq, Mistral, HF, xAI, etc.) were tried and removed, so dropped markers are skipped silently. Harness capabilities such as `Planning` and `SystemReminders` insert a `CachePoint` on every request, so the warning would fire for markers users never wrote and would break test suites that treat warnings as errors.
  - *Instead:* Do not add warnings when an unsupported provider drops a `CachePoint`. Keep dropping it silently.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/_prompt_cache.py:79`: "The harness `Planning` and `SystemReminders` capabilities insert a `CachePoint` on every request, so the warning would fire for markers users never wrote and would break test suites that treat warnings as errors."
- **[decision · not adopted]** Unified prompt caching (`ModelSettings.cache` / `Caching`) stays opt-in. A default-on variant (`cache` defaulting to True on models with `supports_cache`) was tried and not adopted, because the maintainer deferred default-on caching to v3. Caching is off unless `cache`, `Caching()`, or a provider-specific cache setting asks for it.
  - *Instead:* Do not default `cache` to True. Leave caching off unless the user sets `cache`, uses `Caching()`, or sets a provider-specific cache setting. Revisit default-on only for v3.
  - _anchor_ `pr_pydantic__pydantic-ai__7560#event-65`: "Per maintainer decision, caching stays off unless `cache` (or the `Caching` capability) or a provider-specific cache setting asks for it; turning it on by default waits for v3."
- **[decision]** Provider-specific cache settings (`anthropic_cache*`, `bedrock_cache_*`, `openrouter_cache_*`, `google_cached_content`, etc.) always take precedence over the unified `cache` setting, including when set to `False`. When one wins, the resolved `ModelRequestParameters.cache` is cleared so telemetry and durable-exec consumers don't see a retention that never reached the wire. This presence check lives in each provider's `prepare_request`.
  - *Do:* In each provider's `prepare_request`, clear `params.cache` to None when an explicit provider-specific cache setting is present. Do not let the unified value override it.
  - _anchor_ `pr_pydantic__pydantic-ai__7560#event-16`: "Clear `ModelRequestParameters.cache` when explicit provider cache settings
  take precedence"
  - _anchor_ `pr_pydantic__pydantic-ai__7560#event-6`: "Provider-specific cache settings take precedence over the unified one whenever any is present, including `False`."

## pydantic_ai_slim/pydantic_ai/models/__init__.py

- **[gotcha]** `CompletedStreamedResponse.get()` must prepend the wrapping stream's `failed_attempts`. When the fallback target streams a response it already has, as durable models replay one, `get()` otherwise returns its original response and loses the attempts FallbackModel set on the stream.
  - *Do:* When changing `CompletedStreamedResponse` or fallback streaming, keep propagating `failed_attempts` through `get()`.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/__init__.py:1245`: "`get()` now prepends the stream's `failed_attempts`."

## pydantic_ai_slim/pydantic_ai/models/anthropic.py

- **[gotcha]** Anthropic rejects automatic caching (top-level `cache_control`) with a 400 when the last block carries its own explicit `cache_control` with a different TTL. Don't send the automatic `cache_control` when the last block already has its own breakpoint.
  - *Do:* Before adding Anthropic automatic `cache_control` (from `anthropic_cache` or `cache`), check whether the last block has its own breakpoint, and skip the automatic one if so. Handle empty message lists.
  - _anchor_ `pr_pydantic__pydantic-ai__7560#event-94`: "Anthropic rejects automatic caching when the last block's explicit `cache_control` has a different TTL"
- **[gotcha]** The extra previous-tail breakpoint for the 20-block lookback (#9404) is added only when `AnthropicModel` uses `AsyncAnthropicBedrock`. First-party Anthropic and Foundry collapse tool_use/tool_result runs and aren't affected. On those clients the extra breakpoint would take the fourth slot and drop users' explicit `CachePoint`s. Direct Vertex is untested, so leave it out unless a live probe shows the miss. `previous_tail_needing_breakpoint` also returns None when history ends with an assistant turn, to avoid a duplicate `cachePoint`.
  - *Do:* Gate the previous-tail breakpoint on `isinstance(self.client, AsyncAnthropicBedrock)`. Do not add it for the first-party API, Foundry, or Vertex without live evidence.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/anthropic.py:2943`: "#9404 confirmed those aren't affected: the Claude API collapses runs of `tool_use`/`tool_result` blocks"
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/anthropic.py:2943`: "the previous-tail breakpoint is now only added on `AsyncAnthropicBedrock`"

## pydantic_ai_slim/pydantic_ai/models/bedrock.py

- **[gotcha]** Bedrock Claude 1-hour cache TTL is supported only on a per-model list (Claude Sonnet 4.5 and later). `BedrockConverseModel` and `AnthropicModel` on `AsyncAnthropicBedrock` both use this list, so `'1h'` snaps to `'5m'` on Claude 3.7 and 3.5 Sonnet v2. Vertex keeps `('5m', '1h')`.
  - *Do:* When adding Bedrock Claude models, update the per-model 1h-TTL list (`_ONE_HOUR_CACHE_CLAUDE_MODEL_PREFIXES`) per the AWS prompt-caching docs. Don't advertise `'1h'` for all Bedrock models.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/providers/anthropic.py:128`: "Bedrock Claude models now use a per-model list of the models whose Bedrock entry lists the 1-hour TTL"

## pydantic_ai_slim/pydantic_ai/models/decision.py

- **[decision]** `decision_requires_instructions` on a DecisionModelProfile can set the behavior per model name, and the profile takes precedence over the `requires_instructions` class attribute, in the same way as the choice and score limits.
  - *Do:* When adding per-model toggles for decision backends, expose them as DecisionModelProfile fields that override the class attribute.
  - _anchor_ `pr_pydantic__pydantic-ai__9848#event-2`: "the profile takes precedence over the class attribute"
- **[gotcha]** A plain `bool` or bounded `float` output with nothing to ask still raises the existing `UserError` (_ASKS_NOTHING) before any request is sent. The generic-question fallback only applies to choice, score, and yes/no questions with described true/false criteria. Per-option yes/no questions for list/dict fields always carry `option`. A bare `Literal` sends `null` criteria per option, which strands-decider 0.1.0 rejects server-side, and this is out of scope.
  - *Do:* When testing System One with strands-decider 0.1.0, use a described Enum rather than a bare Literal. Don't expect the generic-instructions fallback to cover bool or bounded float outputs with no question.
  - _anchor_ `pr_pydantic__pydantic-ai__9848#event-2`: "A plain `bool` or bounded `float` with nothing to ask still raises the existing `UserError`."
  - _anchor_ `pr_pydantic__pydantic-ai__9848#event-2`: "a bare `Literal` sends `null` criteria per option, which strands-decider 0.1.0 also rejects."

## pydantic_ai_slim/pydantic_ai/models/decision.py, system_one.py

- **[decision]** DecisionModel has a `requires_instructions` class attribute, next to `max_choice_options` and `max_score_levels`. When it is True and a question has nothing to ask (no field, field description, docstring or agent instructions), the question is sent with the generic text 'Which of these applies?' instead of omitting `instructions`. SystemOneModel sets it to True because the System One schema requires `instructions` on every question type.
  - *Do:* When a decision backend refuses questions without `instructions`, set `requires_instructions = True` on the model class (or `decision_requires_instructions` in the DecisionModelProfile) rather than sending `instructions=None`. Also name it in the DecisionModel backend docstring and in docs/models/decision.md.
  - _anchor_ `pr_pydantic__pydantic-ai__9848#event-2`: "This adds a `DecisionModel.requires_instructions` class attribute, next to `max_choice_options` and `max_score_levels`."
  - _anchor_ `pr_pydantic__pydantic-ai__9848#event-2`: "the question is sent with `'Which of these applies?'`"

## pydantic_ai_slim/pydantic_ai/models/fallback.py

- **[decision · not adopted]** On a fallback attempt span, `exception.escaped=True` is kept on purpose. The exception is recorded on the attempt span and ends that span, so it escapes that span. `execute_tool` spans record failures the same way. The recovery happens one level up on `chat`. Automated review suggestions to pass `escaped=False` were declined.
  - *Instead:* Leave `escaped=True` when recording exceptions on fallback attempt spans. Don't change it to `False` in response to review bots.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/fallback.py:568`: "Keeping `escaped=True` on purpose. The exception is recorded on the `fallback attempt` span, not on `chat`, and it is what ends that span, so from that span's point of view the exception escapes it."
- **[decision · not adopted]** Do not record failed FallbackModel attempts as `exception` events on the `chat` span. Logfire sets `is_exception = true` on any record with an event named `exception`, regardless of `exception.escaped`. A successful fallback would then be flagged as an exception, which feeds exception views, alerts and the agent optimizer's failure outcome. This approach was tried in the first version of the PR and replaced.
  - *Instead:* Give each failed attempt its own child span of `chat` that ends in ERROR, and keep the `chat` span free of exception events. Never put an event named `exception` on a span whose operation succeeded.
  - _anchor_ `pr_pydantic__pydantic-ai__8745#event-5`: "A tool call that fails and goes back to the model as a retry gets its own `execute_tool` span. That span has an exception event and ERROR status, and the agent run above it still succeeds."
  - _anchor_ `pr_pydantic__pydantic-ai__8745#event-4`: "Logfire sets `is_exception = true` on any record with an event named `exception`, whatever `exception.escaped` says."
- **[gotcha]** When recording telemetry for a failed attempt, always end the started attempt span in a `finally`. Describing the failure can itself raise, for example an exception whose `__str__` raises while `set_error_status` formats it with content capture on. An outer `suppress(Exception)` would otherwise skip `span.end()` and the span would never be exported.
  - *Do:* Wrap recording logic after `start_span` in try/finally and call `attempt_span.end()` in the finally block.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/fallback.py:566`: "An exception whose `__str__` raises makes `set_error_status` fail when content capture is on, and the attempt span was then never ended or exported."

## pydantic_ai_slim/pydantic_ai/models/fallback.py, _agent_graph.py

- **[gotcha]** On the streaming path, `FallbackModel.request_stream()` only falls back on errors raised while the stream opens, and `fallback_on` response handlers do not apply to streams. Its `FallbackExceptionGroup` therefore holds only `outcome='error'` attempts with `usage=None`, so there is no billed usage to record or check in the pre-stream failure path of `run_stream`. Review findings asking for usage recording and limit checks there were declined.
  - *Do:* Don't add usage recording or limit enforcement for rejected attempts on the streaming pre-stream failure path. Only the non-streaming path has rejected responses with usage.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/_agent_graph.py:2114`: "`FallbackModel.request_stream()` only falls back on errors raised while a stream opens. It never judges a response, because `fallback_on` response handlers don't apply to streams."

## pydantic_ai_slim/pydantic_ai/models/fallback.py, pydantic_ai_slim/pydantic_ai/_model_request_attempts.py

- **[decision]** Failed FallbackModel attempts become child spans of `chat`, named `model request attempt {model}` (attribute `pydantic_ai.model_request.attempt`), originally `fallback attempt {model}`. They are created after the attempt has failed and back-dated to its start. Error attempts get the exception recorded, content-gated, and ERROR status. Rejected responses get ERROR status, the finish reason and usage/cost attributes, but no exception event. The name is deliberately not `chat`, so Logfire's model-call views don't count a failed attempt as a model call. The `chat` span ends OK with the answering model's attributes.
  - *Do:* When adding or changing fallback telemetry, emit attempt spans via the shared helper in `_model_request_attempts.py`. Do not name them `chat`, and do not add events to the `chat` span.
  - _anchor_ `pr_pydantic__pydantic-ai__8745#event-5`: "The child span is deliberately not named `chat`, so Logfire's model-call views don't count a failed attempt as a model call."
  - _anchor_ `pr_pydantic__pydantic-ai__8745#event-1`: "They are renamed `model request attempt {model}` (attribute `pydantic_ai.model_request.attempt`), because that loop also retries the same model."

## pydantic_ai_slim/pydantic_ai/models/fallback.py, usage.py, _agent_graph.py

- **[decision]** For FallbackModel, rejected responses' tokens and cost count in `RunUsage` and towards token and cost limits, but not in the answering response's own `usage`. Their costs are no longer folded into the winner's `usage.cost`. They are not added to message history and do not increase `RunUsage.requests` or count towards `request_limit`. Per-attempt records live in `ModelResponse.failed_attempts` as frozen `ModelRequestAttempt`s, and in `FallbackExceptionGroup.attempts` when every model fails.
  - *Do:* Read `result.usage` for a fallback chain's total. For per-attempt detail use `response.failed_attempts[i].usage`. Do not fold rejected usage into the winner's `usage`, and do not count attempts as requests.
  - _anchor_ `pr_pydantic__pydantic-ai__8745#event-1`: "The answering response's `usage.cost` no longer includes the cost of rejected responses. `result.usage.cost` still does."
  - _anchor_ `pr_pydantic__pydantic-ai__8745#event-1`: "attempts never increase `RunUsage.requests`."

## pydantic_ai_slim/pydantic_ai/models/openai.py

- **[decision · not adopted]** The OpenAI Responses WebSocket PR was closed without merging because the fork was deleted, and the author said it needs a fresh design after the realtime infrastructure landed. The `OpenAIResponsesModel.connect()` ContextVar-session design was not adopted as-is. Its provider-specific `connect()` and private durable-wrapper marker never received final maintainer merge.
  - *Instead:* Before adding OpenAI Responses WebSocket support, design it against the existing realtime infrastructure and the session-lifecycle discussion in #9945. Do not re-apply the closed #4843 `connect()` implementation unchanged.
  - _anchor_ `pr_pydantic__pydantic-ai__4843#event-150`: "this PR needs a fresh design after the addition of the whole realtime infra, let me take a look"
- **[gotcha]** The implicit-cache fallback must fire only for the exact options object produced by `_translate_openai_cache`, checked by identity (`is _PREFIX_ONLY_CACHE_OPTIONS`, with no `.copy()`), not by value equality. A value-equality check overwrote caller-supplied `openai_prompt_cache_options={'mode': 'explicit', 'ttl': '30m'}` with implicit mode, breaking the rule that explicit provider settings take precedence over the unified `cache` setting. It also created a cache-sharing exposure.
  - *Do:* Use identity comparison against the shared `_PREFIX_ONLY_CACHE_OPTIONS` object to detect unified-cache-produced options. Never compare values, and never rewrite caller-supplied `openai_prompt_cache_options`.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/openai.py:1189`: "Comparing values can't tell whether the unified setting produced these options or the user passed `openai_prompt_cache_options={'mode': 'explicit', 'ttl': '30m'}` themselves."
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/openai.py:1189`: "the fallback now checks for the exact options object `_translate_openai_cache` produced (`is _PREFIX_ONLY_CACHE_OPTIONS`) rather than equal values"
- **[decision]** With the unified `cache={'messages': False}` setting on GPT-5.6+ OpenAI models, `mode='explicit'` relies on the instruction breakpoint, which `openai_cache_instructions` skips in several cases (server-side state continuation, compaction, merged or 'user' system prompts, dynamic system prompts, no static instructions). When the mapped request then carries no `prompt_cache_breakpoint` at all, the request falls back to `mode='implicit'` so it still caches. The fallback inspects the mapped request rather than duplicating the instruction-breakpoint gates, so the two cannot drift.
  - *Do:* When changing OpenAI unified cache translation, keep the post-mapping check for any breakpoint (instruction or CachePoint) rather than re-implementing the instruction-breakpoint gating conditions.
  - _anchor_ `pr_pydantic__pydantic-ai__10007#event-1`: "Checking the mapped request rather than duplicating the instruction-breakpoint gates means the two can't drift."
- **[gotcha]** When building OpenAI Responses requests for any transport (HTTP or WebSocket), keep parity with the HTTP path. `parallel_tool_calls` must only be sent when tools are present, and `conversation` and `context_management` must be forwarded. Do not send `stream` over WebSocket. Share param-building code via `_ResponsesRequestParams` rather than duplicating it.
  - *Do:* Reuse the shared Responses request-param builder for new transports, and guard `parallel_tool_calls` with `if tools else OMIT`.
  - _anchor_ `pr_pydantic__pydantic-ai__4843#event-22`: "Guard parallel_tool_calls with `if tools` in _ws_create"
  - _anchor_ `pr_pydantic__pydantic-ai__4843#event-29`: "`_ws_create` forwards `conversation` and `context_management` so"
- **[gotcha]** The OpenAI SDK's WebSocket handshake sends only `client.auth_headers` plus the explicit mapping. Unlike HTTP requests it omits `OpenAI-Project`, `OpenAI-Organization` and custom client default headers. A WebSocket handshake should start from the client's default headers and then apply explicit `extra_headers` as overrides.
  - *Do:* When opening an OpenAI WebSocket connection, merge the `AsyncOpenAI` client's default headers into the handshake and let user-supplied extra headers override them.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/openai.py:2116`: "OpenAI SDK 2.45.0's WebSocket handshake combines `client.auth_headers` with only this explicit mapping"
- **[gotcha]** `_has_prompt_cache_breakpoint` must also scan `function_call_output` items' `output` lists, because `_move_leading_cache_breakpoints` can move a leading CachePoint onto a preceding tool result. Without that arm, a request with only that breakpoint would wrongly flip to implicit mode. A dedicated test pins this: `test_openai_responses_unified_cache_stable_prefix_only_keeps_tool_result_breakpoint`.
  - *Do:* When touching `_has_prompt_cache_breakpoint`, keep the `function_call_output` → `output` scan and its test. Line coverage alone will not catch a regression in that arm.
  - _anchor_ `tests/models/test_openai_prompt_cache.py:2360`: "`_move_leading_cache_breakpoints` moves that breakpoint onto the preceding `function_call_output`'s `output` list, and that arm is then the only thing keeping the request at `mode='explicit'`"
  - _anchor_ `tests/models/test_openai_prompt_cache.py:2360`: "`test_openai_responses_unified_cache_stable_prefix_only_keeps_tool_result_breakpoint`"
- **[gotcha]** For resumed streams (e.g. `starting_after`), deltas and `function_call_arguments.done` snapshots for an item whose `output_item.added` was never seen are skipped, because there is no ToolCallPart with a tool name. `output_item.done` then creates the part from the full item. Without this guard, reconciliation asserted that a part existed and raised AssertionError.
  - *Do:* Keep the guard that skips deltas and done snapshots for items without a prior `output_item.added`, and let `output_item.done` create the part.
  - _anchor_ `pr_pydantic__pydantic-ai__10039#event-7`: "A stream resumed after output_item.added has no complete ToolCallPart, so
skip its deltas and done snapshot and let output_item.done create the part."
- **[decision]** In the Responses stream parser, the completed snapshot from `function_call_arguments.done` (with `output_item.done` as a fallback) is authoritative over delta-built args. If the args received so far are equal, nothing is emitted. If the snapshot extends them, only the missing suffix is emitted as a ToolCallPartDelta. If they disagree, the part's args are replaced with the snapshot. An empty snapshot is ignored. Once an item is finalized, a repeated done or a late delta for it is ignored. The "apply done only when no delta arrived" approach (litellm's) was considered and not adopted.
  - *Do:* Reconcile function-call args against the done snapshot per item id: emit only the missing suffix, replace on mismatch, ignore empty snapshots and anything after finalization. Do not use the narrower "apply done only if no delta arrived" rule.
  - _anchor_ `pr_pydantic__pydantic-ai__10039#event-2`: "the completed snapshot is authoritative when it disagrees with the deltas, because that is what the non-streaming `_process_response` would return (keeps stream-vs-complete parity)"
- **[gotcha]** The ChatGPT/Codex backend (OpenAICodexModel) is stream-only. For responses with parallel tool calls it sends each call's arguments only in `response.function_call_arguments.done` / `response.output_item.done`, with no `delta` events and an empty `response.completed.output`. OpenAIResponsesStreamedResponse therefore has to take the arguments from the done events, or every such ToolCallPart ends up with `args=''`.
  - *Do:* When changing the OpenAI Responses stream parser, keep handling function-call arguments that arrive only in `function_call_arguments.done` or `output_item.done`. Do not assume deltas always arrive.
  - _anchor_ `pr_pydantic__pydantic-ai__10039#event-2`: "The ChatGPT/Codex backend (`OpenAICodexModel`) sends the arguments of parallel tool calls only in `function_call_arguments.done` / `output_item.done`, with no deltas and an empty `response.completed.output`"
- **[decision · not adopted]** In the Responses stream parser, a per-item `function_call_args` dict is kept on purpose instead of querying the parts manager for the received args and the "added was seen" check. `get_part_by_vendor_id` materializes the part, flushing the parts manager's string buffer, on every call. Using it in the per-delta branch would make argument streaming quadratic. The dict keeps the delta path O(1). The reviewer's suggestion to drop the parallel dict was not adopted in this PR.
  - *Instead:* Do not replace the per-item args dict with `get_part_by_vendor_id` in the delta path. It materializes the part and flushes the buffer on every chunk, making streaming quadratic.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/openai.py:4835`: "`get_part_by_vendor_id` materializes the part (flushing the parts manager's string buffer) on every call, so using it as the per-delta "added was seen" check would make argument streaming quadratic."

## pydantic_ai_slim/pydantic_ai/models/typesafe.py

- **[gotcha]** TypeSafeModel (Jev's server) deliberately keeps `requires_instructions = False`. The API reference documents `instructions` as required, but Jev's openapi.json and the TypeSafe SDK make it optional, and a live check showed Jev answering choice questions without `instructions` correctly. TypeSafeModel can set it to True if TypeSafe starts enforcing the documented contract.
  - *Do:* Do not enable `requires_instructions` for TypeSafeModel unless the server starts enforcing it. Requests to Jev stay unchanged.
  - _anchor_ `pr_pydantic__pydantic-ai__9848#event-2`: "Jev's server accepts questions without them (its `openapi.json` and the TypeSafe SDK both make the field optional)"

## pydantic_ai_slim/pydantic_ai/profiles

- **[decision]** `supports_cache` on a model profile means request-side caching configuration exists (the request can opt in or configure breakpoints). Implicit-only providers (Google, OpenAI before GPT-5.6) do not claim it. `supported_cache_retentions` defaults to `()` and advertises only tiers a request can ask for and the provider honors.
  - *Do:* Set `supports_cache=True` only where the request can configure caching. Do not advertise fictitious retention tiers in `supported_cache_retentions`.
  - _anchor_ `pr_pydantic__pydantic-ai__7560#event-6`: "`supports_cache` means "request-side caching configuration exists". Google and OpenAI before GPT-5.6, which cache implicitly, no longer claim it"
  - _anchor_ `pr_pydantic__pydantic-ai__7560#event-6`: "`supported_cache_retentions` defaults to `()`, and only tiers a request can ask for and the provider honors are advertised."

## pydantic_ai_slim/pydantic_ai/profiles, docs/models/openai.md

- **[gotcha]** OpenAI's default prompt-cache retention for pre-GPT-5.6 models depends on the organization's ZDR setting, not the model, so it can't be inferred from the model name. `ModelProfile.default_cache_retention` was therefore left unset for those models, and a 10-minute value was rejected. Only GPT-5.6 and later have a model-determined 30-minute floor. The OpenAI retention numbers live only on the OpenAI provider page.
  - *Do:* Leave cache retention unset ('unknown') where it depends on org or account configuration. Don't assert OpenAI retention defaults in general docs. Link to the OpenAI page.
  - _anchor_ `docs/models/openai.md:129`: "Organizations without ZDR enabled default to `24h`. Organizations with ZDR enabled default to `in_memory`"

## pydantic_ai_slim/pydantic_ai/profiles/__init__.py

- **[decision]** When a profile doesn't declare its supported cache retention tiers, every `CachePoint` TTL still counts as honored. A false 'warm' only defers maintenance, while a false 'cold' throws away a live cache hit. Providers must declare their tiers explicitly instead (OpenAI: `('30m',)` on GPT-5.6+, `()` earlier).
  - *Do:* Keep the rule that a missing `supported_cache_retentions` counts every `CachePoint` TTL. Fix wrong 'warm' results by declaring tiers in the provider's `model_profile()`.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/profiles/__init__.py:498`: "a profile that doesn't declare its tiers still counts every `CachePoint` TTL, because a false `warm` only defers maintenance while a false `cold` throws away a live cache hit."

## pydantic_ai_slim/pydantic_ai/realtime

- **[decision]** On OpenAI, Azure OpenAI and xAI realtime sessions, all_messages(), new_messages(), usage and wait_for_reply() come from the new session core (realtime/_core.py). The older core still streams events, runs tools and owns spans. A private switch, `_session._CORE_MODE = 'legacy'`, restores the old behavior. Gemini Live and GPT-Live stay on the old core because their connections don't report identified lifecycle events yet.
  - *Do:* When changing realtime history, usage or reply-wait behavior for OpenAI-protocol providers, edit realtime/_core.py. Don't expect Gemini Live or GPT-Live to follow it. Use `_CORE_MODE = 'legacy'` only to compare against old behavior.
  - _anchor_ `pr_pydantic__pydantic-ai__9612#event-18`: "A private switch (`_session._CORE_MODE = 'legacy'`) brings back the current behavior. Gemini Live and GPT-Live are unchanged: their connections don't report identified lifecycle events yet."
- **[gotcha]** The `phase` of gpt-realtime-2.x assistant messages is kept in the part's provider_details as 'phase'. It cannot be sent back to the provider, because the realtime API rejects `item.phase` on `conversation.item.create`.
  - *Do:* Record phase in provider_details only. Don't include item.phase when replaying history via conversation.item.create.
  - _anchor_ `pr_pydantic__pydantic-ai__9612#event-18`: "It can't be sent back: the realtime API rejects `item.phase` on `conversation.item.create`."

## pydantic_ai_slim/pydantic_ai/realtime/_core.py

- **[decision]** In the realtime session core, history snapshots only grow. Nothing is inserted ahead of what all_messages() already returned, except that a tool's return still goes directly after its call. A late transcript is handled by making the reply wait for the transcript of the spoken turn before it, bounded to 30 seconds from the reply being ready. After that the turn is recorded with the transcript it has.
  - *Do:* Don't insert late transcripts or turns into earlier history. Hold the later message until the earlier spoken turn's transcript arrives, up to the 30s bound.
  - _anchor_ `pr_pydantic__pydantic-ai__9612#event-18`: "Instead of inserting a late transcript (finding E), a reply waits for the transcript of the spoken turn before it. That wait is bounded: 30 seconds counted from the reply being ready"
- **[gotcha]** A withdrawn input (an evicted image, a failed send, refused content) must be dropped from the session core's collections entirely, placed or not. Merely flagging it `withdrawn` keeps its payload strongly referenced and leaks memory.
  - *Do:* When evicting or withdrawing inputs or audio in the core, remove them from every internal collection so the bytes can be garbage collected. Don't only hide them from all_messages().
  - _anchor_ `pydantic_ai_slim/pydantic_ai/realtime/_session.py:2032`: "a withdrawn input (an evicted image, a send that failed, refused content) is now dropped from the core altogether, placed or not, so nothing keeps its payload alive"

## pydantic_ai_slim/pydantic_ai/realtime/_session.py

- **[decision]** send_audio() hands each audio chunk to the session core before the send, under the send lock. This keeps overlapping sends in wire order and stops the receive pump finalizing a turn before the audio reaches the core. If the send fails, the chunk is taken back with AudioUnsent, by length, from the buffer or from the turn it was cut for.
  - *Do:* Keep core audio hand-off ahead of the awaited send and under the send lock. On a failed send, emit AudioUnsent so the failed bytes don't stay in history.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/realtime/_session.py:1092`: "`send_audio()` hands the chunk to the core before the send, as it already does for the session's own buffer, and takes it back (`AudioUnsent`) if the send fails"

## pydantic_ai_slim/pydantic_ai/realtime/azure.py

- **[gotcha]** The end-of-utterance guard and the pass-through of Azure-only VAD options (`end_of_utterance_detection`, `speech_duration_ms`, `auto_truncate`) must run after the turn-detection setting is resolved. They then apply to `azure_voice_live_turn_detection`, `openai_turn_detection` and the shared `turn_detection` alike. Otherwise an `AzureServerVAD` passed through the inherited `openai_turn_detection` field is silently stripped by the key whitelist.
  - *Do:* When validating or transforming Voice Live turn-detection config, do it after resolving which setting supplies the value, so every entry point (`azure_voice_live_turn_detection`, `openai_turn_detection`, `turn_detection`) is covered.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/realtime/azure.py:387`: "the end-of-utterance guard and the pass-through of Azure-only options now run after the setting is resolved, so they apply equally to `openai_turn_detection` (and the shared `turn_detection`)."
- **[gotcha]** Azure Voice Live end-of-utterance detection works only on cascaded pipelines. A non-cascade model rejects it, then refuses every later frame of the session. The adapter therefore raises `UserError` before connecting when `end_of_utterance_detection` is set on a non-cascade model. A cascade model deployed under another name opts in with `profile=AzureRealtimeModelProfile(azure_voice_live_cascade=True)`.
  - *Do:* When adding Voice Live options that are cascade-only, guard them with a `UserError` before connecting. Use `AzureRealtimeModelProfile.azure_voice_live_cascade` to decide whether the model is a cascade.
  - _anchor_ `pr_pydantic__pydantic-ai__9414#event-3`: "on a non-cascade model it raises `UserError` before connecting. Voice Live rejects it there and then refuses every later frame of the session."
- **[decision]** On Azure Voice Live cascade models, the shared OpenAI setting `openai_input_noise_reduction` is converted to `azure_deep_noise_suppression`, because Microsoft documents `near_field`/`far_field` as gpt-realtime only. The explicit `azure_voice_live_noise_reduction` setting is sent to Voice Live exactly as given, with no remapping. Voice Live was checked live and accepts `near_field`/`far_field` on cascade models, and a test pins this behavior with a comment.
  - *Do:* Keep remapping only for the shared `openai_input_noise_reduction` on cascade models. Send `azure_voice_live_noise_reduction` unchanged. Do not add conversion or restriction for `near_field`/`far_field` on cascade models just because a reviewer suggests it.
  - _anchor_ `pydantic_ai_slim/pydantic_ai/realtime/azure.py:344`: "Converting is the absorb step for the shared OpenAI setting (`openai_input_noise_reduction`). `azure_voice_live_noise_reduction` is the explicit Voice Live setting, and per the approved design it is sent as given, which the test pins with a comment."

## pydantic_ai_slim/pydantic_ai/ui

- **[gotcha]** When serializing a Pydantic `ValidationError` into an HTTP response, `e.json()` can raise `ValueError` for invalid UTF-8 request bodies because the error retains the raw input bytes. The fallback is to retry with `e.json(include_input=False)`, so that handling the validation error does not itself produce a 500.
  - *Do:* Always serialize request `ValidationError`s through the shared helper, which falls back to `include_input=False`. Do not call `e.json()` directly in a response path.
  - _anchor_ `pr_pydantic__pydantic-ai__10042#event-0`: "serializing the error with `e.json()` can raise `ValueError` because those bytes cannot be represented as UTF-8 JSON. The existing adapter handles this by retrying `e.json(include_input=False)`."
- **[style]** A helper imported across modules should not have a leading underscore, because Pyright flagged the private-named cross-module import. The helper was renamed from `_validation_error_response` to `validation_error_response`. It stays module-level in the private `_adapter` module and is not exported publicly.
  - *Do:* Name helpers shared between internal modules without a leading underscore, and keep them out of the public exports by placing them in a private module.
  - _anchor_ `pr_pydantic__pydantic-ai__10042#event-6`: "Fix pyright: drop leading underscore on cross-module helper, ignore guard-only import"

## pydantic_ai_slim/pydantic_ai/ui/_web/api.py

- **[decision]** The 422 handler in `post_chat` must stay narrow, covering only the two pre-dispatch validation stages. The 415 content-type check runs first. The 400 response for a model or native-tool id outside the allowlist stays unchanged. Agent dispatch and streaming stay outside the handler and keep their existing exception behavior.
  - *Do:* Do not widen the 422 catch to include dispatch, streaming, or the allowlist 400 check. Keep the 415 content-type check first.
  - _anchor_ `pr_pydantic__pydantic-ai__10042#event-2`: "The 415 content-type check still runs first; the 400 model/native-tool allowlist check, dispatch and streaming are unchanged and outside the new handler."
- **[decision]** In `Agent.to_web()`'s `POST /api/chat` (`post_chat`), `ValidationError`s from `VercelAIAdapter.from_request()` and `ChatRequestExtra.model_validate()` must be converted to a structured HTTP 422, matching `UIAdapter.dispatch_request()`. Before the fix they escaped as HTTP 500. The conversion lives in a shared `validation_error_response()` helper in `pydantic_ai/ui/_adapter.py`, used by both `dispatch_request()` and the web route.
  - *Do:* When adding request parsing or validation steps to the web chat route, wrap them with the shared `validation_error_response()` helper so client input errors return 422. Do not write a separate conversion.
  - _anchor_ `pr_pydantic__pydantic-ai__10042#event-2`: "This extracts the existing ValidationError-to-422 conversion in `pydantic_ai/ui/_adapter.py` (including the `include_input=False` fallback for bodies that aren't valid UTF-8) into a `validation_error_response()` helper"

## pydantic_clai2 / MCP plugins

- **[decision]** clai2 supports FastMCP 3 and FastMCP 4 deliberately; the team chose not to cap `fastmcp-slim<4` for clai2. Fixes should make code work on both generations. Under FastMCP 4 the MCP client is `httpx2`, not legacy `httpx`.
  - *Do:* When fixing FastMCP 4 incompatibilities in clai2, keep FastMCP 3 working too. Do not add a `fastmcp-slim<4` cap.
  - _anchor_ `pr_pydantic__pydantic-ai__9934#event-1`: "`clai2` already supports FastMCP 4 deliberately."

## pydantic_clai2 logfire_oauth.py, posthog plugin

- **[gotcha]** Under FastMCP 4 (httpx2), `httpx2.BaseClient._build_auth` accepts only an `httpx2.Auth`, a tuple or a callable, and raises `TypeError: Invalid "auth" argument` for legacy `httpx.Auth` subclasses. Custom auth classes passed to the MCP http client must therefore be accepted by both generations. The workspace lock pins FastMCP 3, but a fresh uvx/pip install resolves FastMCP 4, so lock-based tests can miss this.
  - *Do:* Make custom auth classes for MCP clients subclass both `httpx.Auth` and `httpx2.Auth`. Do not pick a base by version or type probe at import time. Use a constrained TypeVar for the Request type and one `pyright: ignore` per class for the inherited flow method.
  - _anchor_ `pr_pydantic__pydantic-ai__9934#event-1`: "`httpx2`'s `BaseClient._build_auth` accepts only an `httpx2.Auth` (or a tuple or a callable) and raises `TypeError: Invalid "auth" argument` for anything else."
  - _anchor_ `pr_pydantic__pydantic-ai__9934#event-1`: "`DeviceAuth` and `SavedKeyAuth` subclass both `httpx.Auth` and `httpx2.Auth`, so whichever client the installed FastMCP builds accepts them."

## pydantic_clai2 plugin MCP toolsets

- **[decision · not adopted]** A failing optional MCP server, such as logfire_mcp while Logfire is unreachable, still fails the whole clai2 turn. Making plugin-contributed MCP toolsets skip servers that fail to connect was deliberately left out as a separate design question (plugin loader or wrapper toolset).
  - *Instead:* Do not fold skip-on-connect-failure behavior into auth or compatibility fixes. Treat it as a separate design change.
  - _anchor_ `pr_pydantic__pydantic-ai__9934#event-1`: "Making plugin-contributed MCP toolsets skip a server that fails to connect is a separate behavior change"

## pydantic_clai2/logfire_oauth.py

- **[gotcha]** The Logfire device flow (discovery, registration, polling, refresh) must not use the MCP `http_client` factory. Under FastMCP 4 that factory yields an httpx2 client, so errors are httpx2 errors and the `except httpx.HTTPError` / `except httpx.TransportError` handlers miss them. The device flow now builds its own legacy `httpx.AsyncClient` with the SDK's 30 s / 300 s read timeouts and no redirects.
  - *Do:* Keep the device flow on its own `httpx.AsyncClient` so the `httpx` exception handlers keep working. Do not reuse `http_client` there.
  - _anchor_ `pr_pydantic__pydantic-ai__9934#event-1`: "Its `except httpx.HTTPError` / `except httpx.TransportError` handlers don't catch those."
  - _anchor_ `pr_pydantic__pydantic-ai__9934#event-1`: "The Logfire device flow builds its own legacy `httpx.AsyncClient`, with the MCP SDK's 30 s / 300 s read timeouts and no redirects"

## pydantic_evals/reporting

- **[gotcha]** In pydantic_evals report rendering (EvaluationReport.render()/print()), all user-supplied text (case names, inputs, outputs, expected output, metadata, score/label/metric names, reasons, evaluator failures, case failure messages, and output of custom RenderValueConfig value_formatter/diff_formatter) must be escaped with rich.markup.escape before going into Rich table cells. Otherwise stray closing tags like `[/INST]` raise MarkupError and tag-like text such as `list[int]` is silently dropped. The renderer's own [bold]/[magenta]/[red]/[i] markup is kept.
  - *Do:* When adding or changing report table cells in pydantic_evals reporting, pass user-supplied text through `_escape_markup` and never interpolate it raw into Rich markup strings.
  - _anchor_ `pr_pydantic__pydantic-ai__9544#event-2`: "This escapes that text with `rich.markup.escape` and keeps the renderer's own `[bold]`, `[magenta]`, `[red]` and `[i]` markup."
- **[gotcha]** rich.markup.escape doubles a single trailing backslash so a closing tag right after the text still works. In pydantic_evals reporting, `_escape_markup` drops that extra backslash so cells ending in a backslash display as written, and `_style_markup` doubles trailing backslashes only where the renderer itself appends a closing tag right after user text.
  - *Do:* When wrapping user text in renderer style tags, use `_style_markup` (which handles trailing backslashes). Use `_escape_markup` for plain cells without a closing tag.
  - _anchor_ `pr_pydantic__pydantic-ai__9544#event-2`: "`_escape_markup` drops that extra backslash and `_style_markup` doubles trailing backslashes only where the renderer adds a closing tag itself."
- **[decision · not adopted]** Using Rich `Text()` for the failures table (as in the stale PR #3975) was not adopted because it does not fit cells that mix user text with the renderer's own markup, such as diff cells and red evaluator names. Escaping with rich.markup.escape was used instead.
  - *Instead:* Do not switch report cells to `Text()` objects for escaping. Use escaped markup strings via `_escape_markup`/`_style_markup`.
  - _anchor_ `pr_pydantic__pydantic-ai__9544#event-2`: "#3975 used `Text()` for the failures table, but that doesn't fit cells that mix user text with the renderer's markup, like diff cells and the red evaluator names."
- **[decision]** Markup returned on purpose from a RenderValueConfig value_formatter or diff_formatter is now escaped and shown as literal tags. With `Console(markup=False)` the escaping backslash is visible (`list\[int]`). This was accepted as non-breaking and not documented as a compatibility impact.
  - *Do:* Do not rely on RenderValueConfig formatters returning Rich markup. Their output is treated as plain text.
  - _anchor_ `pr_pydantic__pydantic-ai__9544#event-2`: "so markup returned from one on purpose now shows as tags, and `print(console=Console(markup=False))` now shows the escaping backslash (`list\[int]`)."

## pyproject.toml

- **[procedure]** The per-package `[tool.uv.exclude-newer-package]` cutoff for `anthropic` in `pyproject.toml` is temporary. It only admits a new SDK release ahead of the global 7-day `exclude-newer` cooldown. Once the global window covers that release, the entry becomes a ceiling that quarantines every later `anthropic` release, so it must be removed. When a newer SDK is needed, the cutoff is replaced, not stacked.
  - *Do:* After the date in the cutoff entry passes, remove the `anthropic` line from `[tool.uv.exclude-newer-package]`. If a newer SDK release is needed sooner, replace the entry with a new dated cutoff instead of adding a second one.
  - _anchor_ `pr_pydantic__pydantic-ai__9988#event-0`: "Past that date it stops acting as a floor and becomes a ceiling that quarantines every later `anthropic` release."

## pyproject.toml, .github/scripts/pydantic-ai-runner.lock

- **[procedure]** The per-package `exclude-newer` cutoff for `anthropic` in `pyproject.toml` (`[tool.uv.exclude-newer-package]`) is temporary. It admits a new SDK release ahead of the 7-day cooldown. Once the global `exclude-newer = "7 days"` covers that release, the entry becomes a ceiling that quarantines later `anthropic` releases, so it must be removed after its date. The same entry is mirrored in `.github/scripts/pydantic-ai-runner.lock`. Each new cutoff replaces the previous one and is tracked by an issue.
  - *Do:* When bumping `anthropic` to a release newer than 7 days, add or replace the dated per-package cutoff and link a tracking issue to remove it. After the date passes, delete the entry and refresh the runner lock with `uv lock --script .github/scripts/pydantic-ai-runner`. Because the lock is under `.github/`, a non-maintainer must ask a maintainer to do that refresh.
  - _anchor_ `pr_pydantic__pydantic-ai__9986#event-0`: "Past that date it stops acting as a floor and becomes a ceiling that quarantines every later `anthropic` release."
  - _anchor_ `pr_pydantic__pydantic-ai__9986#event-0`: "The same entry is mirrored in `.github/scripts/pydantic-ai-runner.lock`, so refresh that with `uv lock --script .github/scripts/pydantic-ai-runner` in the same change."
  - _anchor_ `pr_pydantic__pydantic-ai__9986#event-19`: "the runner's lock mirrors the root `exclude-newer-package` entries"

## repo contribution workflow

- **[gotcha · not adopted]** A PR for a GitHub issue that is not assigned to the author is closed automatically by the Duplicate & Issue-Link Guard. The Haiku 5.5 support PR was closed this way. It was not rejected on technical grounds.
  - *Instead:* Before opening a PR that closes an issue, check that the issue is assigned to the PR author. If it is not, ask on the issue to be assigned and wait, rather than opening the PR.
  - _anchor_ `pr_pydantic__pydantic-ai__9988#event-8`: "To avoid duplicate effort, please wait to be assigned before opening a PR."
  - _anchor_ `pr_pydantic__pydantic-ai__9988#event-8`: "This PR has been closed automatically because [issue #8972](https://github.com/pydantic/pydantic-ai/issues/8972) is not assigned to you."

## repo workflow

- **[gotcha]** A PR that closes an issue is closed automatically if that issue is not assigned to the PR author. The Duplicate & Issue-Link Guard enforces this. Here the PR was closed and had to be superseded by a new PR from the same branch.
  - *Do:* Before opening a PR, make sure the linked issue is assigned to you, or ask a maintainer to assign it. Do not open a PR that says 'Closes #N' for an issue assigned to someone else or unassigned.
  - _anchor_ `pr_pydantic__pydantic-ai__9986#event-17`: "please wait to be assigned before opening a PR."
  - _anchor_ `pr_pydantic__pydantic-ai__9986#event-17`: "This PR has been closed automatically because [issue #8972](https://github.com/pydantic/pydantic-ai/issues/8972) is not assigned to you."

## scripts/issue_pr_attention_monitor.py

- **[decision · not adopted]** A weekly-digest section listing failed scheduled agentic runs was tried and dropped, in favour of a `failed` column in the existing spend report.
  - *Instead:* Report scheduled agentic failures in the spend report's `failed` column, not in the maintainer digest.
  - _anchor_ `.github/scripts/issue_pr_attention_monitor.py:1895`: "This code is gone: the digest section was dropped, and failures now appear as a column in the existing spend report."

## src/pydantic_ai_harness, tests/harness

- **[style]** Harness writing style: do not use Unicode arrows in class docstrings. Main's lint also flags `timezone.utc` (UP017), so use `datetime.UTC`.
  - *Do:* Use ASCII in docstrings (no Unicode arrows) and `from datetime import UTC` instead of `timezone.utc`.
  - _anchor_ `pr_pydantic__pydantic-ai__9899#event-8`: "Also drop a Unicode arrow from the class
docstring per the harness writing style."
  - _anchor_ `pr_pydantic__pydantic-ai__9899#event-12`: "Main's lint now flags `timezone.utc` (UP017), so the live Postgres suite
uses `UTC` as well."

## src/pydantic_ai_harness/step_persistence

- **[gotcha]** Import the Postgres pool protocols (PostgresConnection/PostgresPool) from pydantic_ai_harness.media, where they are defined and publicly exported. Re-importing them through step_persistence._postgres fails pyright with reportPrivateImportUsage and breaks the CI quality checks.
  - *Do:* In step_persistence modules, import PostgresPool and PostgresConnection from pydantic_ai_harness.media, not from a private sibling module.
  - _anchor_ `pr_pydantic__pydantic-ai__9899#event-11`: "Pyright rejects re-importing PostgresConnection/PostgresPool through
step_persistence._postgres (reportPrivateImportUsage), which failed the CI
quality checks"

## src/pydantic_ai_harness/step_persistence/_postgres.py, media Postgres store

- **[decision]** Postgres table prefixes for the new stores are restricted to lowercase identifiers. Postgres folds unquoted identifiers to lowercase, so 'Orders' and 'orders' silently shared tables across supposedly distinct stores. Rejecting uppercase at construction makes the aliasing impossible. The older PostgresMemoryStore `_TABLE_RE` still has this exposure, and tightening it is a compatibility decision for maintainers.
  - *Do:* Validate any Postgres `table=` prefix as lowercase-only. Do not change PostgresMemoryStore's `_TABLE_RE` without a maintainer compatibility decision.
  - _anchor_ `pr_pydantic__pydantic-ai__9899#event-10`: "PostgreSQL folds unquoted identifiers to lowercase, so 'Orders' and 'orders'
silently shared the same tables across supposedly distinct stores"

## tests/

- **[gotcha]** The `strict-no-cover` check flags `# pragma: no cover` placed on a `class` line, because the class statement and its docstring execute at import. Put the pragma on individual method def lines, or add real coverage for the class.
  - *Do:* Do not put `# pragma: no cover` on class lines. Cover the class with a real test, or mark the specific uncovered method defs.
  - _anchor_ `pr_pydantic__pydantic-ai__4843#event-33`: "`strict-no-cover` flags `# pragma: no cover` on a `class` line because the"
- **[style]** Test-style conventions from review: don't add `pytestmark = pytest.mark.anyio` because anyio runs in auto mode (`anyio_mode = "auto"`). Put imports at module level, not inline, unless they're optional dependencies. Keep `@staticmethod` on helpers that don't use `self` rather than turning them into instance methods in a refactor.
  - *Do:* Omit the anyio pytestmark in async tests. Hoist imports to module top unless the dependency is optional. Don't change `@staticmethod` helpers to instance methods when `self` is unused.
  - _anchor_ `tests/test_cache_setting.py:48`: "async tests already run through anyio's auto mode (`anyio_mode = "auto"`), so the marker is noise"
  - _anchor_ `tests/test_cache_setting.py:404`: "None of these modules are optional dependencies, so nothing needs the import deferred."
  - _anchor_ `pydantic_ai_slim/pydantic_ai/models/anthropic.py:2799`: "please keep both as `@staticmethod` so the refactor stays limited to switching to `excess_cache_points`"
- **[style]** Mocked (non-VCR) tests must each have a docstring saying which event sequence they pin and why they are mocked rather than VCR. Examples are Codex-only sequences or defensive edge cases that can't be reproduced reliably against a live API. Helper functions should use precise return types (e.g. `list[ModelResponseStreamEvent]`) instead of `Any`.
  - *Do:* Add a one-line docstring to every non-VCR test explaining which sequence it pins and why it is mocked, and avoid `Any` return types in test helpers.
  - _anchor_ `tests/models/test_openai_responses.py:1383`: "Our test guidelines ask every non-VCR test to say why it isn't, or can't be, a VCR test."
- **[gotcha]** Tests that use optional-extra classes such as `AnthropicModelSettings` must construct them inside the test body, not at collection or module level, because that raises NameError when the extra isn't installed. OTel-SDK-dependent tests are guarded with `try_import`.
  - *Do:* Build optional-extra settings inside test functions. Guard optional-dependency tests with `try_import`.
  - _anchor_ `pr_pydantic__pydantic-ai__6537#event-82`: "which raised NameError without the anthropic extra."
  - _anchor_ `pr_pydantic__pydantic-ai__6537#event-19`: "Use `try_import` for the OTel SDK test guard"
- **[gotcha]** Do not name a test package `tests/websockets/`. It shadows the `websockets` PyPI package when `tests/` is on `sys.path` (as in `tests/import_examples.py`). That breaks `google.genai`'s `from websockets.asyncio.client import connect` and fails the `test examples` CI job.
  - *Do:* Name new test directories and modules so they do not collide with third-party package names such as `websockets`; for example, use `tests/models/test_*_websocket.py`.
  - _anchor_ `pr_pydantic__pydantic-ai__4843#event-31`: "The `tests/websockets/` package shadowed the `websockets` PyPI package:"

## tests/clai2

- **[procedure]** To verify FastMCP 4 behavior, install `fastmcp-slim` 4.x with MCP 2.x in a separate venv and connect a real FastMCP `Client` over `StreamableHttpTransport(..., httpx_client_factory=http_client)`. Regression tests use a real `httpx2.AsyncClient`.
  - *Do:* Reproduce and test FastMCP 4 issues in a separate venv with FastMCP 4, and add regression tests that use a real `httpx2.AsyncClient`.
  - _anchor_ `pr_pydantic__pydantic-ai__9934#event-1`: "Reproduced with `fastmcp-slim` 4.0.11 and MCP 2.3.0 installed in a separate venv, connecting a real FastMCP `Client` over `StreamableHttpTransport(..., httpx_client_factory=http_client)`"
- **[gotcha]** Reproducing the /compact growth bug: a history of one prompt, 92 tool rounds, and a final answer at about 50,127 estimated tokens (186 messages) makes /compact produce 187 messages. This is the regression case, and the new test fails on main.
  - *Do:* Use the 186-message, ~50,127-token history as the regression fixture for /compact on both the summarization and truncation strategies. Use summary replies long enough for a summary to be smaller than what it replaces.
  - _anchor_ `pr_pydantic__pydantic-ai__9923#event-1`: "A history of one prompt, 92 tool rounds, and a final answer at 50,127 estimated tokens reproduces it exactly."

## tests/harness/step_persistence, tests/harness/media, src/pydantic_ai_harness/integration_tests/postgres

- **[decision]** The issue proposed covering the Postgres stores against a real Postgres in CI rather than a hand-maintained SQL fake. Because the CI job could not be included in the PR, the merged change instead covers the stores in the ordinary unit suites through a SqlitePool shim. This is an in-memory SQLite pool that satisfies PostgresPool and rewrites the few Postgres-only spellings. The live Postgres suite is kept as an additional behavior suite that does not run in CI here.
  - *Do:* When adding or changing Postgres store SQL, keep it compatible with the SqlitePool shim so the unit suites cover it on every test leg, and also run the live suite with `make integration-postgres`.
  - _anchor_ `pr_pydantic__pydantic-ai__9899#event-19`: "The live Postgres suite does not run in CI, so the coverage job saw only the
construction tests. SqlitePool satisfies PostgresPool over in-memory SQLite,
rewriting the few Postgres-only spellings"

## tests/models

- **[procedure]** Reviewers require provider-facing features to have recorded VCR tests through `Agent.run` showing the first request writes the cache and the second reads it, snapshotting `result.usage()`. Mock and `prepare_request` unit tests may stay to pin payload shape, but each should say why it isn't a VCR test. Tests of translation should go through the public `prepare_request` path rather than private helpers.
  - *Do:* For new provider-facing behavior, add VCR cassette tests that check the live wire request and the usage snapshot. For mock-based tests, add a note on why they aren't VCR, and call `Model.prepare_request` instead of private translators.
  - _anchor_ `tests/models/test_anthropic.py:2029`: "The mock and `prepare_request` unit tests can stay to pin the payload shape, as long as each one says why it isn't a VCR test."
  - _anchor_ `tests/test_cache_setting.py:403`: "Routing these two the same way would test the public path a user actually hits"

## tests/realtime/simulation

- **[procedure]** When a simulator finding gets fixed for a provider, convert its pinned scenario into a `run_clean` regression test and delete the old pinned scenario. If the finding still reproduces on providers left on the old core (Gemini, GPT-Live), keep a narrowed pinned scenario for those. New findings that rest on fake-server guesses with no recording are pinned rather than fixed.
  - *Do:* After fixing a simulator finding, turn its scenario into a run_clean regression test. Narrow the registered finding to the providers that still reproduce it. Pin, rather than fix, findings that have no recording behind them.
  - _anchor_ `pr_pydantic__pydantic-ai__9612#event-18`: "Fixed for OpenAI-protocol sessions and turned into `run_clean` regression tests"
  - _anchor_ `pr_pydantic__pydantic-ai__9612#event-18`: "Both rest on fake-server guesses (no recording has either), which is why they're pinned rather than fixed here."

## tests/realtime/simulation/_findings.py

- **[decision · not adopted]** Tightening the simulator's SIM-23 finding matcher to correlate a violation with the response of the cancelled deferred request was tried and not adopted. A cut-off frame takes the terminal and usage of the response it carried, so the violation's response isn't the one tied to the cut-off send. Correlating them would require the simulator to map the cancelled response.create to its frame, which it doesn't model. An earlier attempt to correlate by terminal reads stopped the pinned scenario from reproducing.
  - *Instead:* Leave SIM-23 matching on a close-cancelled request the connection was sending. Don't try to correlate by the violation's named response unless the simulator is first taught to map response.create to its frame.
  - _anchor_ `tests/realtime/simulation/_findings.py:884`: "Tying the two together would need the simulator to map the cancelled `response.create` to the frame that sent it, which it doesn't model. An earlier attempt to correlate by terminal reads stopped the pinned scenario from reproducing."
- **[style]** Simulator finding matchers in tests/realtime/simulation/_findings.py must be tied to the specific violation they explain, not just to the presence of a related event in the run. Otherwise unrelated regressions are silently tolerated as known findings. SIM-26 covers only violations with no more phantom turns than the `speech_stopped` frames server VAD took back. SIM-24 matches a `history.order` violation only if the named response is the provider-started one read before any echo.
  - *Do:* When adding or editing a finding matcher, use the violation's own details (named response, count) so it doesn't swallow unrelated violations.
  - _anchor_ `tests/realtime/simulation/_findings.py:726`: "`history.phantom_turn` now reports how many turns too many, and SIM-26 only covers violations with no more phantom turns than `speech_stopped` frames server VAD took back."
  - _anchor_ `tests/realtime/simulation/_findings.py:903`: "when the violation names a response (`history.order`), SIM-24 only matches if that response is the provider-started one read before any echo."
- **[gotcha]** In the realtime simulator's known findings (tests/realtime/simulation/_findings.py), SIM-18 covers the GPT-Live case where a delegated response's later tool call is recorded in whatever response the session is building at that point. This yields `response.duplicated` (nothing spoken in between), `response.mixed`, and `response.truncated` (a new reply started speaking in between). The fix SIM-18 tracks is per-response-id state, which would retire all three codes.
  - *Do:* When a GPT-Live exploration fails with response.mixed, response.truncated, or response.duplicated after a delegated call lands in a later reply, check whether it is SIM-18 before filing a new finding. Retire the SIM-18 pins once per-response-id state lands.
  - _anchor_ `pr_pydantic__pydantic-ai__9861#event-1`: "This is SIM-18's mechanism: the session can't continue a response it has already recorded, so what a delegated response adds later goes into whatever response it is building at that point."
- **[gotcha · not adopted]** A finding predicate in the realtime simulator must be scoped to the current violation's named responses (via `_context_responses`), not scan all truth responses. Whole-trace scanning (an initial SIM-18 attempt using `_continued_after_calling()` over every response) was tried and not adopted. It would excuse unrelated `response.mixed`/`response.truncated` violations as SIM-18 instead of reporting them as new findings.
  - *Instead:* When adding or extending codes for a known finding, make the predicate match only if a response named by the violation (through `_context_responses`) satisfies the condition. Do not use a whole-trace check, and do not widen the codes unless the predicate is scoped this way.
  - _anchor_ `tests/realtime/simulation/_findings.py:659`: "the predicate scanned every response, so any GPT-Live response that continued after a call would have excused an unrelated `response.mixed` or `response.truncated`."
  - _anchor_ `tests/realtime/simulation/_findings.py:659`: "`response.duplicated` also names its response (`{'response': number}`), so there was no reason to keep the whole-trace check for it."

## tests/test_mcp.py

- **[style]** Test tool functions in the MCP Apps visibility test use docstring-only bodies so they need no coverage.
  - *Do:* In tests that define tool functions that are never executed, give them docstring-only bodies to avoid needing coverage pragmas or extra coverage.
  - _anchor_ `pr_pydantic__pydantic-ai__9862#event-21`: "Give the MCP Apps visibility test's tools docstring-only bodies so they need no coverage"
