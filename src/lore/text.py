"""Text hygiene for model output and for anything handed to a person or an agent.

Claims are written by a model from transcripts and pull-request threads that other
people and tools wrote. Control characters and terminal escape sequences in that text
would survive into the book, the CLI output and the MCP payload, where they can hide
content or restyle a terminal. They carry no knowledge, so they are removed at the
point a claim is built and again at the point it is served.
"""

from __future__ import annotations

import re

# ANSI escape sequences (colours, cursor moves, OSC hyperlinks), then any remaining
# C0 control character except newline and tab, plus DEL.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str, *, limit: int | None = None) -> str:
    """Strip escape sequences and control characters; optionally cap the length."""
    cleaned = _CONTROL.sub("", _ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n"))
    if limit is not None and len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + "…"
    return cleaned
