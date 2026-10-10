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


def _claim(
    statement, session, *, topic=None, scope="services/billing", kind="gotcha", when=19,
    action=None, adoption="current",
):
    return Claim(
        statement=statement, kind=kind, scope=scope, topic=topic, action=action,
        adoption=adoption,
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
    pg = _claim(
        "use Postgres for the ledger", "ses_1", topic="ledger-db", kind="decision",
        action="Use Postgres for the ledger.",
    )
    dy = _claim(
        "use DynamoDB for the ledger", "ses_2", topic="ledger-db", kind="decision",
        action="Do not use Postgres for the ledger; use DynamoDB.",
    )
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


# GUARDS: a shared (scope, kind, topic) says two claims answer the same
# question, not that they answer it differently. Real-data false positive
# (pydantic-ai pull requests 9988, 9986 and 9899, compiled 2026-10-09): three
# gotchas that all say contributor PRs must not touch `.github/` were reported
# as a disagreement because their statements differed. Text verbatim from that run.
_GITHUB_GUARD_TOPIC = "github directory maintainer-only changes"
_GITHUB_GUARD_CLAIMS = [
    (
        "pr_pydantic__pydantic-ai__9988",
        "Changes under `.github/` are maintainer-only, and a `.github Directory Guard` CI check "
        "enforces this. Non-maintainer PRs must leave `.github/` files such as the runner lock "
        "untouched and flag the needed refresh for a maintainer.",
        "Do not edit anything under `.github/` in a contributor PR. Note in the PR description "
        "that a maintainer needs to refresh the runner lock.",
    ),
    (
        "pr_pydantic__pydantic-ai__9986",
        "Pull requests from non-maintainers that touch any file under `.github/` (including "
        "`.github/scripts/pydantic-ai-runner.lock`) fail the automatic '.github Directory Guard' "
        "check. Only maintainers may change that directory, because it runs with the repo's "
        "credentials. The contributor has to revert the `.github/` changes on the branch and ask "
        "a maintainer to carry them in a separate PR.",
        "Do not edit anything under `.github/` in a contributor PR. If a change there is needed, "
        "run `git checkout origin/main -- .github`, push, and ask a maintainer in a comment to "
        "make the `.github/` change separately.",
    ),
    (
        "pr_pydantic__pydantic-ai__9899",
        "The .github Directory Guard only accepts changes under .github/ from maintainers. A "
        "contributor PR that touches workflows is blocked, so the CI job was dropped from the "
        "diff and kept in a separate commit for a maintainer to cherry-pick into their own PR.",
        "Do not include .github/ workflow changes in a contributor PR. Keep them in a separate "
        "commit and tell maintainers to carry them forward in their own PR.",
    ),
]


def test_agreeing_claims_on_one_topic_across_sessions_are_not_a_conflict():
    mapping = {
        session: [
            _claim(
                statement, session, scope=".github/", kind="gotcha",
                topic=_GITHUB_GUARD_TOPIC, action=action,
            )
        ]
        for session, statement, action in _GITHUB_GUARD_CLAIMS
    }
    sessions = {session: _signal_events(session) for session in mapping}
    result = compile_sessions(sessions, DictExtractor(mapping))
    assert len(result.claims) == 3
    assert result.conflicts == []


def test_current_vs_not_adopted_on_one_topic_is_a_conflict():
    # The store would otherwise tell a future session both "this is practice"
    # and "this was declined" about one question.
    kept = _claim(
        "Store the idempotency key in Redis.", "ses_1", topic="idem-key-store",
        kind="decision", action="Put the idempotency key in Redis.",
    )
    declined = _claim(
        "Redis for the idempotency key was tried and not adopted.", "ses_2",
        topic="idem-key-store", kind="decision", adoption="not_adopted",
        action="Keep the idempotency key inside the transaction.",
    )
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    result = compile_sessions(sessions, DictExtractor({"ses_1": [kept], "ses_2": [declined]}))
    assert len(result.conflicts) == 1
    assert set(result.conflicts[0].claim_ids) == {kept.id, declined.id}
    assert "not adopted" in result.conflicts[0].reason


def test_adoption_split_within_one_session_is_not_a_conflict():
    # The same pair from one session is one investigation's record — "we tried
    # Redis, declined it, kept the key in the transaction" — not a disagreement.
    # Evidence of disagreement does not waive the cross-session requirement.
    kept = _claim(
        "Store the idempotency key in Redis.", "ses_1", topic="idem-key-store",
        kind="decision", action="Put the idempotency key in Redis.",
    )
    declined = _claim(
        "Redis for the idempotency key was tried and not adopted.", "ses_1",
        topic="idem-key-store", kind="decision", adoption="not_adopted",
        action="Keep the idempotency key inside the transaction.",
    )
    result = compile_sessions(
        {"ses_1": _signal_events("ses_1")}, DictExtractor({"ses_1": [kept, declined]})
    )
    assert len(result.claims) == 2
    assert result.conflicts == []


def test_forbidding_what_another_claim_prescribes_is_a_conflict():
    put = _claim(
        "The idempotency key lives in Redis.", "ses_1", topic="idem-key-store",
        kind="decision", action="Put the idempotency key in Redis.",
    )
    forbid = _claim(
        "The idempotency key must not live in Redis.", "ses_2", topic="idem-key-store",
        kind="decision", action="Don't put the key in Redis. Keep it inside the transaction.",
    )
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    result = compile_sessions(sessions, DictExtractor({"ses_1": [put], "ses_2": [forbid]}))
    assert len(result.conflicts) == 1
    assert set(result.conflicts[0].claim_ids) == {put.id, forbid.id}
    assert "forbids" in result.conflicts[0].reason


def test_prescribing_the_alternative_a_prohibition_names_is_agreement():
    # "Do not X; do Y" and "do Y" agree, although the prohibition overlaps the
    # other claim's directive: the two prescriptions match more closely.
    both = _claim(
        "The key belongs in the transaction, not in Redis.", "ses_1",
        topic="idem-key-store", kind="decision",
        action="Do not store the key in Redis. Store the key in the transaction.",
    )
    same = _claim(
        "The key is written inside the transaction.", "ses_2", topic="idem-key-store",
        kind="decision", action="Store the key in the transaction.",
    )
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    result = compile_sessions(sessions, DictExtractor({"ses_1": [both], "ses_2": [same]}))
    assert result.conflicts == []


def test_different_answers_with_no_marker_are_not_flagged():
    # Deliberate blind spot, recorded so it stays explicit: two decisions that
    # pick different answers, with neither marked not adopted nor forbidding the
    # other, carry no evidence the detector can read offline. Telling "a
    # different answer" from "a different wording" needs a model; guessing it
    # from statement text is what produced the false positive above.
    pg = _claim("use Postgres for the ledger", "ses_1", topic="ledger-db", kind="decision")
    dy = _claim("use DynamoDB for the ledger", "ses_2", topic="ledger-db", kind="decision")
    sessions = {"ses_1": _signal_events("ses_1"), "ses_2": _signal_events("ses_2")}
    result = compile_sessions(sessions, DictExtractor({"ses_1": [pg], "ses_2": [dy]}))
    assert len(result.claims) == 2
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


# GUARDS: corroboration is not usage. Re-observing a claim in a later session
# must not reset its unused-decay clock, or a claim nobody ever reads stays
# active forever just by being rediscovered.
def test_merge_keeps_earliest_compiled_at():
    early = datetime(2026, 5, 1, tzinfo=timezone.utc)
    late = datetime(2026, 5, 20, tzinfo=timezone.utc)
    a = _claim("webhook double-fires", "ses_1", when=19).model_copy(
        update={"compiled_at": early}
    )
    b = _claim("webhook double-fires", "ses_2", when=20).model_copy(
        update={"compiled_at": late}
    )

    result = compile_sessions({}, DictExtractor({}), prior_claims=[a, b])
    assert len(result.claims) == 1
    assert result.claims[0].compiled_at == early


class _FailingExtractor:
    """Raises a chosen exception for every session."""

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def extract(self, events, session_id, known_topics=None):
        self.calls += 1
        raise self.exc


# GUARDS: bad credentials fail identically on every session. Swallowing them
# turns a misconfigured key into a run that reports success, ingests sessions
# and compiles nothing — the worst possible first-run experience.
def test_fatal_extraction_error_aborts_instead_of_compiling_nothing():
    import pytest

    from lore.compile.extractor import FatalExtractionError

    extractor = _FailingExtractor(FatalExtractionError("API key is invalid"))
    sessions = {"s1": _signal_events("s1"), "s2": _signal_events("s2")}

    with pytest.raises(FatalExtractionError):
        compile_sessions(sessions, extractor)
    assert extractor.calls == 1  # stopped on the first failure, did not retry every session


# GUARDS: a transient per-session failure must still be survivable, and must be
# reported rather than hidden behind a zero-claim success.
def test_transient_failures_are_survived_but_counted():
    extractor = _FailingExtractor(RuntimeError("transient 429"))
    sessions = {"s1": _signal_events("s1"), "s2": _signal_events("s2")}

    result = compile_sessions(sessions, extractor)
    assert extractor.calls == 2  # kept going
    assert result.claims == []
    assert result.failed_sessions == 2


# GUARDS: a teammate who pulls the repo and compiles with no local sessions sees
# support=1 for every inherited claim. That must not reset the authority the
# claim already earned — the committed claims.jsonl would churn on every pull.
def test_recompile_without_new_sessions_keeps_earned_authority():
    earned = _claim("dedupe on idempotency key", "ses_1").model_copy(update={"authority": 0.8})
    result = compile_sessions({}, DictExtractor({}), prior_claims=[earned])
    assert len(result.claims) == 1
    assert result.claims[0].authority == 0.8
