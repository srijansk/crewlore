"""A correction is a reader's committed note that a claim is wrong or outdated and what
is true now. The claim stays, marked, wherever it is served; retrieval puts it after
uncorrected claims; nothing is archived on a reader's word alone."""

import asyncio
import json
import re
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
    assert "claims/corrections.jsonl merge=union" in (store.lore / ".gitattributes").read_text()
    assert store.corrections_path.read_text().count("\n") == 3  # one line per note, appended
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
    assert "  - **corrected on 2026-10-14 by alice: moved to the transaction**" in book
    assert "**[gotcha]** dedupe the billing webhook" in book
    assert claim_label(REDIS, corrected=True) == "gotcha · corrected"
    assert claim_label(_claim("x", adoption="not_adopted"), corrected=True) == (
        "gotcha · not adopted · corrected"
    )
    store.add_corrections([note])
    assert "by alice: moved to the transaction" in KnowledgeServer(store).write_book()


def test_book_renders_notes_and_authors_as_inert_markdown():
    note = Correction(
        claim_id=REDIS.id, author="alice on 2020-01-01: forged author note",
        note="renamed to WEBHOOK_KEY_, see [ADR-12](https://evil.example) <img src=x> *now*",
        at=datetime(2026, 10, 14, tzinfo=timezone.utc), via="mcp",
    )
    book = render_book([REDIS], [], {REDIS.id: [note]})
    (line,) = [ln for ln in book.splitlines() if "corrected on" in ln]
    assert line.startswith("  - **corrected on 2026-10-14 by alice on 2020-01-01: forged author")
    assert " via MCP: renamed to WEBHOOK\\_KEY\\_, see \\[ADR-12\\](https://evil.example) " in line
    assert "\\<img src=x\\> \\*now\\***" in line
    inner = line[len("  - **") : -len("**")]
    assert re.search(r"(?<!\\)[\[\]<>*_~]", inner) is None  # every active character escaped
    struck = Correction(claim_id=REDIS.id, note="~~do not~~ use C:\\Users", author="a")
    (line,) = [ln for ln in render_book([REDIS], [], {REDIS.id: [struck]}).splitlines()
               if "corrected by" in ln]
    assert "\\~\\~do not\\~\\~ use C:\\\\Users" in line


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
    assert store.load_corrections()[0].via == "cli"
    assert "by alice: the key moved" in (store.lore / "knowledge" / "README.md").read_text()
    result = runner.invoke(app, ["query", "billing webhook", "--repo", str(tmp_path)])
    lines = result.stdout.splitlines()
    assert lines[0].startswith("[gotcha] (services/billing) dedupe")  # uncorrected first
    assert any(ln.startswith("[gotcha · corrected]") for ln in lines)
    assert any("!! corrected on " in ln and "by alice: the key moved" in ln for ln in lines)
    result = runner.invoke(app, ["query", "billing webhook", "--repo", str(tmp_path), "--json"])
    rows = json.loads(result.stdout)
    assert rows[1]["corrections"][0]["author"] == "alice" and rows[0]["corrections"] == []
    result = runner.invoke(app, ["explain", "services/billing", "--repo", str(tmp_path)])
    assert "!! corrected on " in result.stdout and "by alice: the key moved" in result.stdout
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
    archived = _claim("an old claim", status="archived")
    store.write_claims([REDIS, TXN, archived])
    result = runner.invoke(
        app, ["feedback", archived.id, "--corrected", "x", "--repo", str(tmp_path)]
    )
    assert result.exit_code == 1 and "archived" in result.stdout
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

    assert "unknown claim id" in call(claim_ids=["clm_nope"], verdict="influential")["error"]
    assert "error" in call(claim_ids=[REDIS.id], verdict="corrected")
    assert "error" in call(claim_ids=[REDIS.id], verdict="corrected", note="x" * 501)
    bad = call(claim_ids=["clm_nope"], verdict="corrected", note="x")
    assert "unknown claim id" in bad["error"]
    assert "no claim ids" in call(claim_ids=[], verdict="corrected", note="x")["error"]
    out = call(claim_ids=[REDIS.id, REDIS.id], verdict="corrected", note="moved to the transaction")
    assert out["recorded"] == "corrected" and out["claims"] == [REDIS.id]
    assert out["written_to"].endswith("corrections.jsonl") and "commit" in out["next"]
    (note,) = store.load_corrections()  # duplicate ids make one note
    assert (note.author, note.note, note.via) == ("alice", "moved to the transaction", "mcp")
    rows = asyncio.run(mcp.call_tool("lore_query", {"task": "billing webhook"}))
    text = json.dumps(rows[1]) if isinstance(rows, tuple) else "".join(c.text for c in rows)
    assert "moved to the transaction" in text


