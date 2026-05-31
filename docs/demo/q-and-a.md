# Q&A prep — `agent-lore`

Private reference: insights about *why* `agent-lore` works, what it isn't, and how to answer the sharp questions a sophisticated audience will ask. Captures the positioning reasoning that doesn't belong in the public README. Lives in `docs/demo/` while the repo is private; moves into the lab (`meta/talks/…`) — or gets reframed for a public FAQ — when the repo flips public. See the strategy doc §4 pre-flight cleanup.

## How this is organized

- **Quick-answer table** — what to say in Q&A in 1–2 sentences. Skim this before the talk.
- **Deep dives** — the questions that need more than a sentence, with reasoning, "on stage" one-liners, and honest concessions.
- **Never name competitors** — answer the *category*, not the *product*. The reasoning is sharper that way anyway.

## Quick-answer table

| Question | Stage answer (≤ 30 seconds) |
|---|---|
| Why not just keep a changelog / agent log in the repo? | A changelog is what you *write*; `lore` is what's *compiled*. Changelogs accumulate, compile dedupes. Changelogs depend on agent/dev discipline; `lore` reads existing transcripts. Anchors verify; freeform changelogs don't. |
| Why not put it all in `CLAUDE.md`? | `CLAUDE.md` holds the dozen rules you *already know* matter. `lore` holds the gotchas you'd *never think to write down* because you didn't know them until a session discovered them. They compose. |
| Why not the harness's built-in memory feature? | Per-harness memory is *per-developer*, *in that harness*. `lore`'s contract is the *team* shares *one* knowledge layer across *any* harness, versioned in *your* git. |
| Why not RAG / a vector DB over the code? | RAG searches *the code itself*. `lore` captures *what your team learned working on the code*. Different unit: chunks vs claims. RAG can't tell you about a rejected approach that never got merged. |
| Why not an agent-memory framework? | Personal memory at the developer-IDE scope; `lore` is at the team-repo scope. Complementary tools at different scopes. |
| Cost? | BYO key. Sonnet 4.6 compiles a typical 30–45 min session for ~$0.20. Incremental — only new sessions cost anything. |
| Cursor / Copilot / Aider / Codex? | Adapter contribution — small. Architecture is harness-neutral by design. Claude Code adapter today; more land as soon as the path is proven on one. |
| Secrets? | Scrubbed at ingest before storage or any model call (API keys, AWS keys, private-key blocks, secret assignments). Plus you git-PR-review the `.lore/claims` diff. |
| Doesn't this just grow forever into a dumpyard? | No — actuation loop. Unused claims decay and archive; contradicted claims retire; influential claims reinforce. Healthy `.lore/` plateaus. |
| What if the LLM extracts a wrong claim? | Two layers: (1) every claim has a verbatim anchor a human can verify; (2) the actuation loop retires claims overridden in real use. Explicit human approval gate ships next. |
| Bedrock / Vertex / local model? | LLM provider abstraction. Point `lore` at any `complete(prompt) → str` callable. Nothing routes through us because there's no us. |
| Python-only? | `lore` *runs* in Python. The codebases it *compiles knowledge about* can be in any language — the transcripts are the same shape regardless. |
| Can someone forge a transcript and inject fake claims? | The integrity boundary is the agent runtime + your local filesystem; `lore` inherits whatever trust model your repo already has. Cryptographic provenance is future work. |
| What about successful PRs / merged code as a signal? | Roadmap. Natural extension: claims whose suggested actions ended up in merged code get an authority boost. Wiring not yet in. |
| What about stale claims when the underlying code changes? | Actuation loop handles unused/overridden; "anchor freshness" (re-verify anchor lines against current code) is on the roadmap. For now: re-compile after heavy refactors. |
| Why local-first specifically? | Trust + portability. Compiled team knowledge stays in your git repo; no third-party SaaS to disappear, leak, or change terms. Regulated/IP-sensitive teams can adopt without legal review. |
| How is this different from existing memory layers we already see? | Two structural differences: this is *team-scoped, in the repo* (not personal, not in a cloud), and it does *compilation* (dedup + conflict + actuation), not just storage. |
| Will it work on a huge codebase? | Compile cost is per-session, not per-repo-size — codebase size doesn't change the cost. Where size matters: the agent's exploration produces more events per session, so per-session cost scales with session length (linear), not repo size. |
| Does it work with multiple repos? | One `.lore/` per repo. A multi-repo team gets a knowledge layer per repo; cross-repo synthesis is future work. |

## Deep dives

### "Why not just maintain a changelog or `AGENT_LOG.md`?"

**Headline:** a changelog is what you *write*; `lore` is what's *compiled*. Same plaintext-in-repo property, fundamentally different mechanism.

