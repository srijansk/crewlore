"""Adjudicate mined contradiction candidates.

Structural mining says two pull requests disagreed about a file. It cannot say
whether they disagreed about a *decision*. This module assembles the evidence a
reviewer would read — both PR bodies, the review that rejected the first, and
the competing patches — and asks a model to sort each site into one of four
classes, so the construct's precision becomes a measured number rather than an
assumption.

The adjudicating model is deliberately not the model under study elsewhere in
the pipeline: a system should not grade the quality of its own inputs.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd
from corpus import AIDEV, load_patches, load_tables

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

BODY_CHARS = 1500
PATCH_CHARS = 2200
REVIEW_CHARS = 900

RUBRIC = """You are auditing pairs of pull requests from a real software repository.

Both pull requests changed the SAME FILE. The first was closed without merging.
The second, opened later, was merged. Your job is to decide what that says about
the team's engineering decisions.

Choose exactly one label:

- "reversal": The merged PR pursues the same underlying goal as the closed PR but
  by a materially different route — a different mechanism, library, data model,
  API shape, or policy. Someone joining the team later would be misled if they
  learned the closed PR's approach and did not learn it was superseded.

- "refinement": The merged PR is substantially the same approach as the closed
  PR, re-landed after addressing feedback, rebasing, splitting, or reopening.
  The decision did not change; only the execution did.

- "unrelated": The two PRs pursue different goals and merely happen to touch the
  same file. Neither supersedes the other.

- "unclear": The evidence provided is too thin to distinguish the above.

Answer in strict JSON with these keys:
  "label": one of reversal | refinement | unrelated | unclear
  "confidence": one of high | medium | low
  "reason": one sentence, concrete, citing what differs or matches
  "superseded_claim": if label is "reversal", the belief the closed PR would have
      taught, phrased as a standalone sentence; otherwise null
  "superseding_claim": if label is "reversal", what the merged PR established
      instead, phrased as a standalone sentence; otherwise null

Output only the JSON object."""


def _clip(text: Any, limit: int) -> str:
    s = "" if text is None else str(text)
    s = s.strip()
    return s if len(s) <= limit else s[:limit] + "\n[...truncated]"


def _patch_for(patches: pd.DataFrame, pr_id: int, filename: str) -> str:
    rows = patches[(patches["pr_id"] == pr_id) & (patches["filename"] == filename)]
    if rows.empty:
        return "(no patch recorded)"
    joined = "\n".join(str(p) for p in rows["patch"].dropna())
    return _clip(joined, PATCH_CHARS) or "(empty patch)"


def build_packet(
    site: pd.Series,
    bodies: dict[int, str],
    rejection_notes: dict[int, list[str]],
    patches: pd.DataFrame,
) -> str:
    notes = rejection_notes.get(int(site["rejected_id"]), [])
    notes_text = (
        "\n".join(f"- {_clip(n, REVIEW_CHARS)}" for n in notes[:5])
        if notes
        else "(no review text recorded)"
    )
    return f"""REPOSITORY: {site['repo']}
SHARED FILE: {site['filename']}
DAYS BETWEEN THEM: {site['gap_days']:.1f}

=== CLOSED WITHOUT MERGING ===
PR #{site['rejected_number']} by {site['rejected_user']} (agent: {site['rejected_agent']})
Title: {site['rejected_title']}
Body:
{_clip(bodies.get(int(site['rejected_id'])), BODY_CHARS) or '(empty)'}

Review feedback it received:
{notes_text}

Its patch to {site['filename']}:
{_patch_for(patches, int(site['rejected_id']), site['filename'])}

=== MERGED LATER ===
PR #{site['merged_number']} by {site['merged_user']} (agent: {site['merged_agent']})
Title: {site['merged_title']}
Body:
{_clip(bodies.get(int(site['merged_id'])), BODY_CHARS) or '(empty)'}

