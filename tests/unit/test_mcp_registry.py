"""The MCP Registry listing (server.json) must describe the package this tree builds.

The registry keeps one immutable record per version and checks ownership by fetching
the PyPI description of the exact version named in server.json, so the version, the
PyPI identifier, the README marker and the `crewlore` console script the entry runs
all have to agree with pyproject.toml.
"""

from __future__ import annotations

import json
import re
from importlib.metadata import entry_points
from pathlib import Path

from lore import __version__

ROOT = Path(__file__).resolve().parents[2]
SERVER_NAME = "io.github.srijansk/crewlore"


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.MULTILINE)
    assert match, "pyproject.toml has no [project] version"
    return match.group(1)


def _server_json() -> dict:
    return json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def test_server_json_names_this_package_and_version():
    server = _server_json()
    assert server["name"] == SERVER_NAME
    assert server["version"] == __version__ == _pyproject_version()
    assert 1 <= len(server["description"]) <= 100  # the schema's cap
    (package,) = server["packages"]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == "crewlore"
    assert package["version"] == server["version"]
    assert package["transport"] == {"type": "stdio"}
    # Left out on purpose: the registry defaults it to https://pypi.org, and a client that
    # passes a set value to uvx as --index-url hands it the project site, not the simple index.
    assert "registryBaseUrl" not in package


def test_server_json_runs_serve_through_the_package_name():
    # Clients compose `uvx <runtimeArguments> crewlore@<version> <packageArguments>`, so the
    # entry needs a console script named `crewlore` and the serve extra installed beside it.
    (package,) = _server_json()["packages"]
    assert package["runtimeHint"] == "uvx"
    runtime = [(a["type"], a["name"], a["value"]) for a in package["runtimeArguments"]]
    assert runtime == [("named", "--with", "crewlore[serve]")]
    serve, repo = package["packageArguments"]
    assert serve == {"type": "positional", "value": "serve"}
    assert (repo["type"], repo["name"], repo["isRequired"]) == ("named", "--repo", True)
    scripts = {ep.name: ep.value for ep in entry_points(group="console_scripts")}
    assert scripts.get("crewlore") == "lore.cli:app" == scripts.get("lore")


def test_readme_carries_the_registry_ownership_marker():
    # The registry looks for "mcp-name: <server name>" followed by a boundary in the PyPI
    # description, which is this README.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(rf"mcp-name: {re.escape(SERVER_NAME)}(?![A-Za-z0-9._/-])", readme)
