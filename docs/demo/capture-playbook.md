# Capture playbook — real demo data in ~7 days

How to gather a clean, presentable set of Claude Code sessions on the demo target repo, so we have honest real-data metrics for the conference demo and the README's headline number — and so we discover any bugs `lore` has on real input *before* a live audience does.

## Goal (done-when)

By **June 4**, the demo repo's `.lore/` directory contains:

- [ ] **≥ 6 captured sessions** across **≥ 2 authors** (the multi-user angle is what proves "team knowledge," not just "single-user history")
- [ ] **≥ 8 active compiled claims** spanning at least two scopes
- [ ] **≥ 1 surfaced conflict** (two sessions making different calls about the same question)
- [ ] **Fidelity rate ≥ 95%** on the produced claims
- [ ] **Preventable-rediscovery rate measured** on a held-out session (one of the captured sessions used as the "post-cutoff" replay)
- [ ] **Zero junk claims worse than the median**, or — if any survived — a written note that motivates the human review gate (D2)

## Target repo

`pydantic/pydantic-ai` (or whichever was confirmed). The repo must be public so the demo audience can clone and verify, MIT/Apache-licensed, and have an active issue tracker so the sessions are about real work, not invented problems.

## How to choose tasks (so the data is good)

Pick from **open issues, recent PRs, or first-five-failed-tests** in the repo. Mix shapes:

| Shape of task | Yields | Aim for |
|---|---|---|
| Investigate a bug from an open issue | gotchas + procedures | 2 sessions |
| Add a small feature (touch an existing module) | decisions + style claims | 1–2 sessions |
| Refactor or trace a confusing code path | scope-qualified gotchas | 1 session |
| Review a recent PR / discuss approach | decisions + conflicts (esp. if two of you weigh different options on the same question) | 1–2 sessions |

**Avoid**:
- Trivial "what does this function return" — the signal gate drops these.
- Sessions where you already know the answer — the friction matters.
- Sessions that touch credentials or anything proprietary (this is a public repo; treat it that way).

## Sequencing the sessions (so the multi-user moment lands)

To get a **real conflict surfaced** for the conference demo, you and the collaborator(s) should — independently and without pre-discussion — pick two related issues. E.g., both touch retry behavior, or both involve the same module. Make *different* calls. That's the conflict the demo highlights.

> ⚠ Don't fabricate the disagreement. If you both agree, you both agree — and that's a strong "convergent claims, higher authority" story instead, which is also true to the design.

## Day-by-day plan

### Day 1 — set up (≈ 30 min)

```bash
# 1. Clone the demo repo somewhere clean
gh repo clone pydantic/pydantic-ai ~/demos/pydantic-ai && cd ~/demos/pydantic-ai

# 2. Init lore in it
lore init

# 3. Confirm Claude Code is writing transcripts here:
ls ~/.claude/projects/ | grep pydantic-ai
```

If the project directory doesn't exist yet, open Claude Code once in `~/demos/pydantic-ai` so it registers; then back here.

### Days 2–5 — capture (≈ 30–60 min each)

Do **4–6 real sessions**. Don't try to "perform" — just work the issue. Aim for friction. Each session leaves a `.jsonl` in `~/.claude/projects/-Users-<you>-demos-pydantic-ai/`.

Take a **one-line note per session** of anything you'd want `lore` to capture (a gotcha, a decision, a procedure). We'll cross-check against what it actually extracted on Day 6 — that's the recall check.

### Day 5–6 — collaborator sessions (the multi-user moment)

Ideal: **one collaborator** picks up an issue you didn't, in the same repo, using Claude Code, on their own machine. Their `.jsonl` transcripts ship to you (zip them; gitignored locally; pass over your usual back-channel). You drop them into the local `~/.claude/projects/-Users-<you>-demos-pydantic-ai/` directory before compiling — or compile separately and merge claims.

If a collaborator session isn't possible: you can still claim "multi-author" honestly if the sessions are spaced out enough that they're independent passes, but the demo line is weaker. Strong preference for at least one external session.

### Day 6 — first compile

```bash
cd ~/demos/pydantic-ai
lore watch --once
cat .lore/knowledge/README.md
lore status
```

Inspect carefully:

- **Recall check** — open your one-line session notes. Did `lore` extract each thing you'd want? If something is missing, that's a signal-gate or extractor gap.
- **Precision check** — does any claim feel wrong, hallucinated, or too vague? If so, can you trace its anchor back to a real transcript line?
- **Conflict check** — was at least one disagreement preserved? If not, intentionally seed one (re-do a session with a different choice on the same question).
- **Junk check** — any claim that's confusing or low-value? Note it; this motivates the review gate.

### Day 7 — tune (if needed)

Anything broken or weak on real data gets a small TDD fix. Examples of what we'd expect to need:

- Signal gate too narrow / too wide (already widened once for procedures/style — may need another pass)
- A model output shape we don't parse robustly
- A scope coordinate we keep losing
- A claim category not represented

Anything bigger than a half-day fix gets recorded in the deferred-decision tracker (lab strategy doc §3) and skipped for the demo.

### Day 8 — final compile + replay metric

Hold one session out (don't ingest it). Run replay against the rest:

```bash
# Move one session aside
mv ~/.claude/projects/.../ses-XXXX.jsonl /tmp/holdout.jsonl

# Compile everything else
lore watch --once

# Manually replay the holdout: did its content match a prior claim?
# (we'll write a small helper for this if it's not already wired)
```

The number you get is the headline metric for the demo and the README.

## Privacy guard rails (even on a public repo)

This is a public repo, but Claude Code transcripts can still contain accidental leaks (a pasted env line, a copied URL from another tab, a stray file path from your machine). Before publishing or showing any compiled output:

- [ ] Scan the `.lore/claims/claims.jsonl` for any string that doesn't look like it belongs in a pydantic-ai discussion.
- [ ] Anchors are verbatim — open each one and confirm it's about pydantic-ai code, not about your machine.
- [ ] If any redaction is needed, prefer **dropping the claim** over editing it (editing breaks the anchor contract).

## What we expect to learn (the "test on real data before prod" payoff)

Before the conference we want explicit answers to:

1. Does the signal gate's recall hold on a real codebase, or do meaningful sessions get gated out?
2. Does conflict detection actually surface real disagreements when the scope/topic coordinates drift across sessions?
3. How noisy is the extractor on real transcripts vs the polished synthetic ones — i.e. what % of claims would we be embarrassed to ship?
4. What's the realistic time/cost per compile of ~10 sessions?
5. Does the actuation-loop pruning behave reasonably over a real (not synthetic) week of activity?

Each answer feeds either a small TDD fix or an entry in the deferred-decision tracker. **Either way, we learn it before the audience does.**
