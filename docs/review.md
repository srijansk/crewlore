# Reviewing a change against the team's knowledge

`lore review` takes the files a change touches, finds the claims whose scope covers them, puts declined work first, and flags a change whose own description reads like an approach the team already tried and declined. It is the adoption field at the moment it matters: when someone is about to redo rejected work without knowing it was rejected.

## Locally, before you push

```bash
lore review                  # the current branch against origin's default branch, plus uncommitted edits
lore review --base develop   # a different base
lore review --json           # for scripts and hooks
lore review --exit-code      # exit 5 when a declined approach is flagged (0 otherwise)
```

The change is the branch's commits since the merge base, the uncommitted edits, and untracked files; the text matched against claims is the commit messages. The exit code stays 0 unless you pass `--exit-code`, so an assistant running the command through a shell tool does not see a flag as a failed command; a pre-push hook or a script asks for it.

## A pull request on GitHub

```bash
lore review 42                          # this repository's PR #42, through the gh CLI you already authenticated
lore review 42 --github owner/repo      # another repository
lore review 42 --comment                # also post the Markdown report as a comment on the PR
```

Without `--comment` nothing is posted; the report is printed. With it, one comment is added each time the command runs, so wire it to run once per push rather than per commit. Every claim field in the comment is rendered inside a code span, so model-written text cannot mention a person, link out, or restyle the comment.

## In GitHub Actions

Runs on every pull request, posts the report when a declined approach is flagged, and never fails the build: the claims are evidence, not verdicts.

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
          if ! lore review ${{ github.event.pull_request.number }} --exit-code >/dev/null; then
            lore review ${{ github.event.pull_request.number }} --comment
          fi
```

No model is called: `lore review` reads the committed `.lore/claims/claims.jsonl` and the pull request's metadata only. Nothing leaves the runner except the comment it posts.

## How matching works

A claim's scope is a repository path or area (`services/billing`, `.github/`, `pydantic_ai_slim/pydantic_ai/models`); it covers a file that is the scope or sits under it. A scope that names several areas, comma-separated, counts for each. The repository-wide scope `.` is ignored here: it would match every file and say nothing. Scopes the model wrote as prose rather than paths match nothing, which fails closed.

A declined claim is flagged when at least 40% of its content words (statement, topic and action, minus stopwords) appear in the change's title and description. That is lexical, like retrieval, so treat a flag as "read this before merging" rather than "this is the same approach".
