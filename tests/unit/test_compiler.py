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

    def extract(self, events, session_id):
        return list(self.mapping.get(session_id, []))


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


def test_merge_keeps_latest_observed_at():
    early = _claim("dedupe on idempotency key", "ses_1", when=10)
    late = _claim("dedupe on idempotency key", "ses_2", when=20)
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    extractor = DictExtractor({"ses_1": [early], "ses_2": [late]})
    result = compile_sessions(sessions, extractor)
    assert result.claims[0].observed_at == datetime(2026, 5, 20, tzinfo=timezone.utc)
