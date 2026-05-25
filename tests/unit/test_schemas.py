from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from lore.schemas import Anchor, Claim, Provenance


def _claim(**overrides):
    base = dict(
        statement="Dedupe billing webhooks on idempotency key.",
        kind="gotcha",
        scope="services/billing",
        provenance=Provenance(session="ses_1", author="alice", harness="claude-code"),
        anchors=[
            Anchor(
                source_kind="transcript",
                ref="ses_1#turn-42",
                quote="the webhook fires twice in staging",
            )
        ],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return Claim(**base)


def test_claim_id_is_content_addressed_and_prefixed():
    claim = _claim()
    assert claim.id.startswith("clm_")


def test_same_content_yields_same_id():
    a = _claim()
    b = _claim(provenance=Provenance(session="ses_99", author="bob", harness="cursor"))
    # Provenance differs, but identity is (kind, scope, statement) -> same claim.
    assert a.id == b.id


def test_different_statement_yields_different_id():
    a = _claim()
    b = _claim(statement="Always run migrations before deploy.")
    assert a.id != b.id


def test_statement_normalization_is_stable_across_whitespace_and_case():
    a = _claim(statement="Dedupe billing webhooks on idempotency key.")
    b = _claim(statement="  dedupe   Billing webhooks on idempotency KEY.  ")
    assert a.id == b.id


def test_claim_kind_must_be_valid():
    with pytest.raises(ValidationError):
        _claim(kind="nonsense")


def test_anchor_quote_must_be_nonempty():
    # A claim's anchor is its verbatim fidelity guarantee; an empty quote is a defect.
    with pytest.raises(ValidationError):
        Anchor(source_kind="transcript", ref="ses_1#turn-1", quote="   ")


def test_actuation_fields_default_to_zero_usage_and_active_status():
    # C0: every claim carries the actuation loop's state from birth.
    claim = _claim()
    assert claim.status == "active"
    assert claim.action is None
    assert claim.usage.times_served == 0
    assert claim.usage.times_influential == 0
    assert claim.usage.times_overridden == 0
    assert claim.usage.last_served_at is None


def test_authority_and_confidence_default_and_are_bounded():
    claim = _claim()
    assert 0.0 <= claim.authority <= 1.0
    assert 0.0 <= claim.confidence <= 1.0
    with pytest.raises(ValidationError):
        _claim(confidence=1.5)
    with pytest.raises(ValidationError):
        _claim(authority=-0.1)


def test_topic_defaults_none_and_does_not_change_identity():
    # topic groups claims for conflict detection; it must not change the
    # content-addressed id (else dedup across sessions would break).
    a = _claim()
    b = _claim(topic="dedupe-strategy")
    assert a.topic is None
    assert b.topic == "dedupe-strategy"
    assert a.id == b.id


def test_json_round_trip_preserves_id_and_fields():
    claim = _claim(action="Dedupe on idempotency key before processing.")
    restored = Claim.model_validate_json(claim.model_dump_json())
    assert restored == claim
    assert restored.id == claim.id
    assert restored.action == "Dedupe on idempotency key before processing."
    assert restored.anchors[0].quote == "the webhook fires twice in staging"
