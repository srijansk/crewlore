"""Success-criteria measurement: fidelity + held-out replay.

These are the two numbers that decide whether `lore` works:

1. fidelity — does the compiler lie? Every claim's anchor must resolve verbatim
   against its source. A claim without a verifiable anchor is a defect.
2. preventable-rediscovery rate — does the knowledge actuate? Replay the actual
   post-cutoff sessions and count how many re-derived something a prior claim
   already knew. This measures value, not quiz-passing, and runs offline on a
   real (ideally public) repo's session history.
"""

from __future__ import annotations

from pydantic import BaseModel

# Reuse the compile-time gate's canonical form so the *reported* fidelity number
# uses exactly the contract the gate enforces (Markdown-decoration tolerance,
# whitespace collapse, case-folding) — one definition of "verbatim", not two.
from lore.compile.extractor import _canonical_form
from lore.schemas import Claim, NSFEvent
from lore.serve.server import rank_claims


class FidelityReport(BaseModel):
    rate: float
    total: int
    defects: list[str] = []  # ids of claims with an unresolvable anchor


class ReplayReport(BaseModel):
    total: int
    preventable: int
    rate: float
    hits: dict[str, str] = {}  # session_id -> matched prior claim id


def fidelity_report(claims: list[Claim], source_text: str) -> FidelityReport:
    haystack = _canonical_form(source_text)
    defects: list[str] = []
    for c in claims:
        ok = bool(c.anchors) and all(_canonical_form(a.quote) in haystack for a in c.anchors)
        if not ok:
            defects.append(c.id)
    total = len(claims)
    rate = (total - len(defects)) / total if total else 1.0
    return FidelityReport(rate=rate, total=total, defects=defects)


def replay_report(
    prior_claims: list[Claim],
    post_sessions: dict[str, list[NSFEvent]],
) -> ReplayReport:
    hits: dict[str, str] = {}
    for session_id, events in post_sessions.items():
        query = " ".join(e.content for e in events)
        matched = rank_claims(prior_claims, query, limit=1)
        if matched:
            hits[session_id] = matched[0].id
    total = len(post_sessions)
    preventable = len(hits)
    rate = preventable / total if total else 0.0
    return ReplayReport(total=total, preventable=preventable, rate=rate, hits=hits)
