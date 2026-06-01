# Anchors and the fidelity contract

What "verbatim anchor" means in `crewlore`, exactly. This is the trust contract the project's central claim rests on.

## The claim

Every compiled claim carries one or more **anchors** — `(source_kind, ref, quote)` tuples — that cite where in the source session the claim was learned. The contract:

> A claim's anchor `quote`, after **canonical-form normalization**, must resolve as a substring of the claim's source session's content, after the same normalization. Claims with no surviving anchor are dropped at extraction time.

This is enforced at the *fidelity gate* inside `LLMExtractor.extract`: any claim whose anchors don't canonically resolve gets rejected before it ever enters the store.

## What canonical-form normalization does

The canonical form (see `lore.compile.extractor._canonical_form`) applies exactly three transformations, in order:

| # | Transformation | Why |
|---|---|---|
| 1 | **Strip Markdown decoration markers** (`` ` ``, `*`, `_`) | Agent prose in transcripts is Markdown — backticks around identifiers, `**bold**` for emphasis, `_italic_` occasionally. Models intuitively drop these when quoting (they're presentation, not content). Both sides must drop them to compare semantic content. |
| 2 | **Collapse whitespace** (any run of spaces/tabs/newlines → single space) | A long agent reply may be split across NSF events by intervening tool calls. The model rightly quotes the continuous prose as a human reads it; whitespace collapse makes cross-event-boundary spans match. |
| 3 | **Lowercase** | Case is presentation, not content. Lowercasing prevents the model's occasional capitalization variance from killing legitimate quotes. |

## What canonical-form normalization does NOT do

These are *deliberately* preserved, so the gate stays strict against content drift:

- **Ordinary punctuation** (`. , : ; ? ! ( ) [ ] { } " '`) — stays
- **Word boundaries** — no stemming, no synonym substitution, no stopword removal
- **Token ordering** — a stitch of disjoint substrings out of order will fail
- **Semantically-meaningful words** — substituting `Postgres` for `DynamoDB` is content drift, not presentation; the gate rejects it

The result: the gate accepts *presentation* variance and rejects *content* drift. Fabricated content, paraphrased content, dropped meaningful words, or out-of-order stitching all still fail.

## What's in the fidelity haystack

When the extractor verifies an anchor, the haystack it compares against is built from the session's content, with one specific exclusion:

> The haystack joins the `content` field of every NSF event in the session, **except `tool_call` events**, separated by newlines, then runs canonical-form normalization.

`tool_call` events are excluded because their `content` field is the *tool name* (e.g. `"Read"`, `"Bash"`), not session prose. Including them would inject tool names between agent-message spans, breaking quotes that span those events. Tool-call *inputs* live in `meta`, not `content`, so they're not silently lost from the haystack — they're just not where prose-quoting goes.

## Why the gate exists

This is the project's central trust mechanism. Without it:

- A model hallucinating a citation would never get caught
- A team would have no way to trace a claim back to the conversation that produced it
- The compiled book would be claims-shaped fiction

With it:

- Every line in the book has a verifiable citation back to a real session line
- A reviewer can spot-check any claim by reading the cited content
- A team builds trust in the compiled artifact incrementally

The gate is strict on content (correctness) and tolerant on presentation (Markdown). That's a deliberate, defensible contract.

## Adversarial tests

The spec is pinned down by tests in `tests/unit/test_extractor.py`. Each test pairs a deliberate variation with the expected behavior:

| Test | Variation | Expected |
|---|---|---|
| `test_fidelity_accepts_markdown_decoration_difference` | Source has `` ` `` and `**`; quote omits them | **Accept** |
| `test_fidelity_accepts_quote_spanning_event_boundaries` | Quote spans agent-message events separated by a tool_call | **Accept** |
| `test_fidelity_rejects_fabricated_quote` | Quote has no overlap with source content | **Reject** |
| `test_fidelity_rejects_quote_with_changed_meaningful_word` | Source says `Postgres`; quote says `DynamoDB` | **Reject** |
| `test_fidelity_rejects_quote_stitching_disjoint_substrings` | Both fragments exist; quote splices them out of order | **Reject** |

Adding a new accepted/rejected case starts with an adversarial test. Changing the canonical form requires changing the docstring and the corresponding tests in lockstep.

## Roadmap — anchor schema redesign (v0.2)

The current "model emits a free-form quote, we verify it appears" architecture has an inherent fragility: every new model behavior is a potential new failure mode. The intended v0.2 redesign:

> Anchors become structured **position pointers** — `Anchor(session_id, event_index, char_range)` — rather than free-form quote strings. The "quote" becomes computed canonical content at that position, not authored by the model.

This eliminates the fidelity gate entirely: the anchor IS a reference into real session content, not a guess the model has to make and we have to verify. The current canonical-form contract becomes unnecessary once anchors are pointers, not strings.

Tracked in the project strategy doc; not in v0.1 scope.
