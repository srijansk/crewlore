"""Build the contradiction-candidate corpus from AIDev-pop.

A *contradiction candidate* is a pair of pull requests touching the same file in
the same repository, where the earlier one was closed without merging and the
later one merged. The outcome labels come from the platform, not from a model,
so the construct is mined structurally and only its precision needs adjudicating.

Filters exist to suppress the two failure modes that would inflate yield:
self-retries of the same change, and repositories whose agentic PR volume is a
single author's automation rather than a team's engineering.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq

AIDEV = Path(__file__).resolve().parents[2] / "local" / "aidev"

# Repositories whose agentic PR counts are dominated by one author's bulk
# automation. Including them would let a single repo's conventions stand in for
# the corpus: the two account for ~37% of all agentic PRs.
BULK_AUTOMATION_REPOS = {"mochilang/mochi", "MontrealAI/AGI-Alpha-Agent-v0"}

MIN_DISCUSSION_EVENTS = 3
MIN_GAP_DAYS = 1.0
MAX_GAP_DAYS = 180.0


@dataclass
class CorpusTables:
    pull_requests: pd.DataFrame
    reviews: pd.DataFrame
    comments: pd.DataFrame
    review_comments: pd.DataFrame
    repositories: pd.DataFrame
    touches: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)


def load_tables(root: Path = AIDEV) -> CorpusTables:
    repositories = pd.read_parquet(root / "repository.parquet")
    pull_requests = pd.read_parquet(root / "pull_request.parquet")
    pull_requests["created_at"] = pd.to_datetime(
        pull_requests["created_at"], format="mixed", utc=True
    )
    pull_requests["repo"] = pull_requests["repo_url"].map(
        repositories.set_index("url")["full_name"]
    )
    pull_requests["merged"] = pull_requests["merged_at"].notna()
    pull_requests["rejected"] = (
        pull_requests["merged_at"].isna() & pull_requests["closed_at"].notna()
    )

    reviews = pd.read_parquet(root / "pr_reviews.parquet")
    comments = pd.read_parquet(root / "pr_comments.parquet")
    review_comments = pd.read_parquet(root / "pr_review_comments_v2.parquet")

    discussion = comments.groupby("pr_id").size().add(
        reviews.groupby("pr_id").size(), fill_value=0
    )
    pull_requests["discussion"] = pull_requests["id"].map(discussion).fillna(0)
    pull_requests["changes_requested"] = pull_requests["id"].isin(
        set(reviews[reviews["state"] == "CHANGES_REQUESTED"]["pr_id"])
    )

    touches = pd.read_parquet(
        root / "pr_commit_details.parquet", columns=["pr_id", "filename"]
    ).drop_duplicates()

    return CorpusTables(
        pull_requests=pull_requests,
        reviews=reviews,
        comments=comments,
        review_comments=review_comments,
        repositories=repositories,
        touches=touches,
    )


def build_candidates(tables: CorpusTables) -> pd.DataFrame:
    """Mine (rejected PR, later merged PR, shared file) triples."""
    pull_requests = tables.pull_requests[
        ~tables.pull_requests["repo"].isin(BULK_AUTOMATION_REPOS)
    ]
    carried = [
        "id",
        "number",
        "title",
        "created_at",
        "agent",
        "user",
        "discussion",
        "changes_requested",
    ]
    touched = tables.touches.merge(
        pull_requests[carried + ["repo", "merged", "rejected"]],
        left_on="pr_id",
        right_on="id",
    )

    def side(mask: pd.Series, prefix: str) -> pd.DataFrame:
        frame = touched[mask][["repo", "filename"] + carried]
        return frame.rename(columns={c: f"{prefix}_{c}" for c in carried})

    pairs = side(touched["rejected"], "rejected").merge(
        side(touched["merged"], "merged"), on=["repo", "filename"]
    )
    pairs["gap_days"] = (
        pairs["merged_created_at"] - pairs["rejected_created_at"]
    ).dt.total_seconds() / 86400

    return pairs[
        (pairs["gap_days"] >= MIN_GAP_DAYS)
        & (pairs["gap_days"] <= MAX_GAP_DAYS)
        & (pairs["rejected_discussion"] >= MIN_DISCUSSION_EVENTS)
        # A different author means an independent actor chose a different route,
        # rather than the same one re-pushing a corrected version of its own work.
        & (pairs["rejected_user"] != pairs["merged_user"])
    ].reset_index(drop=True)


def load_patches(root: Path, pr_ids: set[int], filenames: set[str]) -> pd.DataFrame:
    """Read only the patch rows the sampled sites need (the table is ~460 MB)."""
    return pq.read_table(
        root / "pr_commit_details.parquet",
        columns=["pr_id", "filename", "status", "additions", "deletions", "patch"],
        filters=pc.field("pr_id").isin(list(pr_ids))
        & pc.field("filename").isin(list(filenames)),
    ).to_pandas()


def sample_sites(candidates: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """One pair per (repo, file) site, sampled without over-weighting big repos.

    Sampling sites rather than pairs stops a single heavily-revisited file from
    contributing dozens of near-identical rows to the adjudication set.
    """
    closest = candidates.sort_values("gap_days").groupby(
        ["repo", "filename"], as_index=False
    ).first()
    take = min(n, len(closest))
    return closest.sample(n=take, random_state=seed).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--out", type=Path, default=AIDEV / "candidates.parquet")
    args = parser.parse_args()

    tables = load_tables()
    candidates = build_candidates(tables)
    sites = candidates.groupby(["repo", "filename"]).ngroups
    print(
        f"candidates: {len(candidates):,} pairs / {sites:,} sites / "
        f"{candidates['repo'].nunique()} repos"
    )

    sample = sample_sites(candidates, args.sample, args.seed)
    sample.to_parquet(args.out)
    print(f"sampled {len(sample)} sites -> {args.out}")
    print(sample["repo"].value_counts().head(12).to_string())


if __name__ == "__main__":
    main()
