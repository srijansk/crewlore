"""Fetch pull-request threads from GitHub and normalize them for the PR adapter.

This is what makes `lore` usable on a repository you have never run an agent in:
point it at `owner/repo` and it exports the PR threads as sessions, with no local
transcript directory and no waiting for a team to generate history.

Network access goes through the `gh` CLI rather than a new HTTP dependency: `gh`
already holds the user's credentials and handles pagination, so there is nothing
to configure and no token for `lore` to store.

## Attribution

Deciding whether a pull request was written by a coding agent is the interesting
part, and it is done here rather than in the adapter because it needs evidence
the adapter never sees. Published census work found that author metadata alone
badly undercounts some agents — one agent's PRs are dominated by cloud bot
accounts while another commits under a human's account with a trailer — so a
single signal is not enough. Three are combined, and the winning one is recorded
on the record so a downstream disagreement can be audited rather than argued:

* the PR author login (catches bot-account agents),
* commit trailers (catches agents that commit under a human account),
* body markers left by the agent's own template.

An unrecognised author is reported as human. Under-claiming agent authorship is
the safe direction: it shrinks the corpus rather than contaminating it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from lore.capture.adapters.github_pr import pr_session_id

# Bot/app accounts that coding agents open pull requests under.
_AGENT_LOGINS = {
    "chatgpt-codex-connector": "openai-codex",
    "codex": "openai-codex",
    "copilot": "github-copilot",
    "copilot-swe-agent": "github-copilot",
    "devin-ai-integration": "devin",
    "cursoragent": "cursor",
    "cursor": "cursor",
    "google-labs-jules": "google-jules",
    "claude": "claude-code",
}

# Markers agents leave in commit trailers or PR bodies. Matched case-insensitively
# against the combined commit messages and PR body.
_AGENT_MARKERS = [
    (r"co-authored-by:\s*claude", "claude-code"),
    (r"generated with \[?claude code", "claude-code"),
    (r"co-authored-by:\s*codex", "openai-codex"),
    (r"generated with \[?codex", "openai-codex"),
    (r"co-authored-by:\s*cursor", "cursor"),
    (r"generated with \[?cursor", "cursor"),
    (r"co-authored-by:\s*devin", "devin"),
    (r"generated with \[?jules", "google-jules"),
]

# Projects that require contributors to disclose AI assistance name the practice,
# not the product — often in an HTML comment their PR template supplies. That is
# real evidence of agent authorship even though it identifies no agent, so it is
# reported as `unspecified` rather than discarded or guessed at.
_DISCLOSURE_MARKERS = [
    r"ai-assisted",
    r"ai assisted",
    r"generated with \[?[\w .-]*\bai\b",
    r"🤖 generated with",
]

UNSPECIFIED_AGENT = "unspecified"

_LINKED_ISSUE = re.compile(r"\b(?:fixes|closes|resolves)\s+#(\d+)\b", re.IGNORECASE)


class GitHubError(RuntimeError):
    pass


def _gh_api(path: str, paginate: bool = True) -> list | dict:
    """Call the GitHub API through `gh`, returning decoded JSON."""
    cmd = ["gh", "api", path]
    if paginate:
        # --slurp keeps paginated pages as one JSON array instead of concatenated
        # documents, which json.loads cannot parse.
        cmd += ["--paginate", "--slurp"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise GitHubError(
            "the GitHub CLI (`gh`) is required to fetch pull requests; "
            "install it and run `gh auth login`"
        ) from exc
    if proc.returncode != 0:
        raise GitHubError(f"gh api {path} failed: {proc.stderr.strip()}")
    data = json.loads(proc.stdout or "[]")
    # --slurp nests each page in a list; flatten so callers see a flat result.
    if paginate and isinstance(data, list) and data and isinstance(data[0], list):
        return [item for page in data for item in page]
    return data


def detect_agent(
    pr: dict, commits: list[dict], extra_markers: list[str] | None = None
) -> tuple[str | None, str]:
    """Identify the coding agent behind a PR. Returns `(agent, method)`.

    `agent` is None when no evidence was found, in which case the caller should
    treat the author as human. `extra_markers` accepts repo-specific disclosure
    conventions, because projects that mandate disclosure invent their own
    wording and no fixed list stays correct across repositories.
    """
    login = ((pr.get("user") or {}).get("login") or "").lower()
    stripped = login.removesuffix("[bot]")
    if agent := _AGENT_LOGINS.get(stripped):
        return agent, "author-login"

    messages = "\n".join((c.get("commit") or {}).get("message") or "" for c in commits)
    for pattern, agent in _AGENT_MARKERS:
        if re.search(pattern, messages, re.IGNORECASE):
            return agent, "commit-trailer"

    body = pr.get("body") or ""
    for pattern, agent in _AGENT_MARKERS:
        if re.search(pattern, body, re.IGNORECASE):
            return agent, "body-marker"

    for pattern in _DISCLOSURE_MARKERS + list(extra_markers or []):
        if re.search(pattern, body, re.IGNORECASE):
            return UNSPECIFIED_AGENT, "disclosure-marker"

    return None, "none"


def _author(user: dict | None, agent: str | None) -> tuple[str, str | None]:
    """Map a GitHub user onto the record vocabulary: (actor, login)."""
    user = user or {}
    login = user.get("login")
    if agent:
        return "agent", login
    # A bot that is not a recognised coding agent is still not a human; label it
    # so the compiler does not read release-bot chatter as a teammate's opinion.
    if user.get("type") == "Bot" or (login or "").endswith("[bot]"):
        return "bot", login
    return "human", login


class GitHubPRSource:
    """Fetches PR threads and writes them as adapter-ready JSONL sessions."""

    def __init__(self, api=_gh_api, extra_markers: list[str] | None = None):
        self._api = api
        self._extra_markers = extra_markers or []

    def discover(self, repo: str, *, limit: int = 50, state: str = "closed") -> list[dict]:
        """List recent pull requests, most recently updated first.

        Pages are walked explicitly and stopped as soon as `limit` is reached.
        Letting the API layer auto-paginate here would walk the repository's
        entire pull-request history before the limit could apply — on a large
        repo that is tens of thousands of requests for the fifty PRs we want.
        """
        out: list[dict] = []
        page = 1
        while len(out) < limit:
            per_page = min(100, limit - len(out))
            batch = self._api(
                f"repos/{repo}/pulls?state={state}&sort=updated&direction=desc"
                f"&per_page={per_page}&page={page}",
                paginate=False,
            )
            if not batch:
                break
            out.extend(batch)
            if len(batch) < per_page:
                break  # last page
            page += 1
        return out[:limit]

    def fetch_thread(self, repo: str, pr: dict, *, include_checks: bool = True) -> list[dict]:
        """Assemble one PR's full thread as normalized records, in time order."""
        number = pr["number"]
        commits = self._api(f"repos/{repo}/pulls/{number}/commits")
        agent, method = detect_agent(pr, commits, self._extra_markers)
        # The commit list endpoint omits per-commit file lists, so the changed
        # files are taken once at PR level. Without this the diff events carry no
        # refs at all and the compiler loses every file pointer in the change.
        files = [f["filename"] for f in self._api(f"repos/{repo}/pulls/{number}/files")]

        records: list[dict] = []
        records.extend(self._issue_records(repo, pr))
        records.append(self._pr_record(repo, pr, agent, method, files))
        records.extend(self._commit_records(commits, agent))
        records.extend(self._comment_records(repo, number))
        records.extend(self._review_records(repo, number))
        if include_checks:
            records.extend(self._check_records(repo, pr))
        records.sort(key=lambda r: r.get("created_at") or "")
        records.extend(self._outcome_records(pr))
        return records

    def export(
        self,
        repo: str,
        out_dir: Path | str,
        *,
        limit: int = 50,
        agents_only: bool = True,
        include_checks: bool = True,
    ) -> dict:
        """Write one JSONL session per PR into `out_dir` for `lore compile`.

        The filename is the session id, which is what makes ingestion incremental:
        a PR already exported is skipped by the store on the next pass.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        owner, _, name = repo.partition("/")
        written = skipped = 0
        for pr in self.discover(repo, limit=limit):
            records = self.fetch_thread(repo, pr, include_checks=include_checks)
            if agents_only and not any(r.get("agent") for r in records):
                skipped += 1
                continue
            path = out_dir / f"{pr_session_id(owner, name, pr['number'])}.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in records))
            written += 1
        return {"repo": repo, "written": written, "skipped_non_agent": skipped}

    # --- record builders ---
    def _issue_records(self, repo: str, pr: dict) -> list[dict]:
        """The issue a PR closes is the human's original request."""
        match = _LINKED_ISSUE.search(pr.get("body") or "")
        if not match:
            return []
        try:
            issue = self._api(f"repos/{repo}/issues/{match.group(1)}", paginate=False)
        except GitHubError:
            return []  # a linked issue may be deleted or in a private repo
        actor, login = _author(issue.get("user"), None)
        return [{
            "type": "issue", "actor": actor, "login": login,
            "created_at": issue.get("created_at"), "number": issue.get("number"),
            "title": issue.get("title"), "body": issue.get("body"),
        }]

    @staticmethod
    def _pr_record(
        repo: str, pr: dict, agent: str | None, method: str, files: list[str]
    ) -> dict:
        actor, login = _author(pr.get("user"), agent)
        return {
            "type": "pr", "actor": actor, "login": login, "repo": repo,
            "number": pr["number"], "created_at": pr.get("created_at"),
            "title": pr.get("title"), "body": pr.get("body"), "files": files,
            "agent": agent, "detection": method,
        }

    @staticmethod
    def _commit_records(commits: list[dict], agent: str | None) -> list[dict]:
        out = []
        for c in commits:
            commit = c.get("commit") or {}
            out.append({
                "type": "commit", "sha": c.get("sha"),
                "actor": "agent" if agent else "human",
                "created_at": (commit.get("author") or {}).get("date"),
                "message": commit.get("message"),
                "files": [f["filename"] for f in c.get("files") or []],
            })
        return out

    def _comment_records(self, repo: str, number: int) -> list[dict]:
        out = []
        for c in self._api(f"repos/{repo}/issues/{number}/comments"):
            actor, login = _author(c.get("user"), None)
            out.append({
                "type": "comment", "actor": actor, "login": login,
                "created_at": c.get("created_at"), "body": c.get("body"),
            })
        for c in self._api(f"repos/{repo}/pulls/{number}/comments"):
            actor, login = _author(c.get("user"), None)
            out.append({
                "type": "review_comment", "actor": actor, "login": login,
                "created_at": c.get("created_at"), "body": c.get("body"),
                "path": c.get("path"), "line": c.get("line") or c.get("original_line"),
            })
        return out

    def _review_records(self, repo: str, number: int) -> list[dict]:
        out = []
        for r in self._api(f"repos/{repo}/pulls/{number}/reviews"):
            actor, login = _author(r.get("user"), None)
            out.append({
                "type": "review", "actor": actor, "login": login,
                "created_at": r.get("submitted_at"), "state": r.get("state"),
                "body": r.get("body"),
            })
        return out

    def _check_records(self, repo: str, pr: dict) -> list[dict]:
        sha = (pr.get("head") or {}).get("sha")
        if not sha:
            return []
        try:
            payload = self._api(f"repos/{repo}/commits/{sha}/check-runs", paginate=False)
        except GitHubError:
            return []  # checks are not enabled on every repository
        out = []
        for run in (payload or {}).get("check_runs", []):
            output = (run.get("output") or {}).get("summary") or ""
            out.append({
                "type": "check", "created_at": run.get("completed_at") or run.get("started_at"),
                "name": run.get("name"), "conclusion": run.get("conclusion"), "output": output,
            })
        return out

    @staticmethod
    def _outcome_records(pr: dict) -> list[dict]:
        """The terminal verdict, appended last so it closes the session."""
        if pr.get("merged_at"):
            return [{"type": "timeline", "event": "merged", "created_at": pr["merged_at"]}]
        if pr.get("closed_at"):
            return [{"type": "timeline", "event": "closed", "created_at": pr["closed_at"]}]
        return []
