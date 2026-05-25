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


def test_prompt_carries_the_transcript_text():
    captured = {}

    def recording_complete(prompt):
        captured["prompt"] = prompt
        return "[]"

    LLMExtractor(recording_complete).extract(EVENTS, "ses_1")
    assert "fires twice in staging" in captured["prompt"]
    assert "idempotency key" in captured["prompt"]
