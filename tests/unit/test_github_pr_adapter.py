"""The GitHub PR adapter maps one pull-request thread into the harness-agnostic
NSF stream. Tests feed representative normalized thread records directly so they
need no network access and no GitHub credentials.

The records fed here are the source-agnostic shape emitted by both the live
GitHub fetcher and an AIDev-pop export, so this suite pins the contract between
the two layers.
"""

import pytest

from lore.capture.adapters.github_pr import GitHubPRAdapter, pr_session_id

ISSUE = {
    "type": "issue",
    "actor": "human",
    "login": "maintainer",
    "created_at": "2026-05-19T09:00:00Z",
    "number": 41,
    "title": "Billing webhook fires twice",
    "body": "Customers are double-charged when Stripe retries.",
}

PR = {
    "type": "pr",
    "actor": "agent",
    "agent": "claude-code",
    "login": "some-bot",
    "created_at": "2026-05-19T10:00:00Z",
    "title": "Add idempotency key to billing webhook",
    "body": "Stripe retries deliver the same event twice. I considered deduping "
            "in the handler but chose a persisted idempotency key instead.",
}

COMMIT = {
    "type": "commit",
    "sha": "abc1234",
    "created_at": "2026-05-19T10:05:00Z",
    "message": "Persist idempotency key before charging",
    "files": ["services/billing/webhook.py", "tests/test_webhook.py"],
}

HUMAN_COMMENT = {
    "type": "comment",
    "actor": "human",
    "login": "reviewer",
    "created_at": "2026-05-19T11:00:00Z",
    "body": "Don't put the key in Redis, we lose it on eviction.",
}

INLINE_REVIEW_COMMENT = {
    "type": "review_comment",
    "actor": "human",
    "login": "reviewer",
    "created_at": "2026-05-19T11:02:00Z",
    "path": "services/billing/webhook.py",
    "line": 88,
    "body": "This must be inside the transaction.",
}

FAILED_CHECK = {
    "type": "check",
    "created_at": "2026-05-19T10:30:00Z",
    "name": "ci/pytest",
    "conclusion": "failure",
    "output": "test_webhook.py::test_retry FAILED - IntegrityError: duplicate key",
}

CHANGES_REQUESTED = {
    "type": "review",
    "actor": "human",
    "login": "reviewer",
    "created_at": "2026-05-19T11:05:00Z",
    "state": "CHANGES_REQUESTED",
    "body": "Move it into the transaction and re-run.",
}

APPROVED = {
    "type": "review",
    "actor": "human",
    "login": "reviewer",
    "created_at": "2026-05-19T12:00:00Z",
    "state": "APPROVED",
    "body": "",
}

MERGED = {"type": "timeline", "event": "merged", "created_at": "2026-05-19T12:05:00Z"}
CLOSED = {"type": "timeline", "event": "closed", "created_at": "2026-05-19T12:05:00Z"}

UNKNOWN = {"type": "labeled", "created_at": "2026-05-19T10:01:00Z", "label": "bug"}


def parse(records, session="pr_acme__billing__42"):
    return GitHubPRAdapter().parse_records(records, session=session)


def test_adapter_name_and_manifest():
    adapter = GitHubPRAdapter()
    assert adapter.name == "github-pr"
    assert adapter.manifest["harness"] == "github-pr"
    assert "log_location" in adapter.manifest


def test_session_id_is_filesystem_safe_and_carries_coordinates():
    sid = pr_session_id("acme", "billing-svc", 42)
    assert "/" not in sid
    assert sid.startswith("pr_")
    assert "acme" in sid and "billing-svc" in sid and "42" in sid


# GUARDS: the linked issue is the human's original intent. If it were mapped to
# agent, the compiler would attribute the request to the agent and the session
# would read as though nobody asked for anything.
def test_linked_issue_becomes_a_user_message():
    events = parse([ISSUE])
    assert len(events) == 1
    ev = events[0]
    assert ev.actor == "user"
    assert ev.kind == "user_message"
    assert "double-charged" in ev.content
    assert "Billing webhook fires twice" in ev.content


# GUARDS: the PR body is the rationale-bearing artifact — the reason this corpus
# is worth mining at all. It must survive capture with its title attached.
def test_pr_body_becomes_an_agent_message_with_title():
    events = parse([PR])
    assert len(events) == 1
    ev = events[0]
    assert ev.actor == "agent"
    assert ev.kind == "agent_message"
    assert "Add idempotency key" in ev.content
    assert "chose a persisted idempotency key" in ev.content
    assert ev.meta["agent"] == "claude-code"


