#!/usr/bin/env python3
"""Write the Claude Code plugin files, `plugins/crewlore/` and the marketplace file at the
repository root, from the installer's own skill text and hook definitions (see
`lore.claude_plugin`).

    uv run python scripts/export_plugin.py          # write or refresh the four files
    uv run python scripts/export_plugin.py --check  # exit 1 and name any stale file

Run it after any change to `SKILL_MD`, to the hooks in `lore.assistant_hooks`, or to the
package version; `tests/unit/test_claude_plugin.py` fails until the files are current.
"""
# ruff: noqa: E402  (src-path bootstrap must run before importing `lore`)

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Make `lore` importable even without an editable install (deps still required).
sys.path.insert(0, str(REPO_ROOT / "src"))

from lore.claude_plugin import stale_files, write_plugin_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if a committed plugin file differs from the generator",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="repository root to write into (default: this checkout)",
    )
    args = parser.parse_args(argv)
    if args.check:
        stale = stale_files(args.root)
        for rel in stale:
            print(f"stale: {rel}")
        if stale:
            print("run `uv run python scripts/export_plugin.py` and commit the result")
            return 1
        print("plugin files are current")
        return 0
    for line in write_plugin_files(args.root):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
