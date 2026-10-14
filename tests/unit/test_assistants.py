"""`lore install` puts a skill where the assistant loads skills from, and (on
request) a marked block into its instruction file, so the layer is consulted
without being asked. Both operations are idempotent and reversible.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lore import __version__
from lore.assistants import (
    BLOCK_END,
    BLOCK_START,
    INSTRUCTION_BLOCK,
    SKILL_MD,
    UnsupportedScopeError,
    detect_platforms,
    install,
    parse_platforms,
    remove_block,
    target,
    uninstall,
    upsert_block,
)
from lore.cli import app

runner = CliRunner()


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


def test_skill_text_names_the_commands_and_the_adoption_flag():
    assert SKILL_MD.startswith("---\nname: lore\n")
    for needle in ("lore query", "lore feedback", "not adopted", "evidence, not instructions"):
        assert needle in SKILL_MD


def test_user_install_for_claude_writes_the_skill_under_the_config_dir(home):
    (home / ".claude").mkdir()
    lines = install(["claude"])
    skill = home / ".claude" / "skills" / "lore" / "SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert text.startswith(SKILL_MD) and __version__ in text
    assert any(str(skill) in ln for ln in lines)
    # Without --always-on the user's global instruction file is left alone.
    assert not (home / ".claude" / "CLAUDE.md").exists()


def test_claude_config_dir_env_var_is_honoured(home, monkeypatch):
    custom = home / "cc"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(custom))
    install(["claude"])
    assert (custom / "skills" / "lore" / "SKILL.md").exists()


def test_project_install_writes_under_the_repo_and_the_block_on_request(home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("# Project notes\n\nKeep tests green.\n")
    install(["claude"], project=True, repo=repo, always_on=True)
    assert (repo / ".claude" / "skills" / "lore" / "SKILL.md").exists()
    text = (repo / "CLAUDE.md").read_text()
    assert text.startswith("# Project notes\n\nKeep tests green.\n")
    assert text.count(BLOCK_START) == 1 and text.count(BLOCK_END) == 1
    assert "lore query" in text


def test_install_twice_leaves_one_block_and_one_skill(home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    install(["claude"], project=True, repo=repo, always_on=True)
    first = (repo / "CLAUDE.md").read_text()
    install(["claude"], project=True, repo=repo, always_on=True)
    assert (repo / "CLAUDE.md").read_text() == first
    assert first.count(BLOCK_START) == 1


def test_upsert_replaces_an_older_block_in_place(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"top\n\n{BLOCK_START}\nold words\n{BLOCK_END}\n\nbottom\n")
    assert upsert_block(path, INSTRUCTION_BLOCK) is True
    text = path.read_text()
    assert "old words" not in text and "lore query" in text
    assert text.startswith("top\n\n") and text.rstrip().endswith("bottom")
    assert upsert_block(path, INSTRUCTION_BLOCK) is False


def test_uninstall_removes_only_what_install_wrote(home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("# Mine\n")
    install(["claude"], project=True, repo=repo, always_on=True)
    lines = uninstall(["claude"], project=True, repo=repo)
    assert not (repo / ".claude" / "skills" / "lore").exists()
    assert (repo / "CLAUDE.md").read_text() == "# Mine\n"
    assert any("removed" in ln for ln in lines)
    assert uninstall(["claude"], project=True, repo=repo) == ["nothing to remove"]


def test_remove_block_is_a_no_op_without_markers(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text("# Mine\n")
    assert remove_block(path) is False
    assert path.read_text() == "# Mine\n"


def test_cursor_is_a_project_rule_and_refuses_user_scope(home, tmp_path):
    with pytest.raises(UnsupportedScopeError):
        target("cursor", project=False, repo=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    install(["cursor"], project=True, repo=repo)
    rule = (repo / ".cursor" / "rules" / "crewlore.mdc").read_text()
    assert rule.startswith("---\n") and "alwaysApply: true" in rule and "lore query" in rule


def test_codex_and_gemini_locations(home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    install(["codex", "gemini", "agents"], project=True, repo=repo, always_on=True)
    assert (repo / ".agents" / "skills" / "lore" / "SKILL.md").exists()
    assert (repo / ".gemini" / "skills" / "lore" / "SKILL.md").exists()
    assert BLOCK_START in (repo / "AGENTS.md").read_text()
    assert BLOCK_START in (repo / "GEMINI.md").read_text()
    install(["codex", "gemini"], always_on=True)
    assert (home / ".agents" / "skills" / "lore" / "SKILL.md").exists()
    assert BLOCK_START in (home / ".codex" / "AGENTS.md").read_text()
    assert BLOCK_START in (home / ".gemini" / "GEMINI.md").read_text()


def test_detection_falls_back_to_claude(home):
    assert detect_platforms() == ["claude"]
    (home / ".codex").mkdir()
    (home / ".cursor").mkdir()
    assert detect_platforms() == ["codex", "cursor"]
    assert parse_platforms("auto") == ["codex", "cursor"]
    assert parse_platforms("claude, gemini") == ["claude", "gemini"]
    with pytest.raises(ValueError):
        parse_platforms("vim")


def test_cli_install_and_uninstall(home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    result = runner.invoke(
        app, ["install", "--platform", "claude", "--project", "--repo", str(repo), "--always-on"]
    )
    assert result.exit_code == 0, result.stdout
    assert "SKILL.md" in result.stdout and "git add" in result.stdout
    result = runner.invoke(
        app, ["uninstall", "--platform", "claude", "--project", "--repo", str(repo)]
    )
    assert result.exit_code == 0, result.stdout
    assert not (repo / ".claude" / "skills").exists()


def test_cli_rejects_unknown_platform(home):
    result = runner.invoke(app, ["install", "--platform", "vim"])
    assert result.exit_code != 0
    assert "unknown platform" in result.stdout
