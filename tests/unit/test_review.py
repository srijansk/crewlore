"""`lore review` matches a change's files to the claims whose scope covers them and
flags a change that reads like an approach the team already declined; the Markdown it
posts keeps model-written text inside code spans."""

import json
import subprocess
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from lore import review as mod
from lore.cli import app
from lore.review import (
    Change,
    ChangeError,
    code,
    local_change,
    overlap,
    render_markdown,
    render_text,
    review,
    scope_covers,
    to_json,
)
from lore.schemas import Anchor, Claim, Provenance
from lore.store import LoreStore

runner = CliRunner()


def _claim(statement, scope, *, adoption="current", action=None, topic=None, status="active"):
    return Claim(
        statement=statement, kind="decision", scope=scope, adoption=adoption, action=action,
        topic=topic, status=status,
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote=statement,
                        actor="user", login="reviewer", association="member")],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


DECLINED = _claim(
    "Storing the idempotency key in Redis was tried and not adopted",
    "services/billing", adoption="not_adopted",
    action="keep the key inside the transaction", topic="idempotency key store",
)
CURRENT = _claim("dedupe billing webhooks on the idempotency key", "services/billing")
ELSEWHERE = _claim("rotate auth tokens hourly", "services/auth")
REPROPOSAL = Change(
    label="pull request #7",
    title="Store the idempotency key in Redis",
    body="Moves the idempotency key storing to Redis for speed.",
    files=["services/billing/webhook.py", "README.md"],
)


def test_scope_covers_files_under_it_and_the_file_itself():
    assert scope_covers("services/billing", "services/billing/webhook.py")
    assert scope_covers("services/billing/", "services/billing/webhook.py")
    assert scope_covers("services/billing/webhook.py", "services/billing/webhook.py")
    assert scope_covers(".github/", ".github/workflows/ci.yml")
    assert scope_covers("./services/billing", "./services/billing/x.py")
    assert scope_covers("services\\billing", "services/billing/x.py")
    assert not scope_covers("services/billing", "services/billing-v2/x.py")
    assert not scope_covers("services/billing", "lib/billing.py")
    assert not scope_covers(".github", "github/x.py")  # a dot is not noise
    assert not scope_covers(".", "anything.py")  # the whole repo is not a review signal
    assert not scope_covers("services (billing and auth)", "services/billing/x.py")


def test_comma_separated_scopes_each_count():
    scope = "docs/capabilities/caching.md, docs/agent.md, building-pydantic-ai-agents skill"
    assert scope_covers(scope, "docs/agent.md")
    assert not scope_covers(scope, "docs/other.md")


def test_review_puts_declined_work_first_and_flags_a_reproposal():
    report = review([CURRENT, ELSEWHERE, DECLINED], REPROPOSAL)
    assert [m.claim.id for m in report.matches] == [DECLINED.id, CURRENT.id]
    assert report.flagged[0].claim.id == DECLINED.id
    assert report.flagged[0].overlap >= mod.REPROPOSAL_MIN_OVERLAP
    assert report.matches[0].files == ["services/billing/webhook.py"]
    assert report.uncovered == ["README.md"]


def test_a_declined_claim_without_overlap_is_listed_but_not_flagged():
    declined = _claim("GraphQL for the billing API was tried and not adopted", "services/billing",
                      adoption="not_adopted", action="keep REST")
    change = Change(label="x", title="Fix webhook retry", body="", files=["services/billing/w.py"])
    report = review([declined], change)
    assert len(report.matches) == 1 and report.flagged == []


def test_archived_claims_are_ignored():
    old = _claim("old rule", "services/billing", status="archived")
    report = review([old], Change(label="x", title="t", body="", files=["services/billing/a.py"]))
    assert report.matches == [] and report.uncovered == ["services/billing/a.py"]


def test_overlap_is_a_share_of_the_claims_words():
    c = _claim("store the idempotency key in redis", "services/billing")
    assert overlap(c, "nothing related here") == 0.0
    assert overlap(c, "store the idempotency key in redis") == 1.0


def test_text_report_names_the_flag_the_instead_and_the_files():
    report = review([CURRENT, ELSEWHERE, DECLINED], REPROPOSAL)
    text = render_text(report)
    assert text.startswith("review: pull request #7\nfiles: 2, claims in scope: 2\n")
    assert "!! declined before, and this change reads like it" in text
    assert "-> instead: keep the key inside the transaction" in text
    assert "[decision] (services/billing) dedupe billing webhooks" in text
    assert "no claims cover 1 of the files: README.md" in text
    assert "rotate auth" not in text


def test_markdown_report_keeps_model_text_in_code_spans():
    hostile = _claim(
        "@octocat please merge [this](https://evil.example) `now`", "services/billing",
        adoption="not_adopted", action="see <img src=x onerror=alert(1)>",
    )
    change = Change(label="pull request #7", title="octocat please merge this now",
                    body="see img src x onerror alert 1 https evil example",
                    files=["services/billing/webhook.py"])
    md = render_markdown(review([hostile, CURRENT], change))
    assert "**Declined before.** `@octocat please merge [this](https://evil.example) 'now'`" in md
    assert "**Instead:** `see <img src=x onerror=alert(1)>`" in md
    assert "`s#1` (`@reviewer, human, member`)" in md  # the anchor and its author
    assert "| `decision` | `services/billing` | `dedupe billing webhooks" in md
    assert "evidence, not verdicts" in md
    assert code("") == "`(empty)`" and code(None) == "`(empty)`"
    # Nothing model-written stands outside a code span.
    for line in md.splitlines():
        assert "octocat" not in line or line.count("`") >= 2