def test_concurrent_writers_all_keep_their_notes(store):
    import concurrent.futures

    def write(i):
        LoreStore(store.root).add_corrections(
            [Correction(claim_id=REDIS.id, note=f"note {i}", author="w")]
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(200)))
    notes = store.load_corrections()
    assert sorted(int(x.note.split()[1]) for x in notes) == list(range(200))


def test_an_unreadable_line_is_skipped_not_fatal(store, capsys):
    KnowledgeServer(store).correct([REDIS.id], "good note", author="alice")
    with open(store.corrections_path, "a") as handle:
        handle.write("<<<<<<< HEAD\n")
    with open(store.corrections_path, "a") as handle:
        handle.write("\n" + Correction(claim_id=REDIS.id, note="x", author="a", via="cli")
                     .model_dump_json().replace('"cli"', '"telepathy"') + "\n")
    notes = store.load_corrections()
    assert [x.note for x in notes] == ["good note"]  # the bad line and the unknown origin
    err = capsys.readouterr().err
    assert "skipping unreadable line(s) 2, 4 of" in err  # the file's own line numbers
    store.load_corrections()
    assert capsys.readouterr().err == ""  # reported once per process, not on every read
    assert KnowledgeServer(store).query("billing webhook")  # retrieval still works
    assert "good note" in KnowledgeServer(store).write_book()


def test_appending_after_a_hand_edit_without_a_trailing_newline_keeps_both(store):
    KnowledgeServer(store).correct([REDIS.id], "first", author="alice")
    raw = store.corrections_path.read_bytes().rstrip(b"\n")
    store.corrections_path.write_bytes(raw)  # an editor that drops the final newline
    KnowledgeServer(store).correct([TXN.id], "second", author="bob")
    assert [x.note for x in store.load_corrections()] == ["first", "second"]
    assert store.corrections_path.read_bytes().endswith(b"\n")


def test_gitattributes_lines_are_not_duplicated_for_spacing_variants(store):
    attrs = store.lore / ".gitattributes"
    attrs.write_text("claims/corrections.jsonl   merge=union\n*.png binary\n")
    store.ensure_gitattributes()
    assert attrs.read_text() == "claims/corrections.jsonl   merge=union\n*.png binary\n"


def test_corrected_claims_are_demoted_before_the_page_is_cut(tmp_path):
    s = LoreStore(tmp_path)
    s.init()
    a = _claim("billing webhook key in redis, first")
    b = _claim("billing webhook key in the transaction, second")
    c = _claim("billing webhook key retried, third")
    s.write_claims([a, b, c])
    server = KnowledgeServer(s)
    top = server.query("billing webhook key", limit=3)[0]
    server.correct([top.id], "wrong now", author="alice")
    page = server.query("billing webhook key", limit=2)
    assert top.id not in {x.id for x in page}  # both uncorrected claims come first
    assert server.query("billing webhook key", limit=3)[-1].id == top.id


def test_status_reports_notes_whose_claims_are_gone(store, tmp_path):
    store.add_corrections([Correction(claim_id="clm_000000000000", note="orphan", author="a")])
    result = runner.invoke(app, ["status", "--repo", str(tmp_path)])
    assert "1 correction(s) refer to claims no longer in the store" in result.stdout
    assert "(2 active, 0 corrected)" in result.stdout
