"""The GitHub source turns API payloads into adapter-ready thread records.

A fake API stands in for `gh`, so these tests need no network, no credentials,
and no GitHub CLI install. The payload shapes mirror the real REST responses.
"""

import json

import pytest

from lore.capture.adapters.github_pr import GitHubPRAdapter
from lore.capture.sources.github import GitHubPRSource, detect_agent

PR = {
    "number": 42,
    "created_at": "2026-05-19T10:00:00Z",
    "merged_at": "2026-05-19T12:05:00Z",
    "closed_at": "2026-05-19T12:05:00Z",
    "title": "Add idempotency key to billing webhook",
    "body": "Stripe retries deliver the same event twice. Fixes #41",
    "user": {"login": "some-dev", "type": "User"},
    "head": {"sha": "deadbeef"},
}

COMMITS = [{
    "sha": "abc1234",
    "commit": {
        "message": "Persist idempotency key\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
        "author": {"date": "2026-05-19T10:05:00Z"},
    },
    "files": [{"filename": "services/billing/webhook.py"}],
}]

ISSUE = {
    "number": 41, "created_at": "2026-05-19T09:00:00Z",
    "title": "Billing webhook fires twice", "body": "Customers are double-charged.",
    "user": {"login": "maintainer", "type": "User"},
}

ISSUE_COMMENTS = [{
    "created_at": "2026-05-19T11:00:00Z", "body": "Don't put the key in Redis.",
    "user": {"login": "reviewer", "type": "User"},
}]

REVIEW_COMMENTS = [{
    "created_at": "2026-05-19T11:02:00Z", "body": "Must be inside the transaction.",
    "path": "services/billing/webhook.py", "line": 88,
    "user": {"login": "reviewer", "type": "User"},
}]

REVIEWS = [{
    "submitted_at": "2026-05-19T11:05:00Z", "state": "CHANGES_REQUESTED",
    "body": "Move it into the transaction.", "user": {"login": "reviewer", "type": "User"},
}]

CHECK_RUNS = {"check_runs": [{
    "name": "ci/pytest", "conclusion": "failure",
    "completed_at": "2026-05-19T10:30:00Z",
    "output": {"summary": "test_retry FAILED - IntegrityError"},
}]}


def fake_api(path, paginate=True):
    if path.startswith("repos/acme/billing/pulls/42/commits"):
        return COMMITS
    if path.startswith("repos/acme/billing/issues/41"):
        return ISSUE
    if path.startswith("repos/acme/billing/issues/42/comments"):
        return ISSUE_COMMENTS
    if path.startswith("repos/acme/billing/pulls/42/files"):
        return [{"filename": "services/billing/webhook.py"}]
    if path.startswith("repos/acme/billing/pulls/42/comments"):
        return REVIEW_COMMENTS
    if path.startswith("repos/acme/billing/pulls/42/reviews"):
        return REVIEWS
    if path.startswith("repos/acme/billing/commits/deadbeef/check-runs"):
        return CHECK_RUNS
    if path.startswith("repos/acme/billing/pulls?"):
        return [PR]
    raise AssertionError(f"unexpected api path: {path}")


@pytest.fixture
def source():
    return GitHubPRSource(api=fake_api)


# GUARDS: the published census found author metadata alone undercounts agents
# that commit under a human account. If trailer detection regresses, those PRs
# are silently classified as human and drop out of the corpus.
def test_agent_detected_from_commit_trailer_when_author_looks_human():
    agent, method = detect_agent(PR, COMMITS)
    assert agent == "claude-code"
    assert method == "commit-trailer"


def test_agent_detected_from_bot_author_login():
    pr = {"user": {"login": "devin-ai-integration[bot]"}, "body": ""}
    agent, method = detect_agent(pr, [])
    assert agent == "devin"
    assert method == "author-login"


def test_agent_detected_from_body_marker():
    pr = {"user": {"login": "some-dev"}, "body": "Generated with [Claude Code](https://x)"}
    agent, method = detect_agent(pr, [])
    assert agent == "claude-code"
    assert method == "body-marker"


# GUARDS: under-claiming is the safe direction — a false agent label contaminates
# the corpus, a false human label merely shrinks it.
def test_no_evidence_reports_human():
    pr = {"user": {"login": "some-dev"}, "body": "just a normal PR"}
    assert detect_agent(pr, [{"commit": {"message": "fix typo"}}]) == (None, "none")


# GUARDS: discover must never auto-paginate the full pull-request history. On a
# repository with tens of thousands of closed PRs that is thousands of API calls
# to obtain the handful the caller asked for, and it hangs rather than errors.
def test_discover_stops_as_soon_as_the_limit_is_reached():
    calls = []

    def api(path, paginate=True):
        calls.append((path, paginate))
        assert paginate is False, "discover must not auto-paginate"
        return [{"number": n} for n in range(100)]

    pulls = GitHubPRSource(api=api).discover("acme/billing", limit=5)
    assert len(pulls) == 5
    assert len(calls) == 1
    assert "per_page=5" in calls[0][0]


def test_discover_walks_pages_until_the_limit_is_met():
    pages = {1: [{"number": n} for n in range(100)], 2: [{"number": 100}]}

    def api(path, paginate=True):
        page = int(path.split("page=")[-1])
        return pages.get(page, [])

    pulls = GitHubPRSource(api=api).discover("acme/billing", limit=150)
    assert len(pulls) == 101  # stops on the short page, no infinite loop


def test_thread_contains_every_artifact_type(source):
    records = source.fetch_thread("acme/billing", PR)
    types = [r["type"] for r in records]
    assert types.count("issue") == 1
    assert types.count("pr") == 1
    assert "commit" in types
    assert "review_comment" in types
    assert "review" in types
    assert "check" in types


