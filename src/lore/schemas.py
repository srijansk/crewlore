"""Core data model for agent-lore.

The compiled unit of knowledge is a `Claim` carrying provenance and verbatim
anchors. Claim identity is content-addressed (kind, scope, normalized statement)
so that compiling the same knowledge twice is idempotent and concurrent compiles
produce mergeable, collision-free IDs.

Every claim also carries the *actuation loop* state (`status`, `usage`, `action`)
from birth. A knowledge layer's value is an actuation property, not a storage
property: claims must be shaped to change a future session (`action`) and must be
subject to usage-driven lifecycle (`status`/`usage`) so the store churns instead
of growing into a dumpyard.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ClaimKind = Literal["decision", "procedure", "gotcha", "style"]
ClaimStatus = Literal["active", "archived", "superseded"]
Actor = Literal["user", "agent", "system"]


def _normalize_statement(text: str) -> str:
    """Lowercase + collapse whitespace so trivially-different phrasings hash equal."""
    return re.sub(r"\s+", " ", text).strip().lower()


def claim_id(kind: str, scope: str, statement: str) -> str:
    key = f"{kind}|{scope}|{_normalize_statement(statement)}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"clm_{digest}"


class NSFEvent(BaseModel):
    """Normalized Session Format event — the harness-agnostic capture unit.

    Adapters map one harness's raw artifacts (transcript turns, tool calls,
    diffs, accept/reject events) into a stream of these. Nothing downstream
    knows which harness produced a session.
    """

    session: str
    actor: Actor
    kind: str  # user_message | agent_message | tool_call | tool_result | diff | accept | reject
    timestamp: datetime
    content: str
    refs: list[str] = Field(default_factory=list)  # file:line or other source pointers
    meta: dict = Field(default_factory=dict)


class Provenance(BaseModel):
    session: str
    author: str
    harness: str
    run_id: str | None = None


class Anchor(BaseModel):
    source_kind: str  # transcript | diff | file
    ref: str  # e.g. "ses_1#turn-42" or "services/billing/webhook.py:88"
    quote: str  # verbatim excerpt — never a paraphrase

    @field_validator("quote")
    @classmethod
    def _quote_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("anchor quote must be a non-empty verbatim excerpt")
        return v


class UsageStats(BaseModel):
    """The actuation-loop instrument: how a claim has been used at serve time."""

    times_served: int = 0
    times_influential: int = 0
    times_overridden: int = 0
    last_served_at: datetime | None = None


class Claim(BaseModel):
    id: str = ""
    statement: str
    kind: ClaimKind
    scope: str
    # A short normalized key grouping claims that speak to the same question
    # (e.g. "ledger-db"). Same scope + topic, different statement => a conflict.
    # Deliberately excluded from the content-addressed id.
    topic: str | None = None
    # The actionable form — what a future session should *do*. A claim that cannot
    # be made actionable is dumpyard material and should be down-ranked or dropped.
    action: str | None = None
    provenance: Provenance
    anchors: list[Anchor] = Field(default_factory=list)
    authority: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    observed_at: datetime | None = None
    status: ClaimStatus = "active"
    usage: UsageStats = Field(default_factory=UsageStats)

    @model_validator(mode="after")
    def _derive_id(self) -> Claim:
        if not self.id:
            self.id = claim_id(self.kind, self.scope, self.statement)
        return self


class Conflict(BaseModel):
    """A first-class disagreement between claims. Conflicts are knowledge: we
    record them with both provenances rather than silently overwriting."""

    id: str = ""
    scope: str
    claim_ids: list[str] = Field(min_length=2)
    reason: str
    detected_at: datetime | None = None

    @model_validator(mode="after")
    def _derive_id(self) -> Conflict:
        if not self.id:
            key = "|".join(sorted(self.claim_ids))
            digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
            self.id = f"cfl_{digest}"
        return self
