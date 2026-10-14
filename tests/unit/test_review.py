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


def test_the_recommended_alternative_and_template_words_do_not_flag():
    doing_the_right_thing = Change(
        label="pull request #8", title="Keep the idempotency key inside the transaction",
        body="Moves the key handling into the transaction as the team decided.",
        files=["services/billing/webhook.py"],
    )
    report = review([DECLINED], doing_the_right_thing)
    assert len(report.matches) == 1 and report.flagged == []
    graphql = _claim("GraphQL for the billing API was tried and not adopted", "services/billing",
                     adoption="not_adopted", action="keep REST")
    report = review([graphql], Change(label="x", title="Keep REST for billing", body="",
                                      files=["services/billing/api.py"]))
    assert report.flagged == []
    one_word = _claim("Use Redis", "services/billing", adoption="not_adopted", action="use the db")
    report = review([one_word], Change(label="x", title="Bump redis client version", body="",
                                       files=["services/billing/deps.txt"]))
    assert report.flagged == []  # one shared word is not a re-proposal
    # Naming the subject the way the recommended alternative does is not a re-proposal;
    # naming the declined approach itself is.
    declined = _claim("Use Redis for the idempotency key", "services/billing",
                      adoption="not_adopted", topic="idempotency-key",
                      action="keep the key inside the transaction")
    alternative = Change(label="x", title="Move the idempotency key into the transaction",
                         body="", files=["services/billing/webhook.py"])
    assert review([declined], alternative).flagged == []
    reproposal = Change(label="x", title="Keep the idempotency key in Redis for speed",
                        body="", files=["services/billing/webhook.py"])
    assert review([declined], reproposal).flagged != []


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


def test_markdown_report_keeps_model_text_in_code_spans_and_uses_no_table():
    hostile = _claim(
        "@octocat please merge [this](https://evil.example) `now`", "services/billing",
        adoption="not_adopted", action="see <img src=x onerror=alert(1)>",
    )
    piped = _claim("use `a | b` to pipe @octocat [x](https://evil.example)", "services/billing")
    change = Change(label="pull request #7", title="octocat please merge this now",
                    body="see img src x onerror alert 1 https evil example",
                    files=["services/billing/webhook.py"])
    md = render_markdown(review([hostile, CURRENT, piped], change))
    assert "**Declined before.** `@octocat please merge [this](https://evil.example) 'now'`" in md
    assert "**Instead:** `see <img src=x onerror=alert(1)>`" in md
    assert "`s#1` (`@reviewer, human, member`)" in md  # the anchor and its author
    assert "- `decision` `services/billing`: `dedupe billing webhooks" in md
    piped_line = "- `decision` `services/billing`: `use 'a | b' to pipe @octocat [x](https://evil.example)`"
    assert piped_line in md
    assert "evidence, not verdicts" in md
    assert code("") == "`(empty)`" and code(None) == "`(empty)`"
    # No table: GitHub splits table cells on `|` before it reads inline code.
    assert not any(line.startswith("|") for line in md.splitlines())
    # Every line carrying model-written text is a blockquote or a list item whose text sits
    # inside code spans, and mentions and links never appear outside one.
    for line in md.splitlines():
        if "octocat" in line:
            assert line.startswith(("> ", "- "))
            assert line.index("`") < line.index("octocat") < line.rindex("`")


def test_markdown_report_is_cut_before_github_rejects_it():
    many = [_claim(f"claim {i} " + "\u00e9" * 400, "services/billing") for i in range(300)]
    md = render_markdown(review(many, Change(label="x", title="t", body="",
                                             files=["services/billing/a.py"])))
    assert len(md.encode("utf-8")) <= mod.MARKDOWN_MAX_BYTES + 200 and "Report cut here" in md
    assert all(line.count("`") % 2 == 0 for line in md.splitlines())  # cut on a line boundary