**On stage:**
> *"A changelog is what you write during the session, when you might be tired and the work might be incomplete and you have to predict what's worth recording. `lore` extracts after the session from the actual transcript, with the full context of what really happened. That's the first difference. The deeper one: a changelog **accumulates**, `lore` **compiles**. After 100 sessions, your changelog has 100 entries nobody reads — same gotcha recorded seven times by seven different devs, each as a separate line. `lore` dedupes those seven into one claim whose authority climbed because seven people independently hit it. And when two of those seven disagreed, `lore` keeps both — your changelog silently overwrites. The compile step is the product; the file format is incidental."*

**The four real differences:**

1. **Compilation vs accumulation.** Changelog: 7 sessions on the same bug = 7 entries nobody connects. `lore`: content-addressed claim ID dedupes to 1 claim, 7 anchors, authority climbed.
2. **Extraction-after vs writing-during.** Changelog asks the agent to *predict* what's reusable at the end of a tired session. `lore` extracts post-hoc with full context; better selection, less hallucinated "summary."
3. **Task-conditioned retrieval.** A 5000-line changelog goes into agent #2's context as 5000 lines — expensive, distracting, lost-in-the-middle. `lore` serves the relevant claim subset.
4. **Actuation loop.** Old changelog entries become noise. `lore` archives unused, retires contradicted, reinforces influential — active set plateaus.

**Two structural points:**

- **Zero harness compliance.** Every agent already writes transcripts. `lore` reads them. The changelog approach needs every agent + dev + future contributor told "remember to write to PROJECT_NOTES.md with these fields after each session, and please don't make stuff up." Compliance theater across N tools, N humans.
- **Verifiability.** A changelog says "we decided to use Postgres." Why? When? Who? `lore`'s anchor points at the exact transcript turn where the decision happened — a new engineer can verify, an auditor can trust.

**Honest concession.** A changelog is genuinely fine for a *small team (1–3 people), short timeline (< 6 months), high-discipline contributors*. The value compounds with scale, drift, and turnover.

**The killer one-liner if pushed:**
> *"Have you ever **trusted** a 2-year-old CHANGELOG? That's the changelog approach at scale. Nobody curates them; they grow faster than they curate themselves. `lore` does the curation — that's the product."*

### "Why not just put it all in `CLAUDE.md`?"

**Headline:** different units, different lifetimes, complementary.

**On stage:**
> *"CLAUDE.md is hand-curated by you, upfront, with the rules you already know matter. `lore` is auto-extracted from sessions, ongoing, with the gotchas you'd never think to write down because you didn't know them until a session hit them. The webhook double-fire under Stripe retries — you don't write that in CLAUDE.md because you don't know about it until it happens. They compose: CLAUDE.md is your rulebook, .lore/knowledge/ is your team's accumulated working memory."*

**The reasoning:** CLAUDE.md is excellent for the dozen things you *can write down before any work happens* — coding conventions, lint rules, "use Postgres for the ledger." `lore`'s territory is the surprises that *only emerge by working the codebase*: the silent data loss, the provider quirk, the cross-module gotcha, the decision made in passing that the team forgot.

**Honest concession.** If your codebase has so few unknowns that `CLAUDE.md` covers everything, you don't need `lore`. The wedge is complexity + time + turnover.

### "Why not the harness's built-in memory feature?"

**Headline:** per-harness memory is *per-developer*, *in that harness*. `lore` is *per-team*, *across harnesses*, *in your repo*.

**On stage:**
> *"Built-in memory is great for personal continuity within one tool — 'remember I'm working on the X feature.' lore is a different contract: shared with your team, inherited on git pull, the same layer readable from Cursor or Claude Code or Copilot. And lore does compilation — dedup, conflict, actuation — that no built-in memory I know of does."*

**The reasoning:** the structural facts are different in three places:
- **Location.** Built-in: your IDE's local state. `lore`: your repo.
- **Sharing.** Built-in: you. `lore`: the team.
- **Operations.** Built-in: store + recall. `lore`: extract + dedup + conflict-record + actuate.

**Honest concession.** For solo, single-harness work, the built-in memory is enough. The team-shared scope is the moat.

### "Why not RAG / a vector database over the code?"

**Headline:** different unit. RAG searches *code*; `lore` captures *what your team learned working on the code*.

**On stage:**
> *"RAG over a repo tells you what's in `webhook_handler.py`. It won't tell you that two months ago you tried adding a global lock there, rejected it because it slowed staging 3x, and decided to dedupe on the Stripe idempotency key. That decision wasn't in the code — it was in a session that didn't end up merged. RAG can't see it. lore captures the reasoning side. RAG over a lore-augmented repo gives you both layers."*

**The reasoning:** code is the *answer*; the sessions that *produced* the answer carry all the deliberation, false starts, and decisions. RAG indexes answers. `lore` indexes deliberations.

**Honest concession.** For "find the relevant function" → RAG. For "what did we learn last time we touched this?" → different unit. Complementary, not competing.

### "Why not use [generic memory framework]?"

