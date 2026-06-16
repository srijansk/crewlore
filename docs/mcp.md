# MCP server — wiring `crewlore` into your agent

`crewlore` ships an optional [MCP](https://modelcontextprotocol.io/) server that exposes the compiled knowledge layer as a query tool. Any MCP-speaking agent (Claude Desktop, Cursor, Continue, custom MCP clients) can pull the relevant slice of your team's compiled knowledge into its context on demand.

## Install the optional extra

The MCP server lives behind the `[serve]` extra so the base install stays light:

```bash
pipx install 'crewlore[serve]'
# or, if installed without the extra:
pipx inject crewlore 'crewlore[serve]'
```

## Run the server

From the root of a repo that has `.lore/` initialized:

```bash
lore serve --mcp
```

It runs in the foreground over stdio (the standard MCP transport). The server exposes one tool:

| Tool | Args | Returns |
|---|---|---|
| `lore_query` | `task: str`, `limit: int = 5` | List of compiled claims relevant to `task`, each with `statement`, `kind`, `scope`, `action`, and `anchors` |

Every call is *instrumented*: the claims returned have their `times_served` counter bumped, which feeds the actuation loop (unused claims decay; reinforced claims stay fresh).

## Wire it into Claude Desktop

Edit your `mcp.json` (path varies by OS — `~/Library/Application Support/Claude/mcp.json` on macOS, `%APPDATA%\Claude\mcp.json` on Windows) and add a server entry:

```json
{
  "mcpServers": {
    "crewlore": {
      "command": "lore",
      "args": ["serve", "--mcp"],
      "cwd": "/absolute/path/to/your/repo"
    }
  }
}
```

Restart Claude Desktop. In a new conversation, the `lore_query` tool will appear in the tools list, and Claude will call it when it judges that team-knowledge context is relevant to the task.

## Wire it into Cursor

Cursor's MCP config lives in **Settings → Features → Model Context Protocol → Edit `mcp.json`**. Same JSON shape as Claude Desktop. After saving, restart Cursor's MCP runtime.

## Wire it into a custom client

Any client that speaks MCP over stdio works. Spawn `lore serve --mcp` as a subprocess with `cwd` set to the target repo's root, then use your MCP client library to invoke `lore_query(task, limit)`.

## What to expect in the agent's behavior

Once wired, the agent should call `lore_query` near the start of a session — typically right after reading the task. A well-tuned agent will:

1. Call `lore_query("<the current task in natural language>")` and review the returned claims.
2. Treat returned claims as *citations*, not opinions — every claim has an `anchors` list pointing back to the session line it came from.
3. If a claim turns out to be inapplicable or wrong for the current context, call `lore_query` with a refined task description rather than dismissing the claim silently.

The instrumentation closes the loop: the more the layer is *used*, the more its claims get reinforced and ranked; the less a claim is used, the faster it decays.

## Troubleshooting

**`lore: command not found` after install** — `pipx ensurepath` and restart your shell, or use the absolute path to the binary in `mcp.json`'s `command` field.

**The tool list doesn't show `lore_query`** — your client may be caching the previous tool list. Restart the client. If still not listed, run `lore serve --mcp` manually in a terminal and verify it stays running (i.e. it's waiting on stdin); if it exits immediately, the error prints to stderr.

**Returns empty claims** — the repo's `.lore/claims/claims.jsonl` is empty or your query doesn't overlap with any compiled claim's scope/statement/topic vocabulary. Run `lore status` to see how many active claims you have, and `lore query "<your task>"` to check what the same ranking returns from the CLI.

## Privacy posture

The MCP server reads from `.lore/` on local disk. It does **not** make outbound network calls and does not require an API key — the LLM call happens at *compile* time, not *serve* time. Queries from the agent are scored against locally-stored claims with a deterministic token-overlap rank; the only thing that crosses a process boundary is the MCP stdio.
