"""CLI smoke tests via typer's runner. The LLM-dependent `compile` path is
exercised only for its graceful no-credentials error; compile orchestration
itself is covered in test_run_compile.py.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

import lore
from lore.cli import app
from lore.schemas import Anchor, Claim, Conflict, Provenance
from lore.serve.server import Explanation, claim_to_dict
from lore.store import LoreStore

runner = CliRunner()


def _seed_claim(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims(
        [
            Claim(
                statement="dedupe billing webhook on idempotency key",
                kind="gotcha", scope="services/billing",
                provenance=Provenance(session="s", author="a", harness="claude-code"),
                anchors=[Anchor(source_kind="transcript", ref="s#1", quote="fires twice")],
                observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
            )
        ]
    )


def test_init_creates_layout(tmp_path):
    result = runner.invoke(app, ["init", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".lore" / "claims").is_dir()


def test_status_reports_counts(tmp_path):
    _seed_claim(tmp_path)
    result = runner.invoke(app, ["status", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "1" in result.stdout
    assert "claim" in result.stdout.lower()


def test_query_prints_relevant_claim(tmp_path):
    _seed_claim(tmp_path)
    result = runner.invoke(app, ["query", "billing webhook", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "dedupe billing webhook" in result.stdout


def test_query_with_no_match_is_graceful(tmp_path):
    _seed_claim(tmp_path)
    result = runner.invoke(app, ["query", "kubernetes networking", "--repo", str(tmp_path)])
    assert result.exit_code == 0


def test_compile_without_credentials_errors_clearly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    LoreStore(tmp_path).init()
    result = runner.invoke(
        app,
        [
            "compile", "--repo", str(tmp_path), "--transcripts", str(tmp_path / "none"),
            "--expect-head", "0" * 40,  # accepted: the hooks pass it
        ],
    )
    assert result.exit_code != 0
    assert "key" in result.stdout.lower() or "key" in str(result.exception).lower()


def test_watch_once_without_credentials_errors_clearly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    LoreStore(tmp_path).init()
    result = runner.invoke(
        app,
        ["watch", "--once", "--repo", str(tmp_path), "--transcripts", str(tmp_path / "none")],
    )
    assert result.exit_code != 0
    assert "key" in result.stdout.lower() or "key" in str(result.exception).lower()


def test_query_marks_claims_the_team_did_not_adopt(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims(
        [
            Claim(
                statement="Redis for the webhook idempotency key was proposed and not adopted",
                kind="decision", scope="services/billing", adoption="not_adopted",
                action="keep the key inside the database transaction",
                provenance=Provenance(session="s", author="a", harness="claude-code"),
                anchors=[Anchor(source_kind="transcript", ref="s#1", quote="not in Redis")],
                observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
            )
        ]
    )
    result = runner.invoke(app, ["query", "webhook idempotency key", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "[decision · not adopted]" in result.stdout
    assert "-> instead: keep the key" in result.stdout


def test_status_before_init_says_so_instead_of_pretending(tmp_path):
    result = runner.invoke(app, ["status", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "lore init" in result.stdout


def test_init_twice_reports_already_initialised(tmp_path):
    runner.invoke(app, ["init", "--repo", str(tmp_path)])
    result = runner.invoke(app, ["init", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "Already initialised" in result.stdout


def test_query_shows_claim_ids_and_feedback_marks_them(tmp_path):
    _seed_claim(tmp_path)
    shown = runner.invoke(app, ["query", "billing webhook", "--repo", str(tmp_path)])
    cid = next(c.id for c in LoreStore(tmp_path).load_claims())
    assert cid in shown.stdout

    result = runner.invoke(app, ["feedback", cid, "--influential", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert LoreStore(tmp_path).load_claims()[0].usage.times_influential == 1

    result = runner.invoke(app, ["feedback", cid, "--overridden", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert LoreStore(tmp_path).load_claims()[0].usage.times_overridden == 1


def test_feedback_requires_exactly_one_verdict(tmp_path):
    _seed_claim(tmp_path)
    cid = LoreStore(tmp_path).load_claims()[0].id
    both = runner.invoke(
        app, ["feedback", cid, "--influential", "--overridden", "--repo", str(tmp_path)]
    )
    assert both.exit_code == 2
    unknown = runner.invoke(app, ["feedback", "clm_nope", "--influential", "--repo", str(tmp_path)])
    assert unknown.exit_code == 1


def test_import_prs_rejects_an_unknown_state(tmp_path):
    result = runner.invoke(
        app, ["import-prs", "acme/billing", "--state", "merged", "--repo", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "--state" in result.stdout


# GUARDS: the default transcript directory is scoped to this repo. The old
# default (the whole ~/.claude/projects tree) in an existing config is treated
# the same way — nobody intends to compile every project into one repo.
def test_default_transcript_dir_is_scoped_to_this_repo(tmp_path, monkeypatch):
    import yaml

    from lore.capture import ingest
    from lore.cli import _transcript_dir

    monkeypatch.setattr(ingest, "CLAUDE_PROJECTS_ROOT", tmp_path / "projects")
    repo = tmp_path / "repo"
    store = LoreStore(repo)
    store.init()
    scoped = ingest.claude_code_project_dir(repo, projects_root=tmp_path / "projects")
    assert _transcript_dir(store, None) == scoped

    cfg = yaml.safe_load(store.config_path.read_text())
    cfg["capture"]["transcripts"] = str(tmp_path / "projects")  # the pre-0.3 default
    store.config_path.write_text(yaml.safe_dump(cfg))
    assert _transcript_dir(store, None) == scoped

    cfg["capture"]["transcripts"] = str(tmp_path / "elsewhere")  # an explicit choice
    store.config_path.write_text(yaml.safe_dump(cfg))
    assert _transcript_dir(store, None) == tmp_path / "elsewhere"
    assert _transcript_dir(store, tmp_path / "override") == tmp_path / "override"


def test_render_rebuilds_the_book_without_a_model(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _seed_claim(tmp_path)
    result = runner.invoke(app, ["render", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "rendered 1 active claims" in result.stdout
    assert "0 claim line(s) changed" in result.stdout
    book = (tmp_path / ".lore" / "knowledge" / "README.md").read_text()
    assert "dedupe billing webhook" in book


def test_render_counts_sessions_that_still_need_extraction(tmp_path):
    from lore.schemas import NSFEvent

    store = LoreStore(tmp_path)
    store.init()
    store.write_session(
        "ses_new",
        [
            NSFEvent(
                session="ses_new", actor="user", kind="user_message",
                timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
                content="the billing webhook fires twice; we must dedupe it on the key",
            ),
            NSFEvent(
                session="ses_new", actor="agent", kind="agent_message",
                timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
                content="Right, dedupe on the idempotency key before processing.",
            ),
        ],
    )
    result = runner.invoke(app, ["render", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "1 captured session(s) have no cached extraction yet" in result.stdout


def test_hook_commands_round_trip(tmp_path, monkeypatch):
    import lore.hooks as hooks_module

    monkeypatch.setattr(hooks_module, "_import_problem", lambda python: None)  # not the subject
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = runner.invoke(app, ["hook", "install", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    for name in ("post-commit", "post-merge", "post-rewrite"):
        assert f"{name}: written" in result.stdout
    assert "any non-empty value" in result.stdout
    for flags in ([], ["--probe"]):
        result = runner.invoke(app, ["hook", "status", "--repo", str(tmp_path), *flags])
        assert result.exit_code == 0, result.stdout
        for name in ("post-commit", "post-merge", "post-rewrite"):
            assert f"{name}: installed\n" in result.stdout
    assert "last hook output: (no hook has run yet)" in result.stdout
    log = tmp_path / ".lore" / "cache" / "hook.log"
    log.parent.mkdir(parents=True)
    log.write_text("rendered 3 active claims and 0 conflicts\n")
    result = runner.invoke(app, ["hook", "status", "--repo", str(tmp_path)])
    assert "last hook output: rendered 3 active claims" in result.stdout
    result = runner.invoke(app, ["hook", "uninstall", "--repo", str(tmp_path)])
    assert result.exit_code == 0 and "removed" in result.stdout
    result = runner.invoke(app, ["hook", "install", "--repo", str(tmp_path / "nowhere")])
    assert result.exit_code == 2 and "not inside a git repository" in result.stdout


def test_hook_install_refuses_a_hook_it_cannot_safely_edit(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    hook = tmp_path / ".git" / "hooks" / "post-merge"
    hook.write_text("#!/usr/bin/env node\nconsole.log('mine')\n")
    result = runner.invoke(app, ["hook", "install", "--repo", str(tmp_path)])
    assert result.exit_code == 2
    assert "error:" in result.stdout and "node script" in result.stdout
    assert not (tmp_path / ".git" / "hooks" / "post-commit").exists()


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


def test_render_in_a_store_without_claims_creates_no_files(tmp_path):
    LoreStore(tmp_path).init()
    result = runner.invoke(app, ["render", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "nothing to render" in result.stdout
    lore_dir = tmp_path / ".lore"
    assert not (lore_dir / "claims" / "claims.jsonl").exists()
    assert not (lore_dir / "claims" / "conflicts.jsonl").exists()
    assert not (lore_dir / "knowledge" / "README.md").exists()


def test_render_steps_aside_while_another_compile_holds_the_store(tmp_path):
    from lore.compile.run import compile_lock

    _seed_claim(tmp_path)
    with compile_lock(LoreStore(tmp_path)):
        result = runner.invoke(app, ["render", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "another compile is running" in result.stdout
    assert not (tmp_path / ".lore" / "knowledge" / "README.md").exists()


def test_render_with_expect_head_writes_nothing_once_head_moved(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "one")
    _seed_claim(tmp_path)
    book = tmp_path / ".lore" / "knowledge" / "README.md"

    result = runner.invoke(app, ["render", "--repo", str(tmp_path), "--expect-head", "0" * 40])
    assert result.exit_code == 0, result.stdout
    assert "HEAD moved" in result.stdout and not book.exists()

    head = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    result = runner.invoke(app, ["render", "--repo", str(tmp_path), "--expect-head", head])
    assert result.exit_code == 0, result.stdout
    assert "rendered 1 active claims" in result.stdout and book.exists()


# GUARDS: renders that overlap (post-merge hooks from a rebase, a teammate's watch
# loop) must leave claims.jsonl exactly as it was: never empty, never truncated. The
# first batch runs while this process holds the lock, so every one of them must step
# aside: a lock that did not exclude other processes would show up here as a render.
RENDER_PROCESSES = 6


def _render_processes(repo):
    env = {**os.environ, "PYTHONPATH": str(Path(lore.__file__).resolve().parents[1])}
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "lore.cli", "render", "--repo", str(repo)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
        )
        for _ in range(RENDER_PROCESSES)
    ]
    outputs = [p.communicate(timeout=120)[0] for p in procs]
    assert all(p.returncode == 0 for p in procs), outputs
    return outputs


def test_concurrent_renders_leave_the_claims_file_byte_identical(tmp_path):
    from lore.compile.run import compile_lock

    store = LoreStore(tmp_path)
    store.init()
    store.write_claims(
        [
            Claim(
                statement=f"claim number {i} about the billing webhook",
                kind="gotcha", scope="services/billing",
                provenance=Provenance(session="s", author="a", harness="claude-code"),
                anchors=[Anchor(source_kind="transcript", ref=f"s#{i}", quote="fires twice")],
                observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
            )
            for i in range(20)
        ]
    )
    before = store.claims_path.read_bytes()
    assert before

    with compile_lock(store):
        held = _render_processes(tmp_path)
    assert all("skipped: another compile is running" in o for o in held), held
    assert store.claims_path.read_bytes() == before
    assert not (tmp_path / ".lore" / "knowledge" / "README.md").exists()

    free = _render_processes(tmp_path)
    assert all(o.startswith("rendered") or "another compile is running" in o for o in free), free
    assert any(o.startswith("rendered") for o in free), free
    assert store.claims_path.read_bytes() == before
    assert (tmp_path / ".lore" / "knowledge" / "README.md").exists()


def test_settle_time_comes_from_config_with_a_default_for_older_configs(tmp_path):
    import yaml

    from lore.cli import _settle

    store = LoreStore(tmp_path)
    store.init()
    assert _settle(store) == timedelta(minutes=10)
    cfg = yaml.safe_load(store.config_path.read_text())
    cfg["capture"]["settle_minutes"] = 0
    store.config_path.write_text(yaml.safe_dump(cfg))
    assert _settle(store) == timedelta(0)
    del cfg["capture"]["settle_minutes"]  # written by an older version
    store.config_path.write_text(yaml.safe_dump(cfg))
    assert _settle(store) == timedelta(minutes=10)


# GUARDS: a settle time that is not a number used to be a traceback out of `float()`.
# It is a config error, and the message names the setting.
@pytest.mark.parametrize("bad", [None, "abc", -1, True, "inf"])
def test_an_invalid_settle_time_is_a_clear_error_not_a_traceback(tmp_path, bad):
    import yaml

    store = LoreStore(tmp_path)
    store.init()
    cfg = yaml.safe_load(store.config_path.read_text())
    cfg["capture"]["settle_minutes"] = bad
    store.config_path.write_text(yaml.safe_dump(cfg))
    result = runner.invoke(
        app, ["compile", "--repo", str(tmp_path), "--transcripts", str(tmp_path / "none")]
    )
    assert result.exit_code == 2, result.stdout
    assert "capture.settle_minutes" in result.stdout and repr(bad) in result.stdout
    assert result.exception is None or isinstance(result.exception, SystemExit)


# GUARDS: a manual compile right after a session should not have to wait out the
# configured settle time or edit the config: `--settle` overrides it for one run.
def test_settle_can_be_overridden_for_one_run(tmp_path, monkeypatch):
    import lore.cli as cli_module

    calls = []

    def fake_compile_once(store, transcript_dir, **kwargs):
        calls.append(kwargs["settle"])
        return {"ingested": 0, "redactions": 0, "active": 0, "conflicts": 0}

    monkeypatch.setattr(cli_module, "_compile_once", fake_compile_once)
    LoreStore(tmp_path).init()
    tdir = str(tmp_path / "none")
    result = runner.invoke(app, ["compile", "--repo", str(tmp_path), "--transcripts", tdir])
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(
        app, ["compile", "--repo", str(tmp_path), "--transcripts", tdir, "--settle", "0"]
    )
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(
        app, ["watch", "--once", "--repo", str(tmp_path), "--transcripts", tdir, "--settle", "2.5"]
    )
    assert result.exit_code == 0, result.stdout
    assert calls == [timedelta(minutes=10), timedelta(0), timedelta(minutes=2.5)]

    result = runner.invoke(
        app, ["compile", "--repo", str(tmp_path), "--transcripts", tdir, "--settle", "-1"]
    )
    assert result.exit_code == 2 and "--settle must be a number of minutes" in result.stdout
    assert len(calls) == 3


def test_query_output_strips_terminal_escapes(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims(
        [
            Claim(
                statement="dedupe \x1b[31mbilling\x1b[0m webhook on idempotency key",
                kind="gotcha", scope="services/billing",
                provenance=Provenance(session="s", author="a", harness="claude-code"),
                anchors=[Anchor(source_kind="transcript", ref="s#1", quote="fires twice")],
                observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
            )
        ]
    )
    result = runner.invoke(app, ["query", "billing webhook", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "\x1b" not in result.stdout and "dedupe billing webhook" in result.stdout


def _seed_two_scopes(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    prov = Provenance(session="s", author="a", harness="claude-code")
    when = datetime(2026, 5, 19, tzinfo=timezone.utc)
    store.write_claims(
        [
            Claim(
                statement="dedupe billing webhook on idempotency key", kind="gotcha",
                scope="services/billing", provenance=prov, observed_at=when,
                anchors=[Anchor(source_kind="transcript", ref="s#1", quote="fires twice",
                                actor="user", login="reviewer", association="member")],
            ),
            Claim(
                statement="Redis for the idempotency key was tried and not adopted",
                kind="decision", scope="services/billing", adoption="not_adopted",
                action="keep the key inside the transaction", provenance=prov, observed_at=when,
                anchors=[Anchor(source_kind="transcript", ref="s#2", quote="not in Redis")],
            ),
            Claim(
                statement="rotate auth tokens hourly", kind="procedure",
                scope="services/auth", provenance=prov, observed_at=when,
                anchors=[Anchor(source_kind="transcript", ref="s#3", quote="hourly")],
            ),
            Claim(
                statement="retry webhook deliveries three times", kind="procedure",
                scope="services/billing/webhooks", provenance=prov, observed_at=when,
                anchors=[Anchor(source_kind="transcript", ref="s#4", quote="three times")],
            ),
            Claim(
                statement="an archived billing claim", kind="gotcha", status="archived",
                scope="services/billing", provenance=prov, observed_at=when,
                anchors=[Anchor(source_kind="transcript", ref="s#5", quote="old")],
            ),
        ]
    )
    return store


def test_query_json_is_the_shared_claim_shape_and_ascii_safe(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims([
        Claim(
            statement="dedupe billing webhook on idempotency key for the caf\u00e9 tenant",
            kind="gotcha", scope="services/billing",
            provenance=Provenance(session="s", author="a", harness="claude-code"),
            anchors=[Anchor(source_kind="transcript", ref="s#1", quote="fires twice")],
            observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        )
    ])
    result = runner.invoke(app, ["query", "billing webhook", "--repo", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.stdout
    rows = json.loads(result.stdout)
    assert rows[0]["statement"].endswith("caf\u00e9 tenant")
    assert set(rows[0]) == set(claim_to_dict(store.load_claims()[0]))
    assert rows[0]["anchors"][0] == {
        "ref": "s#1", "quote": "fires twice", "actor": None, "login": None, "association": None,
    }
    assert result.stdout.isascii() and "\\u00e9" in result.stdout


def test_query_no_match_exits_0_unless_asked_and_json_is_still_json(tmp_path):
    _seed_claim(tmp_path)
    base = ["query", "kubernetes networking", "--repo", str(tmp_path)]
    assert runner.invoke(app, base).exit_code == 0
    result = runner.invoke(app, base + ["--json"])
    assert result.exit_code == 0 and json.loads(result.stdout) == []
    assert runner.invoke(app, base + ["--exit-code"]).exit_code == 4
    result = runner.invoke(app, base + ["--json", "--exit-code"])
    assert result.exit_code == 4 and json.loads(result.stdout) == []


def test_uninitialised_repo_exits_1_with_the_hint_on_stderr(tmp_path):
    for command in (["query", "anything"], ["explain", "services"]):
        result = runner.invoke(app, command + ["--repo", str(tmp_path), "--json"])
        assert result.exit_code == 1
        assert result.stdout.strip() == "" and "lore init" in result.stderr


def test_explain_prints_a_scope_with_declined_work_after_current(tmp_path):
    _seed_two_scopes(tmp_path)
    result = runner.invoke(app, ["explain", "services/billing", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert out.startswith("services/billing  (2 claims, 1 not adopted)\n")
    assert out.index("[gotcha]") < out.index("[decision · not adopted]")
    assert "-> instead: keep the key inside the transaction" in out
    assert 'anchor s#1 (@reviewer, human, member): "fires twice"' in out
    assert 'anchor s#2: "not in Redis"' in out
    assert "archived billing claim" not in out
    assert out.rstrip().endswith("1 narrower scope: services/billing/webhooks")
    # Under a heading that names the scope, claim lines do not repeat it.
    assert "[gotcha] dedupe billing webhook" in out


def test_explain_singular_heading_and_no_footer_without_narrower_scopes(tmp_path):
    _seed_two_scopes(tmp_path)
    result = runner.invoke(app, ["explain", "services/auth", "--repo", str(tmp_path)])
    assert result.stdout.startswith("services/auth  (1 claim, 0 not adopted)\n")
    assert "narrower" not in result.stdout


@pytest.mark.parametrize(
    "spelling", ["services/billing/", "./services/billing", "services\\billing"]
)
def test_explain_accepts_the_spellings_a_shell_produces(tmp_path, spelling):
    _seed_two_scopes(tmp_path)
    result = runner.invoke(app, ["explain", spelling, "--repo", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["scope"] == "services/billing"


def test_explain_refuses_an_ambiguous_prefix_with_candidates(tmp_path):
    _seed_two_scopes(tmp_path)
    expected = ["services/auth", "services/billing", "services/billing/webhooks"]
    result = runner.invoke(app, ["explain", "services", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert all(sc in result.stdout for sc in expected)
    result = runner.invoke(app, ["explain", "services", "--repo", str(tmp_path), "--exit-code"])
    assert result.exit_code == 3
    result = runner.invoke(app, ["explain", "services", "--repo", str(tmp_path), "--json"])
    payload = json.loads(result.stdout)
    assert payload == {
        "scope": None, "claims": [], "conflicts": [], "ambiguous": expected, "narrower": [],
    }


def test_explain_with_no_match_says_so_and_exits_4_only_when_asked(tmp_path):
    _seed_two_scopes(tmp_path)
    base = ["explain", "frontend", "--repo", str(tmp_path)]
    result = runner.invoke(app, base)
    assert result.exit_code == 0 and "no active claims" in result.stdout
    assert runner.invoke(app, base + ["--exit-code"]).exit_code == 4
    result = runner.invoke(app, base + ["--json"])
    keys = {"scope", "claims", "conflicts", "ambiguous", "narrower"}
    assert set(json.loads(result.stdout)) == keys


def test_explain_rejects_an_empty_name(tmp_path):
    _seed_two_scopes(tmp_path)
    result = runner.invoke(app, ["explain", "  ", "--repo", str(tmp_path)])
    assert result.exit_code == 2 and "scope name" in result.stderr
    result = runner.invoke(app, ["explain", "  ", "--repo", str(tmp_path), "--json"])
    assert result.exit_code == 2 and "scope name" in result.stderr
    assert set(json.loads(result.stdout)) == set(Explanation().to_dict())
    # A lone separator is not a name either; it used to list nearly every scope.
    result = runner.invoke(app, ["explain", "/", "--repo", str(tmp_path), "--json"])
    assert result.exit_code == 0 and json.loads(result.stdout)["ambiguous"] == []


def test_explain_resolves_a_candidate_it_listed_even_for_raw_old_scopes(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    prov = Provenance(session="s", author="a", harness="claude-code")
    when = datetime(2026, 5, 19, tzinfo=timezone.utc)
    store.write_claims([
        Claim(statement="two spaces", kind="gotcha", scope="docs  api", provenance=prov,
              observed_at=when, anchors=[Anchor(source_kind="transcript", ref="s#1", quote="q")]),
        Claim(statement="version two", kind="gotcha", scope="docs api v2", provenance=prov,
              observed_at=when, anchors=[Anchor(source_kind="transcript", ref="s#2", quote="q")]),
        Claim(statement="hidden char", kind="gotcha", scope="services/\u200bbilling",
              provenance=prov, observed_at=when,
              anchors=[Anchor(source_kind="transcript", ref="s#3", quote="q")]),
    ])

    def explain_json(name):
        result = runner.invoke(app, ["explain", name, "--repo", str(tmp_path), "--json"])
        return json.loads(result.stdout)

    assert explain_json("docs")["ambiguous"] == ["docs api", "docs api v2"]
    answer = explain_json("docs api")
    assert answer["scope"] == "docs api"
    assert [c["statement"] for c in answer["claims"]] == ["two spaces"]
    shown = explain_json("services/billing")
    assert shown["scope"] == "services/billing"
    assert shown["claims"][0]["statement"] == "hidden char"


def test_explain_json_marks_only_that_scope_served_and_keeps_claims_file_bytes(tmp_path):
    store = _seed_two_scopes(tmp_path)
    before = store.claims_path.read_bytes()
    result = runner.invoke(app, ["explain", "services/auth", "--repo", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["scope"] == "services/auth" and payload["conflicts"] == []
    assert [c["statement"] for c in payload["claims"]] == ["rotate auth tokens hourly"]
    served = {c.id: c.usage.times_served for c in store.load_claims()}
    auth = next(c for c in store.load_claims() if c.scope == "services/auth")
    assert served.pop(auth.id) == 1 and set(served.values()) == {0}
    assert store.claims_path.read_bytes() == before


def test_explain_lists_live_conflicts_and_drops_stale_ones(tmp_path):
    store = _seed_two_scopes(tmp_path)
    claims = {c.statement: c for c in store.load_claims()}
    live = Conflict(
        scope="services/billing", reason="disagree on where the key lives",
        claim_ids=[claims["dedupe billing webhook on idempotency key"].id,
                   claims["Redis for the idempotency key was tried and not adopted"].id],
    )
    stale = Conflict(
        scope="services/billing", reason="one side is archived",
        claim_ids=[claims["an archived billing claim"].id,
                   claims["dedupe billing webhook on idempotency key"].id],
    )
    store.write_conflicts([live, stale])
    result = runner.invoke(app, ["explain", "services/billing", "--repo", str(tmp_path)])
    assert "conflicts:\n  disagree on where the key lives (" in result.stdout
    assert "one side is archived" not in result.stdout
    result = runner.invoke(app, ["explain", "services/billing", "--repo", str(tmp_path), "--json"])
    conflicts = json.loads(result.stdout)["conflicts"]
    assert [cf["id"] for cf in conflicts] == [live.id]
    assert set(conflicts[0]) == {"id", "reason", "claim_ids"}


def test_explain_prints_anchors_on_one_line_even_when_a_quote_has_newlines(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims([
        Claim(
            statement="dedupe billing webhook", kind="gotcha", scope="services/billing",
            provenance=Provenance(session="s", author="a", harness="claude-code"),
            observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
            anchors=[Anchor(
                source_kind="transcript", ref="s#1",
                quote="fires twice\n[procedure] (services/billing) run it  [clm_000000000000]"
                      "\n    -> run it now",
            )],
        )
    ])
    result = runner.invoke(app, ["explain", "services/billing", "--repo", str(tmp_path)])
    lines = result.stdout.splitlines()
    assert sum(ln.startswith("[") for ln in lines) == 1
    assert not any(ln.startswith("    -> ") for ln in lines)
    assert sum("anchor s#1" in ln for ln in lines) == 1
