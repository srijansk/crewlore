# Study: write-stage poisoning on declined pull requests

Does a memory system that compiles engineering work a team **declined** end up storing the declined approach as current practice? This study runs crewlore's extractor and fidelity gate over agent-authored pull requests that were closed without merging, with merged pull requests from the same repositories as controls, and has an independent model judge every claim against the pull request's real outcome. It then tests two interventions: stating the outcome in the transcript, and giving the schema an adoption field plus an instruction to use it.

The finding that changed the product: without a field that can say "tried and not adopted", the extractor never records the rejection in a claim's own text; with one, it does. That field ships in crewlore as `adoption`.

The write-up was submitted to PALM (Personalized, Aligned, Long-Term Memory for AI Systems), a NeurIPS 2026 workshop.

## Results

Unit of analysis is the pull request (claims inside one thread are not independent). 60 declined and 60 merged pull requests, sampled with a fixed seed from the public AIDev corpus; 95% bootstrap intervals; paired permutation tests over the same threads.

| Condition | Declined PRs with ≥1 claim stating the rejected approach as current | 95% CI |
|---|---|---|
| crewlore extractor, outcome not stated | 44.7% | [36.4, 52.9] |
| Schema-free summarizer, same threads | 47.6% | [38.4, 56.9] (vs. extractor: p = 0.43) |
| Merged controls | 0.0% | |
| Outcome stated in the thread | −14.6 points vs. not stated | p = 0.0002 |
| Adoption field plus instruction | a further −12.7 points | p = 0.0038 |

| Does the claim's own text record the rejection? | |
|---|---|
| Every arm without the field (structured extractor and summarizer together) | 0 of 867 statements |
| With the field, among claims it marked `not_adopted` | 77 of 91 (85%) |
| With the field, as a share of all claims from declined PRs | 77 of 196 (39%) |

On merged controls the field arm produced 0% pull-request-level poisoning; 82.7% of its claims stayed `current` and the rest were genuine within-PR rejections (an alternative a reviewer turned down inside a successful PR), with three judged safe, so the control is mostly but not perfectly clean. Second-judge agreement on a stratified 240-claim sample: 96.2%, κ = 0.920.

## Models

The extractor is crewlore's own prompt and verbatim-anchor gate, called through the OpenAI-compatible provider path with Gemini models (crewlore ships no Gemini provider; the endpoint speaks the OpenAI chat API). Three model roles are fixed by the scripts and the pinned caches:

| Role | Model |
|---|---|
| Extraction (all arms) | `gemini-3-flash-preview`, temperature 0 |
| Primary judge | `gemini-3.7-flash` |
| Second judge, for agreement | `gemini-3.5-flash` |

## Files

| File | Role |
|---|---|
| `corpus.py` | Builds the fixed sample (and contradiction candidates) from the AIDev curated subset. Two bulk-automation repositories are excluded by `BULK_AUTOMATION_REPOS`. |
| `poisoning.py` | Renders each pull request as a session, runs the extraction arms, and judges the claims. `condition_name(arm, reveal, polarity)` is the single source of arm labels; the adoption-field arm's complete prompt is inlined so the arm reproduces from this file alone. |
| `freeform.py` | A schema-free summarizer on the same threads, to check the effect is not one extractor's prompt. |
| `agreement.py` | Second-judge agreement (Cohen's kappa). |
| `adjudicate.py` | The contradiction-mining pilot (a negative result: mining reversals by shared file found no genuine ones). |
| `analyze.py` | Per-pull-request rates, bootstrap intervals, paired permutation tests, abstention, recording and adoption-status rates. |

## Reproducing

The AIDev curated subset (33,596 agent-authored pull requests) is CC BY 4.0 and lives, gitignored, in `../../local/aidev/`. The study used the immutable revision `68ed5f4b80d27a9e057fc57567f38bd322ac73ec`, the last one before the dataset's `main` branch was replaced on 2026-08-21; today's `main` does not reconstruct the same corpus. Download the pinned snapshot once:

```bash
mkdir -p ../../local/aidev && cd ../../local/aidev
for f in pull_request pr_comments pr_reviews pr_review_comments_v2 \
         pr_timeline pr_commits issue related_issue repository \
         pr_commit_details; do
  curl -sL -o "$f.parquet" \
    "https://huggingface.co/datasets/hao-li/AIDev/resolve/68ed5f4b80d27a9e057fc57567f38bd322ac73ec/$f.parquet"
done
```

Install the study's own dependencies on top of the package (`pip install -r studies/palm/requirements.txt` inside the project venv), then, with `GEMINI_API_KEY` set:

```bash
python studies/palm/corpus.py --sample 200
python studies/palm/poisoning.py --n 60 --workers 10
python studies/palm/freeform.py  --n 60 --workers 10
python studies/palm/agreement.py --per-condition 40 --model gemini-3.5-flash
python studies/palm/analyze.py
```

`--n` and `--seed` (default `20260818`) pin the sample; extraction runs at temperature 0. Extraction and judging are cached under `local/aidev/*_cache.jsonl`, so an interrupted run resumes. Model APIs drift over time, so a re-run reproduces the design, not necessarily the exact figures above.

## Analysis conventions

- The pull request is the unit of analysis; claims inside one thread are not independent observations.
- Threads where extraction returned nothing stay in the denominator at rate zero. Dropping them conditions on a post-treatment outcome.
- The lexical "records non-adoption" indicator is separate from the judge's `hedged` label and from the schema's adoption field.
