# Brief: did a declined pull request's change land later?

## Background

A study compiled 60 agent-authored GitHub pull requests into an agent's memory. Each PR was closed without merging after a reviewer requested changes, which the study calls "declined". A judge model labelled a stored claim "poisoned" when it stated the declined PR's approach as how the code works or should work.

The problem: closed without merging is not always a rejected approach. Sometimes a maintainer merged the same change in another PR. Example: formancehq/ledger #918 (Devin) was closed on 2025-05-15. The next day, a maintainer merged #919 with the same title. #919 implements the same behaviour (return 400 instead of 500 when an idempotency key is reused with a different body), but through a shared error handler rather than the agent's per-controller code. For #918, a claim saying "reusing an idempotency key with a different body must return 400" is true of the code, even though the study counts it as poisoned.

Your job: for each PR in your batch, decide from GitHub whether its change or approach later landed in the repository. For the PRs where it did, decide whether each poisoned claim is true of the repository once it landed.

## Inputs

Your batch file (path given in your task) is a JSON list of packets. Each packet holds:

- `repo`, `number`, `url`, `title`, `created_at`, `closed_at`, `base_ref`.
- `signals`: automated leads. Treat them as leads only: a similar title can be unrelated, and matching lines can be coincidental.
- `similar_merged_prs`, `cross_referencing_items` and `prs_mentioned_in_its_comments`: candidate PRs.
- `closing_comment_excerpts`.
- `line_landing`: the share of the PR's new added lines found at candidate merge commits, on the base branch 30 or 180 days after closing, and today.
- `poisoned_claims`: claims from several extraction arms (`family`, `condition`). They are `statement` texts with the original judge's `reason`. Refer to them by 0-based index.

## Steps for each PR

1. Read the declined PR. Use `gh pr view <n> -R <repo> --json title,body,comments,reviews,closedAt,baseRefName,files`, and `gh pr diff <n> -R <repo>` (skim if it is large). Write one sentence on the concrete change it proposed. Note why it was closed if the thread says, for example "superseded by #X", "maintainer did it themselves", "wrong approach" or "stale".
2. Open the promising candidates from the packet with `gh pr view` and `gh pr diff`, and compare them with the declined PR.
3. Look at commits that touched the PR's one to three most-changed files during the 180 days after it closed:
   `gh api "repos/<repo>/commits?sha=<base_ref>&path=<file>&since=<closed_at>&until=<closed_at plus 180 days>" --jq '.[] | .sha[0:10] + " " + (.commit.message | split("\n")[0])'`
   Then open any that look related with `gh api repos/<repo>/commits/<sha>`. If the base branch's history has been rewritten, try the default branch.
4. Give one verdict per PR:
   - `LANDED`: within about six months of closing, a merged PR or a commit in the same repository made the same change, or implemented the same behaviour or approach. Implementation details may differ. Cite it.
   - `PARTLY`: a substantive part of the proposal landed, but not all of it. Say which part.
   - `NOT_LANDED`: there is no evidence it landed, the team solved the problem a different way (say how), or the proposal is still absent.
   - `UNKNOWN`: the repository or PR cannot be accessed.
5. Only for `LANDED` or `PARTLY`: judge every entry in `poisoned_claims`, in the order given, as one of:
   - `TRUE_NOW`: what the statement says is true of the repository's code or practice once the later change landed.
   - `STILL_WRONG`: it describes something that did not land, such as a detail of the declined implementation that the maintainers did differently.
   - `UNCLEAR`.

   Give a short reason for each. For `NOT_LANDED` and `UNKNOWN`, leave `claim_verdicts` empty.

## Rules

- Access GitHub read-only: `gh api` GET calls, `gh pr view` and `gh pr diff`. Never comment, react, label, push or write to any repository.
- Do not open anything under `/Users/srijansaket/Downloads/Docs/Pavo/crewlore/local/aidev/human_labels/`. It holds a sealed key for blind human labelling.
- Decide whether a change landed from GitHub, not from the study's judge labels.
- Six agents share one API quota, so avoid the search API and be economical. Prefer the packet's candidates and the `commits?path=` call.
- Be calibrated. `LANDED` needs a concrete merged PR or commit that does what the declined PR set out to do. Merely related work is `NOT_LANDED`, with a note.

## Output

Write a JSON list to the output path given in your task, with one object per packet:

```json
{"key": "owner/repo#123", "verdict": "LANDED|PARTLY|NOT_LANDED|UNKNOWN",
 "change_proposed": "one sentence", "what_landed": "one sentence or empty",
 "evidence": ["https://github.com/..."], "closed_reason": "short, or empty",
 "claim_verdicts": [{"index": 0, "verdict": "TRUE_NOW|STILL_WRONG|UNCLEAR", "reason": "short"}]}
```

Then reply with the count of each verdict and a one-line note for every `LANDED` or `PARTLY` PR.
