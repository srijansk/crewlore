"""GitHub pull-request capture adapter.

Maps one pull-request thread into the Normalized Session Format: **one PR is one
session**. Like every adapter this one is deliberately thin — it normalizes
faithfully and knows nothing about compile/serve.

Why this source exists at all: coding agents now author the majority of the
reasoning text in many repositories' PR threads. An agent-written PR body states
the intent, the alternatives it weighed, and the constraint it hit — detail human
authors historically never wrote down. That makes public PR threads a capture
surface with no local install, no per-developer transcript directory, and no
waiting for a team to generate sessions.

Two properties make PR threads a *better* NSF fit than transcripts:

* **Outcomes are labelled.** Merge, close, approval and change-request are
  ground truth, so the `accept`/`reject` event kinds carry real verdicts instead
  of sitting unused.
* **Review comments are pre-anchored.** An inline comment already names a
  `path` and `line`, which is exactly the shape `Anchor.ref` wants — provenance
  arrives for free rather than being reconstructed.

Agent-versus-human attribution is deliberately **not** decided here. Published
census work shows PR author fields alone badly undercount some agents (commit
trailers and config files catch adopters that PR metadata misses), so detection
belongs to the source layer that fetches threads. Records arriving without an
explicit `actor` are treated as human and tagged `attribution: unknown`, so a
mislabelling is auditable rather than silent.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from lore.capture.adapters._timestamps import parse_ts
from lore.schemas import NSFEvent

MANIFEST = {
    "harness": "github-pr",
    "log_location": "GitHub REST/GraphQL API, or an offline agent-PR dataset export",
    "session_hook": "one pull request thread = one session",
}

# Source vocabulary -> NSF actor. Anything unrecognised is handled by the caller
# so that the "unknown attribution" tag is applied exactly once.
_ACTOR = {"human": "user", "user": "user", "agent": "agent", "bot": "agent"}

_APPROVAL_VERDICT = {"APPROVED": "accept", "CHANGES_REQUESTED": "reject"}
_OUTCOME_VERDICT = {"merged": "accept", "closed": "reject"}


def pr_session_id(owner: str, repo: str, number: int | str) -> str:
    """Stable, filesystem-safe session id carrying the PR's coordinates.

    The store uses the session id as a filename stem, so the `owner/repo`
    slash cannot survive; `__` separates the three parts instead.
    """
    return f"pr_{owner}__{repo}__{number}"


class GitHubPRAdapter:
    name = "github-pr"
    manifest = MANIFEST

    def parse_records(self, records, session: str | None = None) -> list[NSFEvent]:
        records = list(records)
        sid = session or self._derive_session(records)
        thread_actor = self._thread_actor(records)
        # GitHub emits both `merged` and `closed` for a merged PR. Mapping each
        # record in isolation would append a `reject` after the `accept` and
        # invert the outcome label, so the close is suppressed when a merge exists.
        merged = any(
            r.get("type") == "timeline" and r.get("event") == "merged" for r in records
        )
        events: list[NSFEvent] = []
        for rec in records:
            events.extend(self._record_to_events(rec, sid, thread_actor, merged))
        return events

    def parse_transcript(self, path: Path | str, session: str | None = None) -> list[NSFEvent]:
        import json

        text = Path(path).read_text()
        records = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
        return self.parse_records(records, session=session)

    # --- internals ---
    @staticmethod
    def _derive_session(records) -> str:
        for rec in records:
            if rec.get("type") == "pr" and rec.get("repo"):
                owner, _, repo = str(rec["repo"]).partition("/")
                return pr_session_id(owner, repo or owner, rec.get("number", "0"))
        return "unknown"

    @staticmethod
    def _thread_actor(records) -> str | None:
        """The PR author's NSF actor, used to attribute branch commits."""
        for rec in records:
            if rec.get("type") == "pr" and rec.get("actor"):
                return _ACTOR.get(str(rec["actor"]).lower())
        return None

    def _record_to_events(
        self, rec: dict, sid: str, thread_actor: str | None, merged: bool
    ) -> list[NSFEvent]:
        rtype = rec.get("type")
        ts = parse_ts(rec.get("created_at"))

        if rtype == "issue":
            # The linked issue is the human's original request: the intent the
            # rest of the thread is answering.
            return self._message(rec, sid, ts, forced_actor="user")
        if rtype == "pr":
            # The PR's changed-file list rides on this event: the commit endpoint
            # does not carry per-commit files, so this is where the change's file
            # pointers enter the session.
            return self._message(
                rec, sid, ts, meta=self._agent_meta(rec), refs=list(rec.get("files") or [])
            )
        if rtype == "commit":
            return self._commit(rec, sid, ts, thread_actor)
        if rtype in ("comment", "review_comment"):
            return self._message(rec, sid, ts, refs=self._inline_ref(rec))
        if rtype == "review":
            return self._review(rec, sid, ts)
        if rtype == "check":
            return self._check(rec, sid, ts)
        if rtype == "timeline":
            return self._outcome(rec, sid, ts, merged)
        # labels, assignments, renames and the rest of the timeline are not
        # session knowledge.
        return []

    def _message(
        self,
        rec: dict,
        sid: str,
        ts: datetime,
        *,
        forced_actor: str | None = None,
        refs: list[str] | None = None,
        meta: dict | None = None,
    ) -> list[NSFEvent]:
        content = _text(rec)
        if not content:
            return []  # a blank body is not knowledge; storing it is pure noise
        actor, attribution = self._resolve_actor(rec, forced_actor)
        meta = dict(meta or {})
        if attribution:
            meta["attribution"] = attribution
        if login := rec.get("login"):
            meta["login"] = login
        return [
            NSFEvent(
                session=sid,
                actor=actor,
                kind="agent_message" if actor == "agent" else "user_message",
                timestamp=ts,
                content=content,
                refs=refs or [],
                meta=meta,
            )
        ]

    @staticmethod
    def _resolve_actor(rec: dict, forced: str | None) -> tuple[str, str | None]:
        if forced:
            return forced, None
        raw = rec.get("actor")
        if raw and (mapped := _ACTOR.get(str(raw).lower())):
            return mapped, None
        # Never guess agent-ness: default to human and record that we did.
        return "user", "unknown"

    @staticmethod
    def _agent_meta(rec: dict) -> dict:
        return {"agent": rec["agent"]} if rec.get("agent") else {}

    @staticmethod
    def _inline_ref(rec: dict) -> list[str]:
        path = rec.get("path")
        if not path:
            return []
        line = rec.get("line")
        return [f"{path}:{line}" if line is not None else str(path)]

    @staticmethod
    def _commit(rec: dict, sid: str, ts: datetime, thread_actor: str | None) -> list[NSFEvent]:
        message = (rec.get("message") or "").strip()
        if not message:
            return []
        # Branch commits belong to whoever opened the PR. An explicit actor wins;
        # otherwise inherit the thread, falling back to the agent since this
        # adapter's corpus is agent-authored pull requests.
        actor = _ACTOR.get(str(rec.get("actor", "")).lower()) or thread_actor or "agent"
        return [
            NSFEvent(
                session=sid,
                actor=actor,
                kind="diff",
                timestamp=ts,
                content=message,
                refs=list(rec.get("files") or []),
                meta={"sha": rec.get("sha")},
            )
        ]

    def _review(self, rec: dict, sid: str, ts: datetime) -> list[NSFEvent]:
        # The verdict and its rationale are separate knowledge: emit the body
        # first so a "changes requested" reason is never swallowed by the label.
        events = self._message(rec, sid, ts)
        verdict = _APPROVAL_VERDICT.get(str(rec.get("state", "")).upper())
        if verdict:
            actor, _ = self._resolve_actor(rec, None)
            events.append(
                NSFEvent(
                    session=sid,
                    actor=actor,
                    kind=verdict,
                    timestamp=ts,
                    content=str(rec.get("state", "")),
                    meta={"login": rec.get("login")},
                )
            )
        return events

    @staticmethod
    def _check(rec: dict, sid: str, ts: datetime) -> list[NSFEvent]:
        # CI output is mapped to `tool_result` because that is the only kind the
        # compile gate accepts an "error" signal from — a PR whose sole friction
        # was a red build would otherwise be ingested and never compiled.
        name = rec.get("name", "check")
        conclusion = rec.get("conclusion", "")
        body = (rec.get("output") or "").strip()
        content = f"{name}: {conclusion}"
        if body:
            content = f"{content}\n{body}"
        return [
            NSFEvent(
                session=sid,
                actor="system",
                kind="tool_result",
                timestamp=ts,
                content=content,
                meta={"check": name, "conclusion": conclusion},
            )
        ]

    @staticmethod
    def _outcome(rec: dict, sid: str, ts: datetime, merged: bool) -> list[NSFEvent]:
        event = str(rec.get("event", ""))
        if event == "closed" and merged:
            return []
        verdict = _OUTCOME_VERDICT.get(event)
        if not verdict:
            return []
        return [
            NSFEvent(
                session=sid,
                actor="system",
                kind=verdict,
                timestamp=ts,
                content=event,
                meta={"outcome": event},
            )
        ]


def _text(rec: dict) -> str:
    """Title + body, joined, with blank parts dropped."""
    parts = [str(rec.get("title") or "").strip(), str(rec.get("body") or "").strip()]
    return "\n\n".join(p for p in parts if p)
