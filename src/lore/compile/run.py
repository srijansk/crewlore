"""Compile orchestration: load captured sessions from a store, compile them into
claims + conflicts, persist, and render the knowledge book. The extractor (the
model seam) is injected so this is testable end-to-end without a live LLM.
"""

from __future__ import annotations

from lore.compile.pipeline import CompileResult, Extractor, compile_sessions
from lore.serve.server import KnowledgeServer
from lore.store import LoreStore


def run_compile(store: LoreStore, extractor: Extractor) -> CompileResult:
    sessions = {sid: store.load_session(sid) for sid in store.list_sessions()}
    prior_claims = store.load_claims()
    result = compile_sessions(sessions, extractor, prior_claims=prior_claims)
    store.write_claims(result.claims)
    store.write_conflicts(result.conflicts)
    KnowledgeServer(store).write_book()
    return result
