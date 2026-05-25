"""The knowledge store: read/write the `.lore/` layout.

Git is the append-only timeline; `claims.jsonl` is the compiled-truth surface.
Output is sorted and one-object-per-line so diffs are line-oriented and merges
stay sane across multiple compilers. Raw NSF sessions are gitignored by default
(they can contain secrets); only compiled, anchor-bearing claims are committed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from lore.schemas import Claim, Conflict, NSFEvent

DEFAULT_CONFIG = {
    "harness": "claude-code",
    "model": {"provider": "anthropic", "name": "claude-sonnet-4-6"},
    "scopes": ["."],
    "compile": {"cadence": "manual"},
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
    def conflicts_path(self) -> Path:
        return self.lore / "claims" / "conflicts.jsonl"

    @property
    def config_path(self) -> Path:
        return self.lore / "config.yaml"

    def session_path(self, session_id: str) -> Path:
        return self.lore / "sessions" / f"{session_id}.jsonl"

    # --- lifecycle ---
    def init(self) -> None:
        (self.lore / "claims").mkdir(parents=True, exist_ok=True)
        (self.lore / "knowledge").mkdir(parents=True, exist_ok=True)
        (self.lore / "sessions").mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self.config_path.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False))
        # Raw sessions never get committed — they can carry secrets/PII.
        (self.lore / ".gitignore").write_text("sessions/\n")

    def load_config(self) -> dict:
        if not self.config_path.exists():
            return dict(DEFAULT_CONFIG)
        return yaml.safe_load(self.config_path.read_text()) or {}

    # --- claims ---
    def write_claims(self, claims: list[Claim]) -> None:
        self.claims_path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(claims, key=lambda c: c.id)
        self._write_jsonl(self.claims_path, ordered)

    def load_claims(self) -> list[Claim]:
        return [Claim.model_validate_json(ln) for ln in self._read_jsonl(self.claims_path)]

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

    # --- jsonl helpers ---
    @staticmethod
    def _write_jsonl(path: Path, models) -> None:
        path.write_text("".join(m.model_dump_json() + "\n" for m in models))

    @staticmethod
    def _read_jsonl(path: Path) -> list[str]:
        if not path.exists():
            return []
        return [ln for ln in path.read_text().splitlines() if ln.strip()]
