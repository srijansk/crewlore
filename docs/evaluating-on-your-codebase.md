# Evaluating `crewlore` on your own codebase

How to capture a meaningful set of Claude Code sessions on a real repo, compile them with `crewlore`, and decide whether the output is good enough to adopt. Built around the same loop used for the [pydantic-ai example](examples/pydantic-ai/) — concrete enough to follow, generic enough to apply to any repo.

## Goal

By the end of this guide, you have a real `.lore/knowledge/` book compiled from ~4–6 of your own Claude Code sessions on a real codebase, every claim with a verifiable anchor, and a clear personal answer to "is this worth committing to in our team's workflow."

## Pick a target repo

The cleanest evaluation runs on a codebase where:

- You're **doing real work** (not synthetic exercises). Real friction is what produces real claims; play-acting produces empty sessions.
- The repo has **active issues or recent PRs** — pick from those. Investigating a real bug yields a `gotcha`; deliberating a real design choice yields a `decision`.
- You'll generate **multiple sessions** over the evaluation window (a few days). One session demonstrates the mechanism; several demonstrate the multi-session synthesis.

If you want a public, low-stakes target to evaluate first, any moderately active open-source library you know well will do. The pattern is the same.

## What kind of sessions yield good claims

Aim for a mix; the diversity is what makes the compiled book look like real team knowledge instead of a single-purpose log:

| Session shape | Yields | Notes |
|---|---|---|
| Investigate a bug in an open issue | gotchas, procedures | Real friction. Push back on the agent when it goes wrong direction — your corrections become the gotchas. |
| Discuss adding a small feature | decisions, style claims | Make the design call, don't just have the agent write code. |
| Trace a confusing code path | scope-qualified gotchas | "Why does X work this way" produces clear, citable observations. |
| Review a recent PR or approach choice | decisions; cross-session conflicts | If two of you reach different positions on the same question, the conflict mechanism surfaces it. |

Avoid:

- **Trivial Q&A** ("what does this function return?"). The signal gate drops these by design.
- **Sessions where you already knew the answer.** Friction produces the signal.

## Capture procedure

### Day 1 — set up (~5 min)

```bash
cd path/to/your-repo
lore init
```

This creates `.lore/` in the repo. Claude Code automatically writes session transcripts to `~/.claude/projects/<encoded-path>/` whenever you work in this directory — no hook needed.

### Days 2–N — work (≈ 30–60 min per session)

Open Claude Code in the repo. Work the problem. **Engage** — ask, push back, weigh options, reach a position. Don't passively let the agent run; the value `crewlore` extracts is in the friction.

After each session, note (one line in your own notebook) what you'd expect `lore` to capture from it. We'll cross-check on compile day.

A useful target: **4–6 sessions across at least 2 distinct areas of the codebase**, so the resulting book has scope diversity. If you want a real cross-session conflict to surface, deliberately pick two related issues you and a colleague work independently with different framings — the conflict mechanism only flags claims sharing `(scope, kind, topic)` from ≥2 distinct sessions.

### Compile day

```bash
export ANTHROPIC_API_KEY=...
lore compile
```

This ingests new transcripts, scrubs secrets, runs the LLM extractor with the fidelity gate, and writes `.lore/knowledge/README.md` plus `.lore/claims/claims.jsonl`. Cost is ~$0.20 per signal-bearing session with Sonnet 4.6.

Inspect the book:

```bash
cat .lore/knowledge/README.md
```

Or with the CLI:

```bash
lore status                    # claim/conflict/utilization counts
lore query "<your topic>"      # task-conditioned retrieval
```

## Evaluation checks

Walk through these on the compiled output. Each maps to a yes/no decision about whether `lore` is worth keeping:

| Check | What you're looking for |
|---|---|
| **Recall** | Did `lore` capture the things you'd written down in your one-line-per-session notes? If most of your notes match claims in the book, the extractor is reading the sessions usefully. |
| **Precision** | Are the claims it produced actually useful, or noisy/hallucinated? Click into anchors — each should resolve verbatim against the source session (subject to the canonical-form contract in [`anchors.md`](anchors.md)). |
| **Scope grouping** | Does the book's `## scope` structure match how you mentally organize the codebase? If yes, the topic-reuse is working. |
| **Conflicts** | If two sessions disagreed about something, is it visible as a recorded conflict? If they agreed but came at it differently, do the related claims cluster under the same topic? |
| **Noise** | Are there low-value claims that just take up space? These motivate the human review gate (planned; for now lean on git PR-review of the `.lore/claims` diff). |
| **Day-2 inheritance** | Open a fresh Claude Code session on a related topic. Run `lore query` for that topic. Do the relevant claims surface? Paste them into the agent's context — does it act on them on its first turn? This is the actual product value. |

## What surprises to expect (and what they tell you)

When real data exposes weaknesses, they're informative:

- **Few claims compiled** — the signal gate may be too strict for your style, or your sessions may have been mostly trivial Q&A. Re-check session quality before changing the gate.
- **Claims feel generic** — the extractor may be summarizing rather than citing specifics. Look at anchors: are they substantive quotes from the session, or paraphrases? Verbatim anchors are the strict contract; if anchors are paraphrased, something's drifting.
- **Cross-session inheritance doesn't fire** — sessions may be too disjoint in scope. The book is honest about this; it doesn't manufacture connections.
- **A real conflict surfaces** — even one is a strong signal that the team has implicit disagreement worth surfacing.

## Privacy and safety

- **Secrets in transcripts**: the scrubber runs at ingest and redacts API keys, AWS keys, private-key blocks, and `secret/token/password = ...` assignments before anything is stored or sent to a model.
- **Sensitive prose**: the scrubber doesn't catch customer names, internal repo paths, or proprietary discussion that wasn't in a recognizable secret-shape. Before committing `.lore/` to a public repo, scan `claims/claims.jsonl` and the rendered book.
- **Raw sessions**: `.lore/sessions/` (the scrubbed NSF copies) is gitignored by default; only `claims/` and `knowledge/` are intended to be committed.

## When to stop evaluating and decide

After 4–6 sessions and one compile:

- If the book reads as useful team knowledge and the Day-2 inheritance check works on at least one query: **adopt**. Wire `lore watch` into a daily cron or CI, commit `.lore/knowledge/` to the repo, and tell your teammates about the query CLI.
- If the book reads as noisy or hallucinated: file an issue with the specific failure mode — the project is alpha and real-data failures are the most valuable input we receive.
- If the book is fine but underwhelming: capture more sessions for another two weeks. The value compounds; one week of data is mostly mechanism evidence, not value evidence.

## Privacy-conscious teams

For sensitive codebases (regulated industries, IP-heavy work):

1. Review the `claims.jsonl` diff in every PR that compiles new sessions, exactly like reviewing code. The plaintext format makes this practical.
2. Use a local model (configured in `.lore/config.yaml`) instead of a hosted API if your compliance posture forbids sending code context to a third party. Quality tracks the model; Sonnet-class is the current sweet spot.
3. The on-disk format is plaintext + git; no proprietary store; no phone-home. The audit trail is `git log .lore/`.
