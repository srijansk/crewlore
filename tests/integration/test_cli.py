"""CLI smoke tests via typer's runner. The LLM-dependent `compile` path is
exercised only for its graceful no-credentials error; compile orchestration
itself is covered in test_run_compile.py.
"""

from datetime import datetime, timezone

from typer.testing import CliRunner

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
        app, ["compile", "--repo", str(tmp_path), "--transcripts", str(tmp_path / "none")]
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
