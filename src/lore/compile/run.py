"""Compile orchestration: load captured sessions from a store, compile them into
claims + conflicts, persist, and render the knowledge book. The extractor (the
model seam) is injected so this is testable end-to-end without a live LLM.

One compile runs per store at a time (`compile_lock`): a rebase or cherry-pick fires
the post-commit hook once per commit, and overlapping compiles would otherwise read
each other's half-written files. A caller that knows which commit it is compiling
for passes `expect_head`, and nothing is written if HEAD has moved by the time the
model answers: the checkout the result belongs to is gone.
"""

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

from lore.actuation import apply_lifecycle
from lore.capture.ingest import ingest_transcripts
from lore.compile.pipeline import CompileResult, Extractor, compile_sessions
from lore.schemas import Claim, Conflict
from lore.serve.server import KnowledgeServer
from lore.store import LoreStore

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

DEFAULT_MAX_UNUSED_AGE = timedelta(days=30)


class CompileInProgress(RuntimeError):
    """Another compile holds this store's lock; nothing was read or written."""


class HeadMoved(RuntimeError):
    """HEAD is no longer the commit the caller compiled for; nothing was written."""

    def __init__(self, expected: str, actual: str | None):
        super().__init__(
            f"HEAD moved from {expected[:12]} to {actual[:12] if actual else 'no commit'} "
            "while compiling; nothing written"
        )
        self.expected = expected
        self.actual = actual


class RenderResult(BaseModel):
    claims: list[Claim] = []
    conflicts: list[Conflict] = []
    # False when the store holds no claims file: nothing was written, so a merge into a
    # repository without compiled knowledge creates no untracked files.
    rendered: bool = False
    # Lines of claims.jsonl added or removed by the render. A render reproduces the
    # stored claims, so this is normally 0; anything else is worth a look.
    changed_lines: int = 0
    # Captured sessions with no cached extraction: work for `lore compile`.
    unextracted_sessions: int = 0


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


class _NoExtractor:
    """`run_render` compiles no sessions, so nothing ever reaches this; it exists so a
    render can never make a model call by accident."""

    def extract(self, events, session_id, known_topics=None):
        raise RuntimeError("lore render makes no model calls; run `lore compile` to extract")


# --- one compile per store ------------------------------------------------------


def lock_path(store: LoreStore) -> Path:
    """The lock file, under the gitignored cache. It stays in place once created:
    deleting a lock file another process holds would end the exclusion."""
    return store.lore / "cache" / "compile.lock"


@contextmanager
def compile_lock(store: LoreStore):
    """Hold the store's exclusive compile lock, or raise `CompileInProgress` at once."""
    path = lock_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        _lock_exclusive(fd)
    except OSError as exc:
        os.close(fd)
        raise CompileInProgress(
            "another compile is running on this store; nothing written"
        ) from exc
    try:
        yield
    finally:
        try:
            _unlock(fd)
        finally:
            os.close(fd)


def _lock_exclusive(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif msvcrt is not None:  # pragma: no cover - Windows
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    # Neither module: this platform offers no file locking; compiles run unguarded.


def _unlock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    elif msvcrt is not None:  # pragma: no cover - Windows
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def current_head(repo: Path) -> str | None:
    """The commit HEAD points at, or None outside a git repository or before the first
    commit."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD"],
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return (proc.stdout.strip() or None) if proc.returncode == 0 else None


def _check_head(store: LoreStore, expect_head: str | None) -> None:
    if not expect_head:
        return
    actual = current_head(store.root)
    if actual is None or not actual.startswith(expect_head):
        raise HeadMoved(expect_head, actual)


# --- compile ----------------------------------------------------------------------


def _compile(store: LoreStore, extractor: Extractor, *, rebuild: bool) -> CompileResult:
    sessions = {sid: store.load_session(sid) for sid in store.list_sessions()}
    prior_claims = store.load_claims()
    cached = _CachingExtractor(store, extractor, refresh=rebuild)
    return compile_sessions(sessions, cached, prior_claims=prior_claims)


def _persist(store: LoreStore, result: CompileResult) -> None:
    store.write_claims(result.claims)
    store.write_conflicts(result.conflicts)
    KnowledgeServer(store).write_book()


def run_compile(
    store: LoreStore,
    extractor: Extractor,
    *,
    rebuild: bool = False,
    expect_head: str | None = None,
) -> CompileResult:
    """Compile every captured session (cache first) on top of the stored claims and
    persist claims, conflicts and the book.

    Raises `CompileInProgress` if another compile holds the store, and `HeadMoved`,
    after the model work but before any write, if `expect_head` no longer names HEAD.
    """
    with compile_lock(store):
        result = _compile(store, extractor, rebuild=rebuild)
        _check_head(store, expect_head)
        _persist(store, result)
    return result


def run_render(store: LoreStore, *, expect_head: str | None = None) -> RenderResult:
    """Rebuild claims.jsonl, conflicts.jsonl and the book from the stored claims alone.

    No model call, no sessions, no extraction cache: a render reproduces what is
    committed, so a claim a teammate removed in review cannot come back from this
    machine's cache, and a cached session not yet compiled stays out until `lore
    compile` adds it. A store with no claims file is left untouched.
    """
    with compile_lock(store):
        pending = sum(
            not store.extraction_cache_path(sid).exists() for sid in store.list_sessions()
        )
        if not store.claims_path.exists():
            return RenderResult(unextracted_sessions=pending)
        before = _claim_lines(store)
        result = compile_sessions({}, _NoExtractor(), prior_claims=store.load_claims())
        _check_head(store, expect_head)
        _persist(store, result)
        changed = len(set(before) ^ set(_claim_lines(store)))
    return RenderResult(
        claims=result.claims,
        conflicts=result.conflicts,
        rendered=True,
        changed_lines=changed,
        unextracted_sessions=pending,
    )


def _claim_lines(store: LoreStore) -> list[str]:
    return [ln for ln in store.claims_path.read_text().splitlines() if ln.strip()]


def auto_compile(
    store: LoreStore,
    extractor: Extractor,
    adapter,
    transcript_dir,
    *,
    scrub: bool = True,
    rebuild: bool = False,
    max_unused_age: timedelta = DEFAULT_MAX_UNUSED_AGE,
    settle: timedelta | None = None,
    expect_head: str | None = None,
) -> dict:
    """One automation pass: ingest new transcripts -> compile -> prune -> re-render.

    This is what `lore watch`/cron and the post-commit hook call. Extraction is cached
    per session (see `_CachingExtractor`), so each pass only LLM-extracts sessions
    ingested since the last pass — the work and cost are incremental, and the
    output is idempotent. The prune step (actuation lifecycle) keeps the active
    set churning. Pass `rebuild=True` to ignore the cache and re-extract everything;
    `settle` leaves transcripts modified more recently than that for a later pass
    (see `ingest_transcripts`); `expect_head` and the lock behave as in `run_compile`.
    """
    with compile_lock(store):
        stats = ingest_transcripts(store, adapter, transcript_dir, scrub=scrub, settle=settle)
        result = _compile(store, extractor, rebuild=rebuild)
        _check_head(store, expect_head)
        _persist(store, result)
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
