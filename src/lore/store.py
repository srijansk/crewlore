"""The knowledge store: read/write the `.lore/` layout.

Git is the append-only timeline; `claims.jsonl` is the compiled-truth surface.
Output is sorted and one-object-per-line so diffs are line-oriented and merges
stay sane across multiple compilers. Raw NSF sessions are gitignored by default
(they can contain secrets); only compiled, anchor-bearing claims are committed.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from lore.schemas import Claim, Conflict, NSFEvent, UsageStats

DEFAULT_CONFIG = {
    "harness": "claude-code",
    "model": {"provider": "anthropic", "name": "claude-sonnet-4-6"},
    "scopes": ["."],
    "capture": {"transcripts": "~/.claude/projects"},
    "compile": {"cadence": "auto", "watch_interval_seconds": 300},
}


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
    def init(self) -> None:
        (self.lore / "claims").mkdir(parents=True, exist_ok=True)
        (self.lore / "knowledge").mkdir(parents=True, exist_ok=True)
        (self.lore / "sessions").mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self.config_path.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False))
        # Raw sessions never get committed — they can carry secrets/PII. The
        # extraction cache and volatile usage stats are local-only too.
        (self.lore / ".gitignore").write_text("sessions/\ncache/\nclaims/usage.jsonl\n")

    def load_config(self) -> dict:
        if not self.config_path.exists():
            return dict(DEFAULT_CONFIG)
        return yaml.safe_load(self.config_path.read_text()) or {}

    # --- claims ---
    def write_claims(self, claims: list[Claim]) -> None:
        self.claims_path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(claims, key=lambda c: c.id)
        # Committed truth excludes volatile usage stats — they live in a gitignored
        # sidecar, so retrieval (which bumps usage) leaves claims.jsonl byte-stable.
        self.claims_path.write_text(
            "".join(c.model_dump_json(exclude={"usage"}) + "\n" for c in ordered)
        )
        self._write_usage(ordered)

    def load_claims(self) -> list[Claim]:
        claims = [Claim.model_validate_json(ln) for ln in self._read_jsonl(self.claims_path)]
        usage = self._load_usage()
        for c in claims:
            if c.id in usage:
                c.usage = usage[c.id]
        return claims

    def _write_usage(self, claims: list[Claim]) -> None:
        # Only persist non-default usage, keyed by claim id, to keep the sidecar small.
        rows = [
            {"id": c.id, "usage": c.usage.model_dump(mode="json")}
            for c in claims
            if c.usage != UsageStats()
        ]
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        self.usage_path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def _load_usage(self) -> dict[str, UsageStats]:
        out: dict[str, UsageStats] = {}
        for ln in self._read_jsonl(self.usage_path):
            row = json.loads(ln)
            out[row["id"]] = UsageStats.model_validate(row["usage"])
        return out

    # --- conflicts ---
    def write_conflicts(self, conflicts: list[Conflict]) -> None:
        self.conflicts_path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(conflicts, key=lambda c: c.id)
        self._write_jsonl(self.conflicts_path, ordered)

    def load_conflicts(self) -> list[Conflict]:
        return [Conflict.model_validate_json(ln) for ln in self._read_jsonl(self.conflicts_path)]

    # --- sessions (raw NSF capture) ---
    def write_session(self, session_id: str, events: list[NSFEvent]) -> None:
        path = self.session_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
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
        self._write_jsonl(path, claims)

    # --- jsonl helpers ---
    @staticmethod
    def _write_jsonl(path: Path, models) -> None:
        path.write_text("".join(m.model_dump_json() + "\n" for m in models))

    @staticmethod
    def _read_jsonl(path: Path) -> list[str]:
        if not path.exists():
            return []
        return [ln for ln in path.read_text().splitlines() if ln.strip()]
