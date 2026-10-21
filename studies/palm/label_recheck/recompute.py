"""Recompute the study's numbers under the landing re-check (see ../LABEL_RECHECK.md).

Run from a checkout that holds the pinned AIDev snapshot and the study's results in
`local/aidev/`, with the study's dependencies installed:

    python studies/palm/label_recheck/recompute.py

The per-claim reviewer verdicts are read from `local/aidev/label_recheck/verdicts/`
(gitignored, like the rest of the study's data). A claim's index there is its position
in the list `poisoned_claims_by_pr` builds, the same list the reviewers were given.

Scenarios, applied to the declined arms only:
  original                  as published
  exclude_landed            PRs whose change later landed leave the universe
  exclude_landed_or_partly  so do PRs where part of it landed
  relabel_true_now          in landed and partly landed PRs, poisoned claims the
                            reviewers judged true of the code once it landed count
                            as safe; every other label is unchanged
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyze import AIDEV, load, paired_test, per_pr_rates, thread_universe  # noqa: E402

OUT = AIDEV / "label_recheck"
SAMPLE, SEED = 60, 20260818

ARMS = {"gemini": ["rejected/blind", "rejected/freeform", "rejected/aware", "rejected/polarity"]}
PAIRS = {
    "gemini": [
        ("rejected/blind", "rejected/aware"),
        ("rejected/aware", "rejected/polarity"),
        ("rejected/blind", "rejected/polarity"),
        ("rejected/blind", "rejected/freeform"),
    ],
}


def frames() -> dict[str, pd.DataFrame]:
    return {
        "gemini": load(
            [
                AIDEV / "poisoning.parquet",
                AIDEV / "freeform.parquet",
                AIDEV / "poisoning_merged_polarity.parquet",
            ]
        )
    }


def poisoned_claims_by_pr() -> dict[str, list[dict]]:
    """Every poisoned claim from a declined arm, grouped by PR, in the order the
    reviewers saw them (the reviewers' lists continued with claims from arms not
    published here; those came after these, so these indexes are unchanged)."""
    g = pd.concat(
        [pd.read_parquet(AIDEV / "poisoning.parquet"), pd.read_parquet(AIDEV / "freeform.parquet")],
        ignore_index=True,
    )
    g = g[g["judge_label"] != "error"].assign(family="gemini")
    cols = ["family", "condition", "repo", "pr_number", "statement", "judge_label", "judge_reason"]
    allc = g[cols]
    pois = allc[allc["condition"].str.startswith("rejected/") & (allc["judge_label"] == "poisoned")]
    return {
        f"{repo}#{int(n)}": [
            {"family": r.family, "condition": r.condition, "statement": r.statement}
            for r in grp.itertuples()
        ]
        for (repo, n), grp in pois.groupby(["repo", "pr_number"])
    }


def main() -> None:
    verdicts = {}
    for f in sorted((OUT / "verdicts").glob("batch_*.json")):
        for v in json.loads(f.read_text()):
            verdicts[v["key"]] = v
    landed = {k for k, v in verdicts.items() if v["verdict"] == "LANDED"}
    partly = {k for k, v in verdicts.items() if v["verdict"] == "PARTLY"}
    claims = poisoned_claims_by_pr()
    true_now = set()
    for key, v in verdicts.items():
        repo, num = key.rsplit("#", 1)
        listed = claims.get(key, [])
        for cv in v.get("claim_verdicts", []):
            if cv.get("verdict") == "TRUE_NOW" and 0 <= cv["index"] < len(listed):
                c = listed[cv["index"]]
                true_now.add((c["family"], c["condition"], repo, int(num), c["statement"]))

    universe = thread_universe(SAMPLE, SEED)

    def keep(drop):
        return universe[
            ~universe.apply(lambda r: f"{r['repo']}#{int(r['pr_number'])}" in drop, axis=1)
        ]

    def relabel(frame, family):
        f = frame.copy()
        hit = f.apply(
            lambda r: (
                r["judge_label"] == "poisoned"
                and (family, r["condition"], r["repo"], int(r["pr_number"]), r["statement"])
                in true_now
            ),
            axis=1,
        )
        f.loc[hit, "judge_label"] = "safe"
        return f

    scenarios = {
        "original": lambda f, fam: (f, universe),
        "exclude_landed": lambda f, fam: (f, keep(landed)),
        "exclude_landed_or_partly": lambda f, fam: (f, keep(landed | partly)),
        "relabel_true_now": lambda f, fam: (relabel(f, fam), universe),
    }
    print(f"LANDED {len(landed)}, PARTLY {len(partly)}, claims judged TRUE_NOW {len(true_now)}\n")
    rows, contrasts = [], []
    for family, frame in frames().items():
        declined = frame[frame["condition"].str.startswith("rejected/")]
        for name, make in scenarios.items():
            f, uni = make(declined, family)
            rates = per_pr_rates(f, uni)
            for cond in ARMS[family]:
                r = rates[rates["condition"] == cond]
                rows.append(
                    {
                        "family": family,
                        "condition": cond,
                        "scenario": name,
                        "prs_with_poisoned_claim": f"{int((r['rate'] > 0).sum())} of {len(r)}",
                        "mean_share_pct": round(float(r["rate"].mean() * 100), 1),
                    }
                )
            for left, right in PAIRS[family]:
                res = paired_test(rates, left, right)
                if res:
                    lo, hi = res["ci"]
                    contrasts.append(
                        {
                            "family": family,
                            "scenario": name,
                            "pair": f"{left} - {right}",
                            "n": res["n_pairs"],
                            "diff_pp": round(res["mean_diff"] * 100, 1),
                            "ci": f"[{lo * 100:+.1f}, {hi * 100:+.1f}]",
                            "p": round(res["p"], 4),
                        }
                    )
    table = pd.DataFrame(rows).pivot_table(
        index=["family", "condition"],
        columns="scenario",
        values=["prs_with_poisoned_claim", "mean_share_pct"],
        aggfunc="first",
    )
    print(table.to_string())
    print()
    print(pd.DataFrame(contrasts).to_string(index=False))


if __name__ == "__main__":
    main()
