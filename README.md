# agent-lore

> An open, local-first, harness-agnostic **compiler** that turns a team's AI-coding-agent sessions into a high-quality, versioned, plaintext tribal-knowledge layer living in the team's own git repo — and serves it back into any agent at the start of every session.

**Status:** v0.1, alpha. Building in the open. CLI command is `lore`.

## Why

Knowledge discovered inside an agent session is private by default and lost by default. The next engineer — and every future agent run — re-derives the same context, re-learns the same gotcha, re-makes a decision the team already made. `lore` captures sessions, *compiles* them (dedup, conflict-resolution, authority/recency scoring, distillation) into a shared plaintext artifact in your repo, and serves the relevant slice back to any agent. Nothing leaves your infrastructure.

The compilation quality — not the plumbing — is the product. And a knowledge layer's value is an **actuation** property, not a storage property: `lore` is built around a usage-driven loop so the knowledge layer drives better sessions instead of becoming a dumpyard of unused claims.

## Architecture

```
capture (thin adapters)  ->  compile (the moat)  ->  serve (plaintext + MCP)
       raw session             NSF -> claims            .lore/ in your repo
```

## Quickstart (target DX)

```bash
pipx install agent-lore          # or: uvx --from agent-lore lore
cd my-team-repo
lore init                        # creates .lore/, detects harness, installs session hook
lore compile                     # distills sessions -> .lore/knowledge/ + claims
lore serve                       # MCP server for query-time retrieval
git add .lore/knowledge .lore/claims && git commit
```

## License

MIT. See `LICENSE`.
