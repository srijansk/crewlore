"""Test-wide isolation from the developer's machine."""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_git_config(monkeypatch):
    """No test reads the developer's git configuration. A global `core.hooksPath` would
    otherwise send every hook test into the developer's real hooks directory, and a
    global `commit.gpgsign` or identity would change what `git commit` does in a test."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
