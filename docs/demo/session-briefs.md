# Session briefs

Per-issue cheat sheets for the minimum-viable 4 sessions. Each brief gives you:

- **What's actually broken** in plain English — no pydantic-ai expertise required
- **The suggested prompt** to open Claude Code with (paraphrase, don't paste)
- **What the session should land on** — the conclusion to drive toward
- **Predicted claims** — specific things `lore` *should* extract from this session, written so you can grade output mechanically (✓ found / ✗ missing / ◐ partial) without needing to understand pydantic-ai deeply

After each session, jot one line per predicted claim: yes/no/partial. That's the recall check on Day 6 — you don't need to evaluate the *correctness* of pydantic-ai claims, only whether `lore` captured the shape of what your session worked on.

---

## G1 — #5679 · Vercel AI adapter drops `TextContent.metadata`

### What's actually wrong (plain English)

pydantic-ai supports passing messages between different "frontends" (Vercel AI, AG-UI, etc.) by serializing them into each frontend's format and back. Some messages carry extra metadata (e.g. "this text came from MCP server X, part ID `abc123`") in a field called `metadata`. When messages round-trip through the **Vercel AI adapter** (`dump` then `load`), the **metadata is silently dropped** — the text survives, the metadata is gone. Same bug exists in the **AG-UI adapter**.

Two specific lines named in the issue:
- `pydantic_ai/ui/vercel_ai/_adapter.py:883` — the dump path only copies `content`, not `metadata`
- `pydantic_ai/ui/vercel_ai/_adapter.py:323` — the load path rebuilds a plain string instead of restoring the `TextContent` wrapper

### Suggested prompt to open Claude Code with

> "There's a bug in pydantic-ai where rich text metadata is silently dropped when messages go through the Vercel AI adapter's round-trip — `dump_messages` followed by `load_messages` loses the `metadata` field on `TextContent`. Help me trace the data path through `pydantic_ai/ui/vercel_ai/_adapter.py`. I want to understand exactly *where* the metadata is lost — both the dump side and the load side — before we talk about fixing it. The same shape of bug exists in the AG-UI adapter too."

### What the session should land on

A clear understanding that:
- The dump path (`_convert_user_prompt_part`) doesn't carry `metadata` onto the Vercel-format part at all
- Even if dump did carry it, the load path makes a plain `str`, not a `TextContent` wrapper — so the metadata has nowhere to come back to
- **Both sides need fixes**; fixing just one is incomplete
- The bug repeats in the AG-UI adapter — same shape, same root cause — which suggests there's no shared round-trip contract / test for adapters

(You don't need to actually write the fix. You need to *understand and articulate* the loss path.)

### Predicted claims to check on Day 6

| | Claim shape | Grade |
|---|---|---|
| 1 | **[gotcha]** — `_convert_user_prompt_part` in the Vercel adapter copies `content` but discards `metadata`. Anything carrying metadata on a TextContent loses it at dump. | |
| 2 | **[gotcha]** — `load_messages` rebuilds a plain string instead of restoring the `TextContent` wrapper, so the metadata round-trip is broken on both sides. | |
| 3 | **[procedure]** — When adding or modifying a UI adapter, add a `load(dump(x)) == x` round-trip test for every content type that carries metadata. (Implied by the repeated bug in AG-UI.) | |

---

## G3 — #5358 · `takes_run_context()` silently swallows NameError

### What's actually wrong (plain English)

When a user registers a "history processor" function with pydantic-ai, there's a helper that tries to figure out: *does this function expect a `RunContext` argument or not?* The helper reads the function's type hints. **But:** modern Python idioms (`from __future__ import annotations` + `if TYPE_CHECKING: from pydantic_ai import RunContext`) make `RunContext` invisible at runtime — so resolving the hints raises `NameError`. The helper silently catches that error and returns `None`, which the caller interprets as "no, doesn't need context." The processor then gets dispatched without its `ctx` argument and **crashes on every single invocation** with `TypeError: missing required positional argument`.

The issue author had this take down production for ~58 minutes; the fix once diagnosed was a one-line import lift. Three options proposed: warn on swallow, add `strict=` opt-in, or fail-fast at registration.

### Suggested prompt to open Claude Code with

> "There's a silent-failure bug in pydantic-ai's `takes_run_context()` helper at `pydantic_ai/_utils.py:497-550`. When a user-supplied function uses `from __future__ import annotations` and imports `RunContext` only under `if TYPE_CHECKING:`, the helper returns False (wrong) because the underlying type-hint resolution raises `NameError` and a broad `except` swallows it. The user's processor then crashes on first invocation. Help me read the code and understand: (1) the silent swallow at `get_first_param_type`, (2) why returning `None` propagates to the wrong dispatch branch, (3) what the three proposed fixes (warn / strict opt-in / fail-fast at registration) buy us. I want to take a position on which fix, not just summarize."

### What the session should land on

- A confident articulation of why the symptom (TypeError at first invocation) is so far from the cause (a type-hint resolution swallowed silently at registration)
- A position on which of the three proposed fixes is right. The defensible answer is **emit a warning** (cheapest, non-breaking, gives users a deploy-time signal pointing at the unresolvable annotation); the `strict=` opt-in is the cleanest API but a bigger surface change
- An understanding that the broader anti-pattern here is **silent-fallback-on-introspection-failure** — a general lesson, not just a one-off bug

### Predicted claims to check on Day 6

| | Claim shape | Grade |
|---|---|---|
| 1 | **[gotcha]** — `get_first_param_type` in `_utils.py` swallows `(NameError, TypeError, AttributeError)` and returns `None`, causing `takes_run_context()` to return False for any processor where `RunContext` is imported under `TYPE_CHECKING:`. | |
| 2 | **[decision]** — When type-introspection can't resolve an annotation, warn-and-return-None is preferable to silent-return-None; the failure must be diagnosable at registration time, not at first invocation. | |
| 3 | **[procedure]** — Decorator helpers that branch on type-introspection should fail loudly (or warn) when introspection fails, never silently choose a default that pushes the cost to runtime. | |

---

## D1 — #5536 · HITL approval is a plain `bool` — narrow vs proper fix

### What's actually wrong (plain English)

pydantic-ai supports **human-in-the-loop** (HITL) approval for tool calls — e.g. "this tool charges a credit card; pause and ask a human before running it." The approval signal is a plain `bool` field called `tool_call_approved` on the run context. In a single-process run, this is fine — only the deployer's code can flip the flag. But when running across **durable-execution boundaries** (Temporal), the whole run context is serialized as JSON and shipped between activities, including this bool. Anyone with privileged write access to the Temporal cluster's event history can flip `False` → `True`, forging an approval. Not a CVE (privileged access required), but a defense-in-depth weakness on a Tier-1 feature.

The issue **explicitly proposes two approaches**:

- **Narrow fix (~3 LOC + docs):** drop the field from the wire entirely; `tool_manager.py` already re-derives it per call from `DeferredToolResults`, so behavior is mostly unchanged. Only deployers who read the field directly in their tool bodies see a change.
- **Proper fix (~150–300 LOC, breaking):** replace the bool with an HMAC-signed token containing `(run_id, tool_call_id, expiry)`; issue on raise, verify on resume. Done in a major version bump.

### Suggested prompt to open Claude Code with

> "There's an open design question in pydantic-ai (#5536) about hardening the human-in-the-loop tool-approval signal. Currently `ctx.tool_call_approved` is a plain `bool` and ships across Temporal durable-execution boundaries unsigned — privileged attackers with Temporal event-history write access can forge approvals. The issue proposes two fixes: **narrow** (drop the field from the wire, ~3 LOC) and **proper** (HMAC-signed token replacing the bool, ~150–300 LOC, breaking). Help me think this through. Read the relevant code (`pydantic_ai/_run_context.py`, `pydantic_ai/durable_exec/temporal/_run_context.py`, `pydantic_ai/toolsets/approval_required.py`), then I want to land on a position with reasoning — not just summarize both options."

### What the session should land on

A definite recommendation with reasoning. The most defensible position is **ship the narrow fix in v1.x, track the HMAC-token approach for v2.x** — rationale: narrow is ~3 LOC and non-breaking, `tool_manager` already re-derives the flag, and the in-process default works fine. The "proper" version is the right long-term shape but doesn't justify v1.x breakage given the residual risk only manifests under privileged Temporal cluster access.

If you find yourself drawn to the opposite conclusion (HMAC token now, breaking is justified), commit to that and own the reasoning. The point is to take a clear position. **Don't end the session undecided** — the demo's "conflict moment" only works if your conclusion is firm.

### Predicted claims to check on Day 6

| | Claim shape | Grade |
|---|---|---|
| 1 | **[decision]** — In `tools/approval` (or `durable_exec/temporal`): use the narrow fix (drop `tool_call_approved` from the serialized payload) for v1.x; track HMAC-signed token for v2.x. **Note: this is the predicted shape if you lean narrow. If you lean proper, the predicted [decision] flips — that's the conflict moment if D2/colleague reaches the opposite.** | |
| 2 | **[gotcha]** — `TemporalRunContext.serialize_run_context` ships approval state across activity boundaries as plain JSON; anyone with privileged Temporal event-history access can forge approvals. Approval-gating fields in run-context are adversarial across activity boundaries by default. | |
| 3 | **[procedure]** — When adding a security-relevant flag to the durable-exec wire format, audit whether the value can be re-derived from authoritative state on the receiving side; if so, don't ship it on the wire. | |

---

## D2 — #5617 · `requires_approval` should accept a callable

### What's actually wrong (plain English)

Today the `requires_approval` parameter on `@agent.tool` is a boolean: either every call needs approval or none do. Users want **conditional** approval — e.g. "ask for approval only if `amount > 1000`." The current workaround is to override `wrap_tool_execute` in a capability class, which is awkward: it hardcodes the tool name, runs for every tool call, and lives in a file separate from the tool itself.

The proposal: allow `requires_approval` to also accept a callable `(ctx, args) → dict | None` — returning `None` means "run normally," returning a `dict` means "require approval, with this metadata for the approver." Clean, predicate-next-to-tool, only runs when scheduled.

### Suggested prompt to open Claude Code with

> "There's an open feature request in pydantic-ai (#5617) to extend `requires_approval` on `@agent.tool` to accept a callable in addition to a bool — for per-tool conditional approval based on validated arguments (e.g. 'approve only if amount > 1000'). Read the issue carefully and the relevant code (`pydantic_ai/toolsets/approval_required.py`, the existing `wrap_tool_execute` capability mechanism in `pydantic_ai/capabilities/`), then help me think through: (1) is the proposed API right? (2) what corner cases does it need to handle — sync vs async predicates, predicates that raise, predicates with side effects? (3) what's the relationship to the existing `wrap_tool_execute` capability — does this duplicate it, deprecate it, or complement it? I want to land on a position on the API, not just paraphrase the proposal."

### What the session should land on

A position on the API shape, engaging with:
- **Sync and async predicates** — both should be supported (the proposal already does this with `Awaitable[...]` in the type signature)
- **Predicate exceptions** — should propagate (silent fall-back to "approval required" would hide bugs in the predicate)
- **Metadata return shape** — `dict` is convenient but a typed object (`ApprovalRequest`?) would be more discoverable
- **Relationship to `wrap_tool_execute`** — the callable form covers the common case; capabilities stay for genuinely cross-cutting concerns. Not duplication, not deprecation — complementary

A defensible recommendation: **accept the proposal essentially as written**; refine the return-shape question (dict vs typed object) in implementation review; make explicit that predicate exceptions propagate unchanged.

### Predicted claims to check on Day 6

| | Claim shape | Grade |
|---|---|---|
| 1 | **[decision]** — In `tools/approval`: extend `requires_approval` to accept a callable returning `dict | None | Awaitable[...]`. Keep the bool form. The capability `wrap_tool_execute` mechanism stays for genuinely cross-cutting cases. | |
| 2 | **[procedure]** — Predicates passed to `requires_approval` should propagate exceptions, not be silently coerced into "approval required" — silent fallback hides predicate bugs. | |
| 3 | **[gotcha]** — The `wrap_tool_execute` workaround pattern (hardcoded tool-name check inside a capability) is brittle: breaks silently on tool rename and adds latency to every tool call. Don't use it for per-tool conditional approval once the callable form ships. | |

---

## About the "conflict moment" — be honest

Reading D1 and D2 carefully, they're **both about tool approval but answer different questions** — D1 is about wire integrity, D2 is about per-tool predicate flexibility. They produce *related* claims in the same scope but not directly *contradicting* ones. Whether `lore` flags them as a conflict depends on whether the model assigns overlapping topic keys.

The cleanest way to **guarantee** a conflict surfaces on stage:

- Do **D1 with a "narrow-fix lean"** (you, Day 2)
- Have someone else (or you, Day 4, deliberately framed differently) do **D1 again with a "proper-fix lean"**

Two sessions, same question (`#5536: narrow vs proper`), opposite conclusions. Same scope + same topic → guaranteed conflict in the compiled book. That's the data the demo wants.

If that's too contrived, plan B is: do G1, G3, D1, D2 as written, see what `lore` produces on Day 6, and decide whether to capture a 5th deliberate-conflict session if the natural pair doesn't fire. We'll have honest data either way — and "two sessions converged on the same answer with different reasoning" is also a legitimate (if less dramatic) story.

---

## Recall-check shortcut

After all sessions are captured and compiled, you don't need to re-read pydantic-ai's codebase to grade `lore`. Just:

1. Open `.lore/knowledge/README.md`
2. For each predicted claim in this file, scan the book for a claim that captures the same shape (don't worry about exact wording)
3. Mark ✓ / ✗ / ◐ in the tables above

If `lore` is producing claims you *didn't* predict, that's also data — note them as "unpredicted" and we'll look at whether they're real signal or noise. Noise → motivates the review gate (D2 in the strategy doc). Real signal → great, the system is doing more than we asked.
