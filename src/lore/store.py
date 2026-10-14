"""The knowledge store: read/write the `.lore/` layout.

Git is the append-only timeline; `claims.jsonl` is the compiled-truth surface.
Output is sorted and one-object-per-line so diffs are line-oriented and merges
stay sane across multiple compilers. Raw NSF sessions are gitignored by default
(they can contain secrets); only compiled, anchor-bearing claims are committed.
"""

from __future__ import annotations

import contextlib
import glob
import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

from lore.schemas import Claim, Conflict, Correction, NSFEvent, UsageStats

DEFAULT_CONFIG = {
    "model": {"provider": "anthropic", "name": "claude-sonnet-5-5"},
    "capture": {
        # "auto" = only this repo's own Claude Code transcripts. Set a directory to
        # read transcripts from somewhere else.
        "transcripts": "auto",
        # A transcript modified more recently than this is still being written by a
        # running session and is left for a later pass: a session is captured once,
        # so capturing it mid-way would keep only its first half for good. 0 captures
        # immediately.
        "settle_minutes": 10,
    },
    "compile": {"watch_interval_seconds": 300, "max_unused_days": 30},
}

# Never committed: raw sessions and raw source exports can carry secrets or PII,
# the extraction cache is local, usage stats are volatile, and `.<name>.<pid>.tmp` is
# the temp file of an atomic write, which a crash can leave behind. Sessions and the
# cache have been ignored by every version; the writes a compile makes before its head
# check ask `ensure_gitignore` for just those two lines.
SESSIONS_IGNORE = "sessions/"
CACHE_IGNORE = "cache/"
GITIGNORE_LINES = (SESSIONS_IGNORE, CACHE_IGNORE, "sources/", "claims/usage.jsonl", ".*.tmp")
# The corrections log is appended by every author in time order, so two branches that
# each add a note conflict at its end; git's union driver keeps both lines.
GITATTRIBUTES_LINES = ("claims/corrections.jsonl merge=union",)
# Files whose unreadable lines were already reported in this process.
_WARNED_FILES: set[Path] = set()

