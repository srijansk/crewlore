"""LLM-backed claim extraction.

The model is the only non-deterministic part of the compiler, so it is injected
as a `complete(prompt) -> str` callable. Everything else here — prompt assembly,
JSON parsing, and the verbatim-anchor fidelity gate — is deterministic.

Fidelity gate: a claim's anchor is its proof. Every anchor quote must resolve
verbatim against the session transcript; anchors that don't are dropped, and a
claim left with no surviving anchor is rejected. A claim without a verifiable
anchor is a defect, not a low-confidence claim.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from pydantic import ValidationError

from lore.schemas import Anchor, Claim, NSFEvent, Provenance

Complete = Callable[[str], str]

_PROMPT_HEADER = """You extract reusable team tribal-knowledge claims from one coding-agent session.
Return ONLY a JSON array. Each item:
  {"statement": str, "kind": "decision"|"procedure"|"gotcha"|"style",
   "scope": str (repo path or area), "topic": str|null (short key grouping claims
   that answer the same question), "action": str|null (what a future session should DO),
   "anchors": [{"source_kind":"transcript","ref":str,"quote":str (VERBATIM excerpt)}]}
Rules: quotes must be copied verbatim from the transcript. Only emit claims that
would change a future session. If nothing is worth keeping, return [].
"""

_TOPIC_REUSE = """When a claim concerns the same question as an existing topic below, REUSE that
exact topic key (so disagreements about the same question can be detected). Existing topics:
{topics}
"""

_TRANSCRIPT = """
TRANSCRIPT:
"""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


class LLMExtractor:
    def __init__(
        self, complete: Complete, *, author: str = "unknown", harness: str = "claude-code"
    ):
        self._complete = complete
        self._author = author
        self._harness = harness

    def extract(
        self,
        events: list[NSFEvent],
        session_id: str,
        known_topics: list[str] | None = None,
    ) -> list[Claim]:
        transcript = self._render_transcript(events)
        prompt = _PROMPT_HEADER
        if known_topics:
            prompt += _TOPIC_REUSE.format(topics=", ".join(known_topics))
        prompt += _TRANSCRIPT + transcript
        raw = self._complete(prompt)
        items = _safe_json_array(raw)
        if not items:
            return []

        observed_at = self._latest_timestamp(events)
        haystack = _normalize(transcript)
        provenance = Provenance(session=session_id, author=self._author, harness=self._harness)

        claims: list[Claim] = []
        for item in items:
            claim = self._build_claim(item, provenance, observed_at, haystack)
            if claim is not None:
                claims.append(claim)
        return claims

    # --- internals ---
    @staticmethod
    def _render_transcript(events: list[NSFEvent]) -> str:
        return "\n".join(f"[{e.actor}/{e.kind}] {e.content}" for e in events)

    @staticmethod
    def _latest_timestamp(events: list[NSFEvent]):
        stamps = [e.timestamp for e in events if e.timestamp is not None]
        return max(stamps) if stamps else None

    def _build_claim(self, item, provenance, observed_at, haystack) -> Claim | None:
        verified = [
            Anchor(
                source_kind=a.get("source_kind", "transcript"),
                ref=a.get("ref", ""),
                quote=a["quote"],
            )
            for a in item.get("anchors", [])
            if a.get("quote") and _normalize(a["quote"]) in haystack
        ]
        if not verified:  # fidelity gate: no verbatim anchor -> reject
            return None
        try:
            return Claim(
                statement=item["statement"],
                kind=item["kind"],
                scope=item.get("scope", "."),
                topic=item.get("topic"),
                action=item.get("action"),
                provenance=provenance,
                anchors=verified,
                observed_at=observed_at,
            )
        except (ValidationError, KeyError):
            return None


def _safe_json_array(raw: str) -> list:
    if not isinstance(raw, str):
        return []
    data = _try_load(raw)
    if data is None:
        # Models often wrap the array in ```json ... ``` fences or surrounding
        # prose; fall back to the outermost [ ... ] span.
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end > start:
            data = _try_load(raw[start : end + 1])
    return data if isinstance(data, list) else []


def _try_load(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
