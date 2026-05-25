from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from lore.schemas import Conflict, NSFEvent


def test_nsf_event_minimal_construction():
    ev = NSFEvent(
        session="ses_1",
        actor="user",
        kind="user_message",
        timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
        content="why does the billing webhook fire twice?",
    )
    assert ev.session == "ses_1"
    assert ev.actor == "user"
    assert ev.refs == []
    assert ev.meta == {}


def test_nsf_event_actor_is_constrained():
    with pytest.raises(ValidationError):
        NSFEvent(
            session="ses_1",
            actor="martian",
            kind="user_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content="hi",
        )


def test_nsf_event_round_trips():
    ev = NSFEvent(
        session="ses_1",
        actor="agent",
        kind="tool_result",
        timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
        content="2 rows affected",
        refs=["services/billing/webhook.py:88"],
        meta={"tool": "bash"},
    )
    restored = NSFEvent.model_validate_json(ev.model_dump_json())
    assert restored == ev


def test_conflict_links_two_or_more_claims():
    c = Conflict(
        scope="services/billing",
        claim_ids=["clm_aaa", "clm_bbb"],
        reason="Two decisions disagree on the dedupe key.",
        detected_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert c.id.startswith("cfl_")
    assert len(c.claim_ids) == 2


def test_conflict_requires_at_least_two_claims():
    with pytest.raises(ValidationError):
        Conflict(
            scope="services/billing",
            claim_ids=["clm_aaa"],
            reason="not really a conflict",
            detected_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )
