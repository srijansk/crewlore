"""LLMExtractor turns a session's NSF events into candidate claims via a model.
The model is injected as a `complete(prompt) -> str` callable, so extraction —
prompt assembly, JSON parsing, and the verbatim-anchor fidelity gate — is tested
deterministically without any network call.
"""

import json
from datetime import datetime, timezone

from lore.compile.extractor import LLMExtractor
from lore.schemas import NSFEvent

EVENTS = [
    NSFEvent(
        session="ses_1", actor="user", kind="user_message",
        timestamp=datetime(2026, 5, 19, 10, 0, tzinfo=timezone.utc),
        content="the billing webhook fires twice in staging",
    ),
    NSFEvent(
        session="ses_1", actor="agent", kind="agent_message",
        timestamp=datetime(2026, 5, 19, 10, 1, tzinfo=timezone.utc),
        content="Right, dedupe on the idempotency key.",
    ),
]


def _one_claim_response(quote):
    return json.dumps(
        [
            {
                "statement": "Dedupe billing webhooks on idempotency key.",
                "kind": "gotcha",
                "scope": "services/billing",
                "topic": "webhook-dedupe",
                "action": "Dedupe on idempotency key before processing.",
                "anchors": [{"source_kind": "transcript", "ref": "ses_1#t1", "quote": quote}],
            }
        ]
    )


def test_builds_claim_from_llm_json_with_provenance_and_time():
    extractor = LLMExtractor(lambda prompt: _one_claim_response("fires twice in staging"))
    claims = extractor.extract(EVENTS, "ses_1")
    assert len(claims) == 1
    c = claims[0]
    assert c.kind == "gotcha"
    assert c.scope == "services/billing"
    assert c.topic == "webhook-dedupe"
    assert c.action == "Dedupe on idempotency key before processing."
    assert c.provenance.session == "ses_1"
    # observed_at is the latest event timestamp in the session.
    assert c.observed_at == datetime(2026, 5, 19, 10, 1, tzinfo=timezone.utc)


def test_rejects_claim_whose_anchor_is_not_verbatim_in_transcript():
    # Fidelity gate: an anchor that doesn't resolve verbatim is a defect, so the
    # claim is dropped rather than admitted with a fabricated citation.
    extractor = LLMExtractor(lambda prompt: _one_claim_response("this text never appeared"))
    claims = extractor.extract(EVENTS, "ses_1")
    assert claims == []


def test_malformed_llm_output_yields_no_claims():
    extractor = LLMExtractor(lambda prompt: "sorry, I can't do that")
    assert extractor.extract(EVENTS, "ses_1") == []


def test_invalid_kind_is_skipped_not_crashed():
    bad = json.dumps(
        [
            {
                "statement": "x", "kind": "rumor", "scope": "a",
                "anchors": [{"source_kind": "transcript", "ref": "r", "quote": "fires twice"}],
            }
        ]
    )
    extractor = LLMExtractor(lambda prompt: bad)
    assert extractor.extract(EVENTS, "ses_1") == []


def test_handles_fenced_json_response():
    # Real models (e.g. Haiku) wrap the array in ```json ... ``` fences.
    inner = _one_claim_response("fires twice in staging")
    fenced = f"```json\n{inner}\n```"
    claims = LLMExtractor(lambda prompt: fenced).extract(EVENTS, "ses_1")
    assert len(claims) == 1


def test_handles_fenced_json_with_brackets_in_surrounding_prose():
    # Real-data failure mode: a model returns prose before/after the fenced
    # array containing its own [ or ] (e.g. "[Note]", "(see [42])"). The
    # outermost-bracket-span fallback breaks in that case; fence extraction
    # must take precedence.
    inner = _one_claim_response("fires twice in staging")
    noisy = (
        "Here is my analysis [based on the transcript].\n"
        f"```json\n{inner}\n```\n"
        "Let me know if you want changes [details available]."
    )
    claims = LLMExtractor(lambda prompt: noisy).extract(EVENTS, "ses_1")
    assert len(claims) == 1


def test_handles_prose_wrapped_json_response():
    inner = _one_claim_response("fires twice in staging")
    wrapped = f"Here are the claims I found:\n{inner}\nLet me know if you need more."
    claims = LLMExtractor(lambda prompt: wrapped).extract(EVENTS, "ses_1")
    assert len(claims) == 1


def _claim_with_quote(quote: str, statement: str = "Some fact."):
    return json.dumps([
        {
            "statement": statement,
            "kind": "gotcha",
            "scope": "tools/approval",
            "anchors": [{"source_kind": "transcript", "ref": "agent", "quote": quote}],
        }
    ])


