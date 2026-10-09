"""The MCP surface exposes retrieval AND feedback, so an agent can close the
actuation loop by itself. Requires the optional `mcp` extra (installed in dev)."""

import asyncio
from datetime import datetime, timezone

import pytest

from lore.schemas import Anchor, Claim, Provenance
from lore.store import LoreStore

pytest.importorskip("mcp")


def _store(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims([
        Claim(
            statement="dedupe billing webhook on idempotency key", kind="gotcha",
            scope="services/billing",
            provenance=Provenance(session="s", author="a", harness="claude-code"),
            anchors=[Anchor(source_kind="transcript", ref="s#event-1", quote="fires twice")],
            observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        )
    ])
    return store


def test_mcp_exposes_query_and_feedback_tools(tmp_path):
    from lore.serve.mcp_server import build_server

    mcp = build_server(_store(tmp_path))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"lore_query", "lore_feedback"} <= names


def test_query_results_carry_ids_and_feedback_is_recorded(tmp_path):
    from lore.serve.mcp_server import build_server

    store = _store(tmp_path)
    mcp = build_server(store)
    rows = asyncio.run(mcp.call_tool("lore_query", {"task": "billing webhook", "limit": 5}))
    # FastMCP returns content blocks; find the structured payload in whichever shape it uses.
    text = "".join(getattr(c, "text", "") for c in (rows[0] if isinstance(rows, tuple) else rows))
    cid = store.load_claims()[0].id
    assert cid in text and "adoption" in text

    asyncio.run(mcp.call_tool("lore_feedback", {"claim_ids": [cid], "verdict": "influential"}))
    assert store.load_claims()[0].usage.times_influential == 1