def test_detection_method_is_recorded_for_audit(source):
    records = source.fetch_thread("acme/billing", PR)
    pr_record = next(r for r in records if r["type"] == "pr")
    assert pr_record["agent"] == "claude-code"
    assert pr_record["detection"] == "commit-trailer"
    assert pr_record["actor"] == "agent"


# GUARDS: the outcome must close the session. If a merge landed mid-stream, the
# adapter's accept/reject verdict could be followed by more discussion and the
# session would no longer read as resolved.
def test_outcome_is_the_last_record(source):
    records = source.fetch_thread("acme/billing", PR)
    assert records[-1] == {
        "type": "timeline", "event": "merged", "created_at": "2026-05-19T12:05:00Z"
    }


def test_records_are_time_ordered(source):
    records = source.fetch_thread("acme/billing", PR)
    stamps = [r["created_at"] for r in records if r.get("created_at")]
    assert stamps == sorted(stamps)


# GUARDS: a merged PR carries both merged_at and closed_at. Emitting both would
# append a reject after the accept and invert the recorded outcome.
def test_merged_pr_emits_only_the_merge(source):
    records = source.fetch_thread("acme/billing", PR)
    events = [r for r in records if r["type"] == "timeline"]
    assert [e["event"] for e in events] == ["merged"]


def test_human_reviewers_are_not_labelled_as_the_agent(source):
    records = source.fetch_thread("acme/billing", PR)
    review = next(r for r in records if r["type"] == "review")
    assert review["actor"] == "human"


def test_unrecognised_bots_are_labelled_bot_not_human():
    from lore.capture.sources.github import _author

    actor, login = _author({"login": "release-please[bot]", "type": "Bot"}, None)
    assert actor == "bot"
    assert login == "release-please[bot]"


def test_export_writes_one_session_file_per_pr(tmp_path, source):
    stats = source.export("acme/billing", tmp_path, limit=10)
    assert stats["written"] == 1
    written = list(tmp_path.glob("*.jsonl"))
    assert [p.name for p in written] == ["pr_acme__billing__42.jsonl"]
    lines = [json.loads(ln) for ln in written[0].read_text().splitlines()]
    assert lines[-1]["event"] == "merged"


def test_export_skips_non_agent_prs_when_asked(tmp_path):
    human_pr = {**PR, "body": "no linked issue here"}
    human_commits = [{"sha": "x", "commit": {"message": "fix typo",
                                             "author": {"date": "2026-05-19T10:05:00Z"}}}]

    def api(path, paginate=True):
        if "commits" in path and "check-runs" not in path:
            return human_commits
        if path.startswith("repos/acme/billing/pulls?"):
            return [human_pr]
        if "check-runs" in path:
            return {"check_runs": []}
        return []

    stats = GitHubPRSource(api=api).export("acme/billing", tmp_path, limit=10)
    assert stats["written"] == 0
    assert stats["skipped_non_agent"] == 1


# GUARDS: the whole point of the source layer is that its output feeds the
# adapter unchanged. If the two drift, capture silently yields empty sessions.
def test_exported_records_parse_cleanly_through_the_adapter(tmp_path, source):
    source.export("acme/billing", tmp_path, limit=10)
    path = tmp_path / "pr_acme__billing__42.jsonl"

    events = GitHubPRAdapter().parse_transcript(path, session=path.stem)
    kinds = [e.kind for e in events]
    assert "user_message" in kinds  # the linked issue
    assert "agent_message" in kinds  # the PR body
    assert "diff" in kinds
    assert "tool_result" in kinds  # the failed check
    assert kinds[-1] == "accept"  # merged
    assert all(e.session == "pr_acme__billing__42" for e in events)


# GUARDS: an exported thread must survive the compile gate, or PR sessions get
# ingested and then never compiled.
def test_exported_thread_passes_the_compile_signal_gate(tmp_path, source):
    from lore.capture.signals import session_has_signal

    source.export("acme/billing", tmp_path, limit=10)
    path = tmp_path / "pr_acme__billing__42.jsonl"
    assert session_has_signal(GitHubPRAdapter().parse_transcript(path, session=path.stem))


# GUARDS: the commits endpoint omits per-commit file lists, so files are taken
# once at PR level. If this regresses, every diff event loses its refs and the
# compiler has no file pointers for the change.
def test_pr_record_carries_the_changed_file_list(source):
    records = source.fetch_thread("acme/billing", PR)
    pr_record = next(r for r in records if r["type"] == "pr")
    assert pr_record["files"] == ["services/billing/webhook.py"]

    events = GitHubPRAdapter().parse_records(records, session="s")
    pr_event = next(e for e in events if e.kind == "agent_message")
    assert pr_event.refs == ["services/billing/webhook.py"]


# GUARDS: projects that mandate AI-assistance disclosure invent their own
# wording, under human accounts. Missing these classifies genuinely agentic PRs
# as human and silently empties the corpus on exactly the repos we want.
def test_disclosure_marker_detects_an_unspecified_agent():
    pr = {"user": {"login": "a-human"},
          "body": "<!--\nAI-assisted change; reviewed locally.\n-->\n\n## What Problem This Solves"}
    agent, method = detect_agent(pr, [{"commit": {"message": "fix(ui): thing"}}])
    assert agent == "unspecified"
    assert method == "disclosure-marker"


def test_repo_specific_marker_can_be_supplied():
    pr = {"user": {"login": "a-human"}, "body": "Drafted by our house robot."}
    assert detect_agent(pr, [])[0] is None
    agent, method = detect_agent(pr, [], extra_markers=[r"house robot"])
    assert agent == "unspecified"
    assert method == "disclosure-marker"
