"""Compile orchestration: load captured sessions from a store, compile them into
claims + conflicts, persist, and render the knowledge book. The extractor (the
model seam) is injected so this is testable end-to-end without a live LLM.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lore.actuation import apply_lifecycle
from lore.capture.ingest import ingest_transcripts
from lore.compile.pipeline import CompileResult, Extractor, compile_sessions
from lore.serve.server import KnowledgeServer
from lore.store import LoreStore

DEFAULT_MAX_UNUSED_AGE = timedelta(days=30)


def run_compile(store: LoreStore, extractor: Extractor) -> CompileResult:
    sessions = {sid: store.load_session(sid) for sid in store.list_sessions()}
    prior_claims = store.load_claims()
    result = compile_sessions(sessions, extractor, prior_claims=prior_claims)
    store.write_claims(result.claims)
    store.write_conflicts(result.conflicts)
    KnowledgeServer(store).write_book()
    return result


def auto_compile(
    store: LoreStore,
    extractor: Extractor,
    adapter,
    transcript_dir,
    *,
    scrub: bool = True,
    max_unused_age: timedelta = DEFAULT_MAX_UNUSED_AGE,
) -> dict:
    """One automation pass: ingest new transcripts -> compile -> prune -> re-render.

    Incremental and idempotent, so this is what `lore watch`/cron call on an
    interval. The prune step (actuation lifecycle) keeps the active set churning.
    """
    stats = ingest_transcripts(store, adapter, transcript_dir, scrub=scrub)
    result = run_compile(store, extractor)
    pruned = apply_lifecycle(
        store.load_claims(), now=datetime.now(timezone.utc), max_unused_age=max_unused_age
    )
    store.write_claims(pruned)
    KnowledgeServer(store).write_book()  # reflect pruning
    active = sum(c.status == "active" for c in pruned)
    return {**stats, "claims": len(pruned), "active": active, "conflicts": len(result.conflicts)}
