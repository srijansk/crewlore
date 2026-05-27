# VHS tape for the README hero asciinema.
#
# Render with: vhs docs/demo/recording.tape
# Output:     docs/assets/demo.gif
#
# Requires charmbracelet/vhs:  brew install vhs   (https://github.com/charmbracelet/vhs)
#
# The tape uses the bundled offline demo so the recording is deterministic and
# requires no API key. For a recording against a real repo, swap the Type lines
# that run `scripts/demo.py` for the actual `lore init` / `lore watch` flow.

Output docs/assets/demo.gif

Set FontSize 16
Set Width 1280
Set Height 760
Set Theme "Tokyo Night"
Set TypingSpeed 35ms
Set PlaybackSpeed 1.0
Set Padding 30

# --- Cold start ---
Hide
Type "cd /tmp/agent-lore-demo && clear"
Enter
Show

Type "# agent-lore — turning agent sessions into team knowledge"
Enter
Sleep 1500ms

Type "# 1. The compiled team-knowledge book lives in .lore/ in your repo:"
Enter
Sleep 1s

Type "cat .lore/knowledge/README.md"
Enter
Sleep 6s

# --- Provenance: anchors are verbatim ---
Type "# 2. Every claim has a verbatim anchor — citation, not hallucination:"
Enter
Sleep 1500ms

Type "grep -A1 'anchor' .lore/knowledge/README.md | head -6"
Enter
Sleep 4s

# --- Live: querying the layer ---
Type "# 3. Any agent can pull the relevant slice on demand:"
Enter
Sleep 1500ms

Type "lore query 'billing webhook idempotency'"
Enter
Sleep 5s

# --- Trust beats: actuation health ---
Type "# 4. Usage drives lifecycle — the store stays small and fresh:"
Enter
Sleep 1500ms

Type "lore status"
Enter
Sleep 4s

# --- Close ---
Type "# github.com/srijansk/agent-lore  ·  local-first  ·  alpha"
Enter
Sleep 3s
