"""The MCP surface exposes retrieval AND feedback, so an agent can close the
actuation loop by itself. Requires the optional `mcp` extra (installed in dev)."""

import asyncio
import json
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


def test_query_tool_tells_the_agent_results_are_evidence(tmp_path):
    from lore.serve.mcp_server import build_server

    tools = asyncio.run(build_server(_store(tmp_path)).list_tools())
    description = next(t.description for t in tools if t.name == "lore_query")
    assert "evidence" in description and "instructions" in description


def test_query_payload_names_the_author_of_each_anchor(tmp_path):
    import json

    from lore.serve.mcp_server import build_server

    store = LoreStore(tmp_path)
    store.init()
    store.write_claims([
        Claim(
            statement="keep the billing idempotency key in the transaction", kind="decision",
            scope="services/billing",
            provenance=Provenance(session="pr_acme__billing__42", author="a", harness="github-pr"),
            anchors=[
                Anchor(source_kind="file", ref="webhook.py:88", quote="inside the transaction",
                       actor="user", login="reviewer", association="member"),
                Anchor(source_kind="transcript", ref="old#event-1", quote="legacy"),
            ],
            observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        )
    ])
    rows = asyncio.run(build_server(store).call_tool("lore_query", {"task": "billing key"}))
    text = "".join(getattr(c, "text", "") for c in (rows[0] if isinstance(rows, tuple) else rows))
    payload = json.loads(text)
    anchors = payload[0]["anchors"] if isinstance(payload, list) else payload["anchors"]
    assert anchors[0]["login"] == "reviewer" and anchors[0]["association"] == "member"
    assert anchors[0]["actor"] == "user"
    assert anchors[1] == {
        "ref": "old#event-1", "quote": "legacy", "actor": None, "login": None, "association": None,
    }


def _payload(rows):
    """The tool result as data: structured content when the server provides it (one
    object per call, whatever the shape), else the text blocks parsed one by one."""
    if isinstance(rows, tuple) and len(rows) == 2 and isinstance(rows[1], dict):
        structured = rows[1]
        return structured["result"] if set(structured) == {"result"} else structured
    blocks = rows[0] if isinstance(rows, tuple) else rows
    items = [json.loads(c.text) for c in blocks if getattr(c, "text", "")]
    return items[0] if len(items) == 1 else items


def test_query_tool_payload_is_the_shared_claim_shape(tmp_path):
    from lore.serve.mcp_server import build_server
    from lore.serve.server import claim_to_dict

    store = _store(tmp_path)
    rows = asyncio.run(build_server(store).call_tool("lore_query", {"task": "billing webhook"}))
    row = _payload(rows)
    row = row[0] if isinstance(row, list) else row
    expected = claim_to_dict(store.load_claims()[0])
    assert set(row) == set(expected) and row["anchors"] == expected["anchors"]


def test_explain_tool_answers_refuses_ambiguity_and_keeps_one_shape(tmp_path):
    from lore.serve.mcp_server import build_server

    store = _store(tmp_path)
    mcp = build_server(store)
    assert "lore_explain" in {t.name for t in asyncio.run(mcp.list_tools())}
    answer = _payload(asyncio.run(mcp.call_tool("lore_explain", {"scope": "services/billing"})))
    assert answer["scope"] == "services/billing" and len(answer["claims"]) == 1
    assert set(answer) == {"scope", "claims", "conflicts", "ambiguous", "narrower"}
    miss = _payload(asyncio.run(mcp.call_tool("lore_explain", {"scope": "frontend"})))
    assert miss["scope"] is None and miss["claims"] == [] and miss["ambiguous"] == []
    assert store.load_claims()[0].usage.times_served == 1  # the answer counted, the miss did not
    # The tool declares its output, so clients get structured content, not only text.
    explain_tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == "lore_explain")
    assert explain_tool.outputSchema is not None
    store.write_claims(store.load_claims() + [
        Claim(
            statement="rotate auth tokens hourly", kind="procedure", scope="services/auth",
            provenance=Provenance(session="s", author="a", harness="claude-code"),
            anchors=[Anchor(source_kind="transcript", ref="s#event-2", quote="hourly")],
            observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        )
    ])
    ambiguous = _payload(asyncio.run(mcp.call_tool("lore_explain", {"scope": "services"})))
    assert ambiguous["scope"] is None
    assert ambiguous["ambiguous"] == ["services/auth", "services/billing"]
