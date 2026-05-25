"""The compiler — NSF events into compiled claims. This is the moat.

Pipeline stages: gate on signal -> extract candidate claims (LLM, behind a seam)
-> cluster & dedup -> detect conflicts (record, don't merge) -> score
authority/recency. The deterministic stages live here and are fully tested; only
extraction depends on a model, injected as an `Extractor`.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from lore.capture.signals import session_has_signal
from lore.schemas import Anchor, Claim, Conflict, NSFEvent

# Authority rises with the number of independent sessions that support a claim.
_AUTHORITY_BASE = 0.5
_AUTHORITY_PER_SUPPORT = 0.15
_AUTHORITY_CAP = 1.0


class Extractor(Protocol):
    def extract(self, events: list[NSFEvent], session_id: str) -> list[Claim]: ...


class CompileResult(BaseModel):
    claims: list[Claim] = []
    conflicts: list[Conflict] = []


def compile_sessions(
    sessions: dict[str, list[NSFEvent]],
    extractor: Extractor,
    prior_claims: list[Claim] | None = None,
) -> CompileResult:
    candidates: list[Claim] = list(prior_claims or [])
    for session_id, events in sessions.items():
        if session_has_signal(events):  # C0 lever 3: skip trivial sessions
            candidates.extend(extractor.extract(events, session_id))

    claims = _dedup_and_score(candidates)
    conflicts = _detect_conflicts(claims)
    return CompileResult(claims=claims, conflicts=conflicts)


def _dedup_and_score(candidates: list[Claim]) -> list[Claim]:
    """Cluster claims by content-addressed id; merge anchors, count support,
    keep the latest observation, and score authority by support count."""
    groups: dict[str, list[Claim]] = {}
    order: list[str] = []
    for c in candidates:
        if c.id not in groups:
            groups[c.id] = []
            order.append(c.id)
        groups[c.id].append(c)

    merged: list[Claim] = []
    for cid in order:
        members = groups[cid]
        support = len({m.provenance.session for m in members})
        base = members[0]
        merged.append(
            base.model_copy(
                update={
                    "anchors": _merge_anchors(members),
                    "observed_at": _latest_observed(members),
                    "authority": min(
                        _AUTHORITY_CAP,
                        _AUTHORITY_BASE + _AUTHORITY_PER_SUPPORT * (support - 1),
                    ),
                    "confidence": max(m.confidence for m in members),
                }
            )
        )
    return merged


def _merge_anchors(members: list[Claim]) -> list[Anchor]:
    seen: set[tuple[str, str]] = set()
    out: list[Anchor] = []
    for m in members:
        for a in m.anchors:
            key = (a.ref, a.quote)
            if key not in seen:
                seen.add(key)
                out.append(a)
    return out


def _latest_observed(members: list[Claim]):
    stamps = [m.observed_at for m in members if m.observed_at is not None]
    return max(stamps) if stamps else None


def _detect_conflicts(claims: list[Claim]) -> list[Conflict]:
    """Same scope + topic, different claim ids => a recorded disagreement."""
    groups: dict[tuple[str, str], list[Claim]] = {}
    for c in claims:
        if c.topic is None:
            continue
        groups.setdefault((c.scope, c.topic), []).append(c)

    conflicts: list[Conflict] = []
    for (scope, topic), members in groups.items():
        ids = sorted({m.id for m in members})
        if len(ids) >= 2:
            conflicts.append(
                Conflict(
                    scope=scope,
                    claim_ids=ids,
                    reason=f"Claims disagree on topic '{topic}' within {scope}.",
                    detected_at=_latest_observed(members),
                )
            )
    return conflicts
