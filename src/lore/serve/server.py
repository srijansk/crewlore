"""Serve layer: task-conditioned retrieval + the knowledge book.

Every retrieval is *instrumented* (C0 lever 1): the store records that a claim was
served and, on feedback, whether it was influential or overridden. That usage
signal is what lets the actuation loop keep the store churning instead of growing
into a dumpyard. Retrieval ranks only `active` claims.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from lore.schemas import Claim, Conflict
from lore.store import LoreStore

# Common words carry no retrieval signal and cause false matches across unrelated
# topics (the lab's concept-vs-identifier-vocabulary observation). Drop them so
# overlap reflects shared *concepts*, not shared grammar.
_STOPWORDS = frozenset(
    """a an and are as at be by do does for from how i in into is it its of on or that the
    their then there these this to was we what when where which who why will with you your
    not no don't can cannot need use using configure again do""".split()
)


def _tokens(text: str) -> set[str]:
    return {
        t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in _STOPWORDS
    }


def _claim_text(c: Claim) -> str:
    return " ".join(filter(None, [c.statement, c.scope, c.topic or "", c.action or ""]))


def rank_claims(claims: list[Claim], query: str, limit: int = 5) -> list[Claim]:
    """Pure relevance ranking over active claims. No side effects."""
    q = _tokens(query)
    scored: list[tuple[int, float, Claim]] = []
    for c in claims:
        if c.status != "active":
            continue
        overlap = len(q & _tokens(_claim_text(c)))
        if overlap > 0:
            scored.append((overlap, c.authority, c))
    scored.sort(key=lambda t: (t[0], t[1], t[2].id), reverse=True)
    return [c for _, _, c in scored[:limit]]


def render_book(claims: list[Claim], conflicts: list[Conflict]) -> str:
    """Render compiled claims as a human+agent-readable markdown book."""
    lines = ["# Team knowledge (compiled by agent-lore)", ""]
    by_scope: dict[str, list[Claim]] = {}
    for c in claims:
        if c.status == "active":
            by_scope.setdefault(c.scope, []).append(c)

    for scope in sorted(by_scope):
        lines.append(f"## {scope}")
        lines.append("")
        for c in sorted(by_scope[scope], key=lambda x: x.id):
            lines.append(f"- **[{c.kind}]** {c.statement}")
            if c.action:
                lines.append(f"  - *Do:* {c.action}")
            for a in c.anchors:
                lines.append(f"  - _anchor_ `{a.ref}`: \"{a.quote}\"")
        lines.append("")

    if conflicts:
        lines.append("## Conflicts (unresolved disagreements)")
        lines.append("")
        for cf in conflicts:
            lines.append(f"- **{cf.scope}**: {cf.reason} ({', '.join(cf.claim_ids)})")
        lines.append("")

    return "\n".join(lines)


class KnowledgeServer:
    def __init__(self, store: LoreStore):
        self.store = store

    def query(self, text: str, limit: int = 5) -> list[Claim]:
        claims = self.store.load_claims()
        ranked = rank_claims(claims, text, limit=limit)
        served_ids = {c.id for c in ranked}
        now = datetime.now(timezone.utc)
        for c in claims:
            if c.id in served_ids:
                c.usage.times_served += 1
                c.usage.last_served_at = now
        self.store.write_claims(claims)
        # Return the freshly-incremented claim objects, preserving rank order.
        by_id = {c.id: c for c in claims}
        return [by_id[c.id] for c in ranked]

    def mark_influential(self, claim_ids: list[str]) -> None:
        self._bump(claim_ids, "times_influential")

    def mark_overridden(self, claim_ids: list[str]) -> None:
        self._bump(claim_ids, "times_overridden")

    def write_book(self) -> str:
        claims = self.store.load_claims()
        conflicts = self.store.load_conflicts()
        book = render_book(claims, conflicts)
        path = self.store.lore / "knowledge" / "README.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(book)
        return book

    def _bump(self, claim_ids: list[str], field: str) -> None:
        ids = set(claim_ids)
        claims = self.store.load_claims()
        for c in claims:
            if c.id in ids:
                setattr(c.usage, field, getattr(c.usage, field) + 1)
        self.store.write_claims(claims)
