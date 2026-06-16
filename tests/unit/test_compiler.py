"""Compiler pipeline tests. The LLM lives behind an `Extractor` seam; these tests
use a fake extractor so the deterministic stages — signal-gating, dedup/merge,
conflict-recording, scoring, idempotency — are fully verifiable offline.
"""

from datetime import datetime, timezone

from lore.compile.pipeline import compile_sessions
from lore.schemas import Anchor, Claim, NSFEvent, Provenance


def _signal_events(session, text="No, that's wrong — use the idempotency key instead."):
    return [
        NSFEvent(
            session=session, actor="user", kind="user_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc), content=text,
        )
    ]


def _trivial_events(session):
    return [
        NSFEvent(
            session=session, actor="user", kind="user_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content="what does this function return?",
        )
    ]


def _claim(statement, session, *, topic=None, scope="services/billing", kind="gotcha", when=19):
    return Claim(
        statement=statement, kind=kind, scope=scope, topic=topic,
        provenance=Provenance(session=session, author="alice", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref=f"{session}#t1", quote=statement)],
        observed_at=datetime(2026, 5, when, tzinfo=timezone.utc),
    )


class DictExtractor:
    """Returns preset candidate claims per session id."""

    def __init__(self, mapping):
        self.mapping = mapping

    def extract(self, events, session_id, known_topics=None):
        return list(self.mapping.get(session_id, []))


