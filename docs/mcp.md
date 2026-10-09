# MCP server — wiring `crewlore` into your agent

`crewlore` ships an optional [MCP](https://modelcontextprotocol.io/) server that exposes the compiled knowledge layer to any MCP-speaking agent (Claude Desktop, Claude Code, Cursor, custom clients). The agent pulls the relevant slice of the team's knowledge into its context on demand, and can report back which claims helped.

## Install the optional extra

The server lives behind the `serve` extra so the base install stays light:

```bash
pipx install 'crewlore[serve]'        # fresh install
pipx inject crewlore mcp              # crewlore already installed with pipx
pip install 'crewlore[serve]'         # plain pip / a virtualenv
```

## Run the server

```bash
lore serve --repo /absolute/path/to/your/repo
```

It runs in the foreground over stdio, the standard MCP transport, and reads `.lore/` in the repo you point it at. Always pass `--repo` with an absolute path: MCP clients launch servers from their own working directory, not yours, and a server started elsewhere finds no `.lore/` and returns nothing.

Two tools are exposed:

| Tool | Arguments | Returns |
|---|---|---|
| `lore_query` | `task: str`, `limit: int = 5` | The claims most relevant to `task`, each with `id`, `statement`, `kind`, `adoption`, `scope`, `action`, and `anchors` (`ref` + verbatim `quote`) |
| `lore_feedback` | `claim_ids: list[str]`, `verdict: "influential" \| "overridden"` | Records the verdict against those claims |

Every `lore_query` call records that the returned claims were served; `lore_feedback` records whether they helped. Both feed the lifecycle: claims nobody reads decay, repeatedly overridden claims are retired, influential ones are reinforced.

## Claude Desktop

Edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows: `%APPDATA%\Claude\claude_desktop_config.json`) and add a server entry. Claude Desktop honours `command`, `args` and `env` only, so the repo goes in `args`:

```json
{
  "mcpServers": {
    "crewlore": {
      "command": "lore",
      "args": ["serve", "--repo", "/absolute/path/to/your/repo"]
    }
  }
}
```

Restart Claude Desktop. If `lore` is not on the PATH Claude Desktop uses, put the absolute path to the binary in `command` (`which lore` prints it).

## Claude Code

```bash
claude mcp add crewlore -- lore serve --repo /absolute/path/to/your/repo
```

## Cursor

Add the same JSON shape to `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` in the project, then reload the MCP servers from Cursor's settings.

## Any other client

Spawn `lore serve --repo /absolute/path` as a subprocess speaking MCP over stdio and call `lore_query(task, limit)` with the task in natural language; call `lore_feedback` once the session has acted on the result.

## What to expect in the agent's behavior

Once wired, an agent should call `lore_query` near the start of a session, right after reading the task. A well-behaved agent will:

1. Call `lore_query("<the current task in natural language>")` and read the returned claims.
2. Treat each claim as a citation, not an opinion: every claim carries anchors pointing at the line it came from, and an `adoption` of `not_adopted` means the team tried that approach and declined it.
3. Call `lore_feedback` with the ids that shaped its work (`influential`) or that it had to override (`overridden`), rather than silently ignoring a claim that did not fit.

## Troubleshooting

**`lore: command not found` after install** — run `pipx ensurepath` and restart your shell, or use the absolute path to the binary in the client's `command` field.

**The tool list does not show `lore_query`** — the client may be caching an old tool list; restart it. If it is still missing, run `lore serve --repo /absolute/path` in a terminal and check it stays running (it waits on stdin); if it exits immediately, the error is printed to stderr.

**Returns no claims** — the most common cause is a missing or wrong `--repo`, so the server is looking at the wrong directory. Then: the repo's `.lore/claims/claims.jsonl` is empty, or the query shares no vocabulary with any claim (retrieval is word overlap). Run `lore status --repo …` to see how many active claims exist, and `lore query "<your task>" --repo …` to see what the same ranking returns from the CLI.

## Privacy posture

The MCP server reads `.lore/` on local disk. It makes no outbound network calls and needs no API key: the model call happens at compile time, not at serve time. Queries are scored against locally stored claims with a deterministic word-overlap rank; the only thing that crosses a process boundary is the MCP stdio stream.
