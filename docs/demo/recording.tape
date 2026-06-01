# VHS tape — README hero GIF for agent-lore.
#
# Render: vhs docs/demo/recording.tape
# Output: docs/assets/demo.gif
# Requires: brew install vhs
#
# This tape runs the bundled offline demo (scripts/demo.py) which uses
# deterministic synthetic data — no API key, no network, fully reproducible.
# Anyone can clone the repo and `vhs docs/demo/recording.tape` to regenerate
# the GIF.

Output docs/assets/demo.gif

# --- Visual tuning ---
Set FontSize 14
Set Width 1280
Set Height 820
Set Theme "Tokyo Night"
Set TypingSpeed 30ms
Set PlaybackSpeed 1.0
Set Padding 30
Set BorderRadius 8

# --- Setup: hide cwd noise; assume user is in the repo with venv ready ---
Hide
Type "cd $(git rev-parse --show-toplevel) && clear"
Enter
Show

# --- Frame 1: what is this ---
Type "# agent-lore — your agent sessions, compiled into team knowledge."
Enter
Sleep 1s
Type "# Local-first. Plaintext in your repo. Every claim citable."
Enter
Sleep 1500ms

# --- Frame 2: run it ---
Type "uv run python scripts/demo.py"
Enter
Sleep 10s

# --- Frame 3: close ---
Type "# Browse a real run on pydantic-ai → docs/examples/pydantic-ai/"
Enter
Sleep 1500ms
Type "# github.com/srijansk/agent-lore  ·  alpha"
Enter
Sleep 2500ms
