"""CLI smoke tests via typer's runner. The LLM-dependent `compile` path is
exercised only for its graceful no-credentials error; compile orchestration
itself is covered in test_run_compile.py.
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

import lore
from lore.cli import app
from lore.schemas import Anchor, Claim, Provenance
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


def test_hook_commands_round_trip(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = runner.invoke(app, ["hook", "install", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "post-commit: written" in result.stdout and "post-merge: written" in result.stdout
    result = runner.invoke(app, ["hook", "status", "--repo", str(tmp_path)])
    assert "post-commit: installed" in result.stdout
    result = runner.invoke(app, ["hook", "uninstall", "--repo", str(tmp_path)])
    assert result.exit_code == 0 and "removed" in result.stdout
    result = runner.invoke(app, ["hook", "install", "--repo", str(tmp_path / "nowhere")])
    assert result.exit_code == 2 and "not inside a git repository" in result.stdout


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
# loop) must leave claims.jsonl exactly as it was: never empty, never truncated.
RENDER_PROCESSES = 6


def test_concurrent_renders_leave_the_claims_file_byte_identical(tmp_path):
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
    env = {**os.environ, "PYTHONPATH": str(Path(lore.__file__).resolve().parents[1])}
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "lore.cli", "render", "--repo", str(tmp_path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
        )
        for _ in range(RENDER_PROCESSES)
    ]
    outputs = [p.communicate(timeout=120)[0] for p in procs]
    assert all(p.returncode == 0 for p in procs), outputs
    assert store.claims_path.read_bytes() == before
    assert all(o.startswith("rendered") or "another compile is running" in o for o in outputs)
    assert any(o.startswith("rendered") for o in outputs), outputs


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
