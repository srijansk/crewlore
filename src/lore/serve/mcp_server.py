"""MCP server exposing query-time retrieval to any MCP-speaking harness.

Requires the optional `serve` extra (`pip install 'crewlore[serve]'`). This is a
thin wrapper over the tested `KnowledgeServer`; the retrieval/instrumentation
logic it exposes lives in `lore.serve.server`.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP  # optional dep; ImportError handled by the CLI

from lore.serve.server import KnowledgeServer
from lore.store import LoreStore


def build_server(store: LoreStore) -> FastMCP:
    server = KnowledgeServer(store)
    mcp = FastMCP("crewlore")

    @mcp.tool()
    def lore_query(task: str, limit: int = 5) -> list[dict]:
        """Return team-knowledge claims relevant to a task, each with verbatim anchors."""
        claims = server.query(task, limit=limit)
        return [
            {
                "id": c.id,
                "statement": c.statement,
                "kind": c.kind,
                "adoption": c.adoption,
                "scope": c.scope,
                "action": c.action,
                "anchors": [{"ref": a.ref, "quote": a.quote} for a in c.anchors],
            }
            for c in claims
        ]

    @mcp.tool()
    def lore_feedback(claim_ids: list[str], verdict: str) -> dict:
        """Record whether returned claims helped: verdict is "influential" or "overridden".

        Influential claims are reinforced; claims the session had to override
        are retired once that happens repeatedly.
        """
        if verdict == "influential":
            server.mark_influential(claim_ids)
        elif verdict == "overridden":
            server.mark_overridden(claim_ids)
        else:
            return {"error": "verdict must be 'influential' or 'overridden'"}
        return {"recorded": verdict, "claims": list(claim_ids)}

    return mcp


def run_mcp(store: LoreStore) -> None:
    build_server(store).run()