# A write's temp file exists for the milliseconds between writing it and replacing
# the target, so a `.<name>.<pid>.tmp` sibling older than this is the leftover of a
# writer that crashed in between, and the next write to that path removes it.
STALE_TMP_AGE_SECONDS = 600


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` so a concurrent reader sees the old file or the new one, never a
    truncated one: the content goes to a sibling temp file that then replaces `path`.

    Two compiles that overlap (a rebase fires one post-commit hook per commit) would
    otherwise read each other's half-written claims and persist an empty store.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _sweep_stale_tmp(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _sweep_stale_tmp(path: Path) -> None:
    """Remove the temp files that earlier writers of `path` crashed and left behind. A
    temp file younger than `STALE_TMP_AGE_SECONDS` may belong to a write in progress
    in another process and is left alone."""
    cutoff = time.time() - STALE_TMP_AGE_SECONDS
    for stale in path.parent.glob(f".{glob.escape(path.name)}.*.tmp"):
        with contextlib.suppress(OSError):
            if stale.stat().st_mtime < cutoff:
                stale.unlink()


def _lock_exclusive(fd: int) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        return
    fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock(fd: int) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(fd, fcntl.LOCK_UN)


class LoreStore:
    def __init__(self, repo_root: Path | str):
        self.root = Path(repo_root)
        self.lore = self.root / ".lore"

    # --- paths ---
    @property
    def claims_path(self) -> Path:
        return self.lore / "claims" / "claims.jsonl"

    @property
    def usage_path(self) -> Path:
        # Volatile usage stats live in a gitignored sidecar so that `lore query`
        # (which bumps counters) never churns the git-tracked claims.jsonl.
        return self.lore / "claims" / "usage.jsonl"

    @property
    def corrections_path(self) -> Path:
        # Committed, like the claims: a correction is the team's, not one machine's.
        return self.lore / "claims" / "corrections.jsonl"

    @property
    def conflicts_path(self) -> Path:
        return self.lore / "claims" / "conflicts.jsonl"

    @property
    def config_path(self) -> Path:
        return self.lore / "config.yaml"

    def session_path(self, session_id: str) -> Path:
        return self.lore / "sessions" / f"{session_id}.jsonl"

    def extraction_cache_path(self, session_id: str) -> Path:
        return self.lore / "cache" / f"{session_id}.jsonl"

    # --- lifecycle ---
    @property
    def is_initialised(self) -> bool:
        return self.config_path.exists()

    def init(self) -> None:
        (self.lore / "claims").mkdir(parents=True, exist_ok=True)
        (self.lore / "knowledge").mkdir(parents=True, exist_ok=True)
        (self.lore / "sessions").mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            atomic_write_text(self.config_path, yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False))
        self.ensure_gitignore()
        self.ensure_gitattributes()

    def ensure_gitattributes(self) -> None:
        """Make sure `.lore/.gitattributes` merges the corrections log line by line.
        Lines are compared token-wise, so spacing variants are not duplicated."""
        path = self.lore / ".gitattributes"
        existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        present = {tuple(line.split()) for line in existing}
        missing = [line for line in GITATTRIBUTES_LINES if tuple(line.split()) not in present]
        if missing:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = "".join(f"{line}\n" for line in [*existing, *missing])
            path.write_text(text, encoding="utf-8")

    def ensure_gitignore(self, *needed: str) -> None:
        """Make sure `.lore/.gitignore` exists and covers `needed` — every local-only
        path when nothing is named.

        Called from every write path, not only `init`, so a store that was
        written to before `lore init` ran — or that was initialised by an older
        version with a shorter list — can never commit raw sessions or raw
        source exports by accident. A missing or empty file gets the full list; an
        existing one gains only the lines asked for that it lacks, so a write to a
        directory every version has ignored leaves a tracked `.lore/.gitignore` alone.
        A compile relies on that: before its head check it writes only sessions and
        the extraction cache, and the full refresh comes with the claims, after it.
        """
        path = self.lore / ".gitignore"
        existing = path.read_text().splitlines() if path.exists() else []
        wanted = needed if needed and existing else GITIGNORE_LINES
        missing = [line for line in wanted if line not in existing]
        if not existing or missing:
            atomic_write_text(path, "".join(f"{line}\n" for line in [*existing, *missing]))

    def load_config(self) -> dict:
        if not self.config_path.exists():
            return dict(DEFAULT_CONFIG)
        return yaml.safe_load(self.config_path.read_text()) or {}

    # --- claims ---
    def write_claims(self, claims: list[Claim], *, now: datetime | None = None) -> None:
        self.claims_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_gitignore()
        stamped = self._stamp_entry_time(claims, now or datetime.now(timezone.utc))
        ordered = sorted(stamped, key=lambda c: c.id)
        # Committed truth excludes volatile usage stats — they live in a gitignored
        # sidecar, so retrieval (which bumps usage) leaves claims.jsonl byte-stable.
        atomic_write_text(
            self.claims_path,
            "".join(c.model_dump_json(exclude={"usage"}) + "\n" for c in ordered),
        )
        self._write_usage(ordered)

    def write_usage(self, claims: list[Claim]) -> None:
        """Persist the claims' usage counters to the gitignored sidecar and write nothing
        else. Serving only ever changes usage, so this is the one write a query or a
        feedback call makes: `claims.jsonl` stays byte-stable, and a compile that is
        running at the same time cannot have its result reverted by a serve-time write."""
        self.ensure_gitignore()
        self._write_usage(claims)

    def load_claims(self) -> list[Claim]:
        claims = [Claim.model_validate_json(ln) for ln in self._read_jsonl(self.claims_path)]
        usage = self.load_usage()
        for c in claims:
            if c.id in usage:
                c.usage = usage[c.id]
        return claims

    def load_usage(self) -> dict[str, UsageStats]:
        """The usage sidecar as it is on disk right now, keyed by claim id."""
        out: dict[str, UsageStats] = {}
        for ln in self._read_jsonl(self.usage_path):
            row = json.loads(ln)
            out[row["id"]] = UsageStats.model_validate(row["usage"])
        return out

    def _stamp_entry_time(self, claims: list[Claim], now: datetime) -> list[Claim]:
        """Stamp `compiled_at` on claims entering the store for the first time.

        Entry time is a property of the *store*, not of the object being written,
        so an unstamped claim inherits whatever time the store already recorded
        for that id and only a genuinely new claim gets `now`. That keeps writes
        idempotent (rewriting the same claims is byte-stable) and stops a
        re-extracted claim from resetting its own unused-decay clock.

        Doing this at the store boundary rather than during extraction also keeps
        extraction deterministic, and therefore cacheable.
        """
        known = self._entry_times()
        out: list[Claim] = []
        for c in claims:
            if c.compiled_at:
                out.append(c)
                continue
            out.append(c.model_copy(update={"compiled_at": known.get(c.id, now)}))
        return out

    def _entry_times(self) -> dict[str, datetime]:
        """Already-recorded entry times, read straight from the claims file."""
        out: dict[str, datetime] = {}
        for ln in self._read_jsonl(self.claims_path):
            row = json.loads(ln)
            if stamp := row.get("compiled_at"):
                out[row["id"]] = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return out

    @contextmanager
    def locked(self, name: str) -> Iterator[None]:
        """Hold an exclusive lock on `.lore/cache/<name>.lock` around a read-modify-write
        of a small shared file (the usage sidecar, a hook's state). Hooks run in
        parallel and a query can overlap a compile; without this, one writer's bump is
        lost under another's. The wait is short: these writes take milliseconds."""
        path = self.lore / "cache" / f"{name}.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            _lock_exclusive(fd)
            try:
                yield
            finally:
                _unlock(fd)
        finally:
            os.close(fd)

    def _write_usage(self, claims: list[Claim]) -> None:
        # Only persist non-default usage, keyed by claim id, to keep the sidecar small.
        rows = [
            {"id": c.id, "usage": c.usage.model_dump(mode="json")}
            for c in claims
            if c.usage != UsageStats()
        ]
        atomic_write_text(self.usage_path, "".join(json.dumps(r) + "\n" for r in rows))

    # --- conflicts ---
    def write_conflicts(self, conflicts: list[Conflict]) -> None:
        self.conflicts_path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(conflicts, key=lambda c: c.id)
        self._write_jsonl(self.conflicts_path, ordered)

    def load_conflicts(self) -> list[Conflict]:
        return [Conflict.model_validate_json(ln) for ln in self._read_jsonl(self.conflicts_path)]

    # --- corrections (committed reader feedback) ---
    def load_corrections(self) -> list[Correction]:
        """Every readable note. A line that does not parse (a merge marker, a hand edit)
        is skipped and reported on stderr, once per process and file, so one bad line
        in a committed file never takes retrieval, the book or the MCP tools down for
        the whole team. Line numbers are the file's own, blank lines included."""
        path = self.corrections_path
        if not path.exists():
            return []
        out: list[Correction] = []
        bad: list[int] = []
        for number, raw in enumerate(path.read_bytes().splitlines(), start=1):
            if not raw.strip():
                continue
            try:  # a line that is not UTF-8 is unreadable like one that is not JSON
                out.append(Correction.model_validate_json(raw.decode("utf-8")))
            except ValueError:
                bad.append(number)
        if bad and path not in _WARNED_FILES:
            _WARNED_FILES.add(path)
            lines = ", ".join(map(str, bad))
            print(f"crewlore: skipping unreadable line(s) {lines} of {path}", file=sys.stderr)
        return out

    def add_corrections(self, corrections: list[Correction]) -> None:
        """Append one line per note. The file is append-only: the tool never edits or
        removes a note (a person may, in the committed file), and appending whole
        lines is how concurrent writers, two agents or a person and an agent, all keep
        theirs. A hand-edited file whose last line lacks a newline gets one first, so
        two records are never glued into one unreadable line."""
        path = self.corrections_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_gitignore()
        self.ensure_gitattributes()
        payload = "".join(x.model_dump_json() + "\n" for x in corrections).encode("utf-8")
        with open(path, "a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() > 0:
                handle.seek(-1, 2)
                if handle.read(1) != b"\n":
                    payload = b"\n" + payload
            handle.write(payload)

    # --- sessions (raw NSF capture) ---
    def write_session(self, session_id: str, events: list[NSFEvent]) -> None:
        path = self.session_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_gitignore(SESSIONS_IGNORE)  # raw sessions must never be committable
        self._write_jsonl(path, events)

    def load_session(self, session_id: str) -> list[NSFEvent]:
        lines = self._read_jsonl(self.session_path(session_id))
        return [NSFEvent.model_validate_json(ln) for ln in lines]

    def list_sessions(self) -> list[str]:
        sessions_dir = self.lore / "sessions"
        if not sessions_dir.is_dir():
            return []
        return [p.stem for p in sessions_dir.glob("*.jsonl")]

    # --- extraction cache (gitignored; sessions are immutable so the id is a safe key) ---
    def load_extraction(self, session_id: str) -> list[Claim] | None:
        """Return the cached per-session extraction, or None if not cached.

        An empty list (file exists, no claims) is a real cached result — a
        signal-bearing session can legitimately produce no claims, and we must
        not re-run the model on it every pass.
        """
        path = self.extraction_cache_path(session_id)
        if not path.exists():
            return None
        return [Claim.model_validate_json(ln) for ln in self._read_jsonl(path)]

    def save_extraction(self, session_id: str, claims: list[Claim]) -> None:
        path = self.extraction_cache_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_gitignore(CACHE_IGNORE)
        self._write_jsonl(path, claims)

    # --- jsonl helpers ---
    @staticmethod
    def _write_jsonl(path: Path, models) -> None:
        atomic_write_text(path, "".join(m.model_dump_json() + "\n" for m in models))

    @staticmethod
    def _read_jsonl(path: Path) -> list[str]:
        if not path.exists():
            return []
        return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
