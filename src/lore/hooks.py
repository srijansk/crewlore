"""Git hooks that keep the knowledge layer current without a daemon.

`lore hook install` adds a marked block to the repository's `post-commit`, `post-merge`
and `post-rewrite` hooks. After a commit, `lore compile` runs in the background to pick
up sessions recorded since the last pass; after a merge, `lore render` rebuilds the book
and the conflict list from the merged claims with no model call; after a rebase (which
is also what `git pull --rebase` does) `lore compile` runs once, when HEAD has settled,
while the post-commit hook, which a rebase fires once per replayed commit, steps aside.
The block pins the Python interpreter at install time and falls back to `lore` on PATH,
so the hooks work from GUI git clients and CI runners whose PATH does not carry the
`lore` launcher. Setting `LORE_SKIP_HOOK` to any non-empty value skips a hook, and
uninstall removes the marked block and nothing else.

The block hands git's stdout and stderr back before the compile starts: the background
subshell is redirected to the log and `exec`s the interpreter, so no process keeps
git's pipe open while the model works. It runs the interpreter with the current
directory off `sys.path` (`HOOK_ENTRY`), so no `lore/` package in the repository, at
the top level or planted under `.lore/cache/`, can stand in for the installed one. It
records HEAD when it fires and passes it as `--expect-head`, so a compile that outlives
a `git checkout` writes nothing tracked. With `LORE_HOOK_PROBE`
set to a path, the block touches that path and exits instead of compiling: that is how
`lore hook status --probe` checks that a hook reaches its block at all.

Placing the block: a hook that `exit`s, or `exec`s another program, never reaches
anything appended after that command. `_scan` reads the hook the way the shell does,
as far as this needs: it splits lines into commands at `;`, `&&`, `||`, `|` and `&`
outside quotes and substitutions, skips comments, heredoc bodies and line
continuations, strips `then`/`else`/`do`, case-pattern and assignment prefixes, and
tracks how deeply nested in `if`/`for`/`while`/`until`/`case`/`{` a command is, so the
block goes before the first terminating command, or before the outermost statement
that holds it. A hook whose end the scanner cannot make sense of is refused rather
than given a dead block. Only POSIX shell hooks with LF line endings are edited.
"""

from __future__ import annotations

import errno
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
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
# How long `lore hook status` waits for the pinned interpreter to `import lore.cli`.
IMPORT_PROBE_TIMEOUT_SECONDS = 30
# How long `lore hook status --probe` lets a hook run before calling it stuck. The
# hook's own commands run too, so this covers a test suite or a push, not just the block.
HOOK_PROBE_TIMEOUT_SECONDS = 120
# Set to a path, the block touches that path and exits 0 instead of compiling.
PROBE_VARIABLE = "LORE_HOOK_PROBE"
# Python that drops the current directory from `sys.path` before importing anything: the
# empty entry a `-c` run puts first. `-m lore.cli` would put the directory itself there,
# so a `lore/` package planted under `.lore/cache/`, which only a file the repository
# controls keeps out of review, would run on every teammate's commit and pull. The
# filter works on every supported Python; `-P` does the same only from 3.11, and `-I`
# would also drop PYTHONPATH and the user site-packages a `pip install --user` uses.
_STRIP_CWD = "import sys; sys.path = [p for p in sys.path if p]"
# What the block hands the pinned interpreter with `-c`, single-quoted in the shell, so
# no single quote may appear in it. argv[0] is set so usage text says `lore`, not `-c`.
HOOK_ENTRY = f'{_STRIP_CWD}; sys.argv[0] = "lore"; from lore.cli import app; app()'


@dataclass(frozen=True)
class HookSpec:
    command: str
    description: str
    # Shell tests (`[ ... ]`, joined with `&&`) the hook must pass to run; empty when
    # it always runs.
    when: tuple[str, ...] = ()


