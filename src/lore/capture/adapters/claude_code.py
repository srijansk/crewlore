"""Claude Code capture adapter.

Maps Claude Code's per-session transcript records into the Normalized Session
Format (NSF). Capture is deliberately thin: it normalizes faithfully and knows
nothing about compile/serve. Adding another harness is a sibling module with the
same shape — that is what makes `lore` harness-neutral by construction.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from lore.schemas import NSFEvent

MANIFEST = {
    "harness": "claude-code",
    # Where Claude Code keeps per-project session transcripts.
    "log_location": "~/.claude/projects/",
    "session_hook": "PostToolUse/Stop hooks write transcript JSONL (default)",
}


def _parse_ts(raw: str | None) -> datetime:
    if not raw:
        return datetime.fromtimestamp(0)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


class ClaudeCodeAdapter:
    name = "claude-code"
    manifest = MANIFEST

    def parse_records(self, records, session: str | None = None) -> list[NSFEvent]:
        events: list[NSFEvent] = []
        for rec in records:
            events.extend(self._record_to_events(rec, session))
        return events

    def parse_transcript(self, path: Path | str, session: str | None = None) -> list[NSFEvent]:
        import json

        text = Path(path).read_text()
        records = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
        return self.parse_records(records, session=session)

    # --- internals ---
    def _record_to_events(self, rec: dict, session: str | None) -> list[NSFEvent]:
        rtype = rec.get("type")
        sid = session or rec.get("sessionId") or "unknown"
        ts = _parse_ts(rec.get("timestamp"))
        message = rec.get("message") or {}
        content = message.get("content")

        if rtype == "user":
            return self._user_events(content, sid, ts)
        if rtype == "assistant":
            return self._assistant_events(content, sid, ts)
        # summaries, system/meta lines, anything else: not session knowledge.
        return []

    def _user_events(self, content, sid: str, ts: datetime) -> list[NSFEvent]:
        # A user turn is either a plain string (a real message) or a list of
        # blocks (tool results fed back to the model).
        if isinstance(content, str):
            return [
                NSFEvent(
                    session=sid, actor="user", kind="user_message", timestamp=ts, content=content
                )
            ]
        events: list[NSFEvent] = []
        for block in content or []:
            if block.get("type") == "tool_result":
                events.append(
                    NSFEvent(
                        session=sid,
                        actor="system",
                        kind="tool_result",
                        timestamp=ts,
                        content=_stringify(block.get("content", "")),
                        meta={"tool_use_id": block.get("tool_use_id")},
                    )
                )
        return events

    def _assistant_events(self, content, sid: str, ts: datetime) -> list[NSFEvent]:
        events: list[NSFEvent] = []
        if isinstance(content, str):
            return [
                NSFEvent(
                    session=sid, actor="agent", kind="agent_message", timestamp=ts, content=content
                )
            ]
        for block in content or []:
            btype = block.get("type")
            if btype == "text":
                events.append(
                    NSFEvent(
                        session=sid, actor="agent", kind="agent_message", timestamp=ts,
                        content=block.get("text", ""),
                    )
                )
            elif btype == "tool_use":
                events.append(
                    NSFEvent(
                        session=sid, actor="agent", kind="tool_call", timestamp=ts,
                        content=block.get("name", ""),
                        meta={"input": block.get("input", {}), "tool_use_id": block.get("id")},
                    )
                )
        return events


def _stringify(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in content]
        return "\n".join(p for p in parts if p)
    return str(content)
