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
_URI_WITH_PASSWORD = (
    r"(?P<scheme>postgres|postgresql|mongodb|mysql|redis|amqp|amqps|mssql)"
    r"://(?P<user>[^:/\s@]+):(?P<pwd>[^@\s]+)@"
)

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Long, high-precision shapes first so partial matches don't pre-empt them.
    (re.compile(_PRIVATE_KEY, re.DOTALL), "[REDACTED:private-key]"),
    # OpenAI / Anthropic / generic `sk-*` API keys.
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "[REDACTED:api-key]"),
    # AWS Access Key ID.
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:aws-key]"),
    # GitHub classic personal access token.
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED:github-token]"),
    # GitHub fine-grained PAT (current spec: ≥82 chars; allow ≥22 for fwd-compat).
    (re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), "[REDACTED:github-token]"),
    # Google API key (AIza + 35 chars).
    (re.compile(r"AIza[A-Za-z0-9_\-]{35}"), "[REDACTED:google-api-key]"),
    # Slack tokens (bot, user, app, refresh, app-level — all share the xox?- prefix).
    (re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED:slack-token]"),
    # HuggingFace user-access tokens.
    (re.compile(r"hf_[A-Za-z0-9]{30,}"), "[REDACTED:hf-token]"),
    # JWT (three base64url segments joined by dots, starting with eyJ — base64 of `{"`).
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "[REDACTED:jwt]"),
    # Connection-string passwords (scheme://user:PASSWORD@host). Preserves scheme + user.
    (re.compile(_URI_WITH_PASSWORD), r"\g<scheme>://\g<user>:[REDACTED:uri-password]@"),
    # Generic assignment shapes — last so a more specific pattern can claim the value first.
    # The (?!\[REDACTED) lookahead leaves already-redacted markers alone so we don't relabel
    # e.g. `[REDACTED:slack-token]` back to the less-specific `[REDACTED:secret]`.
    (re.compile(
        r"(?i)(?:password|secret|token|api[_-]?key)\s*[:=]\s*(?!\[REDACTED)['\"]?[^\s'\"]{6,}"
    ), "[REDACTED:secret]"),
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
