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


class FatalExtractionError(RuntimeError):
    """A failure that will recur on every session, so retrying is pointless.

    The compiler deliberately swallows per-session extraction errors — one
    oversized context or transient 429 must not abort a whole pass. Bad
    credentials look identical at the call site but are true of every session,
    and swallowing them turns a misconfigured key into a silent no-op: the run
    reports success, ingests sessions, and compiles nothing. This class marks the
    difference so the compiler can stop and say what is wrong.
    """

_PROMPT_HEADER = """You extract reusable team tribal-knowledge claims from one coding-agent session.
Return ONLY a JSON array. Each item:
  {"statement": str, "kind": "decision"|"procedure"|"gotcha"|"style",
   "adoption": "current"|"not_adopted",
   "scope": str (repo path or area), "topic": str|null (short key grouping claims
   that answer the same question), "action": str|null (what a future session should DO),
   "anchors": [{"source_kind":"transcript","ref":str,"quote":str (VERBATIM excerpt)}]}
Rules: quotes must be copied verbatim from the transcript. Only emit claims that
would change a future session.
Set "adoption" to "not_adopted" when the session shows the described approach was
declined, reverted, or otherwise not accepted; in that case phrase "statement" so
it records that the approach was tried and not adopted, and phrase "action" as
what a future session should do INSTEAD. Otherwise set "adoption" to "current".
If nothing is worth keeping, return [].
"""

_ADOPTION_VALUES = frozenset({"current", "not_adopted"})

_TOPIC_REUSE = """When a claim concerns the same question as an existing topic below, REUSE that
exact topic key (so disagreements about the same question can be detected). Existing topics:
{topics}
"""

_TRANSCRIPT = """
TRANSCRIPT:
"""


_MARKDOWN_DECORATION = re.compile(r"[`*_]")
_WHITESPACE = re.compile(r"\s+")


def _canonical_form(text: str) -> str:
    """The canonical form of a text string for fidelity comparison.

    The fidelity gate's contract is that a claim's anchor quote, after canonical
    normalization, resolves to a substring of the session's content after the
    same normalization. This is what "verbatim anchor" guarantees in crewlore.

    The canonical form applies three transformations, in order:

    1. **Strip Markdown decoration.** Agent prose in transcripts is written in
       Markdown — backticks around identifiers (``ApprovalRequiredToolset``),
       asterisks for **bold**, underscores for *italic*. The model intuitively
       drops these decoration markers when quoting, because they're formatting,
       not content. Both sides must drop them to compare semantic content.

    2. **Collapse whitespace.** All runs of whitespace (spaces, newlines, tabs)
       become a single space. This lets a quote span event boundaries — e.g.,
       a long agent reply punctuated by a tool call — and still match the
       continuous prose a human would read.

    3. **Lowercase.** Case is presentation, not content; lowercasing both sides
       prevents the model's occasional capitalization variance from killing
       legitimate quotes.

    What the canonical form does NOT do:
    - Strip ordinary punctuation (`.`, `,`, `:`, `;`, `?`, `!`, `()`, `[]`, `{}`)
    - Strip words (no stopword removal, no stemming)
    - Reorder tokens
    - Substitute synonyms

    So a quote that drops a meaningful word, paraphrases, or stitches disjoint
    substrings will still be rejected — the gate remains strict against
    fabrication. It is permissive only about presentation, not content.
    """
    text = _MARKDOWN_DECORATION.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    return text.strip().lower()


_LOCATOR_PROBE_CHARS = 40


