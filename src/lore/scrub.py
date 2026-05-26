"""Secret scrubbing, applied at ingest time.

Anchors are verbatim transcript excerpts and the store is committed plaintext, so
secrets printed during a session must never get that far. Scrubbing before the
session is written means secrets never reach the LLM, the anchors, or git. This
is the cheap, automated half of the human review / leakage gate (review C3/C4);
an explicit human review step is the stronger complement.

Deliberately conservative: a handful of high-precision patterns, replaced with a
labelled token. Not a DLP system — it raises the floor, it is not the gate.
"""

from __future__ import annotations

import re

from lore.schemas import NSFEvent

_PRIVATE_KEY = r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(_PRIVATE_KEY, re.DOTALL), "[REDACTED:private-key]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "[REDACTED:api-key]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:aws-key]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED:github-token]"),
    (re.compile(r"(?i)(?:password|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
     "[REDACTED:secret]"),
]


def scrub_text(text: str) -> tuple[str, int]:
    """Return (scrubbed_text, number_of_redactions)."""
    redactions = 0
    for pattern, replacement in _PATTERNS:
        text, n = pattern.subn(replacement, text)
        redactions += n
    return text, redactions


def scrub_events(events: list[NSFEvent]) -> tuple[list[NSFEvent], int]:
    """Return (scrubbed_events, total_redactions). Only `content` is rewritten."""
    out: list[NSFEvent] = []
    total = 0
    for ev in events:
        scrubbed, n = scrub_text(ev.content)
        total += n
        out.append(ev.model_copy(update={"content": scrubbed}) if n else ev)
    return out, total
