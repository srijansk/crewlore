# VHS tape — README hero GIF for crewlore.
#
# Render: vhs docs/recording.tape
# Output: docs/assets/demo.gif
# Requires: brew install vhs
#
# Runs the bundled offline demo (scripts/demo.py --step), which uses
# deterministic synthetic data — no API key, no network, fully reproducible.
# --step pauses between sections so each one is readable; the tape presses
# Enter to advance. Anyone can clone the repo and re-render this GIF.
#
# The launch video for posts is rendered separately: see docs/launch-video/README.md.

Output docs/assets/demo.gif

Set FontSize 17
Set Width 1400
Set Height 920
Set Theme "Catppuccin Mocha"
Set TypingSpeed 25ms
Set Padding 28
Set BorderRadius 8

Hide
Type "cd $(git rev-parse --show-toplevel) && clear"
Enter
Show

Type "# Your coding agents keep relearning what your team already figured out."
Enter
Sleep 1200ms
Type "# crewlore compiles their sessions and pull requests into a knowledge book in your repo."
Enter
Sleep 1500ms

Type "uv run python scripts/demo.py --step"
Enter
Sleep 7s
Enter
Sleep 4500ms
Enter
Sleep 4500ms

Type "# Every claim: a verbatim anchor, and whether the team adopted it or declined it."
Enter
Sleep 1200ms
Type "# pipx install crewlore   |   github.com/srijansk/crewlore"
Enter
Sleep 3s
