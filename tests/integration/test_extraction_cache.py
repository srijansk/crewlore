"""Per-session extraction caching (CODE-5): `lore watch` re-runs every interval,
so it must NOT re-send already-compiled sessions to the (paid) model. Sessions
are immutable once captured, so the session id is a safe cache key. These tests
prove the model is hit once per session, and that --rebuild forces re-extraction.
"""

from datetime import datetime, timezone

from lore.compile.run import run_compile
from lore.schemas import Anchor, Claim, NSFEvent, Provenance
from lore.store import LoreStore


def _signal_session(store, sid, text="No, that's wrong — use the idempotency key."):
    store.write_session(
        sid,
        [NSFEvent(
            session=sid, actor="user", kind="user_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc), content=text,
        )],
    )


def _claim(statement, sid):
    return Claim(
        statement=statement, kind="gotcha", scope="services/billing",
        provenance=Provenance(session=sid, author="alice", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref=f"{sid}#1", quote=statement)],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


class CountingExtractor:
    """Counts how many times the model is actually invoked, per session."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls: list[str] = []

    def extract(self, events, session_id, known_topics=None):
        self.calls.append(session_id)
        return list(self.mapping.get(session_id, []))


def test_unchanged_session_is_not_re_extracted(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1")
    ex = CountingExtractor({"ses_1": [_claim("dedupe on idempotency key", "ses_1")]})

    run_compile(store, ex)           # cache miss -> 1 extraction
    run_compile(store, ex)           # cache hit  -> no new extraction
    run_compile(store, ex)           # cache hit  -> still none

    assert ex.calls == ["ses_1"]     # the model was invoked exactly once, ever
    assert len(store.load_claims()) == 1  # output is unchanged / idempotent


def test_only_new_sessions_are_extracted_on_a_later_pass(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1")
    ex = CountingExtractor({
        "ses_1": [_claim("dedupe on idempotency key", "ses_1")],
        "ses_2": [_claim("run migrations before deploy", "ses_2")],
    })

    run_compile(store, ex)           # extracts ses_1
    _signal_session(store, "ses_2")  # a new session arrives
    run_compile(store, ex)           # must extract ONLY ses_2, reuse ses_1 from cache

    assert ex.calls == ["ses_1", "ses_2"]
    assert len(store.load_claims()) == 2


def test_rebuild_forces_re_extraction(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1")
    ex = CountingExtractor({"ses_1": [_claim("dedupe on idempotency key", "ses_1")]})

    run_compile(store, ex)                  # caches ses_1
    run_compile(store, ex, rebuild=True)    # --rebuild: ignore cache, re-extract

    assert ex.calls == ["ses_1", "ses_1"]   # invoked again under rebuild
