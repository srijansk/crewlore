"""The Claude Code plugin at the root of this repository: the same `/lore` skill and the
same three hooks that `lore install --hooks` writes, in the layout Claude Code's plugin
loader reads, so that

    /plugin marketplace add srijansk/crewlore
    /plugin install crewlore@crewlore

gives a user what `lore install --hooks` gives, from one source of truth. The four files
are generated, never edited by hand: `scripts/export_plugin.py` writes them from
`SKILL_MD` (`lore.assistants`) and `hook_groups()` (`lore.assistant_hooks`), and
`tests/unit/test_claude_plugin.py` fails when a committed file differs from what this
module renders, so the plugin cannot drift from the installer. The plugin bundles no
Python: its skill and its hooks run the `lore` command on PATH (`pipx install crewlore`).

Layout, as the plugin reference documents it: the marketplace file at
`.claude-plugin/marketplace.json` under the repository root, whose one entry points at
`plugins/crewlore/`, the plugin root, so an install copies that directory and not the
repository; under it, the manifest at `.claude-plugin/plugin.json`, the skill at
`skills/lore/SKILL.md`, invoked as `/crewlore:lore`, and the hooks at
`hooks/hooks.json`, the same shape as the `hooks` object in a settings file. `version`
is the package version: Claude Code keeps a user on a plugin version until the string
changes, so each release regenerates the manifest (the test insists on it).
"""

from __future__ import annotations

import json
from pathlib import Path

from lore import __version__
from lore.assistant_hooks import HOOK_COMMAND, hook_groups
from lore.assistants import SKILL_MD, SKILL_NAME, _put, _stamp

PLUGIN_NAME = "crewlore"
MARKETPLACE_NAME = "crewlore"
# The plugin root, relative to the repository root; the marketplace entry's source.
PLUGIN_ROOT = f"plugins/{PLUGIN_NAME}"
REPOSITORY_URL = "https://github.com/srijansk/crewlore"
AUTHOR = {"name": "Srijan Saket", "url": "https://github.com/srijansk"}
# The README lead, as one listing line.
DESCRIPTION = (
    "The /lore skill and hooks for crewlore, which reads the sessions your coding agents "
    "already produce, and your repo's pull requests, and writes the decisions, procedures "
    "and gotchas into a plain-text knowledge book inside your repo, each entry quoting the "
    "line it came from and recording whether the team adopted it or tried it and declined. "
    "Runs the `lore` command: pipx install crewlore first."
)
KEYWORDS = ["team-knowledge", "tribal-knowledge", "coding-agents", "knowledge", "local-first"]
HOOKS_DESCRIPTION = (
    "crewlore: the claims whose scope covers a file as it is read or edited, the claims "
    f"relevant to each prompt, and a reset after compaction. Each hook runs `{HOOK_COMMAND}` "
    "and exits 0 whatever happens, so a machine without crewlore is never blocked."
)

MARKETPLACE_PATH = ".claude-plugin/marketplace.json"
MANIFEST_PATH = f"{PLUGIN_ROOT}/.claude-plugin/plugin.json"
SKILL_PATH = f"{PLUGIN_ROOT}/skills/{SKILL_NAME}/SKILL.md"
HOOKS_PATH = f"{PLUGIN_ROOT}/hooks/hooks.json"


def plugin_manifest() -> dict:
    """`.claude-plugin/plugin.json`: metadata only; every component sits in its default
    location, so no component key is needed."""
    return {
        "name": PLUGIN_NAME,
        "version": __version__,
        "description": DESCRIPTION,
        "author": AUTHOR,
        "homepage": REPOSITORY_URL,
        "repository": REPOSITORY_URL,
        "license": "MIT",
        "keywords": KEYWORDS,
    }


def marketplace_manifest() -> dict:
    """`.claude-plugin/marketplace.json` at the repository root: one entry, the plugin
    under `plugins/crewlore/`. The entry carries no `version`: the manifest's is the one
    that counts, and setting both is a validator warning."""
    return {
        "name": MARKETPLACE_NAME,
        "description": "crewlore's own marketplace: the crewlore plugin for Claude Code.",
        "owner": AUTHOR,
        "plugins": [
            {"name": PLUGIN_NAME, "source": f"./{PLUGIN_ROOT}", "description": DESCRIPTION}
        ],
    }


def hooks_manifest() -> dict:
    """`hooks/hooks.json`: the event map under a top-level `hooks` key, exactly the groups
    `install_hooks` adds to a settings file."""
    return {"description": HOOKS_DESCRIPTION, "hooks": hook_groups()}


def _json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def plugin_files() -> dict[str, str]:
    """Every file of the plugin, keyed by its path under the repository root. The skill is
    the installer's own output, ownership marker included."""
    return {
        MANIFEST_PATH: _json(plugin_manifest()),
        MARKETPLACE_PATH: _json(marketplace_manifest()),
        SKILL_PATH: _stamp(SKILL_MD),
        HOOKS_PATH: _json(hooks_manifest()),
    }


def stale_files(root: Path) -> list[str]:
    """The plugin files under `root` that are missing or differ from what this module
    renders, by path; empty when the checkout is current."""
    stale = []
    for rel, text in plugin_files().items():
        path = Path(root) / rel
        try:
            with open(path, encoding="utf-8", newline="") as handle:
                current = handle.read()
        except (OSError, UnicodeDecodeError):
            current = None
        if current != text:
            stale.append(rel)
    return stale


def write_plugin_files(root: Path) -> list[str]:
    """Write the plugin files under `root`, one line per file: `written` or
    `already current`, so the generator is safe to run on every release."""
    return [f"{_put(Path(root) / rel, text)} {rel}" for rel, text in plugin_files().items()]
