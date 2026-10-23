"""The Claude Code plugin under `plugins/crewlore/`, listed by the marketplace file at
the repository root, is the installer's output in plugin layout: the committed files
equal what `lore.claude_plugin` renders, the skill is byte for byte what `lore install`
writes, the hooks are the entries `lore install --hooks` adds, and the manifests follow
the documented rules.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

from lore import __version__
from lore.assistant_hooks import HOOK_EVENTS, HOOK_SHELL, HOOK_TIMEOUT_SECONDS, install_hooks
from lore.assistants import SKILL_NAME, install
from lore.claude_plugin import (
    HOOKS_PATH,
    MANIFEST_PATH,
    MARKETPLACE_PATH,
    PLUGIN_NAME,
    PLUGIN_ROOT,
    SKILL_PATH,
    plugin_files,
    stale_files,
    write_plugin_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
# Plugin names are kebab-case; marketplace and entry names allow letters, digits, ., _, -.
KEBAB = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
PLUGIN_ID_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


def _committed(rel: str) -> str:
    with open(REPO_ROOT / rel, encoding="utf-8", newline="") as handle:
        return handle.read()


# --- the committed files are the generator's output -------------------------------------


def test_committed_plugin_files_match_the_generator():
    expected = plugin_files()
    assert set(expected) == {MANIFEST_PATH, MARKETPLACE_PATH, SKILL_PATH, HOOKS_PATH}
    # The marketplace file sits at the repository root; everything else is under the
    # plugin root, so an install copies that directory and not the repository.
    assert MARKETPLACE_PATH == ".claude-plugin/marketplace.json"
    for rel in (MANIFEST_PATH, SKILL_PATH, HOOKS_PATH):
        assert rel.startswith(PLUGIN_ROOT + "/"), rel
    assert not (REPO_ROOT / ".claude-plugin" / "plugin.json").exists()
    for rel, text in expected.items():
        assert (REPO_ROOT / rel).is_file(), f"{rel} is missing"
        assert _committed(rel) == text, (
            f"{rel} differs from the generator; run `uv run python scripts/export_plugin.py`"
        )
    assert stale_files(REPO_ROOT) == []


def test_generator_writes_once_and_reports_stale_files(tmp_path):
    first = write_plugin_files(tmp_path)
    assert sorted(first) == sorted(f"written {rel}" for rel in plugin_files())
    assert stale_files(tmp_path) == []
    assert all(line.startswith("already current ") for line in write_plugin_files(tmp_path))
    (tmp_path / HOOKS_PATH).write_text("{}\n")
    (tmp_path / SKILL_PATH).unlink()
    assert stale_files(tmp_path) == [SKILL_PATH, HOOKS_PATH]
    assert f"written {HOOKS_PATH}" in write_plugin_files(tmp_path)
    assert stale_files(tmp_path) == []


def test_every_file_is_utf8_with_lf_endings_and_a_final_newline():
    for rel, text in plugin_files().items():
        assert "\r" not in text and text.endswith("\n"), rel
        assert text == text.encode("utf-8").decode("utf-8")


# --- the skill and the hooks are what `lore install --hooks` writes ---------------------


def test_plugin_skill_is_byte_identical_to_what_lore_install_writes(home):
    install(["claude"])
    installed = home / ".claude" / "skills" / SKILL_NAME / "SKILL.md"
    with open(installed, encoding="utf-8", newline="") as handle:
        assert handle.read() == _committed(SKILL_PATH)
    front = _committed(SKILL_PATH).split("---\n")[1]
    assert f"name: {SKILL_NAME}\n" in front  # so the plugin command is /crewlore:lore


def test_plugin_hooks_are_the_entries_lore_install_writes(tmp_path):
    settings = tmp_path / "settings.json"
    assert install_hooks(settings, tmp_path) == "written"
    installed = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
    committed = json.loads(_committed(HOOKS_PATH))
    assert set(committed) == {"description", "hooks"}
    assert committed["hooks"] == installed
    assert set(committed["hooks"]) == set(HOOK_EVENTS)
    for event, matcher in HOOK_EVENTS.items():
        (group,) = committed["hooks"][event]
        assert group.get("matcher") == matcher
        (hook,) = group["hooks"]
        # The same shell command, not a plugin variant: `lore` on PATH, exit 0 whatever
        # happens, only the hook's own JSON passed on; nothing bundled with the plugin.
        assert hook == {"type": "command", "command": HOOK_SHELL, "timeout": HOOK_TIMEOUT_SECONDS}
        assert "CLAUDE_PLUGIN_ROOT" not in hook["command"]


# --- the manifests follow the documented rules -------------------------------------------


def test_plugin_manifest_names_the_package():
    manifest = json.loads(_committed(MANIFEST_PATH))
    assert manifest["name"] == PLUGIN_NAME and KEBAB.fullmatch(manifest["name"])
    assert manifest["version"] == __version__, "regenerate the plugin on each release"
    assert manifest["license"] == "MIT"
    assert manifest["author"]["name"]
    for field in ("homepage", "repository"):
        url = urlparse(manifest[field])
        assert url.scheme == "https" and url.netloc, field
    assert manifest["description"] and len(manifest["description"]) < 1024
    # Metadata only: every component is in its default location, and nothing here points
    # outside the plugin.
    assert not {"skills", "hooks", "commands", "agents", "mcpServers"} & set(manifest)


def test_marketplace_lists_the_plugin_at_its_own_root():
    market = json.loads(_committed(MARKETPLACE_PATH))
    manifest = json.loads(_committed(MANIFEST_PATH))
    assert PLUGIN_ID_PART.fullmatch(market["name"]) and market["name"] != "."
    assert market["owner"]["name"] and market["description"]
    (entry,) = market["plugins"]
    # The install id is <entry name>@<marketplace name>; the entry name must equal the
    # manifest name, or installing by the manifest name fails.
    assert entry["name"] == manifest["name"] == PLUGIN_NAME
    # A relative source starts with `./` and resolves from the marketplace root.
    assert entry["source"] == f"./{PLUGIN_ROOT}"
    assert (REPO_ROOT / entry["source"] / ".claude-plugin" / "plugin.json").is_file()
    assert "version" not in entry  # the manifest's version is the one that counts
    assert entry["description"] == manifest["description"]


def test_pyproject_version_matches_the_package_version():
    """release.yml checks the tag against pyproject.toml alone, and the plugin manifest
    follows `lore.__version__`; a bump that misses one of them would ship a plugin that
    never updates, so the two must agree."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.M)
    assert match and match.group(1) == __version__