**Headline:** those are personal memory layers for one developer; `lore` is a team knowledge layer.

(Answer the *category*, not the product. Names of specific tools don't appear in our materials — see the project rule.)

**On stage:**
> *"Most agent-memory tools store an individual developer's working memory across their own sessions: skills, preferences, working set. That's personal continuity. lore is at a different scope — team-shared, across developers, across harnesses, in the repo. Different unit, different lifetime, complementary."*

**Honest concession.** These tools solve real problems and compose with `lore`. We're not replacing personal memory; we're filling a different gap.

### "What's the realistic cost?"

**Per-session compile with Sonnet 4.6 on a 30–45 min session: ~$0.20.** Incremental — only new sessions cost anything. A 10-dev team doing ~50 signal-bearing sessions per week ≈ **$10/week**.

BYO key — `lore` doesn't take a cut because there's no `lore` service.

For cost-conscious teams, Haiku currently needs a prompt-trailer fix to work reliably at long context (tracked); after that, ~$0.05/session.

### "What if the LLM extracts a wrong claim?"

Three layers of defense:

1. **Verbatim anchors.** Every claim's citation must resolve verbatim against the transcript at extraction time. Hallucinated quotes get dropped at the fidelity gate. (Real-data runs: 100% fidelity.)
2. **Actuation loop.** Claims overridden in real use are flagged and retired. Wrongness from real use is the strongest signal — better than any pre-screen.
3. **Human review gate (next to ship).** Approve-before-serve, like PR review for knowledge. Today: secret scrubbing is automated; claim approval is git-PR-review.

**Honest concession.** Sensitive deployments should wait for the explicit review step. For most teams, anchors + git PR-review is enough.

### "Can someone forge a transcript and inject fake claims?"

The integrity boundary is the *agent runtime + your local filesystem*. If an attacker has write access to `~/.claude/projects/`, they can forge transcripts — same as forging code in your repo. `lore` inherits whatever trust model your repo already has.

The threat model `lore` *does* meet: a well-meaning but wrong claim doesn't propagate silently — it has an anchor a reviewer can check, and the actuation loop retires it if real use overrides it.

**Honest concession.** Not a cryptographic provenance system. For regulated environments, signing transcripts at write time is the right addition — future work.

### "Will this work with Bedrock / Vertex / a local model?"

Yes — provider abstraction. The extractor takes a `complete(prompt) → str` callable. Built-in clients handle Anthropic and OpenAI; Bedrock/Vertex/local is wiring a new client (small).

Quality tracks the model. Sonnet 4.6 handles long-context structured extraction well; smaller/older models may need prompt adjustments (the Haiku case is documented in the roadmap).

### "What about merged PRs / successful outcomes as a signal?"

Roadmap. Natural extension: when a session's resulting PR is merged, the claims about decisions/procedures from that session get an authority boost via the existing influence channel in the actuation loop. The signal is there; the PR-merge → claim-reinforcement wiring isn't.

### "Doesn't compiled knowledge go stale when the code changes underneath it?"

The actuation loop catches two failure modes (unused, contradicted-in-use). It doesn't yet catch silent drift — a claim whose anchor used to point at `webhook.py:88` but the file was refactored.

This is a real gap. Roadmap: an "anchor freshness" pass that re-verifies anchors against current code state on a cadence, flags broken ones. For now: when you refactor heavily, re-run `lore compile` to surface new claims; broken anchors will be visible in the diff.

### "Why local-first specifically? Why does that matter?"

**Headline:** trust + portability.

**On stage:**
> *"Compiled team knowledge is one of the most sensitive artifacts a codebase produces — it's the team's accumulated working memory, including 'we tried X, it failed because…' kinds of statements. That's harder to send to a third-party SaaS than the code itself. Local-first means no legal review for adoption, no provider you depend on, no cloud lock-in. And it composes with how teams already work — code in git, knowledge alongside it."*

The deeper point: regulated/IP-sensitive teams (the security-conscious cohort that won't ship codebase context anywhere) can adopt `lore` without an architecture-review meeting. That's the wedge.

---

## What this doc isn't

- Not a public FAQ. Public FAQ goes in `README.md` or `docs/` with positive framing, no competitor comparisons, no "vs X" energy. This doc is for understanding and stage prep.
- Not a marketing doc. The "honest concession" sections are real concessions — if a question lands cleanly because the alternative is a fit, say so on stage. Honesty about boundaries reads as confidence; over-defending the moat reads as desperation.
- Not exhaustive. Add to it as new sharp questions surface — that's the value of having a living doc.

## How to use it on the night

1. Skim the quick-answer table day-of. Internalize the headline + one-liner for each.
2. Drill the deep dives for the 3 most likely questions for your audience. For AI Tinkerers Seattle: **changelog · CLAUDE.md · cost** are the most probable.
3. If a question outside this list comes up: answer in the same shape — *headline + reasoning + honest concession*. The pattern is the message.
