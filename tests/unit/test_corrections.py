"""A correction is a reader's committed note that a claim is wrong or outdated and what
is true now. The claim stays, marked, wherever it is served; retrieval puts it after
uncorrected claims; nothing is archived on a reader's word alone."""

import asyncio
import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from lore.cli import app
from lore.schemas import Anchor, Claim, Correction, Provenance
from lore.serve.server import KnowledgeServer, claim_label, claim_to_dict, render_book
from lore.store import LoreStore

runner = CliRunner()


def _claim(statement, scope="services/billing", **kw):
    return Claim(
        statement=statement, kind="gotcha", scope=scope,
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote=statement)],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc), **kw,
    )


REDIS = _claim("the billing webhook key lives in Redis")
TXN = _claim("dedupe the billing webhook inside the transaction")


@pytest.fixture
def store(tmp_path):
    s = LoreStore(tmp_path)
    s.init()
    s.write_claims([REDIS, TXN])
    return s


def test_corrections_are_committed_beside_the_claims_and_appended(store):
    assert store.load_corrections() == []
    server = KnowledgeServer(store)
    first = server.correct([REDIS.id], "the key moved to the transaction in May", author="alice")
    server.correct([REDIS.id, TXN.id], "see ADR-12", author="bob")
    notes = store.load_corrections()
    assert [x.author for x in notes] == ["alice", "bob", "bob"]
    assert notes[0] == first[0] and notes[0].at is not None
    assert store.corrections_path == store.lore / "claims" / "corrections.jsonl"
    assert "corrections" not in (store.lore / ".gitignore").read_text()  # committed, not local
    by_claim = server.corrections_by_claim()
    assert [x.note for x in by_claim[REDIS.id]] == [
        "the key moved to the transaction in May", "see ADR-12",
    ]
    assert [x.note for x in by_claim[TXN.id]] == ["see ADR-12"]
    # A correction marks; it never archives or touches the usage counters.
    assert all(c.status == "active" and c.usage.times_overridden == 0 for c in store.load_claims())


def test_query_serves_corrected_claims_after_the_others_with_their_notes(store):
    server = KnowledgeServer(store)
    first, second = server.query("billing webhook")  # both match; rank decides the order
    server.correct([first.id], "the key moved to the transaction", author="alice")
    ranked = server.query("billing webhook")
    assert [c.id for c in ranked] == [second.id, first.id]  # the corrected one drops last
    payload = claim_to_dict(ranked[1], server.corrections_by_claim()[first.id])
    assert payload["corrections"][0]["note"] == "the key moved to the transaction"
    assert payload["corrections"][0]["author"] == "alice" and payload["corrections"][0]["at"]
    assert claim_to_dict(ranked[0])["corrections"] == []


def test_book_and_label_mark_corrected_claims(store):
    note = Correction(claim_id=REDIS.id, note="moved to the transaction", author="alice",
                      at=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc))
    book = render_book([REDIS, TXN], [], {REDIS.id: [note]})
    assert "**[gotcha · corrected]** the billing webhook key lives in Redis" in book
    assert "  - _corrected by alice on 2026-10-14: moved to the transaction_" in book
    assert "**[gotcha]** dedupe the billing webhook" in book
    assert claim_label(REDIS, corrected=True) == "gotcha · corrected"
    assert claim_label(_claim("x", adoption="not_adopted"), corrected=True) == (
        "gotcha · not adopted · corrected"
    )
    store.add_corrections([note])
    assert "corrected by alice" in KnowledgeServer(store).write_book()


def test_explain_carries_corrections(store):
    KnowledgeServer(store).correct([REDIS.id], "moved", author="alice")
    found = KnowledgeServer(store).explain("services/billing")
    assert [x.note for x in found.corrections[REDIS.id]] == ["moved"]
    payload = found.to_dict()
    by_id = {c["id"]: c for c in payload["claims"]}
    assert by_id[REDIS.id]["corrections"][0]["note"] == "moved"
    assert by_id[TXN.id]["corrections"] == []


def test_cli_feedback_corrected_records_a_note_and_rebuilds_the_book(store, tmp_path, monkeypatch):
    monkeypatch.setattr("lore.cli.git_user", lambda repo: "alice")
    result = runner.invoke(
        app, ["feedback", REDIS.id, "--corrected", "the key moved\nto the transaction",
              "--repo", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stdout
    assert "recorded a correction by alice on 1 claim(s)" in result.stdout
    assert store.load_corrections()[0].note == "the key moved to the transaction"  # one line
    assert "corrected by alice" in (store.lore / "knowledge" / "README.md").read_text()
    result = runner.invoke(app, ["query", "billing webhook", "--repo", str(tmp_path)])
    lines = result.stdout.splitlines()
    assert lines[0].startswith("[gotcha] (services/billing) dedupe")  # uncorrected first
    assert any(ln.startswith("[gotcha · corrected]") for ln in lines)
    assert any("!! corrected by alice on " in ln and "the key moved" in ln for ln in lines)
    result = runner.invoke(app, ["query", "billing webhook", "--repo", str(tmp_path), "--json"])
    rows = json.loads(result.stdout)
    assert rows[1]["corrections"][0]["author"] == "alice" and rows[0]["corrections"] == []
    result = runner.invoke(app, ["explain", "services/billing", "--repo", str(tmp_path)])
    assert "!! corrected by alice" in result.stdout
    result = runner.invoke(app, ["status", "--repo", str(tmp_path)])
    assert "(2 active, 1 corrected)" in result.stdout


def test_cli_feedback_insists_on_one_verdict_and_a_real_note(store, tmp_path):
    base = ["feedback", REDIS.id, "--repo", str(tmp_path)]
    for flags in ([], ["--influential", "--corrected", "x"], ["--influential", "--overridden"]):
        result = runner.invoke(app, base + flags)
        assert result.exit_code == 2 and "exactly one" in result.stdout
    result = runner.invoke(app, base + ["--corrected", "  \x1b[31m  "])
    assert result.exit_code == 2 and "needs a note" in result.stdout
    result = runner.invoke(app, base + ["--corrected", "x" * 501])
    assert result.exit_code == 2 and "needs a note" in result.stdout
    result = runner.invoke(
        app, ["feedback", "clm_nope", "--corrected", "x", "--repo", str(tmp_path)]
    )
    assert result.exit_code == 1 and "unknown claim id" in result.stdout
    assert store.load_corrections() == []


def test_mcp_feedback_accepts_corrected_with_a_note(store, monkeypatch):
    pytest.importorskip("mcp")
    from lore.serve.mcp_server import build_server

    monkeypatch.setattr("lore.serve.mcp_server.git_user", lambda repo: "alice")
    mcp = build_server(store)

    def call(**args):
        rows = asyncio.run(mcp.call_tool("lore_feedback", args))
        if isinstance(rows, tuple) and len(rows) == 2 and isinstance(rows[1], dict):
            return rows[1]
        return json.loads("".join(c.text for c in rows))

    assert "error" in call(claim_ids=[REDIS.id], verdict="corrected")
    assert "error" in call(claim_ids=[REDIS.id], verdict="corrected", note="x" * 501)
    out = call(claim_ids=[REDIS.id], verdict="corrected", note="moved to the transaction")
    assert out["recorded"] == "corrected"
    (note,) = store.load_corrections()
    assert (note.author, note.note) == ("alice", "moved to the transaction")
    rows = asyncio.run(mcp.call_tool("lore_query", {"task": "billing webhook"}))
    text = json.dumps(rows[1]) if isinstance(rows, tuple) else "".join(c.text for c in rows)
    assert "moved to the transaction" in text
