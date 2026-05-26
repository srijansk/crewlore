"""Capture-from-transcripts.

Coding agents already write session transcripts to disk, so for MVP `lore` does
not need a live hook: it reads the existing transcripts, scrubs secrets, and
stores them as NSF. Ingestion is incremental (skips already-captured sessions),
so it is safe to run on a schedule (`lore watch` / cron) — which is what makes
compilation automatic rather than a chore.
"""

from __future__ import annotations

from pathlib import Path

from lore.scrub import scrub_events
from lore.store import LoreStore


def discover_transcripts(root: Path | str) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(root.rglob("*.jsonl"))


def ingest_transcripts(
    store: LoreStore, adapter, transcript_dir: Path | str, scrub: bool = True
) -> dict:
    discovered = discover_transcripts(transcript_dir)
    existing = set(store.list_sessions())
    ingested = 0
    redactions = 0
    for path in discovered:
        session_id = path.stem
        if session_id in existing:
            continue  # incremental: never re-ingest a captured session
        try:
            events = adapter.parse_transcript(path, session=session_id)
        except Exception:
            continue  # skip unparseable/corrupt transcript files
        if not events:
            continue
        if scrub:
            events, n = scrub_events(events)
            redactions += n
        store.write_session(session_id, events)
        ingested += 1
    return {"discovered": len(discovered), "ingested": ingested, "redactions": redactions}
