"""Git hooks that keep the knowledge layer current without a daemon.

`lore hook install` adds a marked block to the repository's `post-commit` and
`post-merge` hooks. After a commit, `lore compile` runs in the background to pick up
sessions recorded since the last pass; after a merge or pull, `lore render` rebuilds
the book and the conflict list from the merged claims with no model call. The block
pins the Python interpreter at install time and falls back to `lore` on PATH, so the
hooks work from GUI git clients and CI runners whose PATH does not carry the `lore`
launcher. Setting `LORE_SKIP_HOOK` to any non-empty value skips either hook, and
uninstall removes only the marked block.

The block hands git's stdout and stderr back before the compile starts: the
background subshell is redirected to the log and `exec`s the interpreter, so no
process keeps git's pipe open while the model works. It records HEAD when it fires
and passes it as `--expect-head`, so a compile that outlives a `git checkout` writes
nothing. The block is placed before any `exit` or `exec` line that would otherwise end
the hook first, and it is only ever added to a POSIX shell hook.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

START = "# crewlore-hook-start"
END = "# crewlore-hook-end"
SHEBANG = "#!/bin/sh\n"
# Where the hooks append their output, relative to the repository root. The hook
# truncates it before a run once it is larger than HOOK_LOG_MAX_BYTES: the log is
# there to show what the last runs did, not to keep history.
HOOK_LOG = ".lore/cache/hook.log"
HOOK_LOG_MAX_BYTES = 1_048_576
# The block is POSIX sh. A hook run by anything else (python3, node, ...) cannot take
# it: appended shell would turn the hook into a syntax error.
SHELL_INTERPRETERS = frozenset({"sh", "bash", "dash", "ksh", "zsh"})
# How long `lore hook status` waits for the pinned interpreter to `import lore`.
IMPORT_PROBE_TIMEOUT_SECONDS = 30
HOOKS = {
    "post-commit": ("compile", "compiles new sessions and re-renders the book"),
    "post-merge": ("render", "re-renders the book from the merged claims, no model call"),
}


class NotAGitRepository(ValueError):
    pass


class HookRefused(ValueError):
    """The hook file cannot safely take, or lose, the crewlore block. The message says
    why and what to do by hand. Nothing has been written."""


def hooks_dir(repo: Path) -> Path:
    """The directory git will read hooks from, honouring `core.hooksPath`."""
    path = Path(_git(repo, "rev-parse", "--git-path", "hooks"))
    return path if path.is_absolute() else (Path(repo) / path).resolve()


def hook_log_path(repo: Path) -> Path:
    """Where the hooks write: `.lore/cache/hook.log` under the repository's top level,
    the same path the block computes at run time."""
    return Path(_git(repo, "rev-parse", "--show-toplevel")) / HOOK_LOG


def block(command: str, description: str, python: str | None = None) -> str:
    """The marked block for one hook, pinning `python` (default: this interpreter)."""
    py = shlex.quote(python or sys.executable)
    args = f'{command} --repo . --expect-head "$_lore_head"'
    return f"""{START}
# crewlore: {description}. Output: {HOOK_LOG}. Set LORE_SKIP_HOOK to any non-empty value to skip.
if [ -z "${{LORE_SKIP_HOOK:-}}" ]; then
  _lore_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
  if [ -n "$_lore_root" ] && [ -d "$_lore_root/.lore" ]; then
    _lore_log="$_lore_root/{HOOK_LOG}"
    _lore_head=$(git rev-parse HEAD 2>/dev/null || true)
    mkdir -p "$_lore_root/.lore/cache"
    if [ -f "$_lore_log" ] && [ $(wc -c <"$_lore_log") -gt {HOOK_LOG_MAX_BYTES} ]; then
      : >"$_lore_log"
    fi
    (
      cd "$_lore_root" || exit 1
      if [ -x {py} ]; then
        exec {py} -m lore.cli {args}
      elif command -v lore >/dev/null 2>&1; then
        exec lore {args}
      fi
      echo "crewlore: the pinned interpreter is gone and lore is not on PATH; {command} skipped" >&2
    ) >>"$_lore_log" 2>&1 </dev/null &
  fi
