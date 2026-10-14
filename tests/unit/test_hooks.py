"""`lore hook install` keeps the layer current through git's own post-commit and
post-merge hooks: a marked, removable block, an executable file, the interpreter
pinned, other hook content left alone."""

import os
import shutil
import subprocess
import sys

import pytest

from lore.hooks import END, START, NotAGitRepository, hooks_dir, install, status, uninstall


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_install_writes_executable_hooks_with_the_pinned_interpreter(repo):
    lines = install(repo)
    for name, command in (("post-commit", "compile"), ("post-merge", "render")):
        hook = repo / ".git" / "hooks" / name
        text = hook.read_text()
        assert text.startswith("#!/bin/sh\n")
        assert START in text and END in text
        assert f'"{sys.executable}" -m lore.cli {command} --repo .' in text
        assert "LORE_SKIP_HOOK" in text
        if os.name != "nt":
            assert hook.stat().st_mode & 0o111
    assert len(lines) == 2 and all("written" in ln for ln in lines)
    assert status(repo) == {"post-commit": "installed", "post-merge": "installed"}


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_generated_hooks_are_valid_shell(repo):
    install(repo)
    for name in ("post-commit", "post-merge"):
        subprocess.run(["sh", "-n", str(repo / ".git" / "hooks" / name)], check=True)


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
    install(repo, python="/old/python")
    assert status(repo)["post-commit"] == "outdated"  # pinned path differs from this interpreter
    install(repo)
    assert status(repo)["post-commit"] == "installed"
    assert (repo / ".git" / "hooks" / "post-commit").read_text().count(START) == 1


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
    install(repo)
    assert hooks_dir(repo) == (repo / ".githooks").resolve()
    assert (repo / ".githooks" / "post-commit").exists()


def test_outside_a_git_repository_is_a_clear_error(tmp_path):
    with pytest.raises(NotAGitRepository):
        install(tmp_path)
