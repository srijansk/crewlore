"""The Claude Code adapter maps raw transcript records (the JSONL Claude Code
writes per session) into the harness-agnostic NSF stream. Tests feed
representative raw records directly so they need no Claude Code install.
"""

from lore.capture.adapters.claude_code import ClaudeCodeAdapter

USER_TEXT = {
    "type": "user",
    "sessionId": "ses_7",
    "timestamp": "2026-05-19T10:00:00Z",
    "message": {"role": "user", "content": "why does the billing webhook fire twice?"},
}

ASSISTANT_TEXT_AND_TOOL = {
    "type": "assistant",
    "sessionId": "ses_7",
    "timestamp": "2026-05-19T10:00:05Z",
    "message": {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me check the webhook handler."},
            {
                "type": "tool_use",
                "id": "tu_1",
                "name": "Bash",
                "input": {"command": "grep webhook"},
            },
        ],
    },
}

TOOL_RESULT = {
    "type": "user",
    "sessionId": "ses_7",
    "timestamp": "2026-05-19T10:00:07Z",
    "message": {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "tu_1",
                "content": "webhook.py:88 no idempotency check",
            }
        ],
    },
}

UNKNOWN = {"type": "summary", "summary": "compacted", "timestamp": "2026-05-19T10:00:09Z"}


def test_adapter_name_and_manifest():
    adapter = ClaudeCodeAdapter()
    assert adapter.name == "claude-code"
    assert "harness" in adapter.manifest
    assert adapter.manifest["harness"] == "claude-code"
    assert "log_location" in adapter.manifest


def test_parses_user_text_message():
    events = ClaudeCodeAdapter().parse_records([USER_TEXT])
    assert len(events) == 1
    ev = events[0]
    assert ev.actor == "user"
    assert ev.kind == "user_message"
    assert ev.session == "ses_7"
    assert "fire twice" in ev.content
    assert ev.timestamp.year == 2026


def test_parses_assistant_text_and_tool_use_as_two_events():
    events = ClaudeCodeAdapter().parse_records([ASSISTANT_TEXT_AND_TOOL])
    kinds = [e.kind for e in events]
    assert kinds == ["agent_message", "tool_call"]
    assert events[0].actor == "agent"
    assert "check the webhook" in events[0].content
    assert events[1].content == "Bash"
    assert events[1].meta["input"] == {"command": "grep webhook"}


def test_parses_tool_result_as_system_event():
    events = ClaudeCodeAdapter().parse_records([TOOL_RESULT])
    assert len(events) == 1
    ev = events[0]
    assert ev.actor == "system"
    assert ev.kind == "tool_result"
    assert "no idempotency check" in ev.content
    assert ev.meta["tool_use_id"] == "tu_1"


def test_unknown_record_types_are_skipped():
    events = ClaudeCodeAdapter().parse_records([UNKNOWN])
    assert events == []


def test_missing_or_naive_timestamp_yields_aware_datetime():
    # Older / edited / third-party transcripts can omit `timestamp`, and a present
    # one may lack a zone. Both must be tz-aware or the actuation lifecycle (which
    # subtracts UTC `now`) crashes with a naive-vs-aware TypeError.
    no_ts = {"type": "user", "message": {"role": "user", "content": "no timestamp here"}}
    naive_ts = {"type": "user", "timestamp": "2026-05-19T10:00:00",
                "message": {"role": "user", "content": "naive timestamp"}}
    events = ClaudeCodeAdapter().parse_records([no_ts, naive_ts])
    assert len(events) == 2
    assert all(e.timestamp.tzinfo is not None for e in events)


def test_full_transcript_preserves_order():
    records = [USER_TEXT, ASSISTANT_TEXT_AND_TOOL, TOOL_RESULT, UNKNOWN]
    events = ClaudeCodeAdapter().parse_records(records)
    assert [e.kind for e in events] == [
        "user_message",
        "agent_message",
        "tool_call",
        "tool_result",
    ]