fi
{END}
"""


# --- install / uninstall / status ---------------------------------------------------


@dataclass
class _Plan:
    name: str
    path: Path
    text: str
    existed: bool
    changed: bool
    was_executable: bool
    placed_before: tuple[int, str] | None  # (line number, keyword) when moved before an exit


def install(repo: Path = Path("."), *, python: str | None = None) -> list[str]:
    """Write or refresh the marked block in each hook.

    Returns one line per hook, plus a note when the hooks directory is tracked by git.
    Raises `HookRefused` before writing anything when a hook cannot safely take the
    block: it is not a shell script, or its existing block is damaged or duplicated.
    """
    directory = hooks_dir(repo)
    plans = [
        _plan(directory / name, command, description, python)
        for name, (command, description) in HOOKS.items()
    ]
    directory.mkdir(parents=True, exist_ok=True)
    lines = []
    for plan in plans:
        if plan.changed:
            _write(plan.path, plan.text)
        _make_executable(plan.path)
        notes = []
        if plan.placed_before:
            line_no, keyword = plan.placed_before
            notes.append(f"placed before the hook's `{keyword}` on line {line_no}")
        if plan.existed and not plan.was_executable:
            notes.append("made executable; it was not")
        detail = f" ({'; '.join(notes)})" if notes else ""
        state = "written" if plan.changed else "already current"
        lines.append(f"{plan.name}: {state}{detail} ({plan.path})")
    if _tracked(repo, directory):
        lines.append(
            f"note: {directory} is tracked by git, so these hooks are shared: they pin this "
            f"machine's interpreter ({python or sys.executable}) and fall back to `lore` on "
            "PATH for everyone else."
        )
    return lines


def uninstall(repo: Path = Path(".")) -> list[str]:
    """Remove the marked block from each hook; delete a hook that held nothing else.
    Refuses, before writing anything, when a block is damaged or duplicated."""
    directory = hooks_dir(repo)
    plans = []
    for name in HOOKS:
        path = directory / name
        if not path.exists():
            continue
        text = _read(path)
        blocks = _blocks(text, str(path))
        if blocks:
            plans.append((name, path, _remove(text, blocks[0], _newline(text))))
    lines = []
    for name, path, remaining in plans:
        rest = remaining.strip()
        if not rest or (rest.startswith("#!") and "\n" not in rest):
            path.unlink()
            lines.append(f"{name}: removed ({path})")
        else:
            _write(path, remaining)
            lines.append(f"{name}: crewlore block removed, rest kept ({path})")
    return lines or ["nothing to remove"]


def status(repo: Path = Path(".")) -> dict[str, str]:
    """Per hook: `installed` (with the pinned interpreter when it is not this one),
    `outdated` (the block differs from what install would write for that interpreter),
    `broken (<reasons>)` (git would not run it, or it could not run `lore`), or
    `missing`."""
    directory = hooks_dir(repo)
    probes: dict[str, str | None] = {}
    report = {}
    for name, (command, description) in HOOKS.items():
        path = directory / name
        if not path.exists():
            report[name] = "missing"
            continue
        text = _read(path)
        try:
            blocks = _blocks(text, name)
        except HookRefused as exc:
            report[name] = f"broken ({exc})"
            continue
        if not blocks:
            report[name] = "missing"
            continue
        start, end = blocks[0]
        current = text[start:end].replace("\r\n", "\n")
        pinned = _pinned_interpreter(current)
        problems, notes = [], []
        if os.name != "nt" and not os.access(path, os.X_OK):
            problems.append("not executable, so git skips it; run `lore hook install`")
        if _first_terminator(text[:start]) is not None:
            problems.append("the hook exits before the crewlore block; run `lore hook install`")
        if pinned is not None:
            if not Path(pinned).exists():
                if _lore_on_path():
                    notes.append(
                        f"pinned interpreter {pinned} is missing; the hook falls back to "
                        "`lore` on PATH"
                    )
                else:
                    problems.append(
                        f"pinned interpreter {pinned} is missing and `lore` is not on PATH"
                    )
            else:
                if pinned not in probes:
                    probes[pinned] = _import_problem(pinned)
                if probes[pinned]:
                    problems.append(probes[pinned])
        if problems:
            report[name] = f"broken ({'; '.join(problems)})"
        elif pinned is None or current != block(command, description, pinned).strip():
            report[name] = "outdated (run `lore hook install` to refresh)"
        elif pinned != sys.executable or notes:
            detail = ([f"pinned to {pinned}"] if pinned != sys.executable else []) + notes
            report[name] = f"installed ({'; '.join(detail)})"
        else:
            report[name] = "installed"
    return report


def last_log_line(repo: Path = Path(".")) -> str | None:
    """The last non-empty line of the hook log: what the most recent hook run said."""
    path = hook_log_path(repo)
    if not path.exists():
        return None
    lines = [ln for ln in path.read_text(errors="replace").splitlines() if ln.strip()]
    return lines[-1] if lines else None


# --- planning an install ---------------------------------------------------------------


def _plan(path: Path, command: str, description: str, python: str | None) -> _Plan:
    existed = path.exists()
    text = _read(path) if existed else SHEBANG
    nl = _newline(text)
    if not text.startswith("#!"):
        text = SHEBANG.rstrip("\n") + nl + text
    interpreter = _shebang_interpreter(text)
    if interpreter not in SHELL_INTERPRETERS:
        raise HookRefused(
            f"{path} is a {interpreter} script; crewlore can only add its block to a POSIX "
            f"shell hook ({', '.join(sorted(SHELL_INTERPRETERS))}). Run `lore {command}` "
            "from it yourself."
        )
    blocks = _blocks(text, str(path))
    new_block = block(command, description, python).replace("\n", nl)
    new, placed = _upsert(text, new_block, blocks[0] if blocks else None, nl)
    return _Plan(
        name=path.name,
        path=path,
        text=new,
        existed=existed,
        changed=not existed or new != text,
        was_executable=existed and os.access(path, os.X_OK),
        placed_before=placed,
    )


def _upsert(
    text: str, new_block: str, existing: tuple[int, int] | None, nl: str
) -> tuple[str, tuple[int, str] | None]:
    if existing is not None:
        start, end = existing
        if _first_terminator(text[:start]) is None:
            # Refresh in place: nothing before the block ends the hook early.
            return text[:start] + new_block.rstrip("\r\n") + text[end:], None
        text = _remove(text, existing, nl)  # dead where it is: move it before the exit
    terminator = _first_terminator(text)
    if terminator is None:
        sep = "" if text.endswith("\n") else nl
        blank = nl if text.strip() and not text.endswith(nl * 2) else ""
        return text + sep + blank + new_block, None
    line_no, keyword, offset = terminator
    before, after = text[:offset], text[offset:]
    blank = nl if before.strip() and not before.endswith(nl * 2) else ""
    return before + blank + new_block + nl + after, (line_no, keyword)


def _remove(text: str, span: tuple[int, int], nl: str) -> str:
    start, end = span
    before = text[:start].rstrip("\r\n")
    after = text[end:].lstrip("\r\n")
    if before and after:
        return before + nl + nl + after
    return (before + nl) if before else after


def _blocks(text: str, where: str) -> list[tuple[int, int]]:
    """Spans of the crewlore blocks in `text`. Refuses an unpaired marker or more than
    one block: editing either in place would corrupt the hook."""
    marks = sorted(
        [(m.start(), START) for m in re.finditer(re.escape(START), text)]
        + [(m.start(), END) for m in re.finditer(re.escape(END), text)]
    )
    damaged = HookRefused(
        f"crewlore block in {where} is damaged; fix by hand "
        f"(expected one `{START}` line followed by one `{END}` line)"
    )
    blocks: list[tuple[int, int]] = []
    open_at = None
    for pos, kind in marks:
        if kind == START and open_at is None:
            open_at = pos
        elif kind == END and open_at is not None:
            blocks.append((open_at, pos + len(END)))
            open_at = None
        else:
            raise damaged
    if open_at is not None:
        raise damaged
    if len(blocks) > 1:
        raise HookRefused(
            f"{where} holds {len(blocks)} crewlore blocks; fix by hand so that one remains"
        )
    return blocks


def _shebang_interpreter(text: str) -> str | None:
    """The program named by the shebang (`bash` for `#!/usr/bin/env bash -e`), or None."""
    first = text.split("\n", 1)[0].rstrip("\r")
    if not first.startswith("#!"):
        return None
    parts = first[2:].split()
    if not parts:
        return None
    exe = _basename(parts[0])
    if exe == "env":
        rest = [p for p in parts[1:] if not p.startswith("-") and "=" not in p]
        exe = _basename(rest[0]) if rest else "env"
    return exe


def _basename(program: str) -> str:
    name = re.split(r"[\\/]", program)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


# A line whose first word is `exit` or `exec` ends the hook there (an `exec` that only
# redirects, like `exec >log 2>&1`, does not). Everything appended after it is dead.
_TERMINATOR = re.compile(r"^[ \t]*(exit|exec)\b(.*)$")
_REDIRECT_ONLY = re.compile(r"^\s*(\d*[<>]|$)")
# Column-0 lines that close a compound statement: an indented exit right after one is
# at the top level, not inside the statement that line closes.
_CLOSERS = ("fi", "done", "esac", "}", ")", ";;")


def _first_terminator(text: str) -> tuple[int, str, int] | None:
    """The first `exit`/`exec` line: (1-based line number, keyword, char offset of the
    line the block must go before so that it still runs). An indented terminator sits
    inside a compound statement, so the block goes before that statement; comment lines
    attached above it move with it."""
    lines = text.split("\n")
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    continued = False
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r")
        match = _TERMINATOR.match(line)
        if match and not continued and not _is_redirect_only(match):
            anchor = i if line[0] not in " \t" else _enclosing_statement(lines, i)
            while anchor > 1 and _is_comment(lines[anchor - 1]):
                anchor -= 1
            return i + 1, match.group(1), offsets[anchor]
        continued = line.endswith("\\") and not line.endswith("\\\\")
    return None


def _is_redirect_only(match: re.Match) -> bool:
    return match.group(1) == "exec" and bool(_REDIRECT_ONLY.match(match.group(2)))


def _is_comment(raw: str) -> bool:
    line = raw.rstrip("\r")
    return line.startswith("#") and not line.startswith("#!")


def _enclosing_statement(lines: list[str], index: int) -> int:
    """Index of the column-0 line that opens the statement an indented line sits in,
    or `index` itself when that line is the shebang or closes an earlier statement."""
    for j in range(index - 1, -1, -1):
        line = lines[j].rstrip("\r")
        if not line.strip() or _is_comment(line) or line[0] in " \t":
            continue
        if line.startswith("#!") or line.split()[0] in _CLOSERS:
            return index
        return j
    return index


_PINNED = re.compile(r"^\s*if \[ -x (?P<py>.+?) \]; then\s*$", re.M)


def _pinned_interpreter(block_text: str) -> str | None:
    match = _PINNED.search(block_text)
    if not match:
        return None
    try:
        return shlex.split(match.group("py"))[0]
    except (ValueError, IndexError):
        return None


def _import_problem(python: str) -> str | None:
    """Why `python -c 'import lore'` fails, or None when it works."""
    try:
        proc = subprocess.run(
            [python, "-c", "import lore"],
            capture_output=True,
            text=True,
            timeout=IMPORT_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{python} could not be run ({exc.__class__.__name__})"
    if proc.returncode != 0:
        return f"{python} cannot import lore (is crewlore installed for it?)"
    return None


def _lore_on_path() -> str | None:
    return shutil.which("lore")


# --- git and file helpers -------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise NotAGitRepository(f"{repo} is not inside a git repository") from exc


def _tracked(repo: Path, directory: Path) -> bool:
    """Whether git tracks files under the hooks directory (a committed `core.hooksPath`)."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", str(directory)],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="surrogateescape")


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8", errors="surrogateescape"))


def _newline(text: str) -> str:
    """The line ending the file uses, judged by its first line."""
    return "\r\n" if text.split("\n", 1)[0].endswith("\r") else "\n"


def _make_executable(path: Path) -> None:
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
