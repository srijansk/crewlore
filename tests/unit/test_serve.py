"""Serve layer: task-conditioned retrieval that *instruments consumption*
(C0 lever 1) so the actuation loop can later decay unused claims and reinforce
used ones. Also renders the human+agent-readable knowledge book.
"""

from datetime import datetime, timezone

from lore.schemas import Anchor, Claim, Conflict, Provenance
from lore.serve.server import KnowledgeServer, rank_claims, render_book
from lore.store import LoreStore


def _claim(statement, scope, *, topic=None, action=None, status="active"):
    return Claim(
        statement=statement, kind="gotcha", scope=scope, topic=topic, action=action, status=status,
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote=statement)],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


def test_rank_returns_relevant_claims_first():
    billing = _claim("dedupe billing webhook on idempotency key", "services/billing")
    auth = _claim("rotate auth tokens hourly", "services/auth")
    ranked = rank_claims([auth, billing], "billing webhook")
    assert ranked[0].id == billing.id


def test_rank_excludes_claims_with_no_overlap():
    auth = _claim("rotate auth tokens hourly", "services/auth")
    ranked = rank_claims([auth], "billing webhook")
    assert ranked == []


def test_rank_skips_non_active_claims():
    archived = _claim("old gotcha", "services/billing", status="archived")
    ranked = rank_claims([archived], "billing")
    assert ranked == []


def test_query_instruments_usage_and_persists(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims([_claim("dedupe billing webhook", "services/billing")])
    server = KnowledgeServer(store)

    results = server.query("billing webhook")
    assert len(results) == 1
    # usage recorded on the returned claim...
    assert results[0].usage.times_served == 1
    assert results[0].usage.last_served_at is not None
    # ...and persisted to the store.
    reloaded = store.load_claims()[0]
    assert reloaded.usage.times_served == 1


def test_query_respects_limit(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims(
        [
            _claim("billing webhook one", "services/billing"),
            _claim("billing webhook two", "services/billing"),
            _claim("billing webhook three", "services/billing"),
        ]
    )
    server = KnowledgeServer(store)
    assert len(server.query("billing webhook", limit=2)) == 2


def test_mark_influential_and_overridden_persist(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    c = _claim("dedupe billing webhook", "services/billing")
    store.write_claims([c])
    server = KnowledgeServer(store)

    server.mark_influential([c.id])
    server.mark_overridden([c.id])

    reloaded = store.load_claims()[0]
    assert reloaded.usage.times_influential == 1
    assert reloaded.usage.times_overridden == 1


def test_render_book_includes_statements_actions_and_conflicts():
    claims = [
        _claim("dedupe billing webhook", "services/billing", action="dedupe on idempotency key"),
    ]
    conflicts = [
        Conflict(
            scope="services/billing", claim_ids=["clm_a", "clm_b"],
            reason="disagree on dedupe key",
            detected_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )
    ]
    book = render_book(claims, conflicts)
    assert "services/billing" in book
    assert "dedupe billing webhook" in book
    assert "dedupe on idempotency key" in book
    assert "Conflicts" in book