# ──────────────────────────────────────────────────────────────────────────
# Fidelity-gate contract tests. These pin down what "verbatim anchor" means:
#
#   ACCEPTED — presentation differences (Markdown decoration, whitespace,
#              case, cross-event-boundary spans) do NOT invalidate a quote.
#   REJECTED — content differences (fabrication, paraphrase, dropped or
#              substituted meaningful words, stitched disjoint substrings)
#              DO invalidate a quote.
#
# The canonical form that defines this contract is `_canonical_form` in
# extractor.py — see its docstring for the precise transformations.
# ──────────────────────────────────────────────────────────────────────────


def test_fidelity_accepts_markdown_decoration_difference():
    """Source has backticks and bold; model's quote drops them. Same content."""
    events = [
        NSFEvent(
            session="s", actor="agent", kind="agent_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content="`ApprovalRequiredToolset.call_tool` — **in the workflow** "
                    "(checks `ctx.tool_call_approved`, raises `ApprovalRequired`).",
        ),
    ]
    raw = _claim_with_quote(
        "ApprovalRequiredToolset.call_tool — in the workflow "
        "(checks ctx.tool_call_approved, raises ApprovalRequired)."
    )
    claims = LLMExtractor(lambda p: raw).extract(events, "s")
    assert len(claims) == 1


def test_fidelity_accepts_quote_spanning_event_boundaries():
    """A long agent reply punctuated by a tool_call splits into separate NSF
    events. The model rightly quotes the continuous prose as a human reads it;
    the haystack reflects session content, not prompt-formatting markers."""
    spanning = [
        NSFEvent(
            session="s", actor="agent", kind="agent_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content="Architecture facts: the toolset hierarchy is",
        ),
        NSFEvent(
            session="s", actor="agent", kind="tool_call",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content="Read", meta={"input": {}},
        ),
        NSFEvent(
            session="s", actor="agent", kind="agent_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content="ApprovalRequiredToolset wrapping the temporalized leaf.",
        ),
    ]
    raw = _claim_with_quote(
        "Architecture facts: the toolset hierarchy is "
        "ApprovalRequiredToolset wrapping the temporalized leaf."
    )
    claims = LLMExtractor(lambda p: raw).extract(spanning, "s")
    assert len(claims) == 1


def test_fidelity_rejects_fabricated_quote():
    """Quote has no overlap with source content. Hard reject."""
    events = [
        NSFEvent(
            session="s", actor="agent", kind="agent_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content="The Vercel adapter drops metadata on round-trip.",
        ),
    ]
    raw = _claim_with_quote("The fabrication that never appeared in the session.")
    claims = LLMExtractor(lambda p: raw).extract(events, "s")
    assert claims == []


def test_fidelity_rejects_quote_with_changed_meaningful_word():
    """Source says 'Postgres'; the would-be quote says 'DynamoDB'. A meaningful
    word change is content drift, not presentation. Reject."""
    events = [
        NSFEvent(
            session="s", actor="agent", kind="agent_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content="We decided to use Postgres for the ledger service.",
        ),
    ]
    raw = _claim_with_quote("We decided to use DynamoDB for the ledger service.")
    claims = LLMExtractor(lambda p: raw).extract(events, "s")
    assert claims == []


def test_fidelity_rejects_quote_stitching_disjoint_substrings():
    """Both fragments exist in source — but the quote splices them in the wrong
    order. Stitching disjoint, out-of-order substrings is fabrication. Reject."""
    events = [
        NSFEvent(
            session="s", actor="agent", kind="agent_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content="The webhook fires twice in staging. "
                    "Separately, the ledger uses Postgres.",
        ),
    ]
    raw = _claim_with_quote("The ledger uses Postgres webhook fires twice")
    claims = LLMExtractor(lambda p: raw).extract(events, "s")
    assert claims == []


def test_prompt_includes_known_topics_for_reuse():
    captured = {}

    def rec(prompt):
        captured["p"] = prompt
        return "[]"

    LLMExtractor(rec).extract(EVENTS, "ses_1", known_topics=["ledger-db", "webhook-dedupe"])
    assert "ledger-db" in captured["p"]
    assert "webhook-dedupe" in captured["p"]


def test_prompt_carries_the_transcript_text():
    captured = {}

    def recording_complete(prompt):
        captured["prompt"] = prompt
        return "[]"

    LLMExtractor(recording_complete).extract(EVENTS, "ses_1")
    assert "fires twice in staging" in captured["prompt"]
    assert "idempotency key" in captured["prompt"]
