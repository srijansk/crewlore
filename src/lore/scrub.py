"""Secret scrubbing, applied at ingest time.

Anchors are verbatim transcript excerpts and the store is committed plaintext, so
secrets printed during a session must never get that far. Scrubbing before the
session is written means secrets never reach the LLM, the anchors, or git. This
is the cheap, automated half of the human review / leakage gate (review C3/C4);
an explicit human review step is the stronger complement.

Both message *content* and event *meta* (where tool-call arguments live — e.g. a
Bash command carrying a token) are scrubbed, recursively. Deliberately
conservative: a set of high-precision patterns, replaced with a labelled token.
Not a DLP system — it raises the floor, it is not the gate. See docs/scrub.md for
the full coverage contract, including what is intentionally NOT redacted.
"""

from __future__ import annotations

import re

from lore.schemas import NSFEvent

_PRIVATE_KEY = r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"
_URI_WITH_PASSWORD = (
    r"(?P<scheme>postgres|postgresql|mongodb|mysql|redis|amqp|amqps|mssql)"
    r"://(?P<user>[^:/\s@]+):(?P<pwd>[^@\s]+)@"
)
# Generic assignment shapes. Matches `keyword = value`, where value is either a
# quoted string (allowing spaces — multi-word passphrases) or a bare token.
# The (?!\[REDACTED) lookaheads leave already-redacted markers alone so a
# more-specific pattern's label isn't overwritten by the generic one.
_ASSIGNMENT = (
    r"(?i)(?:password|passwd|secret|token|api[_-]?key"
    r"|aws_secret_access_key|aws_session_token)\s*[:=]\s*"
    r"(?:"
    r'"(?!\[REDACTED)[^"\n]{4,}"'      # double-quoted (spaces ok)
    r"|'(?!\[REDACTED)[^'\n]{4,}'"     # single-quoted
    r"|(?!\[REDACTED)[^\s'\"]{6,}"     # bare token
    r")"
)

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Long, high-precision shapes first so partial matches don't pre-empt them.
    (re.compile(_PRIVATE_KEY, re.DOTALL), "[REDACTED:private-key]"),
    # OpenAI / Anthropic / generic `sk-*` API keys.
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "[REDACTED:api-key]"),
    # AWS access-key IDs: AKIA (long-term) and ASIA (STS temporary).
    (re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"), "[REDACTED:aws-key]"),
    # GitHub classic personal access token.
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED:github-token]"),
    # GitHub fine-grained PAT (current spec: ≥82 chars; allow ≥22 for fwd-compat).
    (re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), "[REDACTED:github-token]"),
    # Google API key (AIza + 35 chars).
    (re.compile(r"AIza[A-Za-z0-9_\-]{35}"), "[REDACTED:google-api-key]"),
    # Slack tokens — bot/user/app/refresh/config/etc. all share the xox?- prefix.
    (re.compile(r"xox[a-z]-[A-Za-z0-9\-]{10,}"), "[REDACTED:slack-token]"),
    # HuggingFace user-access tokens.
    (re.compile(r"hf_[A-Za-z0-9]{30,}"), "[REDACTED:hf-token]"),
    # JWT (three base64url segments joined by dots, starting with eyJ — base64 of `{"`).
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "[REDACTED:jwt]"),
    # Connection-string passwords (scheme://user:PASSWORD@host). Preserves scheme + user.
    (re.compile(_URI_WITH_PASSWORD), r"\g<scheme>://\g<user>:[REDACTED:uri-password]@"),
    # Generic assignment shapes — last so a more specific pattern can claim the value first.
    (re.compile(_ASSIGNMENT), "[REDACTED:secret]"),
]


def scrub_text(text: str) -> tuple[str, int]:
    """Return (scrubbed_text, number_of_redactions)."""
    redactions = 0
    for pattern, replacement in _PATTERNS:
        text, n = pattern.subn(replacement, text)
        redactions += n
    return text, redactions


def _scrub_obj(obj):
    """Recursively scrub string leaves in a nested structure (dict/list/str).

    Tool-call arguments arrive as `meta={"input": {...}}`, so a secret passed to,
    say, a Bash command lives inside a nested dict. Return (scrubbed_obj, count).
    """
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, list):
        out, total = [], 0
        for item in obj:
            scrubbed, n = _scrub_obj(item)
            out.append(scrubbed)
            total += n
        return out, total
    if isinstance(obj, dict):
        out, total = {}, 0
        for key, value in obj.items():
            scrubbed, n = _scrub_obj(value)
            out[key] = scrubbed
            total += n
        return out, total
    return obj, 0  # numbers, bools, None — nothing to scrub


def scrub_events(events: list[NSFEvent]) -> tuple[list[NSFEvent], int]:
    """Return (scrubbed_events, total_redactions). Both `content` and `meta` are
    rewritten — tool-call arguments in `meta` are exactly where secrets hide."""
    out: list[NSFEvent] = []
    total = 0
    for ev in events:
        scrubbed_content, nc = scrub_text(ev.content)
        scrubbed_meta, nm = (_scrub_obj(ev.meta) if ev.meta else (ev.meta, 0))
        n = nc + nm
        total += n
        if n:
            out.append(
                ev.model_copy(update={"content": scrubbed_content, "meta": scrubbed_meta})
            )
        else:
            out.append(ev)
    return out, total