# A rebase fires post-commit once per replayed commit while `rebase-merge/` (or
# `rebase-apply/rebasing`, for the apply backend) exists, and HEAD only settles when
# it finishes: post-commit steps aside then, and post-rewrite compiles once at the end.
_NOT_REBASING = (
    '[ ! -d "$(git rev-parse --git-path rebase-merge 2>/dev/null)" ]',
    '[ ! -f "$(git rev-parse --git-path rebase-apply/rebasing 2>/dev/null)" ]',
)
HOOKS = {
    "post-commit": HookSpec(
        "compile", "compiles new sessions and re-renders the book", when=_NOT_REBASING
    ),
    "post-merge": HookSpec("render", "re-renders the book from the merged claims, no model call"),
    # post-rewrite's first argument is `rebase` or `amend`; an amend already fired
    # post-commit with HEAD settled, so only a rebase compiles here.
    "post-rewrite": HookSpec(
        "compile",
        "compiles new sessions once a rebase has finished",
        when=('[ "${1:-}" = rebase ]',),
    ),
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


def block(
    command: str, description: str, python: str | None = None, *, when: tuple[str, ...] = ()
) -> str:
    """The marked block for one hook, pinning `python` (default: this interpreter).
    `when` adds shell tests the hook must pass to run (see `HOOKS`)."""
    py = shlex.quote(python or sys.executable)
    args = f'{command} --repo "$_lore_root" --expect-head "$_lore_head"'
    guard = "".join(f" \\\n  && {test}" for test in when)
    return f"""{START}
# crewlore: {description}. Output: {HOOK_LOG}. Set LORE_SKIP_HOOK to any non-empty value to skip.
if [ -n "${{{PROBE_VARIABLE}:-}}" ]; then
  : >"${PROBE_VARIABLE}"  # `lore hook status --probe`: the hook reaches this block
  exit 0
fi
if [ -z "${{LORE_SKIP_HOOK:-}}" ]{guard}; then
  _lore_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
  if [ -n "$_lore_root" ] && [ -d "$_lore_root/.lore" ]; then
    _lore_log="$_lore_root/{HOOK_LOG}"
    _lore_head=$(git rev-parse --verify -q HEAD 2>/dev/null || true)
    mkdir -p "$_lore_root/.lore/cache"
    if [ -f "$_lore_log" ] && [ $(wc -c <"$_lore_log") -gt {HOOK_LOG_MAX_BYTES} ]; then
      : >"$_lore_log"
    fi
    (
      cd "$_lore_root/.lore/cache" || exit 1
      if [ -x {py} ]; then
        exec {py} -c '{HOOK_ENTRY}' {args}
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
    added_newline: bool  # the hook's last line had no newline; one was added before the block
    target: Path | None  # the file a symlinked hook points at: where the block really goes


def install(repo: Path = Path("."), *, python: str | None = None) -> list[str]:
    """Write or refresh the marked block in each hook.

    Returns one line per hook, plus a note when the hooks directory, or the file a
    symlinked hook points at, is tracked by git: such hooks are shared, and the block
    pins this machine's interpreter. A symlinked hook is edited through the link, and
    its line says which file the block went into.
    Raises `HookRefused` before writing anything when a hook cannot safely take the
    block: it is not a shell script, has CRLF line endings, ends inside a construct the
    block could not be placed after, its existing block is damaged or duplicated, or
    it is a symlink to a file that does not exist.
    """
    directory = hooks_dir(repo)
    plans = [_plan(directory / name, spec, python) for name, spec in HOOKS.items()]
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
        if plan.added_newline:
            notes.append("ended the hook's last line with a newline, which it lacked")
        if plan.existed and not plan.was_executable:
            notes.append("made executable; it was not")
        if plan.target is not None:
            notes.append(f"a symlink; the block went into {plan.target}")
        detail = f" ({'; '.join(notes)})" if notes else ""
        state = "written" if plan.changed else "already current"
        lines.append(f"{plan.name}: {state}{detail} ({plan.path})")
    shared = [f"{directory} is tracked by git"] if _tracked(repo, directory) else []
    shared += [
        f"{plan.name} is a symlink to {plan.target}, which is tracked by git"
        for plan in plans
        if plan.target is not None and _tracked(repo, plan.target)
    ]
    if shared:
        lines.append(
            f"note: {'; '.join(shared)}, so these hooks are shared: they pin this machine's "
            f"interpreter ({python or sys.executable}) and fall back to `lore` on PATH for "
            "everyone else."
        )
    return lines


def uninstall(repo: Path = Path(".")) -> list[str]:
    """Remove the marked block, byte for byte, from each hook; delete a hook that held
    nothing else. A symlinked hook is written back through the link, never deleted:
    the file it points at is not ours. Refuses, before writing anything, when a block
    is damaged or duplicated."""
    directory = hooks_dir(repo)
    plans = []
    for name in HOOKS:
        path = directory / name
        if not path.exists():
            continue
        text = _read(path)
        blocks = _blocks(text, str(path))
        if blocks:
            plans.append((name, path, _remove(text, blocks[0])))
    lines = []
    for name, path, remaining in plans:
        rest = remaining.strip()
        if not path.is_symlink() and (not rest or (rest.startswith("#!") and "\n" not in rest)):
            path.unlink()
            lines.append(f"{name}: removed ({path})")
        else:
            _write(path, remaining)
            where = f"{path.resolve()}, which {path} links to" if path.is_symlink() else path
            lines.append(f"{name}: crewlore block removed, rest kept ({where})")
    return lines or ["nothing to remove"]


def status(repo: Path = Path("."), *, probe: bool = False) -> dict[str, str]:
    """Per hook: `installed` (with the pinned interpreter when it is not this one),
    `outdated` (the block differs from what install would write for that interpreter),
    `broken (<reasons>)` (git would not run it, it would not reach the block, or it
    could not run `lore`), or `missing`.

    With `probe`, each hook that could run is run with `LORE_HOOK_PROBE` set, which
    makes the block touch a file and exit before compiling, so a block the hook never
    reaches is reported whatever stands before it. That runs the hook's other commands
    too, so it is opt-in."""
    directory = hooks_dir(repo)
    probes: dict[str, str | None] = {}
    report = {}
    for name, spec in HOOKS.items():
        path = directory / name
        if not path.exists():
            report[name] = "missing"
            continue
        text = _read(path)
        if "\r\n" in text:
            report[name] = "broken (CRLF line endings; git cannot exec it)"
            continue
        try:
            blocks = _blocks(text, name)
        except HookRefused as exc:
            report[name] = f"broken ({exc})"
            continue
        if not blocks:
            report[name] = "missing"
            continue
        start, end = blocks[0]
        current = text[start:end]
        pinned = _pinned_interpreter(current)
        problems, notes = [], []
        runnable = True
        if os.name != "nt" and not os.access(path, os.X_OK):
            problems.append("not executable, so git skips it; run `lore hook install`")
            runnable = False
        if syntax := _syntax_problem(path, text):
            problems.append(syntax)
            runnable = False
        prefix = _scan(text[:start])
        if _terminator(prefix) is not None:
            problems.append("the hook exits before the crewlore block; run `lore hook install`")
        elif prefix.unfinished in _NEVER_RUN:
            problems.append(
                f"the crewlore block sits inside {prefix.unfinished} and is never run; "
                "run `lore hook install`"
            )
        elif prefix.commands:
            if not probe:
                notes.append(
                    "not probed: `lore hook status --probe` runs the hook to confirm it "
                    "reaches the block"
                )
            elif runnable and (unreached := _probe_problem(path, repo)):
                problems.append(unreached)
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
        elif pinned is None or current != block(
            spec.command, spec.description, pinned, when=spec.when
        ).strip():
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


def _plan(path: Path, spec: HookSpec, python: str | None) -> _Plan:
    existed = path.exists()  # follows a symlink: False for a dangling one
    target = path.resolve() if path.is_symlink() else None
    if target is not None and not existed:
        raise HookRefused(
            f"{path} is a symlink to {target}, which does not exist, so crewlore would be "
            "writing a hook there through the link. Remove the link or create the file it "
            "points at, then run `lore hook install` again."
        )
    text = _read(path) if existed else SHEBANG
    if "\r\n" in text:
        raise HookRefused(
            f"{path} has CRLF line endings: git cannot run it (`/bin/sh\\r` is not an "
            "interpreter) and the crewlore block would be a shell syntax error in it. "
            "Convert the file to LF line endings, then run `lore hook install` again."
        )
    interpreter = _shebang_interpreter(text)
    if interpreter is not None and interpreter not in SHELL_INTERPRETERS:
        raise HookRefused(
            f"{path} is a {interpreter} script; crewlore can only add its block to a POSIX "
            f"shell hook ({', '.join(sorted(SHELL_INTERPRETERS))}). Run `lore {spec.command}` "
            "from it yourself."
        )
    blocks = _blocks(text, str(path))
    new_block = block(spec.command, spec.description, python, when=spec.when)
    new, placed, added_newline = _upsert(
        text, new_block, blocks[0] if blocks else None, where=str(path), command=spec.command
    )
    return _Plan(
        name=path.name,
        path=path,
        text=new,
        existed=existed,
        changed=not existed or new != text,
        was_executable=existed and os.access(path, os.X_OK),
        placed_before=placed,
        added_newline=added_newline,
        target=target,
    )


def _upsert(
    text: str, new_block: str, existing: tuple[int, int] | None, *, where: str, command: str
) -> tuple[str, tuple[int, str] | None, bool]:
    """`text` with `new_block` in place: refreshed where it is when the hook reaches it
    there, otherwise before the first command that ends the hook, otherwise appended.
    The block is the only thing added (plus a newline when the hook's last line lacked
    one), so uninstall can take exactly it out again."""
    if existing is not None:
        start, end = existing
        prefix = _scan(text[:start])
        if _terminator(prefix) is None and prefix.unfinished is None:
            return text[:start] + new_block.rstrip("\n") + text[end:], None, False
        text = _remove(text, existing)  # dead where it is: move it to where it runs
    scan = _scan(text)
    terminator = _terminator(scan)
    if terminator is None:
        if scan.unfinished is not None:
            raise HookRefused(
                f"{where} ends inside {scan.unfinished} that never closes, so crewlore "
                "cannot place its block where the hook would run it; add `lore "
                f"{command}` to the hook by hand."
            )
        if text and not text.endswith("\n"):
            return text + "\n" + new_block, None, True
        return text + new_block, None, False
    line_no, keyword, anchor = terminator
    lines = text.split("\n")
    # Comment lines attached above the statement move with it.
    while anchor > 0 and _is_comment(lines[anchor - 1]) and anchor - 1 not in scan.heredoc_lines:
        anchor -= 1
    offset = sum(len(line) + 1 for line in lines[:anchor])
    return text[:offset] + new_block + text[offset:], (line_no, keyword), False


def _remove(text: str, span: tuple[int, int]) -> str:
    """`text` without the block: its lines from `START` through `END` and the newline
    that ends the `END` line, nothing else."""
    start, end = span
    if text[end : end + 1] == "\n":
        end += 1
    return text[:start] + text[end:]


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
    """The program named by the shebang (`bash` for `#!/usr/bin/env bash -e`), or None.
    A hook without one is run by git through `sh`."""
    first = text.split("\n", 1)[0]
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


# --- reading the hook as the shell would ---------------------------------------------


@dataclass
class _Command:
    """One command the shell would run: the 0-based line it starts on, the line its
    logical line starts on (earlier when a `\\` continuation leads up to it; nothing
    can be inserted between the two), and its words. A quoted string, a `$( )`
    substitution or a `( )` group is one word, whatever it holds, so an `exit` inside
    one is never mistaken for the hook's."""

    line: int
    logical_line: int
    words: list[str]


@dataclass
class _Scan:
    commands: list[_Command]
    heredoc_lines: set[int]  # 0-based lines that are heredoc body or terminator lines
    unfinished: str | None  # what is still open where the text ends, or None


_OPEN_NAMES = {
    "sq": "a quoted string",
    "dq": "a quoted string",
    "bq": "a backquoted command",
    "sub": "a `$(` substitution",
    "paren": "a `(` group",
}
# A block standing inside one of these is text, not code the hook runs.
_NEVER_RUN = frozenset({"a heredoc", "a quoted string", "a backquoted command"})
_HEREDOC_WORD_END = frozenset(" \t\n;|&<>()")


class _Scanner:
    def __init__(self, text: str):
        self.text = text
        self.commands: list[_Command] = []
        self.heredoc_lines: set[int] = set()
        self.unfinished: str | None = None
        self.stack: list[str] = []
        self.pending: list[tuple[str, bool]] = []  # heredoc (delimiter, strip leading tabs)
        self.words: list[str] = []
        self.word: list[str] = []
        self.in_word = False
        self.line = 0
        self.logical_start = 0  # first physical line of the logical line being read
        self.command_line = 0
        self.command_logical_line = 0

    def run(self) -> _Scan:
        text, n, i = self.text, len(self.text), 0
        while i < n:
            ch = text[i]
            state = self.stack[-1] if self.stack else None
            if state == "sq":
                if ch == "'":
                    self.stack.pop()
                i = self._take(ch, i)
            elif state in ("dq", "bq"):
                if ch == "\\" and i + 1 < n:
                    i = self._take(text[i : i + 2], i)
                elif ch == ('"' if state == "dq" else "`"):
                    self.stack.pop()
                    i = self._take(ch, i)
                elif state == "dq" and text.startswith("$(", i):
                    self.stack.append("sub")
                    i = self._take("$(", i)
                elif state == "dq" and ch == "`":
                    self.stack.append("bq")
                    i = self._take(ch, i)
                else:
                    i = self._take(ch, i)
            elif ch == "\\":
                if i + 1 < n and text[i + 1] == "\n":  # line continuation
                    self.line += 1
                    i += 2
                else:
                    i = self._take(text[i : i + 2], i)
            elif ch == "'":
                self.stack.append("sq")
                i = self._take(ch, i)
            elif ch == '"':
                self.stack.append("dq")
                i = self._take(ch, i)
            elif ch == "`":
                self.stack.append("bq")
                i = self._take(ch, i)
            elif text.startswith("$(", i):
                self.stack.append("sub")
                i = self._take("$(", i)
            elif ch == "(":
                self.stack.append("paren")
                i = self._take(ch, i)
            elif ch == ")":
                if state in ("sub", "paren"):
                    self.stack.pop()
                i = self._take(ch, i)  # a stray `)` ends a case pattern
            elif ch == "#" and (i == 0 or text[i - 1] in " \t\n(;"):
                while i < n and text[i] != "\n":
                    i += 1
            elif state is not None:  # inside `$( )` or `( )`: one word, no splitting
                i = self._take(ch, i)
            elif ch == "\n":
                self._end_command()
                self.line += 1
                i = self._skip_heredoc_bodies(i + 1)
                self.logical_start = self.line
            elif ch in " \t":
                self._end_word()
                i += 1
            elif text.startswith("<<", i) and not text.startswith("<<<", i):
                i = self._heredoc_operator(i)
            elif ch in ";|":
                self._end_command()
                i += 1
            elif ch == "&":
                before = text[i - 1] if i else ""
                after = text[i + 1] if i + 1 < n else ""
                if before in "<>" or after == ">":  # `2>&1`, `&>file`: a redirection
                    i = self._take(ch, i)
                else:
                    self._end_command()
                    i += 1
            else:
                i = self._take(ch, i)
        self._end_command()
        if self.stack:
            self.unfinished = _OPEN_NAMES[self.stack[-1]]
        elif self.pending:
            self.unfinished = "a heredoc"
        return _Scan(self.commands, self.heredoc_lines, self.unfinished)

    def _take(self, chars: str, i: int) -> int:
        if not self.in_word and not self.words:
            self.command_line = self.line
            self.command_logical_line = self.logical_start
        self.in_word = True
        self.word.append(chars)
        self.line += chars.count("\n")
        return i + len(chars)

    def _end_word(self) -> None:
        if self.in_word:
            self.words.append("".join(self.word))
            self.word, self.in_word = [], False

    def _end_command(self) -> None:
        self._end_word()
        if self.words:
            self.commands.append(
                _Command(self.command_line, self.command_logical_line, self.words)
            )
            self.words = []

    def _heredoc_operator(self, i: int) -> int:
        """Record the heredoc `<<WORD` / `<<-WORD` at `i` opens; its body starts on the
        next line and ends at the line holding WORD alone."""
        text, n = self.text, len(self.text)
        j = i + 2
        strip_tabs = j < n and text[j] == "-"
        if strip_tabs:
            j += 1
        while j < n and text[j] in " \t":
            j += 1
        if j < n and text[j] in "'\"":
            close = text.find(text[j], j + 1)
            if close == -1:
                self.stack.append("sq" if text[j] == "'" else "dq")
                return n
            delimiter, j = text[j + 1 : close], close + 1
        else:
            if j < n and text[j] == "\\":
                j += 1
            start = j
            while j < n and text[j] not in _HEREDOC_WORD_END:
                j += 1
            delimiter = text[start:j]
        self._end_word()
        self.words.append(text[i:j])
        if delimiter:
            self.pending.append((delimiter, strip_tabs))
        return j

    def _skip_heredoc_bodies(self, i: int) -> int:
        """Consume the body lines of every heredoc opened on the line that just ended."""
        text, n = self.text, len(self.text)
        while self.pending:
            delimiter, strip_tabs = self.pending.pop(0)
            while True:
                if i >= n:
                    self.unfinished = "a heredoc"
                    return n
                end = text.find("\n", i)
                line = text[i:] if end == -1 else text[i:end]
                self.heredoc_lines.add(self.line)
                self.line += 1
                i = n if end == -1 else end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
        return i


def _scan(text: str) -> _Scan:
    return _Scanner(text).run()


_OPENERS = frozenset({"if", "for", "while", "until", "case"})
_CLOSERS = frozenset({"fi", "done", "esac", "}"})
# Words that stand before a command without being one.
_PREFIXES = frozenset({"then", "else", "do", "!"})
_CASE_PATTERN = re.compile(r"^(\(.*\)|[^()\s]+\))$")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# A redirection word, with its target attached (`2>&1`, `>>log`) or not (`>` alone).
_REDIRECTION = re.compile(r"^(\d*[<>]{1,2}[&|]?|&>>?)(.*)$")


def _terminator(scan: _Scan) -> tuple[int, str, int] | None:
    """The first command that ends the hook: (its 1-based line, `exit` or `exec`, the
    0-based line of the top-level statement the block must go before so that it still
    runs). An `exec` that only redirects (`exec >log 2>&1`) does not end the hook."""
    depth, opener = 0, 0
    for cmd in scan.commands:
        words = list(cmd.words)
        while words and (
            words[0] in _PREFIXES
            or words[0] == "{"
            or _CASE_PATTERN.match(words[0])
            or _ASSIGNMENT.match(words[0])
        ):
            if words.pop(0) == "{":
                if depth == 0:
                    opener = cmd.logical_line
                depth += 1
        if not words:
            continue
        head = words[0]
        if head in _OPENERS:
            if depth == 0:
                opener = cmd.logical_line
            depth += 1
        elif head in _CLOSERS:
            depth = max(depth - 1, 0)
        elif head == "exit" or (head == "exec" and not _redirect_only(words[1:])):
            return cmd.line + 1, head, opener if depth else cmd.logical_line
        elif words[-1] == "{":  # `f() {`, `function f {`
            if depth == 0:
                opener = cmd.logical_line
            depth += 1
    return None


def _redirect_only(words: list[str]) -> bool:
    expect_target = False
    for word in words:
        if expect_target:
            expect_target = False
            continue
        match = _REDIRECTION.match(word)
        if not match:
            return False
        expect_target = not match.group(2)
    return True


def _is_comment(line: str) -> bool:
    return line.startswith("#") and not line.startswith("#!")


# --- what status checks ------------------------------------------------------------------


_PINNED = re.compile(r"^\s*if \[ -x (?P<py>.+?) \]; then\s*$", re.M)
# The probe drops the current directory from sys.path, as the hook's entry does, and runs
# from an empty one, so a `lore/` package in the directory `status` runs from cannot
# stand in for crewlore.
_IMPORT_PROBE = f"{_STRIP_CWD}; import lore.cli"


def _pinned_interpreter(block_text: str) -> str | None:
    match = _PINNED.search(block_text)
    if not match:
        return None
    try:
        return shlex.split(match.group("py"))[0]
    except (ValueError, IndexError):
        return None


def _import_problem(python: str) -> str | None:
    """Why `python -c 'import lore.cli'` fails, or None when it works."""
    with tempfile.TemporaryDirectory() as empty:
        try:
            proc = subprocess.run(
                [python, "-c", _IMPORT_PROBE],
                cwd=empty,
                capture_output=True,
                text=True,
                timeout=IMPORT_PROBE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"{python} could not be run ({exc.__class__.__name__})"
    if proc.returncode != 0:
        return f"{python} cannot import lore.cli (is crewlore installed for it?)"
    return None


def _syntax_problem(path: Path, text: str) -> str | None:
    """What the hook's shell says when asked to parse (`-n`) it, or None."""
    shell = _shebang_interpreter(text) or "sh"
    if shell not in SHELL_INTERPRETERS or shutil.which(shell) is None:
        return None
    proc = subprocess.run([shell, "-n", str(path)], capture_output=True, text=True)
    if proc.returncode == 0:
        return None
    first = next((ln for ln in proc.stderr.splitlines() if ln.strip()), "syntax error")
    return f"not valid {shell}: {first.strip()}"


def _probe_problem(path: Path, repo: Path) -> str | None:
    """Run the hook with `PROBE_VARIABLE` set, from the repository's top level as git
    would, and say so when the block was never reached."""
    env = {k: v for k, v in os.environ.items() if k != "LORE_SKIP_HOOK"}
    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "reached"
        env[PROBE_VARIABLE] = str(marker)
        try:
            proc = _run_hook(
                path,
                cwd=_git(repo, "rev-parse", "--show-toplevel"),
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=HOOK_PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return (
                f"did not finish within {HOOK_PROBE_TIMEOUT_SECONDS}s when run with "
                f"{PROBE_VARIABLE} set"
            )
        except OSError as exc:
            return f"could not be run ({exc.strerror or exc})"
        reached = marker.exists()
    if reached:
        return None
    if proc.returncode:
        return f"block is never reached (the hook exited {proc.returncode} before it)"
    return "block is never reached"


def _run_hook(path: Path, **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([str(path)], **kwargs)
    except OSError as exc:
        if exc.errno != errno.ENOEXEC:
            raise
        return subprocess.run(["sh", str(path)], **kwargs)  # no shebang: git uses sh too


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


def _tracked(repo: Path, path: Path) -> bool:
    """Whether git tracks `path`: a file, or any file under a directory (the hooks
    directory of a committed `core.hooksPath`). A path outside the repository is not."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", str(path)],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="surrogateescape")


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8", errors="surrogateescape"))


def _make_executable(path: Path) -> None:
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