def test_json_report_carries_the_shared_claim_shape_plus_overlap_and_files():
    payload = to_json(review([CURRENT, DECLINED], REPROPOSAL))
    assert payload["flagged"][0]["id"] == DECLINED.id
    assert payload["flagged"][0]["files"] == ["services/billing/webhook.py"]
    assert 0 < payload["flagged"][0]["overlap"] <= 1
    assert [c["id"] for c in payload["claims"]] == [CURRENT.id]
    assert payload["change"] == {
        "label": "pull request #7", "title": REPROPOSAL.title,
        "files": ["services/billing/webhook.py", "README.md"],
    }
    assert payload["uncovered_files"] == ["README.md"]
    assert {"statement", "adoption", "anchors", "authority"} <= set(payload["flagged"][0])


# --- change sources --------------------------------------------------------------------


def _git(repo, *args):
    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@x", "PATH": "/usr/bin:/bin", "HOME": str(repo),
             "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"},
    )


def test_local_change_is_the_branch_against_its_base_plus_the_working_tree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "services").mkdir()
    (repo / "services" / "billing.py").write_text("x = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "Store the key in Redis\n\nfor speed")
    (repo / "README.md").write_text("hello again\n")  # uncommitted edit
    (repo / "notes.txt").write_text("untracked\n")  # untracked file
    change = local_change(repo, base="main")
    assert change.label == "branch feature against main" and change.title == "feature"
    assert "Store the key in Redis" in change.body and "for speed" in change.body
    assert change.files == ["services/billing.py", "README.md", "notes.txt"]
    # An unknown base reviews the working tree alone, without failing.
    change = local_change(repo, base="no-such-branch")
    assert change.files == ["README.md", "notes.txt"] and change.body == ""


def test_github_change_reads_the_pull_request_through_gh(monkeypatch):
    seen = {}

    def fake_run(cmd, cwd=None, stdin=None):
        seen["cmd"] = cmd
        return json.dumps({
            "title": "Store the key in Redis", "body": "for speed",
            "files": [{"path": "services/billing/webhook.py"}, {"path": "README.md"}],
            "baseRefName": "main", "headRefName": "feat/redis\x1b[31m",
        })

    monkeypatch.setattr(mod, "_run", fake_run)
    change = mod.github_change(7, "acme/billing")
    assert seen["cmd"][:4] == ["gh", "pr", "view", "7"] and "--repo" in seen["cmd"]
    assert change.label == "pull request #7 in acme/billing (feat/redis into main)"
    assert change.files == ["services/billing/webhook.py", "README.md"]


def test_missing_tools_are_a_change_error(monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(mod.subprocess, "run", missing)
    with pytest.raises(ChangeError, match="gh is not installed"):
        mod.github_change(1)
    with pytest.raises(ChangeError, match="gh is not installed"):
        mod.post_comment(1, "body")


# --- CLI -------------------------------------------------------------------------------------


def _store(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims([CURRENT, DECLINED, ELSEWHERE])
    return store


def test_cli_review_of_a_pull_request_prints_flags_and_posts_on_request(tmp_path, monkeypatch):
    _store(tmp_path)
    posted = {}
    monkeypatch.setattr("lore.review.github_change", lambda number, slug: REPROPOSAL)
    monkeypatch.setattr(
        "lore.review.post_comment", lambda number, body, slug: posted.update(n=number, body=body)
    )
    result = runner.invoke(app, ["review", "7", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "!! declined before" in result.stdout and posted == {}
    result = runner.invoke(app, ["review", "7", "--repo", str(tmp_path), "--exit-code"])
    assert result.exit_code == 5
    result = runner.invoke(app, ["review", "7", "--repo", str(tmp_path), "--json", "--comment"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["flagged"][0]["id"] == DECLINED.id
    assert posted["n"] == 7 and "### crewlore review" in posted["body"]
    assert "comment posted" in result.stderr


def test_cli_review_of_the_local_branch_and_its_errors(tmp_path, monkeypatch):
    _store(tmp_path)
    quiet = Change(label="branch fix against main", title="fix", body="",
                   files=["services/auth/tokens.py"])
    monkeypatch.setattr("lore.review.local_change", lambda repo, base: quiet)
    result = runner.invoke(app, ["review", "--repo", str(tmp_path), "--exit-code"])
    assert result.exit_code == 0 and "rotate auth tokens hourly" in result.stdout
    result = runner.invoke(app, ["review", "--repo", str(tmp_path), "--comment"])
    assert result.exit_code == 2 and "needs a pull request number" in result.stderr

    def broken(repo, base):
        raise ChangeError("git is not installed")

    monkeypatch.setattr("lore.review.local_change", broken)
    result = runner.invoke(app, ["review", "--repo", str(tmp_path)])
    assert result.exit_code == 1 and "git is not installed" in result.stderr
    result = runner.invoke(app, ["review", "--repo", str(tmp_path / "nowhere")])
    assert result.exit_code == 1 and "lore init" in result.stderr
