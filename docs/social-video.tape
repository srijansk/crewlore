# VHS tape — short explainer video for LinkedIn / X.
#
# Render: vhs docs/social-video.tape
# Output: docs/assets/crewlore-explainer.mp4 (1920x1080, ~55 s, silent)
#
# Same offline demo as the README GIF, paced for a viewer: the problem in two
# lines, the compiled book (with a declined claim next to an adopted one), the
# query, the success criteria, the zero-session path via pull requests, and
# the install line. No API key, no network, fully reproducible.

Output docs/assets/crewlore-explainer.mp4

Set FontSize 22
Set Width 1920
Set Height 1080
Set Theme "Catppuccin Mocha"
Set TypingSpeed 24ms
Set Padding 40
Set Framerate 30

Hide
Type "cd $(git rev-parse --show-toplevel) && clear"
Enter
Show

Type "# Your coding agents keep relearning what your team already figured out."
Enter
Sleep 2000ms
Type "# The reasoning lives in one chat session, and chat sessions die."
Enter
Sleep 2000ms
Type "# crewlore compiles those sessions into a knowledge book inside your repo."
Enter
Sleep 2000ms

Type "uv run python scripts/demo.py --step"
Enter
Sleep 8s
Enter
Sleep 5s
Enter
Sleep 5s

Type "clear"
Enter
Type "# No sessions yet? Coding agents write their reasoning in pull requests."
Enter
Sleep 2s
Type "# Compile a repo's PR threads instead. No transcripts needed:"
Enter
Sleep 1500ms
Type "uv run lore import-prs --help"
Enter
Sleep 6s

Type "clear"
Enter
Type "# Every claim carries a verbatim anchor to its source line,"
Enter
Sleep 1500ms
Type "# and records whether the team adopted it or tried it and declined."
Enter
Sleep 2000ms
Type "# Local-first. Your own model key. Plaintext in git. No hosted service."
Enter
Sleep 2000ms
Type "# pipx install crewlore   |   github.com/srijansk/crewlore"
Enter
Sleep 4s
