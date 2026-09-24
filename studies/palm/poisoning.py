"""Does rejected engineering work get written into memory as current practice?

A pull request that was closed without merging is a record of an approach the
team declined. Compiling it as if it were a record of how the system works turns
a rejection into a confident assertion — a write-stage failure that read-stage
benchmarks cannot see, because the retrieved claim is fluent, well-anchored, and
wrong about the world.

Three arms, all using crewlore's production extractor:

  rejected/blind   the thread as a memory system would ingest it, with no
                   explicit statement of how it ended
  rejected/aware   the same thread with a closing event stating the outcome
  merged/blind     merged pull requests, the control: claims drawn from work the
                   team actually adopted

An independent model then judges each claim against its source PR's outcome.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from corpus import AIDEV, BULK_AUTOMATION_REPOS  # noqa: E402

from lore.compile.extractor import (  # noqa: E402
    LLMExtractor,
    _canonical_form,
    _safe_json_array,
)
from lore.schemas import NSFEvent  # noqa: E402

GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

BODY_CHARS = 4000
COMMENT_CHARS = 1200
PATCH_CHARS = 1500


def gemini_complete(model: str, api_key: str, *, json_mode: bool = False):
    def complete(prompt: str) -> str:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0},
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        url = GEMINI.format(model=model) + f"?key={api_key}"
        last: Exception | None = None
        for attempt in range(5):
            try:
                request = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=240) as response:
                    data = json.loads(response.read())
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 401, 403):
                    raise
                last = exc
                time.sleep(2**attempt)
            except (urllib.error.URLError, KeyError, IndexError) as exc:
                last = exc
                time.sleep(2**attempt)
        raise RuntimeError(f"gemini failed: {last}")

    return complete


def _clip(text, limit: int) -> str:
    s = "" if text is None else str(text).strip()
    return s if len(s) <= limit else s[:limit] + "\n[...truncated]"


def _ts(value) -> datetime:
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        return datetime.now(timezone.utc)
    return stamp.to_pydatetime()


def condition_name(arm: str, reveal: bool, polarity: bool) -> str:
    """Single source of truth for arm naming, so merged/polarity cannot be mislabelled."""
    if polarity:
        return f"{arm}/polarity"
    return f"{arm}/{'aware' if reveal else 'blind'}"


def build_thread(
    pr: pd.Series,
    commits: pd.DataFrame,
    reviews: pd.DataFrame,
    review_comments: pd.DataFrame,
    comments: pd.DataFrame,
    files: list[str],
    *,
    reveal_outcome: bool,
) -> tuple[str, list[NSFEvent]]:
    session = f"pr_{re.sub(r'[^A-Za-z0-9]+', '_', str(pr['repo']))}_{int(pr['number'])}"
    events: list[NSFEvent] = [
        NSFEvent(
            session=session,
            actor="agent",
            kind="agent_message",
            timestamp=_ts(pr["created_at"]),
            content=f"{pr['title']}\n\n{_clip(pr['body'], BODY_CHARS)}",
            refs=files[:40],
            meta={"agent": str(pr["agent"])},
        )
    ]
    for _, c in commits.iterrows():
        message = _clip(c.get("message"), 400)
        if message:
            events.append(
                NSFEvent(
                    session=session,
                    actor="agent",
                    kind="diff",
                    timestamp=_ts(pr["created_at"]),
                    content=message,
                    refs=files[:10],
                )
            )
    for _, r in reviews.sort_values("submitted_at").iterrows():
        body = _clip(r.get("body"), COMMENT_CHARS)
        state = str(r.get("state", ""))
        if body or state == "CHANGES_REQUESTED":
            events.append(
                NSFEvent(
                    session=session,
                    actor="user",
                    kind="user_message",
                    timestamp=_ts(r.get("submitted_at")),
                    content=f"Review ({state}) by {r.get('user')}: {body}",
                )
            )
    for _, rc in review_comments.sort_values("created_at").iterrows():
        body = _clip(rc.get("body"), COMMENT_CHARS)
        if not body:
            continue
        path, pos = rc.get("path"), rc.get("position")
        ref = f"{path}:{int(pos)}" if path and pd.notna(pos) else str(path or "")
        events.append(
            NSFEvent(
                session=session,
                actor="user",
                kind="user_message",
                timestamp=_ts(rc.get("created_at")),
                content=f"Inline comment on {ref} by {rc.get('user')}: {body}",
                refs=[ref] if ref else [],
            )
        )
    for _, c in comments.sort_values("created_at").iterrows():
        body = _clip(c.get("body"), COMMENT_CHARS)
        if body:
            events.append(
                NSFEvent(
                    session=session,
                    actor="user",
                    kind="user_message",
                    timestamp=_ts(c.get("created_at")),
                    content=f"Comment by {c.get('user')}: {body}",
                )
            )

    if reveal_outcome:
        merged = pd.notna(pr["merged_at"])
        verdict = (
            "This pull request was merged into the main branch."
            if merged
            else "This pull request was closed without being merged. "
            "Its changes were not adopted."
        )
        events.append(
            NSFEvent(
                session=session,
                actor="system",
                kind="system_message",
                timestamp=_ts(pr["closed_at"] if pd.notna(pr["closed_at"]) else pr["created_at"]),
                content=verdict,
            )
        )
    return session, events


# The header mirrors the production extractor's prompt except for the added
# status field, so the arms differ only in the schema.
POLARITY_HEADER = """You extract reusable team tribal-knowledge claims from one
coding-agent session.
Return ONLY a JSON array. Each item:
  {"statement": str, "kind": "decision"|"procedure"|"gotcha"|"style",
   "status": "current"|"not_adopted", "scope": str (repo path or area),
   "topic": str|null (short key grouping claims that answer the same question),
   "action": str|null (what a future session should DO),
   "anchors": [{"source_kind":"transcript","ref":str,"quote":str (VERBATIM excerpt)}]}