def test_commit_becomes_a_diff_event_with_file_refs():
    events = parse([COMMIT])
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "diff"
    assert ev.actor == "agent"
    assert "Persist idempotency key" in ev.content
    assert ev.refs == ["services/billing/webhook.py", "tests/test_webhook.py"]
    assert ev.meta["sha"] == "abc1234"


# GUARDS: inline review comments are natively anchored to path:line, which is the
# exact shape Anchor.ref needs. Dropping the ref would throw away the highest-
# fidelity provenance the PR corpus offers.
def test_inline_review_comment_carries_a_path_line_ref():
    events = parse([INLINE_REVIEW_COMMENT])
    assert len(events) == 1
    ev = events[0]
    assert ev.actor == "user"
    assert ev.refs == ["services/billing/webhook.py:88"]
    assert "inside the transaction" in ev.content


# GUARDS: signals.py only counts an "error" signal when it comes from a
# tool_result. If CI failures were mapped to any other kind, every PR whose only
# friction was a failing build would be silently dropped by the compile gate.
def test_failed_check_is_a_tool_result_so_the_error_gate_fires():
    from lore.capture.signals import signal_reasons

    events = parse([FAILED_CHECK])
    assert len(events) == 1
    assert events[0].kind == "tool_result"
    assert events[0].actor == "system"
    assert "error" in signal_reasons(events)


def test_review_states_map_to_accept_and_reject():
    changes = parse([CHANGES_REQUESTED])
    kinds = [e.kind for e in changes]
    assert "reject" in kinds
    # the review body is knowledge too and must not be swallowed by the verdict
    assert "agent_message" in kinds or "user_message" in kinds

    approved = parse([APPROVED])
    assert [e.kind for e in approved] == ["accept"]


# GUARDS: merge/close is the ground-truth outcome label that transcripts lack.
# It is the reason PR threads populate the accept/reject NSF kinds at all.
@pytest.mark.parametrize(
    "record,expected", [(MERGED, "accept"), (CLOSED, "reject")]
)
def test_merge_and_close_are_outcome_events(record, expected):
    events = parse([record])
    assert len(events) == 1
    assert events[0].kind == expected
    assert events[0].actor == "system"


def test_unknown_record_types_are_skipped():
    assert parse([UNKNOWN]) == []


# GUARDS: agent-vs-human attribution is a source-layer concern (the published
# census shows PR author fields alone undercount Claude Code ~30x). The adapter
# must never guess: unlabeled authors default to human and are marked unknown so
# the mislabelling is auditable rather than silent.
def test_unlabelled_actor_defaults_to_human_and_is_marked_unknown():
    rec = dict(HUMAN_COMMENT)
    del rec["actor"]
    events = parse([rec])
    assert events[0].actor == "user"
    assert events[0].meta["attribution"] == "unknown"


def test_labelled_actor_is_not_marked_unknown():
    events = parse([HUMAN_COMMENT])
    assert events[0].meta.get("attribution") != "unknown"


def test_missing_or_naive_timestamp_yields_aware_datetime():
    no_ts = {"type": "comment", "actor": "human", "body": "no timestamp"}
    naive = {"type": "comment", "actor": "human", "created_at": "2026-05-19T11:00:00",
             "body": "naive timestamp"}
    events = parse([no_ts, naive])
    assert len(events) == 2
    assert all(e.timestamp.tzinfo is not None for e in events)


def test_empty_bodies_are_dropped_rather_than_stored_as_blank_events():
    empty = {"type": "comment", "actor": "human", "created_at": "2026-05-19T11:00:00Z",
             "body": "   "}
    assert parse([empty]) == []


def test_full_thread_preserves_order_and_session():
    records = [ISSUE, PR, COMMIT, FAILED_CHECK, HUMAN_COMMENT,
               INLINE_REVIEW_COMMENT, CHANGES_REQUESTED, APPROVED, MERGED, UNKNOWN]
    events = parse(records)
    assert all(e.session == "pr_acme__billing__42" for e in events)
    kinds = [e.kind for e in events]
    assert kinds[0] == "user_message"
    assert kinds[1] == "agent_message"
    assert kinds[2] == "diff"
    assert kinds[3] == "tool_result"
    assert kinds[-1] == "accept"


# GUARDS: a real PR thread carries the friction signals the compile gate looks
# for. If this regresses, PR sessions get ingested and then silently never
# compiled, which looks like "the corpus has no knowledge in it".
def test_realistic_thread_passes_the_compile_signal_gate():
    from lore.capture.signals import session_has_signal

    events = parse([ISSUE, PR, COMMIT, FAILED_CHECK, HUMAN_COMMENT,
                    INLINE_REVIEW_COMMENT, CHANGES_REQUESTED, MERGED])
    assert session_has_signal(events)
