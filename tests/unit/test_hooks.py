"""`lore hook install` keeps the layer current through git's own post-commit and
post-merge hooks: a marked, removable block, an executable file, the interpreter
pinned with `lore` on PATH as the fallback, other hook content left alone, and the
block placed where the hook actually reaches it."""

import os
import re
import shlex
import shutil
import subprocess
import sys
import time

import pytest

import lore.hooks as hooks_module
from lore.hooks import (
    END,
    HOOK_LOG_MAX_BYTES,
    START,
    HookRefused,
    NotAGitRepository,
    block,
    hooks_dir,
    install,
    last_log_line,
    status,
    uninstall,
)

# The fake interpreter sleeps this long to stand in for a model call; git must return
# well before it finishes, so the budget is half the sleep.
FAKE_COMPILE_SECONDS = 3
HOOK_RETURN_BUDGET_SECONDS = FAKE_COMPILE_SECONDS / 2
MARKER_TIMEOUT_SECONDS = FAKE_COMPILE_SECONDS + 10
# How long to wait before concluding a hook that must not run did not run.
NEGATIVE_WAIT_SECONDS = 0.5
POLL_SECONDS = 0.05

needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def _git(repo, *args, **kwargs):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


def _fake_interpreter(directory, marker, *, sleep_seconds=0):
    """A shell script standing in for the pinned Python: optionally sleeps, then writes
    the arguments it was given to `marker`."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "python"
    body = "#!/bin/sh\n"
    if sleep_seconds:
        body += f"sleep {sleep_seconds}\n"
    body += f'echo "$@" > {shlex.quote(str(marker))}\n'
    script.write_text(body)
    script.chmod(0o755)
    return script


def _wait_for(path, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(POLL_SECONDS)
    return path.exists()


def _run_hook(hook, cwd, env=None):
    subprocess.run(
        ["sh", str(hook)], cwd=cwd, check=True, capture_output=True, env=env, timeout=60
    )


def test_install_writes_executable_hooks_with_the_pinned_interpreter(repo):
    lines = install(repo)
    for name, command in (("post-commit", "compile"), ("post-merge", "render")):
        hook = repo / ".git" / "hooks" / name
        text = hook.read_text()
        assert text.startswith("#!/bin/sh\n")
        assert START in text and END in text
        pinned = shlex.quote(sys.executable)
        assert f'exec {pinned} -m lore.cli {command} --repo . --expect-head "$_lore_head"' in text
        assert f'exec lore {command} --repo . --expect-head "$_lore_head"' in text  # PATH fallback
        assert 'if [ -z "${LORE_SKIP_HOOK:-}" ]' in text
        if os.name != "nt":
            assert hook.stat().st_mode & 0o111
    assert len(lines) == 2 and all("written" in ln for ln in lines)
    assert status(repo) == {"post-commit": "installed", "post-merge": "installed"}


@pytest.mark.parametrize("shell", ["sh", "bash", "dash", "ksh", "zsh"])
def test_generated_hooks_are_valid_shell(repo, shell):
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not installed")
    install(repo, python="/opt/py dir/$HOME/python")  # a path that needs quoting
    for name in ("post-commit", "post-merge"):
        subprocess.run([shell, "-n", str(repo / ".git" / "hooks" / name)], check=True)


def test_install_is_idempotent_and_keeps_existing_hook_content(repo):
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho mine\n")
    install(repo, python="/opt/py/bin/python")
    first = hook.read_text()
    assert first.startswith("#!/bin/sh\necho mine\n") and first.count(START) == 1
    lines = install(repo, python="/opt/py/bin/python")
    assert hook.read_text() == first
    assert any("already current" in ln for ln in lines)


def test_reinstall_replaces_an_outdated_block_in_place(repo):
    install(repo)
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text(hook.read_text().replace("# crewlore: compiles", "# crewlore: compiled"))
    assert status(repo)["post-commit"] == "outdated (run `lore hook install` to refresh)"
    install(repo)
    assert status(repo)["post-commit"] == "installed"
    assert hook.read_text().count(START) == 1


def test_uninstall_removes_only_the_block(repo):
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho mine\n")
    install(repo)
    lines = uninstall(repo)
    assert hook.read_text() == "#!/bin/sh\necho mine\n"
    assert not (repo / ".git" / "hooks" / "post-merge").exists()  # held nothing else
    assert any("rest kept" in ln for ln in lines) and any("removed" in ln for ln in lines)
    assert status(repo) == {"post-commit": "missing", "post-merge": "missing"}
    assert uninstall(repo) == ["nothing to remove"]


def test_core_hookspath_is_honoured(repo):
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".githooks"], check=True)
    lines = install(repo)
    assert hooks_dir(repo) == (repo / ".githooks").resolve()
    assert (repo / ".githooks" / "post-commit").exists()
    assert not any(ln.startswith("note:") for ln in lines)  # not tracked: nothing to warn about


def test_outside_a_git_repository_is_a_clear_error(tmp_path):
    with pytest.raises(NotAGitRepository):
        install(tmp_path)


# GUARDS: git waits for the hook's stdout/stderr to close. The compile runs for as long
# as a model call, so it must not hold them — a GUI client, `gh`, CI or any script
# capturing git's output would otherwise block until the compile finishes.
@needs_sh
def test_git_commit_returns_before_the_background_compile_finishes(repo, tmp_path):
    marker = tmp_path / "ran"
    fake = _fake_interpreter(tmp_path / "bin", marker, sleep_seconds=FAKE_COMPILE_SECONDS)
    (repo / ".lore").mkdir()
    install(repo, python=str(fake))

    started = time.perf_counter()
    _git(repo, "commit", "-q", "--allow-empty", "-m", "one", timeout=120)
    elapsed = time.perf_counter() - started
    assert elapsed < HOOK_RETURN_BUDGET_SECONDS, f"git commit held for {elapsed:.1f}s"

    assert _wait_for(marker, MARKER_TIMEOUT_SECONDS)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert marker.read_text().split() == [
        "-m", "lore.cli", "compile", "--repo", ".", "--expect-head", head,
    ]


# GUARDS: the interpreter path is a shell word. Unquoted, `$` would expand, backticks
# would run and spaces would split; LORE_SKIP_HOOK skips on any non-empty value.
@needs_sh
def test_quoted_interpreter_path_runs_and_skip_variable_is_honoured(repo, tmp_path):
    marker = tmp_path / "ran"
    fake = _fake_interpreter(tmp_path / "py $HOME `dir`", marker)
    (repo / ".lore").mkdir()
    install(repo, python=str(fake))
    hook = repo / ".git" / "hooks" / "post-merge"
    assert shlex.quote(str(fake)) in hook.read_text()

    _run_hook(hook, repo, env={**os.environ, "LORE_SKIP_HOOK": "0"})
    assert not _wait_for(marker, NEGATIVE_WAIT_SECONDS)

    _run_hook(hook, repo)
    assert _wait_for(marker, MARKER_TIMEOUT_SECONDS)
    assert marker.read_text().split()[:3] == ["-m", "lore.cli", "render"]


@needs_sh
def test_hook_log_is_truncated_once_it_outgrows_the_cap(repo, tmp_path):
    marker = tmp_path / "ran"
    fake = _fake_interpreter(tmp_path / "bin", marker)
    log = repo / ".lore" / "cache" / "hook.log"
    log.parent.mkdir(parents=True)
    log.write_bytes(b"x" * (HOOK_LOG_MAX_BYTES + 1))
    install(repo, python=str(fake))

    _run_hook(repo / ".git" / "hooks" / "post-commit", repo)
    assert _wait_for(marker, MARKER_TIMEOUT_SECONDS)
    assert log.stat().st_size < HOOK_LOG_MAX_BYTES


# GUARDS: appended after an `exit`, the block is dead code that `status` would still
# call installed. It goes before the first exit/exec instead, and install says so.
def test_block_is_placed_before_a_top_level_exit(repo):
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\nnpm test\nexit 0\n")
    lines = install(repo, python="/opt/py/bin/python")
    text = hook.read_text()
    assert text.index("npm test") < text.index(START) < text.index(END) < text.index("exit 0")
    assert any("placed before the hook's `exit` on line 3" in ln for ln in lines)
    if shutil.which("sh"):
        subprocess.run(["sh", "-n", str(hook)], check=True)
    again = install(repo, python="/opt/py/bin/python")
    assert hook.read_text() == text and any("already current" in ln for ln in again)


def test_block_is_placed_before_the_statement_holding_an_indented_exec(repo):
    body = (
        "#!/usr/bin/env bash\n"
        "INSTALL_PYTHON=/opt/venv/bin/python\n"
        "ARGS=(hook-impl --hook-type=post-commit)\n"
        "\n"
        "# run from the interpreter the framework was installed with\n"
        'if [ -x "$INSTALL_PYTHON" ]; then\n'
        '    exec "$INSTALL_PYTHON" -mframework "${ARGS[@]}"\n'
        "elif command -v framework > /dev/null; then\n"
        '    exec framework "${ARGS[@]}"\n'
        "else\n"
        "    echo 'framework not found' 1>&2\n"
        "    exit 1\n"
        "fi\n"
    )
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text(body)
    lines = install(repo, python="/opt/py/bin/python")
    text = hook.read_text()
    assert text.index("ARGS=") < text.index(START) < text.index("# run from the interpreter")
    assert text.endswith("fi\n") and text.count("exec framework") == 1
    assert any("placed before the hook's `exec` on line 7" in ln for ln in lines)
    if shutil.which("bash"):
        subprocess.run(["bash", "-n", str(hook)], check=True)


def test_a_dead_block_after_an_exit_is_moved_on_reinstall(repo):
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\nexit 0\n\n" + block("compile", "compiles", "/opt/py/bin/python"))
    assert "exits before the crewlore block" in status(repo)["post-commit"]
    install(repo, python="/opt/py/bin/python")
    text = hook.read_text()
    assert text.count(START) == 1 and text.index(END) < text.index("exit 0")


def test_a_redirection_only_exec_does_not_count_as_the_end_of_the_hook(repo):
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\nexec >>/tmp/hook.log 2>&1\necho mine\n")
    lines = install(repo, python="/opt/py/bin/python")
    text = hook.read_text()
    assert text.index("echo mine") < text.index(START)
    assert not any("placed before" in ln for ln in lines)


# GUARDS: shell appended to a python3 (or node, or ruby) hook is a syntax error that
# silently breaks the user's hook. Refuse, and write nothing to either hook.
def test_a_non_shell_hook_is_refused_untouched(repo):
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/usr/bin/env python3\nprint('mine')\n")
    with pytest.raises(HookRefused, match="python3 script"):
        install(repo)
    assert hook.read_text() == "#!/usr/bin/env python3\nprint('mine')\n"
    assert not (repo / ".git" / "hooks" / "post-merge").exists()


@pytest.mark.parametrize(
    "damaged",
    [
        pytest.param(f"#!/bin/sh\n{START}\necho half\n", id="start-without-end"),
        pytest.param(f"#!/bin/sh\n{END}\necho mine\n{START}\n", id="end-before-start"),
        pytest.param(
            "#!/bin/sh\n" + block("compile", "a", "/opt/py") + block("compile", "b", "/opt/py"),
            id="two-blocks",
        ),
    ],
)
def test_a_damaged_or_duplicated_block_is_refused_by_install_and_uninstall(repo, damaged):
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text(damaged)
    with pytest.raises(HookRefused, match="fix by hand"):
        install(repo)
    with pytest.raises(HookRefused, match="fix by hand"):
        uninstall(repo)
    assert hook.read_text() == damaged
    assert not (repo / ".git" / "hooks" / "post-merge").exists()
    assert status(repo)["post-commit"].startswith("broken (")


# GUARDS: `status` must say why a hook will not work, not compare strings. Git skips a
# non-executable hook; the pinned interpreter may be gone or may not have crewlore.
def test_status_explains_why_a_hook_is_broken(repo, tmp_path, monkeypatch):
    hook = repo / ".git" / "hooks" / "post-commit"
    install(repo)
    hook.chmod(0o644)
    state = status(repo)["post-commit"]
    assert state.startswith("broken (") and "not executable" in state

    gone = tmp_path / "gone" / "python"
    install(repo, python=str(gone))
    monkeypatch.setattr(hooks_module, "_lore_on_path", lambda: None)
    state = status(repo)["post-commit"]
    assert state.startswith("broken (") and f"{gone} is missing" in state
    monkeypatch.setattr(hooks_module, "_lore_on_path", lambda: "/usr/local/bin/lore")
    state = status(repo)["post-commit"]
    assert state.startswith("installed (") and "falls back to `lore` on PATH" in state

    no_lore = tmp_path / "nolore"
    no_lore.write_text("#!/bin/sh\nexit 1\n")
    no_lore.chmod(0o755)
    install(repo, python=str(no_lore))
    state = status(repo)["post-commit"]
    assert state.startswith("broken (") and "cannot import lore" in state

    wrapper = tmp_path / "wrapper"
    wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    wrapper.chmod(0o755)
    install(repo, python=str(wrapper))
    assert status(repo)["post-commit"] == f"installed (pinned to {wrapper})"


def test_status_surfaces_the_last_hook_log_line(repo):
    assert last_log_line(repo) is None
    log = repo / ".lore" / "cache" / "hook.log"
    log.parent.mkdir(parents=True)
    log.write_text("ingested 2 new sessions\nrendered 3 active claims and 0 conflicts\n\n")
    assert last_log_line(repo) == "rendered 3 active claims and 0 conflicts"


def test_install_says_when_it_makes_an_existing_hook_executable(repo):
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho mine\n")
    hook.chmod(0o644)
    lines = install(repo)
    assert any("made executable; it was not" in ln for ln in lines if ln.startswith("post-commit"))
    assert not any("made executable" in ln for ln in lines if ln.startswith("post-merge"))


def test_crlf_hook_keeps_its_line_endings(repo):
    hook = repo / ".git" / "hooks" / "post-commit"
    original = b"#!/bin/sh\r\necho mine\r\n"
    hook.write_bytes(original)
    install(repo, python="/opt/py/bin/python")
    data = hook.read_bytes()
    assert START.encode() in data and not re.search(rb"[^\r]\n", data)  # every newline is CRLF
    assert status(repo)["post-commit"].startswith("installed (pinned to")
    uninstall(repo)
    assert hook.read_bytes() == original


# GUARDS: a committed core.hooksPath shares the hook file with the team. The pinned
# interpreter is this machine's; everyone else needs the PATH fallback, and the
# installer says so.
def test_tracked_hooks_dir_gets_a_note_and_the_path_fallback(repo):
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".githooks"], check=True)
    (repo / ".githooks").mkdir()
    (repo / ".githooks" / "post-commit").write_text("#!/bin/sh\n")
    _git(repo, "add", ".githooks")
    lines = install(repo)
    assert any(ln.startswith("note:") and "tracked by git" in ln for ln in lines)
    text = (repo / ".githooks" / "post-commit").read_text()
    assert "elif command -v lore >/dev/null 2>&1; then" in text
    assert 'exec lore compile --repo . --expect-head "$_lore_head"' in text