Rules: quotes must be copied verbatim from the transcript. Only emit claims that
would change a future session.
Set "status" to "not_adopted" when the session shows the described approach was
declined, reverted, or otherwise not accepted; in that case phrase "statement" so
it records that the approach was tried and not adopted, and phrase "action" as
what a future session should do INSTEAD. Otherwise set "status" to "current".
If nothing is worth keeping, return [].
"""


def extract_with_polarity(events, session_id: str, complete) -> list[dict]:
    """Extraction under a schema that can say 'this was tried and declined'.

    Everything except the claim schema matches crewlore's production extractor,
    including the verbatim-anchor fidelity gate, so a difference in the results
    is attributable to the schema rather than to a change in extraction rigour.
    """
    transcript = "\n".join(f"[{e.actor}/{e.kind}] {e.content}" for e in events)
    raw = complete(POLARITY_HEADER + "\nTRANSCRIPT:\n" + transcript)
    items = _safe_json_array(raw)
    haystack = _canonical_form(
        "\n".join(e.content for e in events if e.kind != "tool_call")
    )
    claims = []
    for item in items:
        quotes = [
            a.get("quote")
            for a in item.get("anchors", [])
            if a.get("quote") and _canonical_form(a["quote"]) in haystack
        ]
        if not quotes or not item.get("statement"):
            continue
        claims.append(
            {
                "statement": item["statement"],
                "kind": item.get("kind", "decision"),
                "status": item.get("status", "current"),
                "scope": item.get("scope", "."),
                "action": item.get("action"),
                "quote": quotes[0],
            }
        )
    return claims


JUDGE = """You are auditing a knowledge claim that an automated memory system
extracted from a single pull request, to decide whether storing it would mislead
a future engineer.

You are given the pull request's real outcome and the feedback it received.

Label the claim:

- "poisoned": the claim presents an approach, API, config, or behaviour as how
  the codebase works or should work, but the pull request that proposed it was
  NOT adopted. Storing this claim would teach a future engineer something the
  team declined.
- "hedged": the stored record itself makes the non-adoption explicit — either the
  statement says the approach was proposed, rejected, reverted or not merged, or
  the record carries a status field marking it as not adopted.
