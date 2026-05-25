"""MCP server exposing query-time retrieval to any MCP-speaking harness.

Requires the optional `serve` extra (`pip install 'agent-lore[serve]'`). This is a
thin wrapper over the tested `KnowledgeServer`; the retrieval/instrumentation
logic it exposes lives in `lore.serve.server`.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP  # optional dep; ImportError handled by the CLI

from lore.serve.server import KnowledgeServer
from lore.store import LoreStore


def build_server(store: LoreStore) -> FastMCP:
    server = KnowledgeServer(store)
    mcp = FastMCP("agent-lore")

    @mcp.tool()
    def lore_query(task: str, limit: int = 5) -> list[dict]:
        """Return team tribal-knowledge claims relevant to a task, with anchors."""
        claims = server.query(task, limit=limit)
        return [
            {
                "statement": c.statement,
                "kind": c.kind,
                "scope": c.scope,
                "action": c.action,
                "anchors": [{"ref": a.ref, "quote": a.quote} for a in c.anchors],
            }
            for c in claims
        ]

    return mcp


def run_mcp(store: LoreStore) -> None:
    build_server(store).run()
