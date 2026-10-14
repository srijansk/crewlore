"""Serve layer: task-conditioned retrieval + the knowledge book.

Every retrieval is *instrumented* (C0 lever 1): the store records that a claim was
served and, on feedback, whether it was influential or overridden. That usage
signal is what lets the actuation loop keep the store churning instead of growing
into a dumpyard. Retrieval ranks only `active` claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from lore.schemas import Anchor, Claim, Conflict
from lore.store import LoreStore
from lore.text import sanitize_line, sanitize_text

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


def anchor_to_dict(a: Anchor) -> dict:
    """The machine-readable shape of an anchor: ref, verbatim quote, and who wrote it."""
    return {
        "ref": sanitize_line(a.ref),
        "quote": sanitize_text(a.quote),
        "actor": a.actor,
        "login": sanitize_line(a.login) if a.login else None,
        "association": sanitize_line(a.association) if a.association else None,
    }


def claim_to_dict(c: Claim) -> dict:
    """The machine-readable shape of a claim, shared by `--json` output and the MCP tools.

    Model-written fields are cleaned single lines; anchor quotes keep their verbatim
    text apart from escape sequences and invisible characters.
    """
    return {
        "id": c.id,
        "statement": sanitize_line(c.statement),
        "kind": c.kind,
        "adoption": c.adoption,
        "scope": sanitize_line(c.scope),
        "topic": sanitize_line(c.topic) if c.topic else None,
        "action": sanitize_line(c.action) if c.action else None,
        "authority": c.authority,
        "anchors": [anchor_to_dict(a) for a in c.anchors],
    }


def conflict_to_dict(cf: Conflict) -> dict:
    return {"id": cf.id, "reason": sanitize_line(cf.reason), "claim_ids": list(cf.claim_ids)}


def scope_key(scope: str) -> str:
    """The identity of a scope for lookup: cleaned like the book's heading, slashes
    normalised, without a leading `./` or a trailing slash. `services/billing`,
    `services/billing/`, `.\\services\\billing` and a copy with a zero-width character
    inside are one scope to a reader, so they are one scope here."""
    cleaned = sanitize_line(scope).replace("\\", "/")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    # `./` and `.` both mean the whole repository, which the extractor writes as `.`.
    return cleaned.rstrip("/") or cleaned or "."


class ScopeIndex:
    """Active claims grouped by scope key, with the name a reader sees for each key.

    Stores compiled before claim text was cleaned at build time hold raw scopes, while
    the book prints them cleaned; resolving on the cleaned form is what makes "call
    again with one of the candidates" land on the scope the candidate named.
    """

    def __init__(self, claims: list[Claim]):
        self.by_key: dict[str, list[Claim]] = {}
        self.names: dict[str, str] = {}
        active = [c for c in claims if c.status == "active"]
        for c in sorted(active, key=lambda c: sanitize_line(c.scope)):
            key = scope_key(c.scope)
            self.by_key.setdefault(key, []).append(c)
            self.names.setdefault(key, sanitize_line(c.scope))

    def match(self, name: str) -> list[str]:
        """The scope names a typed name refers to.

        An exact match (in any spelling `scope_key` folds together) wins outright.
        Otherwise every scope whose name starts with the typed text, or failing that
        contains it, case-insensitively, is a candidate; the caller refuses to guess
        between several. A name that is empty or only separators matches nothing.
        """
        key = scope_key(name)
        if key in self.by_key:
            return [self.names[key]]
        needle = name.strip().casefold()
        if not needle.strip("/\\. "):
            return []
        names = sorted(self.names.values())
        prefixed = [n for n in names if n.casefold().startswith(needle)]
        if prefixed:
            return prefixed
        return [n for n in names if needle in n.casefold()]

    def claims(self, name: str) -> list[Claim]:
        """Active claims under one scope: current practice first, declined work after,
        each group by authority (highest first) and then id for a stable order."""
        chosen = self.by_key.get(scope_key(name), [])
        return sorted(chosen, key=lambda c: (c.adoption != "current", -c.authority, c.id))

    def narrower(self, name: str) -> list[str]:
        """Scopes nested under `name`, which an exact match would otherwise hide. The
        boundary is a slash, so `services/billing-v2` is not under `services/billing`;
        a prose scope that happens to start with the name and a slash is listed."""
        key = scope_key(name)
        prefix = key + "/"
        return sorted(self.names[k] for k in self.names if k != key and k.startswith(prefix))


def match_scopes(claims: list[Claim], name: str) -> list[str]:
    return ScopeIndex(claims).match(name)


def claims_in_scope(claims: list[Claim], scope: str) -> list[Claim]:
    return ScopeIndex(claims).claims(scope)


def narrower_scopes(claims: list[Claim], scope: str) -> list[str]:
    return ScopeIndex(claims).narrower(scope)


@dataclass
class Explanation:
    """What `explain` found for a name. Exactly one of these holds: `scope` is set (an
    answer), `candidates` is non-empty (the name was ambiguous), or neither (no match).
    The dict form always has the same keys, so a script never switches on shape."""

    scope: str | None = None
    claims: list[Claim] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    narrower: list[str] = field(default_factory=list)

    @property
    def answered(self) -> bool:
        return self.scope is not None

    def to_dict(self) -> dict:
        return {
            "scope": sanitize_line(self.scope) if self.scope else None,
            "claims": [claim_to_dict(c) for c in self.claims],
            "conflicts": [conflict_to_dict(cf) for cf in self.conflicts],
            "ambiguous": [sanitize_line(sc) for sc in self.candidates],
            "narrower": [sanitize_line(sc) for sc in self.narrower],
        }


def claim_label(c: Claim) -> str:
    """The bracketed tag a reader sees: the kind, plus a marker when the team
    declined what the claim describes, so a rejected approach is never mistaken
    for current practice at a glance."""
    return c.kind if c.adoption == "current" else f"{c.kind} · not adopted"


_ACTOR_WORD = {"user": "human", "agent": "agent", "system": "system"}


def anchor_attribution(a: Anchor) -> str:
    """Who wrote the quoted text, as a reader-facing phrase such as
    `@reviewer, human, member`; empty when the source recorded nothing."""
    parts = []
    login = sanitize_line(a.login) if a.login else ""
    if a.actor == "agent" and login:
        # Agent authorship is often detected from a commit trailer or body marker
        # while the account is a person's: say so rather than calling them the agent.
        parts.append(f"agent under @{login}")
    else:
        if login:
            parts.append(f"@{login}")
        if a.actor:
            parts.append(_ACTOR_WORD.get(a.actor, sanitize_line(a.actor)))
    if a.association:
        role = sanitize_line(a.association).lower().replace("_", " ")
        parts.append("no repository role" if role == "none" else role)
    return ", ".join(parts)


def render_book(claims: list[Claim], conflicts: list[Conflict]) -> str:
    """Render compiled claims as a human+agent-readable markdown book.

    Every model-written field and every quote is printed as one cleaned line, so a
    claim occupies exactly the lines the layout gives it and text inside a claim
    cannot pose as a second claim. Each anchor names who wrote the quoted text when
    the source recorded it.
    """
    lines = ["# Team knowledge (compiled by crewlore)", ""]
    by_scope: dict[str, list[Claim]] = {}
    for c in claims:
        if c.status == "active":
            by_scope.setdefault(sanitize_line(c.scope), []).append(c)

    for scope in sorted(by_scope):
        lines.append(f"## {scope}")
        lines.append("")
        for c in sorted(by_scope[scope], key=lambda x: x.id):
            lines.append(f"- **[{claim_label(c)}]** {sanitize_line(c.statement)}")
            if c.action:
                verb = "Do" if c.adoption == "current" else "Instead"
                lines.append(f"  - *{verb}:* {sanitize_line(c.action)}")
            for a in c.anchors:
                who = anchor_attribution(a)
                by = f" ({who})" if who else ""
                quote = sanitize_line(a.quote)
                lines.append(f"  - _anchor_ `{sanitize_line(a.ref)}`{by}: \"{quote}\"")
        lines.append("")

    if conflicts:
        lines.append("## Conflicts (unresolved disagreements)")
        lines.append("")
        for cf in conflicts:
            ids = ", ".join(cf.claim_ids)
            lines.append(f"- **{sanitize_line(cf.scope)}**: {sanitize_line(cf.reason)} ({ids})")
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

    def explain(self, name: str) -> Explanation:
        """Everything active under the scope `name` refers to, with the live conflicts
        recorded for it and the scopes nested under it, from one read of the store.

        Reading a scope is retrieval too, so its claims are marked served like a
        query's results, which also keeps them from decaying as unread. A name that
        matches several scopes, or none, marks nothing and answers nothing.
        """
        claims = self.store.load_claims()
        index = ScopeIndex(claims)
        candidates = index.match(name)
        if len(candidates) > 1:
            return Explanation(candidates=candidates)
        if not candidates:
            return Explanation()
        scope = candidates[0]
        chosen = index.claims(scope)
        served_ids = {c.id for c in chosen}
        now = datetime.now(timezone.utc)
        for c in claims:
            if c.id in served_ids:
                c.usage.times_served += 1
                c.usage.last_served_at = now
        self.store.write_claims(claims)
        # Conflicts are rewritten only by a compile, so one can outlive a side that the
        # lifecycle has since archived; show only those whose sides are still active.
        key = scope_key(scope)
        conflicts = [
            cf
            for cf in self.store.load_conflicts()
            if scope_key(cf.scope) == key and len(served_ids & set(cf.claim_ids)) >= 2
        ]
        by_id = {c.id: c for c in claims}
        return Explanation(
            scope=scope,
            claims=[by_id[c.id] for c in chosen],
            conflicts=conflicts,
            narrower=index.narrower(scope),
        )

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

    def _bump(self, claim_ids: list[str], counter: str) -> None:
        ids = set(claim_ids)
        claims = self.store.load_claims()
        for c in claims:
            if c.id in ids:
                setattr(c.usage, counter, getattr(c.usage, counter) + 1)
        self.store.write_claims(claims)
