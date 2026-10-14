"""Capture-from-transcripts.

Coding agents already write session transcripts to disk, so for MVP `lore` does
not need a live hook: it reads the existing transcripts, scrubs secrets, and
stores them as NSF. Ingestion is incremental (skips already-captured sessions),
so it is safe to run on a schedule (`lore watch` / cron) — which is what makes
compilation automatic rather than a chore.
"""

from __future__ import annotations

import re
import time
from datetime import timedelta
from pathlib import Path

from lore.scrub import scrub_events
from lore.store import LoreStore

CLAUDE_PROJECTS_ROOT = Path("~/.claude/projects")


def claude_code_project_dir(repo_root: Path | str, projects_root: Path | str | None = None) -> Path:
    """The directory where Claude Code keeps the transcripts for ONE repo.

    Claude Code stores every session under `~/.claude/projects/<encoded cwd>/`,
    where the encoding replaces every character that is not a letter or digit
    with `-` (so `/Users/me/work/app` becomes `-Users-me-work-app`). Scoping to
    that one directory is what keeps `lore compile` from reading every project
    on the machine into this repo's committed knowledge, and from billing the
    model key for all of them.
    """
    root = Path(projects_root or CLAUDE_PROJECTS_ROOT).expanduser()
    encoded = re.sub(r"[^A-Za-z0-9]", "-", str(Path(repo_root).resolve()))
    return root / encoded


def discover_transcripts(root: Path | str) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(root.rglob("*.jsonl"))


def ingest_transcripts(
    store: LoreStore,
    adapter,
    transcript_dir: Path | str,
    scrub: bool = True,
    settle: timedelta | None = None,
) -> dict:
    """Capture every transcript not yet in the store.

    `settle`: leave a transcript alone until it has gone unmodified for this long. A
    coding agent writes its transcript for as long as the session runs, and a session
    is captured once, so capturing it mid-way (a post-commit hook fires while the agent
    is still working) would keep only its first half for good. Skipped transcripts are
    counted under `settling` and picked up by a later pass.
    """
    discovered = discover_transcripts(transcript_dir)
    existing = set(store.list_sessions())
    cutoff = time.time() - settle.total_seconds() if settle else None
    ingested = 0
    redactions = 0
    settling = 0
    for path in discovered:
        session_id = path.stem
        if session_id in existing:
            continue  # incremental: never re-ingest a captured session
        if cutoff is not None and path.stat().st_mtime > cutoff:
            settling += 1
            continue
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
    return {
        "discovered": len(discovered),
        "ingested": ingested,
        "redactions": redactions,
        "settling": settling,
    }
