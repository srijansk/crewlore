"""Git hooks that keep the knowledge layer current without a daemon.

`lore hook install` adds a marked block to the repository's `post-commit` and
`post-merge` hooks. After a commit, `lore compile` runs in the background to pick up
sessions recorded since the last pass; after a merge or pull, `lore render` rebuilds
the book and the conflict list from the merged claims with no model call. The Python
interpreter is pinned at install time, so the hooks work from GUI git clients and CI
runners whose PATH does not carry the `lore` launcher. `LORE_SKIP_HOOK=1` skips either
hook, and uninstall removes only the marked block.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

START = "# crewlore-hook-start"
END = "# crewlore-hook-end"
SHEBANG = "#!/bin/sh\n"
HOOKS = {
    "post-commit": ("compile", "compiles new sessions and re-renders the book"),
    "post-merge": ("render", "re-renders the book from the merged claims, no model call"),
}


class NotAGitRepository(ValueError):
    pass


def hooks_dir(repo: Path) -> Path:
    """The directory git will read hooks from, honouring `core.hooksPath`."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise NotAGitRepository(f"{repo} is not inside a git repository") from exc
    path = Path(out)
    return path if path.is_absolute() else (Path(repo) / path).resolve()


def block(command: str, description: str, python: str | None = None) -> str:
    python = python or sys.executable
    return f"""{START}
# crewlore: {description}. Output: .lore/cache/hook.log. Set LORE_SKIP_HOOK=1 to skip.
if [ -z "$LORE_SKIP_HOOK" ]; then
  _lore_root=$(git rev-parse --show-toplevel 2>/dev/null)
  if [ -n "$_lore_root" ] && [ -d "$_lore_root/.lore" ]; then
    mkdir -p "$_lore_root/.lore/cache"
    ( cd "$_lore_root" && "{python}" -m lore.cli {command} --repo . >> .lore/cache/hook.log 2>&1 ) &
  fi
fi
{END}
"""


def install(repo: Path = Path("."), *, python: str | None = None) -> list[str]:
    """Write or refresh the marked block in each hook. Returns one line per hook."""
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, (command, description) in HOOKS.items():
        path = directory / name
        text = path.read_text(encoding="utf-8") if path.exists() else SHEBANG
        if not text.startswith("#!"):
            text = SHEBANG + text
        new = _upsert(text, block(command, description, python))
        changed = new != text or not path.exists()
        path.write_text(new, encoding="utf-8")
        _make_executable(path)
        lines.append(f"{name}: {'written' if changed else 'already current'} ({path})")
    return lines


def uninstall(repo: Path = Path(".")) -> list[str]:
    """Remove the marked block from each hook; delete a hook that held nothing else."""
    directory = hooks_dir(repo)
    lines = []
    for name in HOOKS:
        path = directory / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if START not in text:
            continue
        remaining = _remove(text)
        if remaining.strip() in ("", SHEBANG.strip()):
            path.unlink()
            lines.append(f"{name}: removed ({path})")
        else:
            path.write_text(remaining, encoding="utf-8")
            lines.append(f"{name}: crewlore block removed, rest kept ({path})")
    return lines or ["nothing to remove"]


def status(repo: Path = Path(".")) -> dict[str, str]:
    """Per hook: `installed`, `outdated` (block differs from what install would write now),
    or `missing`."""
    directory = hooks_dir(repo)
    report = {}
    for name, (command, description) in HOOKS.items():
        path = directory / name
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        current = _extract(text)
        if current is None:
            report[name] = "missing"
        elif current == block(command, description).strip():
            report[name] = "installed"
        else:
            report[name] = "outdated"
    return report


# --- text helpers -------------------------------------------------------------


def _extract(text: str) -> str | None:
    start, end = text.find(START), text.find(END)
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + len(END)].strip()


def _upsert(text: str, new_block: str) -> str:
    start, end = text.find(START), text.find(END)
    if start != -1 and end != -1 and end > start:
        return text[:start] + new_block + text[end + len(END) :].lstrip("\n")
    sep = "" if text.endswith("\n") else "\n"
    return text + sep + ("\n" if text.strip() and not text.endswith("\n\n") else "") + new_block


def _remove(text: str) -> str:
    start, end = text.find(START), text.find(END)
    before = text[:start].rstrip("\n")
    after = text[end + len(END) :].lstrip("\n")
    if before and after:
        return before + "\n\n" + after
    return (before + "\n") if before else after


def _make_executable(path: Path) -> None:
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