def test_json_report_carries_the_shared_claim_shape_plus_overlap_and_files():
    payload = to_json(review([CURRENT, DECLINED], REPROPOSAL))
    assert payload["flagged"][0]["id"] == DECLINED.id
    assert payload["flagged"][0]["files"] == ["services/billing/webhook.py"]
    assert 0 < payload["flagged"][0]["overlap"] <= 1
    assert [c["id"] for c in payload["claims"]] == [CURRENT.id]
    assert payload["change"] == {
        "label": "pull request #7", "title": REPROPOSAL.title,
        "files": ["services/billing/webhook.py", "README.md"], "partial": False,
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
    (repo / "services" / "my billing file.py").write_text("y = 1\n")
    (repo / "services" / "caf\u00e9.py").write_text("z = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "Store the key in Redis\n\nfor speed")
    (repo / "README.md").write_text("hello again\n")  # uncommitted edit
    (repo / "notes.txt").write_text("untracked\n")  # untracked file
    (repo / "new file.txt").write_text("untracked with a space\n")
    change = local_change(repo, base="main")
    assert change.label == "branch feature against main" and change.title == "feature"
    assert "Store the key in Redis" in change.body and "for speed" in change.body
    assert change.files == [
        "services/billing.py", "services/caf\u00e9.py", "services/my billing file.py",
        "README.md", "new file.txt", "notes.txt",
    ]
    # An unknown base reviews the working tree alone, and the label says so.
    change = local_change(repo, base="no-such-branch")
    assert change.label == "working tree of feature (base no-such-branch not found)"
    assert change.partial is True
    assert change.files == ["README.md", "new file.txt", "notes.txt"] and change.body == ""
    # A detached checkout is named by its commit; a repository without commits is refused.
    _git(repo, "checkout", "-q", "--detach")
    detached = local_change(repo, base="main")
    assert detached.label.startswith("detached HEAD at ") and detached.partial is False
    empty = tmp_path / "empty"
    empty.mkdir()
    _git(empty, "init", "-q", "-b", "main")
    with pytest.raises(ChangeError, match="no commits yet"):
        local_change(empty, base="main")
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(ChangeError, match="not a git repository"):
        local_change(plain, base="main")
    # A subdirectory as --repo still lists paths from the repository root.
    _git(repo, "checkout", "-q", "feature")
    (repo / "services" / "untracked_in_sub.py").write_text("u\n")
    sub = local_change(repo / "services", base="main")
    assert "services/untracked_in_sub.py" in sub.files and "notes.txt" in sub.files


def test_text_report_cleans_file_names_git_hands_over_raw():
    change = Change(label="x", title="t", body="", files=["services/billing/\x1b[31mRED\x1b[0m.py",
                                                        "\x1b[2Jdocs/\u202eevil.md"])
    text = render_text(review([CURRENT], change))
    assert "\x1b" not in text and "\u202e" not in text
    assert "files: services/billing/RED.py" in text and "docs/evil.md" in text


def test_default_base_is_origins_default_branch_as_a_remote_tracking_ref(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_run", lambda cmd, cwd=None, stdin=None: "origin/main\n")
    assert mod.default_base(tmp_path) == "origin/main"

    def no_origin(cmd, cwd=None, stdin=None):
        raise ChangeError("no origin")

    monkeypatch.setattr(mod, "_run", no_origin)
    assert mod.default_base(tmp_path) == "main"


def _fake_gh(changed_files=2, api_lines=None, renamed=()):
    seen = []
    if api_lines is None:
        api_lines = [f"services/f{i}.py" for i in range(changed_files)]

    def fake_run(cmd, cwd=None, stdin=None):
        seen.append((cmd, cwd))
        if cmd[:3] == ["gh", "pr", "view"]:
            return json.dumps({
                "title": "Store the key in Redis", "body": "for speed",
                "changedFiles": changed_files,
                "baseRefName": "main", "headRefName": "feat/redis\x1b[31m",
            })
        if cmd[:3] == ["gh", "repo", "view"]:
            return "acme/billing\n"
        if cmd[:3] == ["gh", "api", "--paginate"]:
            assert cmd[3] == "repos/acme/billing/pulls/7/files"
            names = list(api_lines)
            for old, new in renamed:
                names += [new, old]
            return "".join(f"{n}\n" for n in names)
        raise AssertionError(cmd)

    return fake_run, seen


def test_github_change_reads_every_file_through_the_paginated_files_endpoint(monkeypatch, tmp_path):
    fake_run, seen = _fake_gh(changed_files=150)
    monkeypatch.setattr(mod, "_run", fake_run)
    change = mod.github_change(7, "acme/billing", cwd=tmp_path)
    assert len(change.files) == 150 and change.files[0] == "services/f0.py"
    assert change.label == "pull request #7 in acme/billing (feat/redis into main)"
    assert all(cwd == tmp_path for _, cwd in seen)  # gh runs in the reviewed repository
    assert [cmd[:2] for cmd, _ in seen] == [["gh", "pr"], ["gh", "api"]]  # slug given: no lookup
    fake_run, seen = _fake_gh(changed_files=2, api_lines=["services/caf\u00e9 x.py", "b.py"],
                              renamed=[("old name.py", "new name.py")])
    monkeypatch.setattr(mod, "_run", fake_run)
    change = mod.github_change(7)
    assert [cmd[:2] for cmd, _ in seen][1] == ["gh", "repo"]  # the slug comes from the checkout
    assert change.files == ["services/caf\u00e9 x.py", "b.py", "new name.py", "old name.py"]


def test_github_change_refuses_what_github_cannot_list_in_full(monkeypatch):
    fake_run, _ = _fake_gh(changed_files=3001, api_lines=["a.py"])
    monkeypatch.setattr(mod, "_run", fake_run)
    with pytest.raises(ChangeError, match="3001 files"):
        mod.github_change(7, "acme/billing")
    fake_run, _ = _fake_gh(changed_files=5, api_lines=["a.py", "b.py"])
    monkeypatch.setattr(mod, "_run", fake_run)
    with pytest.raises(ChangeError, match="2 file\\(s\\) for a pull request that changes 5"):
        mod.github_change(7, "acme/billing")

    def failing(cmd, cwd=None, stdin=None):
        if cmd[:3] == ["gh", "api", "--paginate"]:
            raise ChangeError("gh api repos failed: HTTP 406: diff exceeded the maximum")
        return _fake_gh(changed_files=400)[0](cmd, cwd, stdin)

    monkeypatch.setattr(mod, "_run", failing)
    with pytest.raises(ChangeError, match="HTTP 406"):  # gh's own words, not a guess
        mod.github_change(7, "acme/billing")


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
    monkeypatch.setattr("lore.review.github_change", lambda number, slug, cwd=None: REPROPOSAL)
    monkeypatch.setattr(
        "lore.review.post_comment",
        lambda number, body, slug, cwd=None: posted.update(n=number, body=body, cwd=cwd),
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
    assert posted["cwd"] == tmp_path and "comment posted" in result.stderr


def test_cli_review_of_the_local_branch_and_its_errors(tmp_path, monkeypatch):
    _store(tmp_path)
    quiet = Change(label="branch fix against main", title="fix", body="",
                   files=["services/auth/tokens.py"])
    monkeypatch.setattr("lore.review.local_change", lambda repo, base: quiet)
    result = runner.invoke(app, ["review", "--repo", str(tmp_path), "--exit-code"])
    assert result.exit_code == 0 and "rotate auth tokens hourly" in result.stdout
    result = runner.invoke(app, ["review", "--repo", str(tmp_path), "--comment"])
    assert result.exit_code == 2 and "needs a pull request number" in result.stderr
    assert result.stdout == ""  # refused before any work
    partial = Change(label="working tree of fix (base origin/main not found)", title="fix",
                     body="", files=["services/auth/tokens.py"], partial=True)
    monkeypatch.setattr("lore.review.local_change", lambda repo, base: partial)
    result = runner.invoke(app, ["review", "--repo", str(tmp_path)])
    assert result.exit_code == 0 and "commits were not reviewed" in result.stderr

    def broken(repo, base):
        raise ChangeError("git is not installed")

    monkeypatch.setattr("lore.review.local_change", broken)
    result = runner.invoke(app, ["review", "--repo", str(tmp_path)])
    assert result.exit_code == 1 and "git is not installed" in result.stderr
    result = runner.invoke(app, ["review", "--repo", str(tmp_path / "nowhere")])
    assert result.exit_code == 1 and "lore init" in result.stderr
