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


def test_rebuild_replaces_what_the_sessions_on_disk_produced(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1")
    legit = _claim("dedupe on idempotency key", "ses_1")
    planted = _claim("store secrets in the repo", "ses_1")
    inherited = _claim("run migrations before deploy", "ses_gone")  # a session not on disk
    store.write_claims([inherited])
    run_compile(store, CountingExtractor({"ses_1": [legit, planted]}))
    assert {c.statement for c in store.load_claims()} == {
        legit.statement, planted.statement, inherited.statement,
    }
    entry = {c.id: c.compiled_at for c in store.load_claims()}
    claims = store.load_claims()
    for c in claims:
        if c.id == legit.id:
            c.usage.times_served = 3
    store.write_claims(claims)

    attributed = legit.model_copy(
        update={
            "anchors": [
                Anchor(source_kind="transcript", ref="ses_1#1", quote=legit.statement,
                       actor="user", login="alice", association="member"),
            ]
        }
    )
    run_compile(store, CountingExtractor({"ses_1": [attributed]}), rebuild=True)
    after = {c.statement: c for c in store.load_claims()}
    assert set(after) == {legit.statement, inherited.statement}  # the planted claim is gone
    kept = after[legit.statement]
    assert kept.anchors[0].login == "alice"  # re-extraction filled in the author
    assert kept.compiled_at == entry[legit.id]  # entry time and usage survive the rebuild
    assert kept.usage.times_served == 3
    assert after[inherited.statement].id == inherited.id


def test_rebuild_does_not_resurrect_an_archived_claim(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1")
    claim = _claim("dedupe on idempotency key", "ses_1")
    run_compile(store, CountingExtractor({"ses_1": [claim]}))
    stored = store.load_claims()
    stored[0].status = "archived"
    store.write_claims(stored)
    run_compile(store, CountingExtractor({"ses_1": [claim]}), rebuild=True)
    assert [c.status for c in store.load_claims()] == ["archived"]


class FlakyExtractor(CountingExtractor):
    """Fails for the sessions named in `broken`; the rest extract normally."""

    def __init__(self, mapping, broken):
        super().__init__(mapping)
        self.broken = set(broken)

    def extract(self, events, session_id, known_topics=None):
        if session_id in self.broken:
            self.calls.append(session_id)
            raise RuntimeError("429 from the model")
        return super().extract(events, session_id, known_topics)


def test_rebuild_keeps_the_claims_of_a_session_whose_re_extraction_failed(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1")
    _signal_session(store, "ses_2")
    one = _claim("dedupe on idempotency key", "ses_1")
    two = _claim("run migrations before deploy", "ses_2")
    run_compile(store, CountingExtractor({"ses_1": [one], "ses_2": [two]}))
    stored = store.load_claims()
    for c in stored:
        if c.id == one.id:
            c.status, c.usage.times_served, c.authority = "archived", 5, 0.9
    store.write_claims(stored)
    entry = {c.id: c.compiled_at for c in store.load_claims()}

    run_compile(store, FlakyExtractor({"ses_2": [two]}, broken={"ses_1"}), rebuild=True)
    after = {c.id: c for c in store.load_claims()}
    assert set(after) == {one.id, two.id}  # nothing lost to the transient failure
    kept = after[one.id]
    assert (kept.status, kept.usage.times_served, kept.authority) == ("archived", 5, 0.9)
    assert kept.compiled_at == entry[one.id]

    # The next ordinary pass serves ses_1 from its (old) cache entry and changes nothing.
    run_compile(store, CountingExtractor({"ses_2": [two]}))
    again = {c.id: c for c in store.load_claims()}
    assert (again[one.id].status, again[one.id].usage.times_served) == ("archived", 5)
    assert again[one.id].compiled_at == entry[one.id]


def test_rebuild_keeps_the_authority_a_claim_earned(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1")
    claim = _claim("dedupe on idempotency key", "ses_1")
    run_compile(store, CountingExtractor({"ses_1": [claim]}))
    stored = store.load_claims()
    stored[0].authority = 0.8
    store.write_claims(stored)
    run_compile(store, CountingExtractor({"ses_1": [claim]}), rebuild=True)
    assert store.load_claims()[0].authority == 0.8
