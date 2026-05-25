"""Integration: orchestrate a full compile from captured sessions in a store,
using a fake extractor, and verify claims, conflicts, and the book are written.
"""

from datetime import datetime, timezone

from lore.compile.run import run_compile
from lore.schemas import Anchor, Claim, NSFEvent, Provenance
from lore.store import LoreStore


def _signal_session(store, sid, text):
    events = [
        NSFEvent(
            session=sid, actor="user", kind="user_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content=f"No, that's wrong — {text}",
        )
    ]
    store.write_session(sid, events)


def _claim(statement, sid, *, topic=None, kind="gotcha"):
    return Claim(
        statement=statement, kind=kind, scope="services/billing", topic=topic,
        provenance=Provenance(session=sid, author="alice", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref=f"{sid}#1", quote=statement)],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


class DictExtractor:
    def __init__(self, mapping):
        self.mapping = mapping

    def extract(self, events, session_id, known_topics=None):
        return list(self.mapping.get(session_id, []))


def test_run_compile_writes_claims_conflicts_and_book(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1", "use idempotency key")
    _signal_session(store, "ses_2", "use idempotency key")
    extractor = DictExtractor(
        {
            "ses_1": [
                _claim("use Postgres for ledger", "ses_1", topic="ledger-db", kind="decision")
            ],
            "ses_2": [
                _claim("use Dynamo for ledger", "ses_2", topic="ledger-db", kind="decision")
            ],
        }
    )

    result = run_compile(store, extractor)

    assert len(result.claims) == 2
    assert len(result.conflicts) == 1
    # persisted
    assert len(store.load_claims()) == 2
    assert len(store.load_conflicts()) == 1
    # book rendered
    book = (tmp_path / ".lore" / "knowledge" / "README.md").read_text()
    assert "ledger" in book.lower()


def test_run_compile_is_idempotent_across_runs(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1", "use idempotency key")
    extractor = DictExtractor({"ses_1": [_claim("dedupe on idempotency key", "ses_1")]})

    first = run_compile(store, extractor)
    second = run_compile(store, extractor)  # prior claims loaded from store
    assert [c.id for c in second.claims] == [c.id for c in first.claims]
    assert len(store.load_claims()) == 1
