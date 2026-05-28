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
    def extract(
        self,
        events: list[NSFEvent],
        session_id: str,
        known_topics: list[str] | None = None,
    ) -> list[Claim]: ...


class CompileResult(BaseModel):
    claims: list[Claim] = []
    conflicts: list[Conflict] = []


def compile_sessions(
    sessions: dict[str, list[NSFEvent]],
    extractor: Extractor,
    prior_claims: list[Claim] | None = None,
) -> CompileResult:
    candidates: list[Claim] = list(prior_claims or [])
    # Feed the existing topic vocabulary to the extractor so it reuses keys across
    # sessions; without this, the model invents a fresh topic per session and
    # genuinely-conflicting claims never group. Seed from prior claims, then grow.
    known_topics: set[str] = {c.topic for c in candidates if c.topic}
    for session_id, events in sessions.items():
        if session_has_signal(events):  # C0 lever 3: skip trivial sessions
            extracted = extractor.extract(events, session_id, sorted(known_topics))
            candidates.extend(extracted)
            known_topics.update(c.topic for c in extracted if c.topic)

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
    """Same scope + kind + topic, different claim ids => a recorded disagreement.

    Kind must match: a gotcha (the problem) and a decision (the fix) can share a
    topic without disagreeing, so conflicts are only sought within a single kind.
    """
    groups: dict[tuple[str, str, str], list[Claim]] = {}
    for c in claims:
        if c.topic is None:
            continue
        groups.setdefault((c.scope, c.kind, c.topic), []).append(c)

    conflicts: list[Conflict] = []
    for (scope, _kind, topic), members in groups.items():
        ids = sorted({m.id for m in members})
        # Require claims from ≥2 distinct sessions: a single session's
        # complementary findings under the same topic aren't disagreements,
        # they're a collected investigation. True conflicts surface across
        # sessions / authors.
        sessions = {m.provenance.session for m in members}
        if len(ids) >= 2 and len(sessions) >= 2:
            conflicts.append(
                Conflict(
                    scope=scope,
                    claim_ids=ids,
                    reason=f"Claims disagree on topic '{topic}' within {scope}.",
                    detected_at=_latest_observed(members),
                )
            )
    return conflicts
