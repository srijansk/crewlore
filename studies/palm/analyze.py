"""Turn judged claims into the study's summary tables.

Claims are nested inside pull requests: one thread yields several claims that
share a topic, an author and a reviewer, so they are not independent samples.
Every headline number here is therefore computed per pull request first and
aggregated across pull requests, and every condition comparison is paired on the
pull request, because all conditions ran over the same threads.

Threads that yielded no claims at all are kept, at a rate of zero. Whether an arm
emits any claim is downstream of the treatment -- revealing the outcome makes the
compiler abstain on some threads -- so dropping those threads would condition on a
post-treatment variable and would discard exactly the cases where an arm behaved
best. The thread universe therefore comes from the sampler, not from the results.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd
from corpus import AIDEV, load_tables
from poisoning import sample_prs

# Does the claim's own prose record that the work was not adopted? Deliberately
# generous: any of these phrasings counts, so a low rate is not a matter of the
# pattern being too strict.
NON_ADOPTION_TEXT = re.compile(
    r"\b(not adopted|was not merged|were not merged|rejected|declined|tried and|"
    r"proposed but|not accepted|abandoned|superseded|reverted|was closed|"
    r"did not merge|unmerged)\b",
    re.I,
)

CONDITION_ORDER = [
    "merged/blind",
    "merged/freeform",
    "merged/polarity",
    "rejected/blind",
    "rejected/freeform",
    "rejected/aware",
    "rejected/polarity",
]


def load(paths: list[Path]) -> pd.DataFrame:
    frames = [pd.read_parquet(p) for p in paths if p.exists()]
    if not frames:
        raise SystemExit("no result files found")
    frame = pd.concat(frames, ignore_index=True)
    return frame[frame["judge_label"] != "error"].copy()


def thread_universe(n: int, seed: int) -> pd.DataFrame:
    """Every thread each arm was asked to compile, whether or not it produced claims."""
    sample = sample_prs(load_tables(), n, seed)
    return sample[["arm", "repo", "number"]].rename(columns={"number": "pr_number"})


def per_pr_rates(frame: pd.DataFrame, universe: pd.DataFrame | None = None) -> pd.DataFrame:
    """Poisoning rate within each (condition, pull request), including empty threads."""
    frame = frame.assign(is_poisoned=(frame["judge_label"] == "poisoned").astype(float))
    rates = frame.groupby(["condition", "repo", "pr_number"], as_index=False).agg(
        rate=("is_poisoned", "mean"), claims=("is_poisoned", "size")
    )
    if universe is None:
        return rates
    filled = []
    for condition in sorted(set(frame["condition"])):
        arm = condition.split("/")[0]
        expected = universe[universe["arm"] == arm][["repo", "pr_number"]].assign(
            condition=condition
        )
        merged = expected.merge(rates, on=["condition", "repo", "pr_number"], how="left")
        filled.append(merged.fillna({"rate": 0.0, "claims": 0}))
    return pd.concat(filled, ignore_index=True)


def bootstrap_ci(values: np.ndarray, iterations: int = 10000, seed: int = 0) -> tuple[float, float]:
    if len(values) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(iterations, len(values)), replace=True).mean(axis=1)
    return tuple(np.percentile(draws, [2.5, 97.5]))


def paired_test(rates: pd.DataFrame, left: str, right: str, seed: int = 0) -> dict | None:
    """Paired bootstrap on the per-PR poisoning rate difference."""
    a = rates[rates["condition"] == left].set_index(["repo", "pr_number"])["rate"]
    b = rates[rates["condition"] == right].set_index(["repo", "pr_number"])["rate"]
    shared = a.index.intersection(b.index)
    if len(shared) < 5:
        return None
    diff = (a.loc[shared] - b.loc[shared]).to_numpy()
    rng = np.random.default_rng(seed)
    draws = rng.choice(diff, size=(10000, len(diff)), replace=True).mean(axis=1)
    low, high = np.percentile(draws, [2.5, 97.5])
    # Two-sided p for "the paired difference is zero", by sign flipping.
    signs = rng.choice([-1.0, 1.0], size=(10000, len(diff)))
    null = (signs * diff).mean(axis=1)
    p = float((np.abs(null) >= abs(diff.mean())).mean())
    return {
        "left": left,
        "right": right,
        "n_pairs": len(shared),
        "mean_diff": float(diff.mean()),
        "ci": (float(low), float(high)),
        "p": p,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs",
        type=Path,
        nargs="+",
        default=[
            AIDEV / "poisoning.parquet",
            AIDEV / "freeform.parquet",
            AIDEV / "poisoning_merged_polarity.parquet",
        ],
    )
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260818)
    args = parser.parse_args()

    frame = load(args.inputs)
    present = [c for c in CONDITION_ORDER if c in set(frame["condition"])]
    universe = thread_universe(args.sample_size, args.seed)

    print("=== claims and threads per condition ===")
    summary = frame.groupby("condition").agg(
        claims=("statement", "size"),
        threads=("pr_number", "nunique"),
    )
    print(summary.reindex(present).to_string())

    print("\n=== judge labels, share of claims (%) ===")
    table = pd.crosstab(frame["condition"], frame["judge_label"], normalize="index") * 100
    print(table.reindex(present).round(1).to_string())

    rates = per_pr_rates(frame, universe)

    print("\n=== abstention: threads that produced no claims at all ===")
    empty = rates[rates["claims"] == 0].groupby("condition").size()
    for condition in present:
        total = int((rates["condition"] == condition).sum())
        print(f"  {condition:22s} {int(empty.get(condition, 0)):2d} / {total} threads empty")

    print("\n=== poisoning rate per pull request (unit = PR, 95% bootstrap CI) ===")
    for condition in present:
        values = rates[rates["condition"] == condition]["rate"].to_numpy()
        low, high = bootstrap_ci(values)
        print(
            f"  {condition:22s} n={len(values):3d}  mean={values.mean() * 100:5.1f}%"
            f"  CI=[{low * 100:5.1f}, {high * 100:5.1f}]"
        )

    print("\n=== paired comparisons (same pull requests) ===")
    comparisons = [
        ("rejected/blind", "merged/blind"),
        ("rejected/blind", "rejected/aware"),
        ("rejected/aware", "rejected/polarity"),
        ("rejected/blind", "rejected/polarity"),
        ("rejected/freeform", "merged/freeform"),
        ("rejected/blind", "rejected/freeform"),
    ]
    for left, right in comparisons:
        if left not in present or right not in present:
            continue
        result = paired_test(rates, left, right)
        if not result:
            continue
        low, high = result["ci"]
        stars = "*" if result["p"] < 0.05 else " "
        print(
            f"  {left:20s} - {right:20s} n={result['n_pairs']:3d} "
            f"diff={result['mean_diff'] * 100:+6.1f}pp CI=[{low * 100:+6.1f},{high * 100:+6.1f}] "
            f"p={result['p']:.4f}{stars}"
        )

    print("\n=== hedging: share of claims that record non-adoption (%) ===")
    hedged = (
        frame.assign(h=(frame["judge_label"] == "hedged").astype(float))
        .groupby("condition")["h"]
        .mean()
        * 100
    )
    print(hedged.reindex(present).round(1).to_string())

    print("\n=== recording: statements whose own text says the work was not adopted ===")
    print("(no arm is prevented from writing this in prose; only one arm has a field for it)")
    records = frame["statement"].map(lambda s: bool(NON_ADOPTION_TEXT.search(str(s))))
    marked = frame.assign(m=records)
    for condition in present:
        subset = marked[marked["condition"] == condition]
        if not len(subset):
            continue
        print(
            f"  {condition:22s} {int(subset['m'].sum()):3d} / {len(subset):3d} "
            f"({subset['m'].mean() * 100:4.1f}%)"
        )

    if "status" in frame.columns:
        polarity = frame[frame["condition"] == "rejected/polarity"]
        if len(polarity):
            used = (polarity["status"] == "not_adopted").mean() * 100
            print(
                f"\npolarity arm: {used:.1f}% of claims used status=not_adopted "
                f"({len(polarity)} claims)"
            )
            leaked = polarity[
                (polarity["status"] != "not_adopted")
                & (polarity["judge_label"] == "poisoned")
            ]
            print(
                f"  poisoned claims that left status=current: {len(leaked)} "
                f"({len(leaked) / max(len(polarity), 1) * 100:.1f}% of arm)"
            )


if __name__ == "__main__":
    main()