class RecordingExtractor:
    """Records the known_topics it was handed per session."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.seen_topics: dict[str, list[str]] = {}

    def extract(self, events, session_id, known_topics=None):
        self.seen_topics[session_id] = list(known_topics or [])
        return list(self.mapping.get(session_id, []))


def test_known_topics_seeded_from_prior_claims():
    prior = [_claim("use Postgres", "ses_0", topic="ledger-db", kind="decision")]
    ex = RecordingExtractor({"ses_1": []})
    compile_sessions({"ses_1": _signal_events("ses_1")}, ex, prior_claims=prior)
    assert "ledger-db" in ex.seen_topics["ses_1"]


def test_known_topics_accumulate_across_sessions_in_one_run():
    a = _claim("use Postgres", "ses_1", topic="ledger-db", kind="decision")
    b = _claim("use Dynamo", "ses_2", topic="ledger-db", kind="decision")
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    ex = RecordingExtractor({"ses_1": [a], "ses_2": [b]})
    compile_sessions(sessions, ex)
    # ses_2 should be told about the topic produced while processing ses_1.
    assert "ledger-db" in ex.seen_topics["ses_2"]


def test_only_signal_sessions_are_compiled():
    sessions = {"ses_triv": _trivial_events("ses_triv"), "ses_sig": _signal_events("ses_sig")}
    extractor = DictExtractor(
        {
            "ses_triv": [_claim("should never appear", "ses_triv")],
            "ses_sig": [_claim("dedupe on idempotency key", "ses_sig")],
        }
    )
    result = compile_sessions(sessions, extractor)
    statements = {c.statement for c in result.claims}
    assert statements == {"dedupe on idempotency key"}


def test_dedup_merges_identical_claims_and_raises_authority():
    s1 = _claim("dedupe on idempotency key", "ses_1")
    s2 = _claim("dedupe on idempotency key", "ses_2")  # same id, different session/anchor
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    extractor = DictExtractor({"ses_1": [s1], "ses_2": [s2]})

    result = compile_sessions(sessions, extractor)
    assert len(result.claims) == 1
    merged = result.claims[0]
    assert len(merged.anchors) == 2  # anchors from both sessions

    single = compile_sessions({"ses_1": _signal_events("ses_1")}, DictExtractor({"ses_1": [s1]}))
    assert merged.authority > single.claims[0].authority  # more support -> more authority


def test_conflict_recorded_not_merged_for_same_scope_topic():
    pg = _claim("use Postgres for the ledger", "ses_1", topic="ledger-db", kind="decision")
    dy = _claim("use DynamoDB for the ledger", "ses_2", topic="ledger-db", kind="decision")
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    extractor = DictExtractor({"ses_1": [pg], "ses_2": [dy]})

    result = compile_sessions(sessions, extractor)
    assert len(result.claims) == 2  # both survive; disagreement is not merged away
    assert len(result.conflicts) == 1
    assert set(result.conflicts[0].claim_ids) == {pg.id, dy.id}


def test_no_conflict_when_all_claims_come_from_same_session():
    # Real-data finding (G1 session, 2026-05-28): a single session naturally
    # emits multiple complementary claims under the same (scope, kind, topic)
    # — a webhook investigation produces several gotchas about the same bug,
    # not contradicting each other. Flagging these as conflicts is a false
    # positive. Conflicts only mean something across sessions.
    a = _claim("dump drops metadata", "ses_1", topic="metadata-loss", kind="gotcha")
    b = _claim("load drops metadata too", "ses_1", topic="metadata-loss", kind="gotcha")
    sessions = {"ses_1": _signal_events("ses_1")}
    extractor = DictExtractor({"ses_1": [a, b]})
    result = compile_sessions(sessions, extractor)
    assert result.conflicts == []


def test_different_kinds_same_topic_do_not_conflict():
    # A gotcha (the problem) and a decision (the fix) can share a topic without
    # disagreeing. Conflicts require the same kind, else complementary claims
    # get falsely flagged (observed with a real model on a billing session).
    gotcha = _claim("handler lacks idempotency check", "ses_1", topic="webhook-idem", kind="gotcha")
    decision = _claim("use idempotency key", "ses_2", topic="webhook-idem", kind="decision")
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    extractor = DictExtractor({"ses_1": [gotcha], "ses_2": [decision]})
    result = compile_sessions(sessions, extractor)
    assert result.conflicts == []


def test_no_conflict_when_topic_absent():
    a = _claim("use Postgres for the ledger", "ses_1", kind="decision")
    b = _claim("cache tenants per-request", "ses_2", kind="decision")
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    extractor = DictExtractor({"ses_1": [a], "ses_2": [b]})
    result = compile_sessions(sessions, extractor)
    assert result.conflicts == []


def test_recompile_is_idempotent():
    s1 = _claim("dedupe on idempotency key", "ses_1")
    sessions = {"ses_1": _signal_events("ses_1")}
    extractor = DictExtractor({"ses_1": [s1]})

    first = compile_sessions(sessions, extractor)
    second = compile_sessions(sessions, extractor, prior_claims=first.claims)
    assert [c.id for c in second.claims] == [c.id for c in first.claims]
    assert len(second.claims) == 1


class _PartlyRaisingExtractor:
    """Raises on one session id, returns claims for others — models a transient
    API failure / oversized-context error on a single session."""

    def __init__(self, mapping, fail_on):
        self.mapping = mapping
        self.fail_on = fail_on

    def extract(self, events, session_id, known_topics=None):
        if session_id == self.fail_on:
            raise RuntimeError("simulated 429 / context overflow")
        return list(self.mapping.get(session_id, []))


def test_extractor_failure_on_one_session_does_not_abort_compile():
    good = _claim("dedupe on idempotency key", "ses_ok")
    sessions = {"ses_bad": _signal_events("ses_bad"), "ses_ok": _signal_events("ses_ok")}
    extractor = _PartlyRaisingExtractor({"ses_ok": [good]}, fail_on="ses_bad")
    # The bad session is skipped; the good session still compiles.
    result = compile_sessions(sessions, extractor)
    assert {c.statement for c in result.claims} == {"dedupe on idempotency key"}


def test_merge_keeps_latest_observed_at():
    early = _claim("dedupe on idempotency key", "ses_1", when=10)
    late = _claim("dedupe on idempotency key", "ses_2", when=20)
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    extractor = DictExtractor({"ses_1": [early], "ses_2": [late]})
    result = compile_sessions(sessions, extractor)
    assert result.claims[0].observed_at == datetime(2026, 5, 20, tzinfo=timezone.utc)
