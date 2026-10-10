"""The compiler — NSF events into compiled claims. This is where the value is made.

Pipeline stages: gate on signal -> extract candidate claims (LLM, behind a seam)
-> cluster & dedup -> detect conflicts (record, don't merge) -> score
authority/recency. The deterministic stages live here and are fully tested; only
extraction depends on a model, injected as an `Extractor`.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Protocol

from pydantic import BaseModel

from lore.capture.signals import session_has_signal
from lore.compile.extractor import FatalExtractionError
from lore.schemas import Anchor, Claim, Conflict, NSFEvent

# Authority rises with the number of independent sessions that support a claim.
_AUTHORITY_BASE = 0.5
_AUTHORITY_PER_SUPPORT = 0.15
_AUTHORITY_CAP = 1.0

# Evidence of disagreement. A shared (scope, kind, topic) says two claims answer
# the same question, not that they answer it differently: three gotchas that
# each say "contributor PRs must not touch .github/" share all three keys and
# agree. A conflict is recorded only for a cross-session pair carrying a marker
# the detector can read offline — an adoption split, or one claim's directive
# forbidding what the other's prescribes. Two bare answers with neither marker
# are deliberately not flagged; telling "a different answer" from "a different
# wording" needs a model, and guessing it from text is what over-flagged.

# A directive sentence forbids when it opens with one of these. The extractor
# writes actions as imperatives, so a prohibition sits at the head; a "not"
# further in is almost always a qualifier on an affirmative directive.
_FORBIDDING_OPENERS = (
    "do not", "don't", "never", "avoid", "must not", "mustn't",
    "should not", "shouldn't", "no longer",
)
# Function words carry no content for the overlap test.
_STOPWORDS = frozenset(
    "a an the this that these those it its in on at to of for from by with without into onto "
    "as and or but if then than so is are be been being was were do does did done not no any "
    "anything all every each some there here when where which who whom what how why your you "
    "we our us they them their he she his her i me my up out over under through before after "
    "during while also only just instead rather always ever still again must should can could "
    "would will may might have has had need needs needed".split()
)
# A forbidding sentence and a prescribing one are about the same thing when at
# least this share of the shorter one's content tokens appears in the other...
_OPPOSITION_MIN_OVERLAP = 0.6
# ...and each carries at least this many content tokens, so "Avoid it." matches nothing.
_OPPOSITION_MIN_TOKENS = 2

_SENTENCE_BREAK = re.compile(r"(?<=[.!?;])\s+")
_MARKUP = re.compile(r"[`*\[\]()\"]")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_./'-]*[a-z0-9]|[a-z0-9]")


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
    # Sessions whose extraction raised and were skipped. Reported rather than
    # hidden: "compiled nothing" and "compiled nothing because every session
    # failed" look identical to a user otherwise.
    failed_sessions: int = 0


def compile_sessions(
    sessions: dict[str, list[NSFEvent]],
    extractor: Extractor,
    prior_claims: list[Claim] | None = None,
) -> CompileResult:
    candidates: list[Claim] = list(prior_claims or [])
    failed = 0
    # Feed the existing topic vocabulary to the extractor so it reuses keys across
    # sessions; without this, the model invents a fresh topic per session and
    # genuinely-conflicting claims never group. Seed from prior claims, then grow.
    known_topics: set[str] = {c.topic for c in candidates if c.topic}
    for session_id, events in sessions.items():
        if not session_has_signal(events):  # C0 lever 3: skip trivial sessions
            continue
        try:
            extracted = extractor.extract(events, session_id, sorted(known_topics))
        except FatalExtractionError:
            # Bad credentials or a misconfigured provider will fail identically on
            # every remaining session. Continuing would report a successful run
            # that compiled nothing, so stop and let the caller explain why.
            raise
        except Exception:
            # One problematic session (oversized context, transient 429/500) must
            # not abort the whole compile — skip it and continue. Nothing is cached
            # on failure, so the next pass retries it. Mirrors ingest's defensive
            # per-file posture.
            failed += 1
            continue
        candidates.extend(extracted)
        known_topics.update(c.topic for c in extracted if c.topic)

    claims = _dedup_and_score(candidates)
    conflicts = _detect_conflicts(claims)
    return CompileResult(claims=claims, conflicts=conflicts, failed_sessions=failed)


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
                    "compiled_at": _earliest_compiled(members),
                    # Never below what the claim already earned: a teammate who
                    # compiles with no local sessions sees support=1 for every
                    # inherited claim and must not reset the whole store to base.
                    "authority": max(
                        base.authority,
                        min(
                            _AUTHORITY_CAP,
                            _AUTHORITY_BASE + _AUTHORITY_PER_SUPPORT * (support - 1),
                        ),
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


def _earliest_compiled(members: list[Claim]):
    """Keep the first time this claim entered the store.

    Re-observing a claim in a later session is corroboration, not usage, so it
    must not reset the unused-decay clock — otherwise a claim nobody ever reads
    stays active forever simply because it keeps being rediscovered.
    """
    stamps = [m.compiled_at for m in members if m.compiled_at is not None]
    return min(stamps) if stamps else None


def _detect_conflicts(claims: list[Claim]) -> list[Conflict]:
    """Same scope + kind + topic, claims from ≥2 sessions, and evidence that they
    disagree => a recorded disagreement.

    Kind must match: a gotcha (the problem) and a decision (the fix) can share a
    topic without disagreeing, so conflicts are only sought within a single kind.
    Sessions must differ: one session's complementary findings under a topic are
    a collected investigation, not a disagreement. And the pair must carry
    evidence (`_disagreement`), because sharing a topic only says the claims
    answer the same question.
    """
    groups: dict[tuple[str, str, str], list[Claim]] = {}
    for c in claims:
        if c.topic is None:
            continue
        groups.setdefault((c.scope, c.kind, c.topic), []).append(c)

    conflicts: list[Conflict] = []
    for (scope, _kind, topic), members in groups.items():
        evidence: list[str] = []
        involved: list[Claim] = []
        for a, b in combinations(members, 2):
            if a.id == b.id or a.provenance.session == b.provenance.session:
                continue
            found = _disagreement(a, b)
            if found:
                evidence.append(found)
                involved.extend((a, b))
        if evidence:
            conflicts.append(
                Conflict(
                    scope=scope,
                    claim_ids=sorted({c.id for c in involved}),
                    reason=(
                        f"Claims disagree on topic '{topic}' within {scope}: "
                        + "; ".join(evidence)
                        + "."
                    ),
                    detected_at=_latest_observed(involved),
                )
            )
    return conflicts


def _disagreement(a: Claim, b: Claim) -> str | None:
    """Why two claims on one question disagree, or None when nothing says they do."""
    if a.adoption != b.adoption:
        declined, current = (a, b) if a.adoption == "not_adopted" else (b, a)
        return (
            f"{declined.id} records the approach as not adopted "
            f"while {current.id} holds it current"
        )
    opposed = _opposed_directives(a, b)
    if opposed:
        forbids, prescribes = opposed
        return f"{forbids.id} forbids what {prescribes.id} prescribes"
    return None


def _opposed_directives(a: Claim, b: Claim) -> tuple[Claim, Claim] | None:
    """(forbidding claim, prescribing claim) when a sentence of one claim's
    directive forbids what a sentence of the other's prescribes, and the two
    oppose more closely than they agree — so "do not X; do Y" and "do Y" agree."""
    best_oppose, best_agree, pair = 0.0, 0.0, None
    directives_a, directives_b = _directives(a), _directives(b)
    for forbids_x, tokens_x in directives_a:
        for forbids_y, tokens_y in directives_b:
            overlap = _containment(tokens_x, tokens_y)
            if forbids_x == forbids_y:
                best_agree = max(best_agree, overlap)
            elif overlap > best_oppose:
                best_oppose, pair = overlap, ((a, b) if forbids_x else (b, a))
    if pair and best_oppose >= _OPPOSITION_MIN_OVERLAP and best_oppose > best_agree:
        return pair
    return None


def _directives(c: Claim) -> list[tuple[bool, frozenset[str]]]:
    """Each sentence of the claim's directive as (forbids?, content tokens).

    The action is the directive form; a claim without one falls back to its
    statement. Sentences too short to say what they are about are dropped.
    """
    out: list[tuple[bool, frozenset[str]]] = []
    for sentence in _SENTENCE_BREAK.split(c.action or c.statement):
        text = _MARKUP.sub(" ", sentence.lower()).lstrip(" -:;,.")
        forbids = False
        for opener in _FORBIDDING_OPENERS:
            after = text[len(opener):]
            if text.startswith(opener) and (not after or not after[0].isalnum()):
                forbids, text = True, after
                break
        tokens = frozenset(t for t in _TOKEN.findall(text) if t not in _STOPWORDS)
        if len(tokens) >= _OPPOSITION_MIN_TOKENS:
            out.append((forbids, tokens))
    return out


def _containment(x: frozenset[str], y: frozenset[str]) -> float:
    """Share of the smaller set's tokens that the other contains."""
    return len(x & y) / min(len(x), len(y))
