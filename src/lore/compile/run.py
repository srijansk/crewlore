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


class _CachingExtractor:
    """Per-session extraction cache. Sessions are immutable once captured, so the
    session id is a safe cache key: only newly-ingested sessions ever hit the
    model. This is what makes `lore watch` incremental in *work and cost*, not
    merely idempotent in output — without it, every interval would re-run the LLM
    over the entire corpus against the user's BYO key.

    `refresh=True` (the `--rebuild` escape hatch) ignores existing cache entries
    and re-extracts, then rewrites the cache — use it after a model/prompt change.
    """

    def __init__(self, store: LoreStore, inner: Extractor, *, refresh: bool = False):
        self._store = store
        self._inner = inner
        self._refresh = refresh

    def extract(self, events, session_id, known_topics=None):
        if not self._refresh:
            cached = self._store.load_extraction(session_id)
            if cached is not None:
                return cached
        claims = self._inner.extract(events, session_id, known_topics)
        # Only reached on a cache miss / refresh and only if extract() didn't raise,
        # so a failed extraction is never cached and will be retried next pass.
        self._store.save_extraction(session_id, claims)
        return claims


def run_compile(store: LoreStore, extractor: Extractor, *, rebuild: bool = False) -> CompileResult:
    sessions = {sid: store.load_session(sid) for sid in store.list_sessions()}
    prior_claims = store.load_claims()
    prior_by_id = {c.id: c for c in prior_claims}
    if rebuild:
        # A rebuild re-extracts every session still on disk, so what those sessions
        # produced before (under an older prompt or model) is not carried forward: a
        # claim that does not re-emerge is gone. Claims from sessions no longer on
        # disk, such as a teammate's, are kept as they are.
        prior_claims = [c for c in prior_claims if c.provenance.session not in sessions]
    cached = _CachingExtractor(store, extractor, refresh=rebuild)
    result = compile_sessions(sessions, cached, prior_claims=prior_claims)
    if rebuild:
        # A claim that re-emerges is the same claim: it keeps its usage and its
        # lifecycle status (the store keeps its entry time by id on its own).
        result = result.model_copy(
            update={"claims": [_carry_over(c, prior_by_id.get(c.id)) for c in result.claims]}
        )
    store.write_claims(result.claims)
    store.write_conflicts(result.conflicts)
    KnowledgeServer(store).write_book()
    return result


def _carry_over(claim, prior):
    if prior is None:
        return claim
    return claim.model_copy(update={"usage": prior.usage, "status": prior.status})


def auto_compile(
    store: LoreStore,
    extractor: Extractor,
    adapter,
    transcript_dir,
    *,
    scrub: bool = True,
    rebuild: bool = False,
    max_unused_age: timedelta = DEFAULT_MAX_UNUSED_AGE,
) -> dict:
    """One automation pass: ingest new transcripts -> compile -> prune -> re-render.

    This is what `lore watch`/cron call on an interval. Extraction is cached per
    session (see `_CachingExtractor`), so each pass only LLM-extracts sessions
    ingested since the last pass — the work and cost are incremental, and the
    output is idempotent. The prune step (actuation lifecycle) keeps the active
    set churning. Pass `rebuild=True` to ignore the cache and re-extract everything.
    """
    stats = ingest_transcripts(store, adapter, transcript_dir, scrub=scrub)
    result = run_compile(store, extractor, rebuild=rebuild)
    pruned = apply_lifecycle(
        store.load_claims(), now=datetime.now(timezone.utc), max_unused_age=max_unused_age
    )
    store.write_claims(pruned)
    KnowledgeServer(store).write_book()  # reflect pruning
    active = sum(c.status == "active" for c in pruned)
    return {
        **stats,
        "claims": len(pruned),
        "active": active,
        "conflicts": len(result.conflicts),
        "failed": result.failed_sessions,
    }
