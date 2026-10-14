"""Review a change against the team's compiled knowledge.

Given the files a change touches, from a pull request on GitHub or from the local branch
against its base, find the claims whose scope covers those files, put declined work
first, and flag a change whose own description reads like an approach the team already
tried and declined. The adoption field exists for exactly this moment: the point where
someone is about to redo rejected work without knowing it was rejected.

No model is called. The change's title and description are other people's text: they
are tokenised for overlap and never printed beyond a short label, and every claim field
that reaches a pull-request comment is rendered inside a code span, so model-written
text cannot mention a person, link out, or restyle the comment.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from lore.schemas import Claim
from lore.serve.server import _tokens, anchor_attribution, claim_label, claim_to_dict
from lore.text import sanitize_line

# Share of a declined claim's content words that also appear in the change's title and
# description before the change is flagged as re-proposing it, and the least number of
# shared words, so a one-word claim is not flagged by one word. Lexical, like retrieval;
# the flag says "look at this", not "this is the same approach". Only the statement and
# topic count: the action is the recommended alternative, and a change that does the
# recommended thing must not be flagged for matching it.
REPROPOSAL_MIN_OVERLAP = 0.5
REPROPOSAL_MIN_SHARED_WORDS = 2
# The extractor's own template words for declined work carry no signal about a change.
_TEMPLATE_WORDS = frozenset(
    "tried adopted declined rejected reverted proposed merged instead approach was".split()
)
# Anchors quoted per flagged claim in the Markdown report.
MARKDOWN_ANCHORS = 2
# Uncovered files named in the text report before "…".
UNCOVERED_LISTED = 8
# GitHub rejects comments over 65,536 characters; stop well short and say so.
MARKDOWN_MAX_CHARS = 60_000


class ChangeError(RuntimeError):
    """The change could not be read (git or gh failed, or is not installed)."""


@dataclass
class Change:
    label: str
    title: str
    body: str
    files: list[str]


@dataclass
class Match:
    claim: Claim
    files: list[str]
    overlap: float = 0.0

    @property
    def flagged(self) -> bool:
        return self.claim.adoption == "not_adopted" and self.overlap >= REPROPOSAL_MIN_OVERLAP


@dataclass
class Report:
    change: Change
    matches: list[Match] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> list[Match]:
        return [m for m in self.matches if m.flagged]


# --- what a scope covers ------------------------------------------------------------


def _norm(path: str) -> str:
    """A path as the repository sees it: forward slashes, no leading `./` or `/`."""
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def scope_parts(scope: str) -> list[str]:
    """A scope is a path or area; the extractor sometimes writes several, comma-separated.
    The repository-wide scope `.` is left out: it covers every file and says nothing."""
    parts = []
    for raw in sanitize_line(scope).split(","):
        part = _norm(raw.strip().strip("`")).rstrip("/")
        if part and part != ".":
            parts.append(part)
    return parts


def _covered_by(parts: list[str], path: str) -> bool:
    file = _norm(path)
    return any(file == part or file.startswith(part + "/") for part in parts)


def scope_covers(scope: str, path: str) -> bool:
    """True when the file is the scope or sits under it."""
    return _covered_by(scope_parts(scope), path)


def _content_words(claim: Claim) -> set[str]:
    return _tokens(" ".join(filter(None, [claim.statement, claim.topic]))) - _TEMPLATE_WORDS


def overlap(claim: Claim, text: str) -> float:
    """Share of the claim's content words (statement and topic, minus the extractor's
    template words) present in the change text; 0 when fewer than
    `REPROPOSAL_MIN_SHARED_WORDS` are shared."""
    words = _content_words(claim)
    shared = words & _tokens(text)
    if not words or len(shared) < REPROPOSAL_MIN_SHARED_WORDS:
        return 0.0
    return len(shared) / len(words)


def review(claims: list[Claim], change: Change) -> Report:
    text = f"{change.title}\n{change.body}"
    matches: list[Match] = []
    covered: set[str] = set()
    for c in claims:
        if c.status != "active":
            continue
        parts = scope_parts(c.scope)
        files = [f for f in change.files if _covered_by(parts, f)]
        if not files:
            continue
        covered.update(files)
        matches.append(Match(c, files, overlap(c, text)))
    # Declined work first, flagged before unflagged, then authority, then id: stable.
    matches.sort(
        key=lambda m: (m.claim.adoption == "current", not m.flagged, -m.claim.authority, m.claim.id)
    )
    uncovered = [f for f in change.files if f not in covered]
    return Report(change, matches, uncovered)


# --- change sources -------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path | None = None, stdin: str | None = None) -> str:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, cwd=cwd, input=stdin
        )
    except FileNotFoundError as exc:
        raise ChangeError(f"{cmd[0]} is not installed") from exc
    if proc.returncode != 0:
        detail = sanitize_line(proc.stderr.strip() or proc.stdout.strip())
        raise ChangeError(f"{' '.join(cmd[:3])} failed: {detail}")
    return proc.stdout


def _paths(output: str) -> list[str]:
    """File paths from a NUL-separated git listing: spaces, quotes and non-ASCII intact."""
    return [p for p in output.split("\0") if p]


def default_base(repo: Path) -> str:
    """The ref the local change will merge into: origin's default branch as the
    remote-tracking ref (it exists whenever origin's HEAD is known; a local copy of
    that branch may not), else `main`."""
    try:
        ref = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=repo)
    except ChangeError:
        return "main"
    return ref.strip() or "main"


def local_change(repo: Path, base: str | None = None) -> Change:
    """The current branch against its base, plus uncommitted edits: what is about to land.

    The text matched against claims is the commit messages since the merge base. When
    the base cannot be found locally, the working tree alone is reviewed and the label
    says so, so a smaller review is never mistaken for the whole one.
    """
    repo = Path(repo)
    base = base or default_base(repo)
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).strip()
    files: list[str] = []
    try:
        merge_base = _run(["git", "merge-base", base, "HEAD"], cwd=repo).strip()
    except ChangeError:
        label = f"working tree of {sanitize_line(branch)} (base {sanitize_line(base)} not found)"
        body = ""
    else:
        label = f"branch {sanitize_line(branch)} against {sanitize_line(base)}"
        span = f"{merge_base}..HEAD"
        files += _paths(_run(["git", "diff", "--name-only", "--no-renames", "-z", span], cwd=repo))
        body = _run(["git", "log", "--format=%s%n%b", span], cwd=repo)
    files += _paths(_run(["git", "diff", "--name-only", "--no-renames", "-z", "HEAD"], cwd=repo))
    files += _paths(_run(["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=repo))
    return Change(label=label, title=branch, body=body, files=list(dict.fromkeys(files)))


def github_change(number: int, repo_slug: str | None = None, cwd: Path | None = None) -> Change:
    """A pull request's title, description and files, through the `gh` CLI, run in the
    repository being reviewed so the pull request resolves against it."""
    where = ["--repo", repo_slug] if repo_slug else []
    fields = "title,body,baseRefName,headRefName,changedFiles,files"
    data = json.loads(_run(["gh", "pr", "view", str(number), "--json", fields, *where], cwd=cwd))
    # `gh pr view --json files` stops at 100 files without saying so; the diff listing
    # is complete. Fall back to the capped list only on a gh too old for `--name-only`.
    try:
        listing = _run(["gh", "pr", "diff", str(number), "--name-only", *where], cwd=cwd)
        files = [ln for ln in listing.splitlines() if ln]
    except ChangeError:
        files = [f["path"] for f in data.get("files", []) if isinstance(f, dict) and f.get("path")]
        expected = data.get("changedFiles")
        if isinstance(expected, int) and expected > len(files):
            raise ChangeError(
                f"gh listed {len(files)} of {expected} changed files; upgrade gh so "
                "`gh pr diff --name-only` is available"
            ) from None
    place = f" in {sanitize_line(repo_slug)}" if repo_slug else ""
    head, into = sanitize_line(data.get("headRefName")), sanitize_line(data.get("baseRefName"))
    return Change(
        label=f"pull request #{number}{place} ({head} into {into})",
        title=str(data.get("title") or ""),
        body=str(data.get("body") or ""),
        files=files,
    )


def post_comment(
    number: int, body: str, repo_slug: str | None = None, cwd: Path | None = None
) -> None:
    where = ["--repo", repo_slug] if repo_slug else []
    _run(["gh", "pr", "comment", str(number), "--body-file", "-", *where], cwd=cwd, stdin=body)


# --- rendering ----------------------------------------------------------------------------


def _line(m: Match) -> str:
    c = m.claim
    return f"[{claim_label(c)}] ({sanitize_line(c.scope)}) {sanitize_line(c.statement)}  [{c.id}]"


def render_text(report: Report) -> str:
    lines = [
        f"review: {report.change.label}",
        f"files: {len(report.change.files)}, claims in scope: {len(report.matches)}",
    ]
    for m in report.flagged:
        lines.append("")
        share = f"{m.overlap:.0%} overlap"
        lines.append(f"!! declined before, and this change reads like it ({share}):")
        lines.append("   " + _line(m))
        if m.claim.action:
            lines.append(f"   -> instead: {sanitize_line(m.claim.action)}")
        lines.append(f"   files: {', '.join(m.files)}")
    others = [m for m in report.matches if not m.flagged]
    if others:
        lines.append("")
        for m in others:
            lines.append(_line(m))
            if m.claim.action:
                verb = "" if m.claim.adoption == "current" else "instead: "
                lines.append(f"    -> {verb}{sanitize_line(m.claim.action)}")
            lines.append(f"    files: {', '.join(m.files)}")
    if report.uncovered:
        lines.append("")
        shown = ", ".join(report.uncovered[:UNCOVERED_LISTED])
        more = " …" if len(report.uncovered) > UNCOVERED_LISTED else ""
        lines.append(f"no claims cover {len(report.uncovered)} of the files: {shown}{more}")
    return "\n".join(lines)


def code(text: object) -> str:
    """Model-written text as a Markdown code span: never a mention, a link or markup.

    The report never puts a code span in a table: GitHub splits table cells on `|`
    before it reads inline code, so a `|` in a claim would end the span.
    """
    cleaned = sanitize_line(text).replace("`", "'")
    return f"`{cleaned}`" if cleaned else "`(empty)`"


def render_markdown(report: Report) -> str:
    lines = [
        "### crewlore review",
        "",
        f"{len(report.matches)} claim(s) cover the files in this change; "
        f"{len(report.flagged)} flagged.",
    ]
    for m in report.flagged:
        lines.append("")
        lines.append(f"> **Declined before.** {code(m.claim.statement)}")
        if m.claim.action:
            lines.append(f"> **Instead:** {code(m.claim.action)}")
        for a in m.claim.anchors[:MARKDOWN_ANCHORS]:
            who = anchor_attribution(a)
            by = f" ({code(who)})" if who else ""
            lines.append(f"> {code(a.ref)}{by}: {code(a.quote)}")
    others = [m for m in report.matches if not m.flagged]
    if others:
        lines.append("")
        for m in others:
            lines.append(
                f"- {code(claim_label(m.claim))} {code(m.claim.scope)}: {code(m.claim.statement)}"
            )
    lines.append("")
    lines.append(
        "<sub>Claims come from the repository's `.lore/`; they are evidence, not verdicts.</sub>"
    )
    text = "\n".join(lines)
    if len(text) > MARKDOWN_MAX_CHARS:
        cut = text[:MARKDOWN_MAX_CHARS].rsplit("\n", 1)[0]
        text = cut + "\n\n<sub>Report cut here; `lore review` locally prints it in full.</sub>"
    return text


def _entry(m: Match) -> dict:
    return {**claim_to_dict(m.claim), "overlap": round(m.overlap, 3), "files": m.files}


def to_json(report: Report) -> dict:
    return {
        "change": {
            "label": report.change.label,
            "title": sanitize_line(report.change.title),
            "files": report.change.files,
        },
        "flagged": [_entry(m) for m in report.flagged],
        "claims": [_entry(m) for m in report.matches if not m.flagged],
        "uncovered_files": report.uncovered,
    }
