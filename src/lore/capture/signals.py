"""Selective ingestion (C0 lever 3).

The dumpyard starts at the input: compiling every session yields mostly noise.
We gate compilation on *friction and resolution* signals — corrections,
tool errors, deliberated decisions, gotchas — rather than compiling all sessions.

This is a deliberately simple, recall-favoring keyword heuristic for v0.1: when in
doubt it includes the session, because the actuation loop (usage-driven decay)
prunes anything that turns out to be unused. The lab's own research warns that
keyword guidance is a weak lever, so this gate is intentionally only a coarse
trivial-session filter, not a quality judge.
"""

from __future__ import annotations

from lore.schemas import NSFEvent

_CORRECTION = ("no,", "no.", "not right", "that's wrong", "that is wrong", "actually",
               "instead", "don't", "do not", "revert", "undo")
_ERROR = ("error", "failed", "failure", "exception", "traceback", "no such",
          "denied", "not found", "cannot", "can't")
_DECISION = ("let's go with", "lets go with", "we decided", "we chose", "decided to",
             "go with", "should we use", "we'll use", "we will use")
_GOTCHA = ("careful", "watch out", "gotcha", "fires twice", "double-fire", "race condition",
           "edge case", "footgun", "subtle", "beware")

_MARKERS = {
    "correction": _CORRECTION,
    "error": _ERROR,
    "decision": _DECISION,
    "gotcha": _GOTCHA,
}


def signal_reasons(events: list[NSFEvent]) -> list[str]:
    """Return the distinct signal categories present in a session, in fixed order."""
    found: set[str] = set()
    for ev in events:
        text = ev.content.lower()
        for reason, markers in _MARKERS.items():
            if any(m in text for m in markers):
                # Tool errors only count from tool output, not casual mentions.
                if reason == "error" and ev.kind != "tool_result":
                    continue
                found.add(reason)
    return [r for r in _MARKERS if r in found]


def session_has_signal(events: list[NSFEvent]) -> bool:
    return bool(signal_reasons(events))
