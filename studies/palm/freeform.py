"""Generalization check: does the failure survive without crewlore's schema?

If only crewlore poisons on rejected pull requests, the finding is a bug report.
The claim worth making is that *compiling a declined pull request into durable
notes* poisons regardless of representation, so this arm drops the structured
schema entirely and asks the model to write free-form team knowledge — the
artifact a harness produces on its own, with no memory system involved.

Scored by the same judge, against the same pull requests, as poisoning.py.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from pathlib import Path

import pandas as pd
from corpus import AIDEV, load_tables
from poisoning import _clip, build_thread, gemini_complete, judge_claims, sample_prs

FREEFORM_PROMPT = """You are keeping a team's engineering knowledge base up to date.

Below is the complete thread of one pull request from a real repository. Write
the durable notes a future engineer on this team should know, based on it.

Write 1-5 notes. Each note is one self-contained sentence stating something the
team should carry forward. Return ONLY a JSON array of objects:
  {"note": str, "quote": str (a VERBATIM excerpt from the thread supporting it)}

THREAD:
"""


def parse_notes(raw: str) -> list[dict]:
    text = raw.strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [
        {"note": str(i["note"]), "quote": str(i.get("quote", ""))}
        for i in items
        if isinstance(i, dict) and i.get("note")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--extract-model", default="gemini-3-flash-preview")
    parser.add_argument("--judge-model", default="gemini-3.7-flash")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--out", type=Path, default=AIDEV / "freeform.parquet")
    parser.add_argument("--cache", type=Path, default=AIDEV / "freeform_cache.jsonl")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not set")

    tables = load_tables()
    # Same seed and same selection rule as poisoning.py, so both arms score the
    # identical pull requests.
    sample = sample_prs(tables, args.n, args.seed)

    ids = set(sample["id"])
    commits = pd.read_parquet(AIDEV / "pr_commits.parquet")
    commits = commits[commits["pr_id"].isin(ids)]
    touches = tables.touches[tables.touches["pr_id"].isin(ids)]
    reviews = tables.reviews[tables.reviews["pr_id"].isin(ids)]
    comments = tables.comments[tables.comments["pr_id"].isin(ids)]
    rc = tables.review_comments.copy()
    rc["pr_id"] = rc["pull_request_review_id"].map(tables.reviews.set_index("id")["pr_id"])
    rc = rc[rc["pr_id"].isin(ids)]

    complete = gemini_complete(args.extract_model, api_key)

    cached: dict[str, list[dict]] = {}
    if args.cache.exists():
        for line in args.cache.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                cached[record["job_key"]] = record["claims"]

    jobs = list(sample.iterrows())

    def key_for(pr) -> str:
        return f"{args.extract_model}|freeform|{pr['repo']}|{pr['number']}"

    def run(job):
        _, pr = job
        pid = int(pr["id"])
        _, events = build_thread(
            pr,
            commits[commits["pr_id"] == pid],
            reviews[reviews["pr_id"] == pid],
            rc[rc["pr_id"] == pid],
            comments[comments["pr_id"] == pid],
            sorted(touches[touches["pr_id"] == pid]["filename"].dropna().astype(str)),
            reveal_outcome=False,
        )
        transcript = "\n".join(f"[{e.actor}/{e.kind}] {e.content}" for e in events)
        try:
            notes = parse_notes(complete(FREEFORM_PROMPT + transcript))
        except Exception as exc:
            print(f"  freeform failed {pr['repo']}#{pr['number']}: {exc}")
            return []
        feedback = "\n".join(
            f"- {_clip(b, 400)}" for b in reviews[reviews["pr_id"] == pid]["body"].dropna()
        )[:2000]
        return [
            {
                "condition": f"{pr['arm']}/freeform",
                "arm": pr["arm"],
                "repo": pr["repo"],
                "pr_number": int(pr["number"]),
                "pr_title": pr["title"],
                "outcome": "merged" if pr["arm"] == "merged" else "closed without merging",
                "feedback": feedback,
                "statement": n["note"],
                "kind": "freeform-note",
                "status": None,
                "scope": ".",
                "action": None,
                "quote": n["quote"],
            }
            for n in notes
        ]

    todo = [j for j in jobs if key_for(j[1]) not in cached]
    print(f"{len(cached)} cached, {len(todo)} to extract")

    rows: list[dict] = []
    for _, pr in jobs:
        if key_for(pr) in cached:
            rows.extend(cached[key_for(pr)])

    with args.cache.open("a") as sink:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for i, (job, batch) in enumerate(zip(todo, pool.map(run, todo), strict=False), 1):
                rows.extend(batch)
                sink.write(json.dumps({"job_key": key_for(job[1]), "claims": batch}) + "\n")
                sink.flush()
                if i % 20 == 0:
                    print(f"  {i}/{len(todo)} threads, {len(rows)} notes")

    print(f"\n{len(rows)} notes; judging with {args.judge_model}")
    judged = judge_claims(rows, args.judge_model, api_key, args.workers)
    frame = pd.DataFrame(judged)
    frame.to_parquet(args.out)

    print("\n=== judge labels by condition (%) ===")
    shares = pd.crosstab(frame["condition"], frame["judge_label"], normalize="index") * 100
    print(shares.round(1).to_string())
    print(f"\nwritten -> {args.out}")


if __name__ == "__main__":
    main()
