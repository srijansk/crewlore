# Demo materials

Reproducible artifacts for showing `agent-lore` to other people — the README hero asciinema, the conference live-demo arc, and the playbook for capturing the real session data that backs both.

## Files

| File | What it's for |
|---|---|
| [`conference-runbook.md`](conference-runbook.md) | The 6-minute live-demo arc: scene-by-scene timings, speaker notes, Q&A prep, backup plan, rehearsal checklist. |
| [`capture-playbook.md`](capture-playbook.md) | How to gather real Claude Code sessions on the demo target repo over ~7 days so the demo runs on real data, not synthetic. |
| [`candidate-tasks.md`](candidate-tasks.md) | The curated shortlist of open `pydantic/pydantic-ai` issues — pre-selected for claim-type diversity and a paired conflict moment. |
| [`session-briefs.md`](session-briefs.md) | Per-issue cheat sheet: plain-English explanation, the prompt to use, what the session should land on, and **predicted claims you can grade `lore` against without needing deep pydantic-ai expertise**. **Start here when capturing.** |
| [`recording.tape`](recording.tape) | A [charmbracelet/vhs](https://github.com/charmbracelet/vhs) tape script that renders the README hero asciinema/GIF. |

## Reproducing the README hero asciinema

```bash
brew install vhs                          # one-time
vhs docs/demo/recording.tape              # renders docs/assets/demo.gif
git add docs/assets/demo.gif && git commit -m "docs: refresh hero demo"
```

The tape is deterministic and uses the bundled offline demo, so re-recording it requires no API key.

## Reproducing the conference live demo on your own machine

Follow [`capture-playbook.md`](capture-playbook.md) to capture sessions, then walk through [`conference-runbook.md`](conference-runbook.md) in your terminal. The runbook calls out which moments are live (deterministic) and which are pre-staged (LLM-dependent).

## Why both?

The asciinema is the **always-available, zero-network proof** of what `agent-lore` does — embedded in the README and shown to anyone who finds the repo. The conference live demo is the **on-stage version** with the real-repo headline number; it also acts as the testing ground that surfaces real-data bugs before they reach a public audience.
