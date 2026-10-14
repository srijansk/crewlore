# Reviewing a change against the team's knowledge

`lore review` takes the files a change touches, finds the claims whose scope covers them, puts declined work first, and flags a change whose own description reads like an approach the team already tried and declined. It is the adoption field at the moment it matters: when someone is about to redo rejected work without knowing it was rejected.

## Locally, before you push

```bash
lore review                  # the current branch against origin's default branch, plus uncommitted edits
lore review --base develop   # a different base
lore review --json           # for scripts and hooks
lore review --exit-code      # exit 5 when a declined approach is flagged (0 otherwise)
```

The change is the branch's commits since the merge base with origin's default branch (`origin/main` as the remote-tracking ref, or `--base`), the uncommitted edits, and untracked files, with a renamed file listed under both names; the text matched against claims is the commit messages. When the base cannot be found locally (a single-branch clone), only the working tree is reviewed and the report says so. The exit code stays 0 unless you pass `--exit-code`, so an assistant running the command through a shell tool does not see a flag as a failed command; a pre-push hook or a script asks for it. Reviewing does not count as reading for the lifecycle: nothing a review touches is marked served, since a CI checkout is throwaway.

## A pull request on GitHub

```bash
lore review 42                          # this repository's PR #42, through the gh CLI you already authenticated
lore review 42 --github owner/repo      # another repository
lore review 42 --comment                # also post the Markdown report as a comment on the PR
```

Without `--comment` nothing is posted; the report is printed. With it, one comment is added each time the command runs, so wire it to run once per push rather than per commit. Every claim field in the comment is rendered inside a code span and never inside a table (GitHub splits table cells on `|` before it reads inline code), so model-written text cannot mention a person, link out, or restyle the comment. The file list comes from GitHub's paginated pull-request files endpoint, so pull requests with more than 100 files (`gh pr view` stops there without saying so) and non-ASCII paths are read in full; renamed files are listed under both names. GitHub lists at most 3000 files, and a larger pull request is refused rather than reviewed in part.

## In GitHub Actions

Runs on every pull request, posts the report when a declined approach is flagged, and never fails the build: the claims are evidence, not verdicts. It needs a crewlore release that includes `lore review`. On a pull request from a fork the workflow token is read-only, so the comment step reports that it could not post instead of failing.

```yaml
name: crewlore review
on:
  pull_request:
    types: [opened, synchronize]
permissions:
  contents: read
  pull-requests: write
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uv tool install crewlore
      - name: Review the change against .lore/
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set +e
          lore review ${{ github.event.pull_request.number }} --exit-code >/dev/null
          rc=$?
          set -e
          case "$rc" in
            5) lore review ${{ github.event.pull_request.number }} --comment \
                 || echo "could not post the comment (a fork's token is read-only)" ;;
            0) echo "no declined approach flagged" ;;
            *) echo "lore review did not run (exit $rc); not failing the build" ;;
          esac
```

No model is called: `lore review` reads the committed `.lore/claims/claims.jsonl` and the pull request's metadata only. Nothing leaves the runner except the comment it posts.

## How matching works

A claim's scope is a repository path or area (`services/billing`, `.github/`, `pydantic_ai_slim/pydantic_ai/models`); it covers a file that is the scope or sits under it. A scope that names several areas, comma-separated, counts for each. The repository-wide scope `.` is ignored here: it would match every file and say nothing. Scopes the model wrote as prose rather than paths match nothing, which fails closed.

A declined claim is flagged when at least half of its content words appear in the change's title and description, and at least two words are shared. The content words are the statement and topic minus stopwords and the extractor's own template words (tried, adopted, declined, instead, and the like). The action is left out on purpose: it is the recommended alternative, and a change that does the recommended thing must not be flagged for matching it. At least one shared word must also be specific to the declined approach: in the statement but in neither the topic nor the action, so a change that only names the question or the alternative is not flagged. The match is lexical, like retrieval, so it has limits: a change that reuses another noun from the declined statement (`key store`, say) can still be flagged, and a paraphrase that shares no words is missed. Treat a flag as "read this before merging" rather than "this is the same approach".
