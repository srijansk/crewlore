"""Secret scrubbing runs at ingest time so secrets never reach the LLM, the
anchors, or the committed store. The cheap half of the C3/C4 leakage gate.
"""

from datetime import datetime, timezone

from lore.schemas import NSFEvent
from lore.scrub import scrub_events, scrub_text


def test_redacts_api_key():
    out, n = scrub_text("export ANTHROPIC_API_KEY=sk-ant-api03-AbCdEf123456_xyz789TOKENvalue")
    assert "sk-ant" not in out
    assert "REDACTED" in out
    assert n >= 1


def test_redacts_aws_access_key():
    out, n = scrub_text("aws key AKIAIOSFODNN7EXAMPLE in the logs")
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert n >= 1


def test_redacts_private_key_block():
    blob = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBA...\n-----END RSA PRIVATE KEY-----"
    out, n = scrub_text(f"here is the key:\n{blob}\ndone")
    assert "PRIVATE KEY" not in out or "REDACTED" in out
    assert "MIIEowIBA" not in out
    assert n >= 1


def test_redacts_inline_secret_assignment():
    out, n = scrub_text("config: password = hunter2supersecret")
    assert "hunter2supersecret" not in out
    assert n >= 1


def test_leaves_ordinary_text_untouched():
    text = "the billing webhook fires twice in staging; dedupe on idempotency key"
    out, n = scrub_text(text)
    assert out == text
    assert n == 0


def test_scrub_events_redacts_content():
    ev = NSFEvent(
        session="s", actor="system", kind="tool_result",
        timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
        content="printed token=sk-ant-api03-LEAKED_secret_value_1234567890",
    )
    scrubbed, n = scrub_events([ev])
    assert "sk-ant" not in scrubbed[0].content
    assert n >= 1
    # other fields preserved
    assert scrubbed[0].kind == "tool_result"
