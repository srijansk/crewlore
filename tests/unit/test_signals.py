"""C0 lever 3 — be selective at ingestion. A session where the agent one-shotted
a trivial task has ~zero tribal value and should not be compiled into claims.
The gate is permissive (favor recall; the actuation loop prunes the rest) but it
must reject clearly-trivial sessions.
"""

from datetime import datetime, timezone

from lore.capture.signals import session_has_signal, signal_reasons
from lore.schemas import NSFEvent


def _ev(actor, kind, content):
    return NSFEvent(
        session="s",
        actor=actor,
        kind=kind,
        timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
        content=content,
    )


def test_trivial_session_has_no_signal():
    events = [
        _ev("user", "user_message", "what does this function return?"),
        _ev("agent", "agent_message", "It returns the user id."),
    ]
    assert session_has_signal(events) is False


def test_user_correction_is_a_signal():
    events = [
        _ev("agent", "agent_message", "I'll cache it globally."),
        _ev("user", "user_message", "No, that's wrong — use a per-tenant cache instead."),
    ]
    assert session_has_signal(events) is True
    assert "correction" in signal_reasons(events)


def test_tool_error_is_a_signal():
    events = [
        _ev("agent", "tool_call", "Bash"),
        _ev("system", "tool_result", "Traceback (most recent call last): KeyError: 'tenant'"),
    ]
    assert session_has_signal(events) is True
    assert "error" in signal_reasons(events)


def test_decision_phrase_is_a_signal():
    events = [
        _ev("user", "user_message", "Let's go with Postgres for the ledger."),
    ]
    assert session_has_signal(events) is True
    assert "decision" in signal_reasons(events)


def test_gotcha_phrase_is_a_signal():
    events = [
        _ev("agent", "agent_message", "Careful: the webhook fires twice in staging."),
    ]
    assert session_has_signal(events) is True
    assert "gotcha" in signal_reasons(events)