class _LocatorIndex:
    """Resolves a verified quote to an addressable location in the session.

    Verbatim verification and addressability are different properties, and the
    fidelity gate only establishes the first: it proves the quote was really
    said, not where. Deriving the ref from the match closes that gap, so an
    anchor is something a reader can navigate to rather than a claim about
    provenance.

    Preference order for the ref, most navigable first:

    1. a file locator the event already carries (`path:line` on an inline review
       comment is the best pointer any source gives us),
    2. `<session>#event-<n>`, which resolves against the stored session file.
    """

    def __init__(self, events: list[NSFEvent], session_id: str):
        self._session = session_id
        self._events = events
        self._canonical = [_canonical_form(e.content) for e in events]

    def locate(self, quote: str) -> tuple[str, str]:
        canonical = _canonical_form(quote)
        position = self._find(canonical)
        if position is None:
            # The quote validated against the joined transcript but sits in no
            # single event — it spans a reply split by tool calls. The session
            # is still a true, resolvable location, so degrade to it rather than
            # inventing a pointer.
            return self._session, "transcript"
        event = self._events[position]
        if file_ref := self._file_ref(event):
            return file_ref, "file"
        return f"{self._session}#event-{position}", self._source_kind(event)

    def _find(self, canonical: str) -> int | None:
        for i, text in enumerate(self._canonical):
            if canonical and canonical in text:
                return i
        # A quote may straddle two events; fall back to whichever event opens it
        # so the reader still lands at the right place.
        probe = canonical[:_LOCATOR_PROBE_CHARS]
        if len(probe) < _LOCATOR_PROBE_CHARS:
            return None
        for i, text in enumerate(self._canonical):
            if probe in text:
                return i
        return None

    @staticmethod
    def _file_ref(event: NSFEvent) -> str | None:
        """The first ref that names a line in a file — the most precise pointer."""
        for ref in event.refs:
            if ":" in ref and not ref.startswith(("http://", "https://")):
                return ref
        return None

    @staticmethod
    def _source_kind(event: NSFEvent) -> str:
        return "diff" if event.kind == "diff" else "transcript"


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
        # Fidelity haystack reflects session *prose*, not prompt formatting.
        # We drop two things from it:
        #  - the `[actor/kind]` markers we render into the prompt for context
        #  - `tool_call` events (their content is just the tool *name*, e.g.
        #    "Read"/"Bash" — not prose; including it breaks substring matches
        #    when a long agent reply is split by a tool_call between segments)
        # The result: a quote that spans an agent reply punctuated by tool
        # calls still validates against the continuous prose.
        haystack = _canonical_form(
            "\n".join(e.content for e in events if e.kind != "tool_call")
        )
        provenance = Provenance(session=session_id, author=self._author, harness=self._harness)
        index = _LocatorIndex(events, session_id)

        claims: list[Claim] = []
        for item in items:
            claim = self._build_claim(item, provenance, observed_at, haystack, index)
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

    def _build_claim(self, item, provenance, observed_at, haystack, index) -> Claim | None:
        verified = []
        for a in item.get("anchors", []):
            quote = a.get("quote")
            if not quote or _canonical_form(quote) not in haystack:
                continue  # fidelity gate: the quote must appear verbatim
            # The ref is derived from where the quote actually resolved, never
            # taken from the model. A model-stated ref is unverified prose: it
            # produced things like "agent/agent_message" and section headings,
            # which read as provenance while pointing nowhere a reader can go.
            ref, source_kind = index.locate(quote)
            verified.append(Anchor(source_kind=source_kind, ref=ref, quote=quote))
        if not verified:  # fidelity gate: no verbatim anchor -> reject
            return None
        adoption = item.get("adoption", "current")
        if adoption not in _ADOPTION_VALUES:
            # Never coerce an unrecognised value to "current": turning a negative
            # the model tried to express into an affirmative is the exact
            # inversion the field exists to prevent. Losing the claim is safer.
            return None
        try:
            return Claim(
                statement=item["statement"],
                kind=item["kind"],
                adoption=adoption,
                scope=item.get("scope", "."),
                topic=item.get("topic"),
                action=item.get("action"),
                provenance=provenance,
                anchors=verified,
                observed_at=observed_at,
            )
        except (ValidationError, KeyError):
            return None


_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)\n\s*```", re.DOTALL)


def _safe_json_array(raw: str) -> list:
    if not isinstance(raw, str):
        return []
    # 1. Strict: response is pure JSON.
    data = _try_load(raw)
    # 2. Fenced: ```json ... ``` — handles prose with brackets around the fence.
    if data is None:
        m = _FENCE_RE.search(raw)
        if m:
            data = _try_load(m.group(1).strip())
    # 3. Last resort: the outermost [ ... ] span. Brittle if prose contains
    #    brackets; only reached when neither strict-parse nor fence extraction works.
    if data is None:
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end > start:
            data = _try_load(raw[start : end + 1])
    return data if isinstance(data, list) else []


def _try_load(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