Its patch to {site['filename']}:
{_patch_for(patches, int(site['merged_id']), site['filename'])}
"""


def call_gemini(prompt: str, model: str, api_key: str, retries: int = 4) -> dict:
    payload = {
        "systemInstruction": {"parts": [{"text": RUBRIC}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    url = ENDPOINT.format(model=model) + f"?key={api_key}"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                data = json.loads(response.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            KeyError,
            json.JSONDecodeError,
        ) as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 401, 403):
                raise
            import time

            time.sleep(2**attempt)
    raise RuntimeError(f"gemini call failed after {retries} attempts: {last}")


def adjudicate(
    sites: pd.DataFrame, model: str, api_key: str, workers: int, cache: Path
) -> pd.DataFrame:
    tables = load_tables()
    pr_ids = set(sites["rejected_id"]) | set(sites["merged_id"])
    bodies = (
        tables.pull_requests.set_index("id")["body"]
        .reindex(list(pr_ids))
        .to_dict()
    )

    notes: dict[int, list[str]] = {}
    reviews = tables.reviews[tables.reviews["pr_id"].isin(pr_ids)]
    for pr_id, group in reviews.groupby("pr_id"):
        texts = [str(b) for b in group["body"].dropna() if str(b).strip()]
        if texts:
            notes[int(pr_id)] = texts
    comments = tables.comments[tables.comments["pr_id"].isin(pr_ids)]
    for pr_id, group in comments.groupby("pr_id"):
        texts = [str(b) for b in group["body"].dropna() if str(b).strip()]
        notes.setdefault(int(pr_id), []).extend(texts)

    patches = load_patches(AIDEV, pr_ids, set(sites["filename"]))

    done: dict[str, dict] = {}
    if cache.exists():
        for line in cache.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                done[record["site_key"]] = record

    def key_for(site: pd.Series) -> str:
        return (
            f"{model}|{site['repo']}|{site['filename']}"
            f"|{site['rejected_number']}|{site['merged_number']}"
        )

    pending = [
        (i, row) for i, row in sites.iterrows() if key_for(row) not in done
    ]
    print(f"[{model}] {len(done)} cached, {len(pending)} to adjudicate")

    def work(item: tuple[int, pd.Series]) -> dict:
        _, row = item
        packet = build_packet(row, bodies, notes, patches)
        try:
            verdict = call_gemini(packet, model, api_key)
        except Exception as exc:  # keep one bad site from sinking the run
            verdict = {"label": "error", "reason": str(exc)[:300], "confidence": "low"}
        return {
            "site_key": key_for(row),
            "repo": row["repo"],
            "filename": row["filename"],
            "rejected_number": int(row["rejected_number"]),
            "merged_number": int(row["merged_number"]),
            "gap_days": float(row["gap_days"]),
            "rejected_agent": row["rejected_agent"],
            "merged_agent": row["merged_agent"],
            **{k: verdict.get(k) for k in
               ("label", "confidence", "reason", "superseded_claim", "superseding_claim")},
        }

    with cache.open("a") as sink:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for n, record in enumerate(pool.map(work, pending), 1):
                done[record["site_key"]] = record
                sink.write(json.dumps(record) + "\n")
                sink.flush()
                if n % 25 == 0:
                    print(f"  [{model}] {n}/{len(pending)}")

    return pd.DataFrame([done[key_for(row)] for _, row in sites.iterrows()])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", type=Path, default=AIDEV / "candidates.parquet")
    parser.add_argument("--model", default="gemini-3-flash-preview")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", type=Path, default=AIDEV / "adjudicated.parquet")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not set")

    sites = pd.read_parquet(args.sites)
    if args.limit:
        sites = sites.head(args.limit)

    cache = AIDEV / f"adjudication_cache_{re.sub(r'[^a-z0-9]+', '_', args.model)}.jsonl"
    results = adjudicate(sites, args.model, api_key, args.workers, cache)
    results.to_parquet(args.out)

    print("\n=== label distribution ===")
    counts = results["label"].value_counts()
    for label, n in counts.items():
        print(f"  {label:12s} {n:4d}  ({n / len(results) * 100:5.1f}%)")
    reversals = results[results["label"] == "reversal"]
    print(f"\nprecision of the mined construct: {len(reversals) / len(results) * 100:.1f}%")
    print(f"written -> {args.out}")


if __name__ == "__main__":
    main()
