"""Inter-judge agreement on the poisoning labels.

The headline numbers come from one model's judgement, so they are only worth as
much as that judgement is reproducible. This re-scores a stratified subsample
with a different, stronger model and reports raw agreement and Cohen's kappa.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from corpus import AIDEV
from poisoning import judge_claims


def cohens_kappa(a: pd.Series, b: pd.Series) -> float:
    labels = sorted(set(a) | set(b))
    observed = (a.to_numpy() == b.to_numpy()).mean()
    expected = sum(
        (a == label).mean() * (b == label).mean() for label in labels
    )
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs", type=Path, nargs="+",
        default=[AIDEV / "poisoning.parquet", AIDEV / "freeform.parquet"],
    )
    parser.add_argument("--per-condition", type=int, default=40)
    parser.add_argument("--model", default="gemini-3.1-pro-preview")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--out", type=Path, default=AIDEV / "agreement.parquet")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not set")

    frame = pd.concat(
        [pd.read_parquet(p) for p in args.inputs if p.exists()], ignore_index=True
    )
    frame = frame[frame["judge_label"] != "error"]
    # Sampled per condition with an explicit loop: a groupby-apply drops the
    # grouping column, and the condition has to survive into the re-judged frame.
    sample = pd.concat(
        [
            group.sample(n=min(args.per_condition, len(group)), random_state=args.seed)
            for _, group in frame.groupby("condition")
        ]
    ).reset_index(drop=True)
    print(f"re-judging {len(sample)} claims with {args.model}")

    rows = sample.drop(columns=["judge_label", "judge_reason"]).to_dict("records")
    rejudged = pd.DataFrame(judge_claims(rows, args.model, api_key, args.workers))
    rejudged["primary_label"] = sample["judge_label"].to_numpy()
    rejudged = rejudged[rejudged["judge_label"] != "error"]
    rejudged.to_parquet(args.out)

    agree = (rejudged["judge_label"] == rejudged["primary_label"]).mean()
    kappa = cohens_kappa(rejudged["primary_label"], rejudged["judge_label"])
    print(f"\nn={len(rejudged)}  raw agreement={agree * 100:.1f}%  Cohen's kappa={kappa:.3f}")

    print("\n=== confusion (rows: primary judge, cols: second judge) ===")
    print(pd.crosstab(rejudged["primary_label"], rejudged["judge_label"]).to_string())

    print("\n=== poisoning rate by condition, both judges (%) ===")
    both = pd.DataFrame({
        "condition": rejudged["condition"],
        "primary": (rejudged["primary_label"] == "poisoned") * 100,
        "second": (rejudged["judge_label"] == "poisoned") * 100,
    })
    print(both.groupby("condition").mean().round(1).to_string())


if __name__ == "__main__":
    main()
