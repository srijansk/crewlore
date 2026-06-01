# VHS tape — README hero GIF for crewlore.
#
# Render: vhs docs/recording.tape
# Output: docs/assets/demo.gif
# Requires: brew install vhs
#
# This tape runs the bundled offline demo (scripts/demo.py) which uses
# deterministic synthetic data — no API key, no network, fully reproducible.
# Anyone can clone the repo and `vhs docs/recording.tape` to regenerate
# the GIF.

Output docs/assets/demo.gif

# --- Visual tuning ---
# Higher contrast theme + larger font for README-hero legibility on dark/light.
Set FontSize 18
Set Width 1400
Set Height 900
Set Theme "Catppuccin Mocha"
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
Type "# crewlore — your agent sessions, compiled into team knowledge."
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
Type "# github.com/srijansk/crewlore  ·  alpha"
Enter
Sleep 2500ms
