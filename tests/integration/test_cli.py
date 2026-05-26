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
