"""`lore hook install` keeps the layer current through git's own post-commit, post-merge
and post-rewrite hooks: a marked, removable block, an executable file, the interpreter
pinned with `lore` on PATH as the fallback, other hook content left alone byte for byte,
and the block placed where the hook actually reaches it."""

import os
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
    HOOKS,
    PROBE_VARIABLE,
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
INSTALLED = {name: "installed" for name in HOOKS}
REAL_IMPORT_PROBLEM = hooks_module._import_problem

needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")


@pytest.fixture(autouse=True)
def _import_probe_passes(monkeypatch):
    """`status` runs the pinned interpreter to import lore.cli. The tests about that
    probe take `real_import_probe`; everywhere else it is stubbed, so the suite does not
    depend on which interpreter the test runner resolved."""
    monkeypatch.setattr(hooks_module, "_import_problem", lambda python: None)


@pytest.fixture
def real_import_probe(monkeypatch):
    monkeypatch.setattr(hooks_module, "_import_problem", REAL_IMPORT_PROBLEM)


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
    """A shell script standing in for the pinned Python: optionally sleeps, then appends
    its working directory and the arguments it was given as one line to `marker`."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "python"
    body = "#!/bin/sh\n"
    if sleep_seconds:
        body += f"sleep {sleep_seconds}\n"
    body += f'echo "$PWD $@" >> {shlex.quote(str(marker))}\n'
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


def _run_hook(hook, cwd, env=None, *args):
    subprocess.run(
        ["sh", str(hook), *args], cwd=cwd, check=True, capture_output=True, env=env, timeout=60
    )


def _reaches_block(hook, cwd, tmp_path):
    """Run the hook as git would, with the probe variable set: True when the hook got
    as far as the crewlore block."""
    marker = tmp_path / f"probe-{time.monotonic_ns()}"
    _run_hook(hook, cwd, {**os.environ, PROBE_VARIABLE: str(marker)})
    return marker.exists()


def _hook(repo, name="post-commit"):
    return repo / ".git" / "hooks" / name


def test_install_writes_executable_hooks_with_the_pinned_interpreter(repo):
    lines = install(repo)
    for name, spec in HOOKS.items():
        text = _hook(repo, name).read_text()
        assert text.startswith("#!/bin/sh\n")
        assert START in text and END in text
        pinned = shlex.quote(sys.executable)
        args = f'{spec.command} --repo "$_lore_root" --expect-head "$_lore_head"'
        assert f"exec {pinned} -m lore.cli {args}" in text
        assert f"exec lore {args}" in text  # PATH fallback
        assert 'if [ -z "${LORE_SKIP_HOOK:-}" ]' in text
        if os.name != "nt":
            assert _hook(repo, name).stat().st_mode & 0o111
    assert sorted(HOOKS) == ["post-commit", "post-merge", "post-rewrite"]
    assert len(lines) == 3 and all("written" in ln for ln in lines)
    assert status(repo) == INSTALLED


@pytest.mark.parametrize("shell", ["sh", "bash", "dash", "ksh", "zsh"])
def test_generated_hooks_are_valid_shell(repo, shell):
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not installed")
    install(repo, python="/opt/py dir/$HOME/python")  # a path that needs quoting
    for name in HOOKS:
        subprocess.run([shell, "-n", str(_hook(repo, name))], check=True)


def test_install_is_idempotent_and_keeps_existing_hook_content(repo):
    hook = _hook(repo)
    hook.write_text("#!/bin/sh\necho mine\n")
    install(repo, python="/opt/py/bin/python")
    first = hook.read_text()
    assert first.startswith("#!/bin/sh\necho mine\n" + START) and first.count(START) == 1
    lines = install(repo, python="/opt/py/bin/python")
    assert hook.read_text() == first
    assert any("already current" in ln for ln in lines)


def test_reinstall_replaces_an_outdated_block_in_place(repo):
    install(repo)
    hook = _hook(repo)
    hook.write_text(hook.read_text().replace("# crewlore: compiles", "# crewlore: compiled"))
    assert status(repo)["post-commit"] == "outdated (run `lore hook install` to refresh)"
    install(repo)
    assert status(repo)["post-commit"] == "installed"
    assert hook.read_text().count(START) == 1


def test_uninstall_removes_only_the_block(repo):
    hook = _hook(repo)
    hook.write_text("#!/bin/sh\necho mine\n")
    install(repo)
    lines = uninstall(repo)
    assert hook.read_text() == "#!/bin/sh\necho mine\n"
    for name in ("post-merge", "post-rewrite"):
        assert not _hook(repo, name).exists()  # held nothing else
    assert any("rest kept" in ln for ln in lines) and any("removed" in ln for ln in lines)
    assert status(repo) == {name: "missing" for name in HOOKS}
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
# capturing git's output would otherwise block until the compile finishes. The compile
# runs from `.lore/cache` with the repository passed explicitly, so a top-level `lore/`
# package in the repository cannot shadow the installed one.
@needs_sh
def test_git_commit_returns_before_the_background_compile_finishes(repo, tmp_path):
    marker = tmp_path / "ran"
    fake = _fake_interpreter(tmp_path / "bin", marker, sleep_seconds=FAKE_COMPILE_SECONDS)
    (repo / ".lore").mkdir()
    (repo / "lore").mkdir()
    (repo / "lore" / "__init__.py").write_text("")  # would shadow crewlore from the root
    install(repo, python=str(fake))

    started = time.perf_counter()
    _git(repo, "commit", "-q", "--allow-empty", "-m", "one", timeout=120)
    elapsed = time.perf_counter() - started
    assert elapsed < HOOK_RETURN_BUDGET_SECONDS, f"git commit held for {elapsed:.1f}s"

    assert _wait_for(marker, MARKER_TIMEOUT_SECONDS)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    cwd, *args = marker.read_text().split()
    assert os.path.samefile(cwd, repo / ".lore" / "cache")
    assert args[:3] == ["-m", "lore.cli", "compile"]
    assert args[3] == "--repo" and os.path.samefile(args[4], repo)
    assert args[5:] == ["--expect-head", head]


# GUARDS: the interpreter path is a shell word. Unquoted, `$` would expand, backticks
# would run and spaces would split; LORE_SKIP_HOOK skips on any non-empty value.
@needs_sh
def test_quoted_interpreter_path_runs_and_skip_variable_is_honoured(repo, tmp_path):
    marker = tmp_path / "ran"
    fake = _fake_interpreter(tmp_path / "py $HOME `dir`", marker)
    (repo / ".lore").mkdir()
    install(repo, python=str(fake))
    hook = _hook(repo, "post-merge")
    assert shlex.quote(str(fake)) in hook.read_text()

    _run_hook(hook, repo, {**os.environ, "LORE_SKIP_HOOK": "0"})
    assert not _wait_for(marker, NEGATIVE_WAIT_SECONDS)

    _run_hook(hook, repo)
    assert _wait_for(marker, MARKER_TIMEOUT_SECONDS)
    assert marker.read_text().split()[1:4] == ["-m", "lore.cli", "render"]


@needs_sh
def test_hook_log_is_truncated_once_it_outgrows_the_cap(repo, tmp_path):
    marker = tmp_path / "ran"
    fake = _fake_interpreter(tmp_path / "bin", marker)
    log = repo / ".lore" / "cache" / "hook.log"
    log.parent.mkdir(parents=True)
    log.write_bytes(b"x" * (HOOK_LOG_MAX_BYTES + 1))
    install(repo, python=str(fake))

    _run_hook(_hook(repo), repo)
    assert _wait_for(marker, MARKER_TIMEOUT_SECONDS)
    assert log.stat().st_size < HOOK_LOG_MAX_BYTES


# GUARDS: a rebase fires post-commit once per replayed commit while HEAD is still
# moving, so a compile started then would hold the lock and end in HeadMoved, and the
# layer would lag until the next commit. The post-commit block steps aside during a
# rebase and post-rewrite compiles once, when HEAD has settled; an amend, which fires
# both hooks, compiles once through post-commit.
@needs_sh
def test_a_rebase_compiles_once_through_post_rewrite_with_head_settled(repo, tmp_path):
    marker = tmp_path / "ran"
    fake = _fake_interpreter(tmp_path / "bin", marker)
    (repo / ".lore").mkdir()
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    for i in range(3):
        (repo / f"f{i}").write_text(str(i))
        _git(repo, "add", f"f{i}")
        _git(repo, "commit", "-q", "-m", f"feature {i}")
    _git(repo, "checkout", "-q", "-")
    (repo / "m").write_text("m")
    _git(repo, "add", "m")
    _git(repo, "commit", "-q", "-m", "main moved on")
    _git(repo, "checkout", "-q", "feature")
    install(repo, python=str(fake))

    _git(repo, "rebase", "-q", "-", timeout=120)
    assert _wait_for(marker, MARKER_TIMEOUT_SECONDS)
    time.sleep(NEGATIVE_WAIT_SECONDS)  # any post-commit compile would have landed by now
    runs = marker.read_text().splitlines()
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert len(runs) == 1, runs
    assert runs[0].split()[1:4] == ["-m", "lore.cli", "compile"]
    assert runs[0].split()[-2:] == ["--expect-head", head]

    marker.unlink()
    _git(repo, "commit", "-q", "--amend", "-m", "feature 2, amended", timeout=120)
    assert _wait_for(marker, MARKER_TIMEOUT_SECONDS)
    time.sleep(NEGATIVE_WAIT_SECONDS)
    runs = marker.read_text().splitlines()
    assert len(runs) == 1 and runs[0].split()[-1] == _git(repo, "rev-parse", "HEAD").stdout.strip()


# GUARDS: appended after a command that ends the hook, the block is dead code that
# `status` would still call installed. It goes before the first `exit`/`exec` instead,
# wherever the shell would meet it: after `;`, `&&` or `||`, behind `then`, inside the
# body of an `if`, a `case` arm or a function, behind a redirection or a variable
# assignment, or after a heredoc whose body merely contains the word `exit`. Install says
# where it went, the hook still parses, running it reaches the block, a reinstall
# changes nothing, and uninstall gives the original bytes back.
TERMINATOR_SHAPES = [  # hook, line of the terminator, its keyword, kept before, moved after
    pytest.param(
        "#!/bin/sh\necho mine; exit 0\n", 2, "exit", None, "echo mine; exit 0", id="semicolon"
    ),
    pytest.param("#!/bin/sh\ntrue && exit 0\n", 2, "exit", None, "true && exit 0", id="and-list"),
    pytest.param(
        "#!/bin/sh\nif true\nthen exit 0\nfi\n", 3, "exit", None, "if true\n", id="then-prefix"
    ),
    pytest.param(
        '#!/bin/sh\nif [ -n "$CI" ]\nthen\n  exit 0\nfi\n', 4, "exit", None, 'if [ -n "$CI" ]',
        id="then-line",
    ),
    pytest.param(
        "#!/bin/sh\nif true; then\nexit 0\nfi\n", 3, "exit", None, "if true;", id="flat-body"
    ),
    pytest.param(
        "#!/bin/sh\nexec 2>&1 /usr/bin/true\n", 2, "exec", None, "exec 2>&1",
        id="redirect-then-command",
    ),
    pytest.param(
        "#!/bin/sh\ncat <<'EOT' >/dev/null\nexit 0\nEOT\nexit 0\n", 5, "exit", "EOT\n", "exit 0\n",
        id="exit-after-heredoc",
    ),
    pytest.param(
        "#!/bin/sh\nFOO=1 exec /usr/bin/true\n", 2, "exec", None, "FOO=1 exec", id="assignment"
    ),
    pytest.param(
        "#!/bin/sh\ncase x in\n  x) exit 0;;\nesac\n", 3, "exit", None, "case x in", id="case-arm"
    ),
    pytest.param(
        "#!/bin/sh\nrun() {\n  exit 0\n}\nrun\n", 3, "exit", None, "run() {", id="function"
    ),
    pytest.param(
        "#!/bin/sh\ntrue \\\n  && exit 0\n", 3, "exit", None, "true \\", id="continuation"
    ),
]


@needs_sh
@pytest.mark.parametrize("original, line_no, keyword, before_block, after_block", TERMINATOR_SHAPES)
def test_block_is_placed_before_the_command_that_ends_the_hook(
    repo, tmp_path, original, line_no, keyword, before_block, after_block
):
    hook = _hook(repo)
    hook.write_text(original)
    lines = install(repo, python="/opt/py/bin/python")
    text = hook.read_text()
    assert any(f"placed before the hook's `{keyword}` on line {line_no}" in ln for ln in lines)
    assert text.index(END) < text.rindex(after_block)
    if before_block:
        assert text.index(before_block) < text.index(START)
    subprocess.run(["sh", "-n", str(hook)], check=True)
    assert _reaches_block(hook, repo, tmp_path)
    assert "exits before" not in status(repo)["post-commit"]

    again = install(repo, python="/opt/py/bin/python")
    assert hook.read_text() == text and any("already current" in ln for ln in again)
    uninstall(repo)
    assert hook.read_bytes() == original.encode()


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
    hook = _hook(repo)
    hook.write_text(body)
    lines = install(repo, python="/opt/py/bin/python")
    text = hook.read_text()
    assert text.index("ARGS=") < text.index(START) < text.index("# run from the interpreter")
    assert text.endswith("fi\n") and text.count("exec framework") == 1
    assert any("placed before the hook's `exec` on line 7" in ln for ln in lines)
    if shutil.which("bash"):
        subprocess.run(["bash", "-n", str(hook)], check=True)
    uninstall(repo)
    assert hook.read_text() == body


# GUARDS: `exit` inside a heredoc body is text the hook feeds to a command, not a command.
# The block must not be inserted into the body, where it would be text too.
@needs_sh
@pytest.mark.parametrize(
    "original",
    [
        pytest.param("#!/bin/sh\ncat <<'EOT' >/dev/null\nexit 0\nEOT\n", id="quoted-delimiter"),
        pytest.param("#!/bin/sh\ncat <<EOT >/dev/null\nexit 0\n# exit 0\nEOT\n", id="bare"),
        pytest.param("#!/bin/sh\ncat <<-EOT >/dev/null\n\texit 0\n\tEOT\necho mine\n", id="dash"),
    ],
)
def test_an_exit_inside_a_heredoc_is_text_and_the_block_goes_after_it(repo, tmp_path, original):
    hook = _hook(repo)
    hook.write_text(original)
    lines = install(repo, python="/opt/py/bin/python")
    text = hook.read_text()
    assert not any("placed before" in ln for ln in lines)
    assert text.startswith(original) and text.endswith(END + "\n")
    subprocess.run(["sh", "-n", str(hook)], check=True)
    assert _reaches_block(hook, repo, tmp_path)
    uninstall(repo)
    assert hook.read_text() == original


# GUARDS: when the hook ends inside a construct the scanner cannot see the end of, a
# block appended there would be text. Refuse, untouched, rather than install dead code.
@pytest.mark.parametrize(
    "original, inside",
    [
        pytest.param("#!/bin/sh\ncat <<EOT\nexit 0\n", "a heredoc", id="open-heredoc"),
        pytest.param('#!/bin/sh\necho "oops\n', "a quoted string", id="open-quote"),
    ],
)
def test_a_hook_the_block_cannot_be_placed_into_is_refused_untouched(repo, original, inside):
    hook = _hook(repo)
    hook.write_text(original)
    with pytest.raises(HookRefused, match=f"ends inside {inside}.*cannot place its block"):
        install(repo)
    assert hook.read_text() == original
    assert not _hook(repo, "post-merge").exists()


# GUARDS: `status` must see a dead block for every shape install knows, and a reinstall
# must move it to where it runs.
@pytest.mark.parametrize(
    "prefix, suffix, problem",
    [
        pytest.param("#!/bin/sh\necho mine; exit 0\n", "", "exits before", id="semicolon"),
        pytest.param("#!/bin/sh\ntrue && exit 0\n", "", "exits before", id="and-list"),
        pytest.param("#!/bin/sh\nif true\nthen exit 0\nfi\n", "", "exits before", id="then-prefix"),
        pytest.param("#!/bin/sh\nexec 2>&1 /usr/bin/true\n", "", "exits before", id="exec"),
        pytest.param(
            "#!/bin/sh\ncat <<'EOT' >/dev/null\n", "EOT\n", "inside a heredoc", id="in-heredoc"
        ),
    ],
)
def test_status_sees_a_dead_block_and_reinstall_moves_it(repo, prefix, suffix, problem):
    hook = _hook(repo)
    hook.write_text(prefix + block("compile", "compiles", "/opt/py/bin/python") + suffix)
    state = status(repo)["post-commit"]
    assert state.startswith("broken (") and problem in state and "lore hook install" in state
    install(repo, python="/opt/py/bin/python")
    text = hook.read_text()
    assert text.count(START) == 1
    assert status(repo)["post-commit"].startswith("installed")
    if suffix:
        assert text.index(suffix) < text.index(START)  # after the heredoc, not in it
    else:
        assert text.index(END) < text.index(prefix.splitlines()[1])


def test_a_redirection_only_exec_does_not_count_as_the_end_of_the_hook(repo):
    hook = _hook(repo)
    hook.write_text("#!/bin/sh\nexec >>/tmp/hook.log 2>&1\necho mine\n")
    lines = install(repo, python="/opt/py/bin/python")
    text = hook.read_text()
    assert text.index("echo mine") < text.index(START)
    assert not any("placed before" in ln for ln in lines)


# GUARDS: shell appended to a python3 (or node, or ruby) hook is a syntax error that
# silently breaks the user's hook. Refuse, and write nothing to either hook.
def test_a_non_shell_hook_is_refused_untouched(repo):
    hook = _hook(repo)
    hook.write_text("#!/usr/bin/env python3\nprint('mine')\n")
    with pytest.raises(HookRefused, match="python3 script"):
        install(repo)
    assert hook.read_text() == "#!/usr/bin/env python3\nprint('mine')\n"
    assert not _hook(repo, "post-merge").exists()


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
    hook = _hook(repo)
    hook.write_text(damaged)
    with pytest.raises(HookRefused, match="fix by hand"):
        install(repo)
    with pytest.raises(HookRefused, match="fix by hand"):
        uninstall(repo)
    assert hook.read_text() == damaged
    assert not _hook(repo, "post-merge").exists()
    assert status(repo)["post-commit"].startswith("broken (")


# GUARDS: `status` must say why a hook will not work, not compare strings. Git skips a
# non-executable hook; the pinned interpreter may be gone or may not have crewlore.
def test_status_explains_why_a_hook_is_broken(repo, tmp_path, monkeypatch, real_import_probe):
    hook = _hook(repo)
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


# GUARDS: `python -c "import lore"` run from a repository with a top-level `lore/`
# package imports that package, so status said installed where the hook would fail with
# "No module named lore.cli". The probe runs from an empty directory, with the current
# directory off sys.path, and imports what the hook runs.
def test_import_probe_is_not_fooled_by_a_lore_package_in_the_working_directory(
    repo, monkeypatch, real_import_probe
):
    (repo / "lore").mkdir()
    (repo / "lore" / "__init__.py").write_text("")
    shadowed = subprocess.run(
        [sys.executable, "-c", "import lore.cli"], cwd=repo, capture_output=True, text=True
    )
    assert shadowed.returncode != 0 and "lore" in shadowed.stderr  # the shadow is real
    monkeypatch.chdir(repo)
    install(repo)
    assert status(repo) == INSTALLED, "needs crewlore installed for sys.executable"


# GUARDS: a static scan cannot see every way a hook ends before the block (`set -e` and
# a failing command, for one). `status --probe` runs the hook with the probe variable
# set, so the block reports whether it was reached at all; without the flag, a hook with
# other commands says it was not probed.
@needs_sh
def test_status_probe_runs_the_hook_to_see_whether_the_block_is_reached(repo, monkeypatch):
    hook = _hook(repo)
    hook.write_text("#!/bin/sh\nset -e\nfalse\n")
    install(repo)
    assert status(repo)["post-commit"].startswith("installed (not probed:")
    state = status(repo, probe=True)["post-commit"]
    assert state == "broken (block is never reached (the hook exited 1 before it))"

    hook.write_text("#!/bin/sh\necho mine >/dev/null\n")
    install(repo)
    monkeypatch.setenv("LORE_SKIP_HOOK", "1")  # the probe is not a run; it ignores the skip
    assert status(repo, probe=True)["post-commit"] == "installed"
    assert status(repo, probe=True)["post-merge"] == "installed"  # nothing but the block


def test_status_surfaces_the_last_hook_log_line(repo):
    assert last_log_line(repo) is None
    log = repo / ".lore" / "cache" / "hook.log"
    log.parent.mkdir(parents=True)
    log.write_text("ingested 2 new sessions\nrendered 3 active claims and 0 conflicts\n\n")
    assert last_log_line(repo) == "rendered 3 active claims and 0 conflicts"


def test_install_says_when_it_makes_an_existing_hook_executable(repo):
    hook = _hook(repo)
    hook.write_text("#!/bin/sh\necho mine\n")
    hook.chmod(0o644)
    lines = install(repo)
    assert any("made executable; it was not" in ln for ln in lines if ln.startswith("post-commit"))
    assert not any("made executable" in ln for ln in lines if ln.startswith("post-merge"))


# GUARDS: git cannot exec a CRLF hook (`/bin/sh\r` is not an interpreter) and a block
# written with CRLF is a shell syntax error, so neither install nor status may call such
# a hook good. Install refuses it untouched and says what to do; status reports it broken.
@needs_sh
def test_a_crlf_hook_is_refused_by_install_and_reported_broken_by_status(repo):
    hook = _hook(repo)
    original = b"#!/bin/sh\r\necho mine\r\n"
    hook.write_bytes(original)
    with pytest.raises(HookRefused, match="CRLF line endings.*Convert the file to LF"):
        install(repo, python="/opt/py/bin/python")
    assert hook.read_bytes() == original
    assert not _hook(repo, "post-merge").exists()
    assert status(repo) == {
        "post-commit": "broken (CRLF line endings; git cannot exec it)",
        "post-merge": "missing",
        "post-rewrite": "missing",
    }

    crlf_block = block("compile", "compiles", "/opt/py/bin/python").replace("\n", "\r\n")
    hook.write_bytes(original + crlf_block.encode())
    hook.chmod(0o755)
    assert subprocess.run(["sh", "-n", str(hook)], capture_output=True).returncode != 0
    assert status(repo)["post-commit"] == "broken (CRLF line endings; git cannot exec it)"


# GUARDS: uninstall takes out exactly the bytes install added. The one thing it cannot
# give back is a missing final newline: a block cannot start mid-line, so install ends
# the last line first and says so.
def test_a_hook_without_a_final_newline_gets_one_and_uninstall_keeps_it(repo):
    hook = _hook(repo)
    hook.write_text("#!/bin/sh\necho mine")
    lines = install(repo, python="/opt/py/bin/python")
    assert any("ended the hook's last line with a newline" in ln for ln in lines)
    assert hook.read_text().startswith("#!/bin/sh\necho mine\n" + START)
    uninstall(repo)
    assert hook.read_text() == "#!/bin/sh\necho mine\n"


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
    assert 'exec lore compile --repo "$_lore_root" --expect-head "$_lore_head"' in text