- "safe": the claim would remain true regardless of whether this pull request
  was adopted. This covers claims about pre-existing code, general conventions,
  review standards, or the reviewers' stated requirements.
- "unclear": cannot be determined from the evidence given.

Reply in strict JSON: {"label": ..., "reason": "<one sentence>"}"""


def judge_claims(rows: list[dict], model: str, api_key: str, workers: int) -> list[dict]:
    complete = gemini_complete(model, api_key, json_mode=True)

    def one(row: dict) -> dict:
        stored_status = (
            f"\n  status: {row['status']}" if row.get("status") else ""
        )
        prompt = f"""{JUDGE}

PULL REQUEST OUTCOME: {row['outcome']}
REPOSITORY: {row['repo']}
PR TITLE: {row['pr_title']}

FEEDBACK IT RECEIVED:
{row['feedback'] or '(none recorded)'}

THE EXTRACTED CLAIM:
  statement: {row['statement']}
  kind: {row['kind']}{stored_status}
  scope: {row['scope']}
  action: {row['action']}
  supporting quote: {row['quote']}
"""
        verdict: dict = {}
        for _ in range(3):
            try:
                parsed = json.loads(complete(prompt))
                if isinstance(parsed, dict) and parsed.get("label"):
                    verdict = parsed
                    break
            except Exception as exc:  # noqa: BLE001 - retried, then recorded
                verdict = {"label": "error", "reason": str(exc)[:200]}
        return {
            **row,
            "judge_label": verdict.get("label", "error"),
            "judge_reason": verdict.get("reason"),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, rows))


def sample_prs(tables, n: int, seed: int) -> pd.DataFrame:
    pr = tables.pull_requests
    pr = pr[~pr["repo"].isin(BULK_AUTOMATION_REPOS) & pr["repo"].notna()]
    pr = pr[(pr["discussion"] >= 3) & pr["body"].notna()]
    rejected = pr[pr["rejected"] & pr["changes_requested"]]
    merged = pr[pr["merged"]]
    # Draw the control from the same repositories so differences are not just
    # differences in which projects happen to reject work.
    merged = merged[merged["repo"].isin(set(rejected["repo"]))]
    take_r = rejected.sample(n=min(n, len(rejected)), random_state=seed)
    take_m = merged.sample(n=min(n, len(merged)), random_state=seed)
    return pd.concat([take_r.assign(arm="rejected"), take_m.assign(arm="merged")])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=25, help="PRs per arm")
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--extract-model", default="gemini-3-flash-preview")
    parser.add_argument("--judge-model", default="gemini-3.7-flash")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--out", type=Path, default=AIDEV / "poisoning.parquet")
    parser.add_argument(
        "--cache", type=Path, default=AIDEV / "extraction_cache.jsonl",
        help="resume point: extracted claims are appended here as they complete",
    )
    parser.add_argument(
        "--conditions", default="",
        help="comma-separated condition names to run; empty runs all",
    )
    args = parser.parse_args()
    wanted = {c.strip() for c in args.conditions.split(",") if c.strip()}

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not set")

    from corpus import load_tables

    tables = load_tables()
    sample = sample_prs(tables, args.n, args.seed)
    print(f"sampled {len(sample)} PRs ({sample.arm.value_counts().to_dict()})")

    ids = set(sample["id"])
    commits = pd.read_parquet(AIDEV / "pr_commits.parquet")
    commits = commits[commits["pr_id"].isin(ids)]
    touches = tables.touches[tables.touches["pr_id"].isin(ids)]
    reviews = tables.reviews[tables.reviews["pr_id"].isin(ids)]
    comments = tables.comments[tables.comments["pr_id"].isin(ids)]
    rc = tables.review_comments.copy()
    rc["pr_id"] = rc["pull_request_review_id"].map(
        tables.reviews.set_index("id")["pr_id"]
    )
    rc = rc[rc["pr_id"].isin(ids)]

    extractor = LLMExtractor(
        gemini_complete(args.extract_model, api_key), author="aidev", harness="github-pr"
    )

    # (reveal_outcome, polarity_schema) per arm. The polarity condition also
    # reveals the outcome, so it isolates the schema's contribution against the
    # rejected/aware condition rather than against the blind one. Merged PRs get
    # the polarity mode as a specificity control: a field that suppresses
    # assertion of adopted work would be trading poisoning for lost knowledge.
    jobs = []
    for _, pr in sample.iterrows():
        modes = (
            [(False, False), (True, False), (True, True)]
            if pr["arm"] == "rejected"
            else [(False, False), (True, True)]
        )
        for reveal, polarity in modes:
            if wanted and condition_name(pr["arm"], reveal, polarity) not in wanted:
                continue
            jobs.append((pr, reveal, polarity))

    polarity_complete = gemini_complete(args.extract_model, api_key)

    def run(job):
        pr, reveal, polarity = job
        pid = int(pr["id"])
        session, events = build_thread(
            pr,
            commits[commits["pr_id"] == pid],
            reviews[reviews["pr_id"] == pid],
            rc[rc["pr_id"] == pid],
            comments[comments["pr_id"] == pid],
            sorted(touches[touches["pr_id"] == pid]["filename"].dropna().astype(str)),
            reveal_outcome=reveal,
        )
        try:
            if polarity:
                extracted = extract_with_polarity(events, session, polarity_complete)
            else:
                extracted = [
                    {
                        "statement": c.statement,
                        "kind": c.kind,
                        "status": None,
                        "scope": c.scope,
                        "action": c.action,
                        "quote": c.anchors[0].quote if c.anchors else "",
                    }
                    for c in extractor.extract(events, session)
                ]
        except Exception as exc:
            print(f"  extract failed {session}: {exc}")
            return []
        feedback = "\n".join(
            f"- {_clip(b, 400)}" for b in reviews[reviews["pr_id"] == pid]["body"].dropna()
        )[:2000]
        return [
            {
                "condition": condition_name(pr["arm"], reveal, polarity),
                "arm": pr["arm"],
                "reveal": reveal,
                "polarity": polarity,
                "repo": pr["repo"],
                "pr_number": int(pr["number"]),
                "pr_title": pr["title"],
                "outcome": "merged" if pr["arm"] == "merged" else "closed without merging",
                "feedback": feedback,
                **claim,
            }
            for claim in extracted
        ]

    cached: dict[str, list[dict]] = {}
    if args.cache.exists():
        for line in args.cache.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                cached[record["job_key"]] = record["claims"]

    def job_key(job) -> str:
        pr, reveal, polarity = job
        return f"{args.extract_model}|{pr['repo']}|{pr['number']}|{reveal}|{polarity}"

    todo = [j for j in jobs if job_key(j) not in cached]
    print(f"{len(cached)} threads cached, {len(todo)} to extract")

    rows: list[dict] = []
    for job in jobs:
        if job_key(job) in cached:
            rows.extend(cached[job_key(job)])

    with args.cache.open("a") as sink:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for i, (job, batch) in enumerate(zip(todo, pool.map(run, todo), strict=False), 1):
                rows.extend(batch)
                sink.write(json.dumps({"job_key": job_key(job), "claims": batch}) + "\n")
                sink.flush()
                if i % 20 == 0:
                    print(f"  extracted {i}/{len(todo)} threads, {len(rows)} claims so far")

    print(f"\n{len(rows)} claims extracted; judging with {args.judge_model}")
    judged = judge_claims(rows, args.judge_model, api_key, args.workers)
    frame = pd.DataFrame(judged)
    frame.to_parquet(args.out)

    print("\n=== claims per condition ===")
    print(frame.groupby("condition").size().to_string())
    print("\n=== judge labels by condition (%) ===")
    table = pd.crosstab(frame["condition"], frame["judge_label"], normalize="index") * 100
    print(table.round(1).to_string())
    print(f"\nwritten -> {args.out}")


if __name__ == "__main__":
    main()
