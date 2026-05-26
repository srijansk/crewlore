"""Capture-from-transcripts: read Claude Code's existing on-disk session
transcripts, scrub, and write them as NSF sessions — incrementally, so this is
safe to run on a schedule. No live hook needed for MVP.
"""

import json

from lore.capture.adapters.claude_code import ClaudeCodeAdapter
from lore.capture.ingest import discover_transcripts, ingest_transcripts
from lore.store import LoreStore


def _write_transcript(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records))


def _user(text, ts="2026-05-19T10:00:00Z"):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}


def test_discover_finds_jsonl_recursively(tmp_path):
    (tmp_path / "projA").mkdir()
    (tmp_path / "projB").mkdir()
    _write_transcript(tmp_path / "projA" / "s1.jsonl", [_user("hi")])
    _write_transcript(tmp_path / "projB" / "s2.jsonl", [_user("yo")])
    found = discover_transcripts(tmp_path)
    assert len(found) == 2


def test_ingest_writes_sessions(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    _write_transcript(tdir / "s1.jsonl", [_user("No, that's wrong — use the idempotency key")])
    store = LoreStore(tmp_path / "repo")
    store.init()

    stats = ingest_transcripts(store, ClaudeCodeAdapter(), tdir)
    assert stats["ingested"] == 1
    assert "s1" in store.list_sessions()
    assert store.load_session("s1")[0].content.startswith("No,")


def test_ingest_is_incremental(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    _write_transcript(tdir / "s1.jsonl", [_user("first session")])
    store = LoreStore(tmp_path / "repo")
    store.init()

    first = ingest_transcripts(store, ClaudeCodeAdapter(), tdir)
    second = ingest_transcripts(store, ClaudeCodeAdapter(), tdir)
    assert first["ingested"] == 1
    assert second["ingested"] == 0  # already captured


def test_ingest_scrubs_secrets_before_storing(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    _write_transcript(
        tdir / "s1.jsonl",
        [_user("here is the key sk-ant-api03-SECRET_value_0123456789abcd to use")],
    )
    store = LoreStore(tmp_path / "repo")
    store.init()

    stats = ingest_transcripts(store, ClaudeCodeAdapter(), tdir)
    stored = store.load_session("s1")[0].content
    assert "sk-ant" not in stored
    assert stats["redactions"] >= 1


def test_ingest_skips_unparseable_file(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    (tdir / "broken.jsonl").write_text("this is not json\n{also bad")
    _write_transcript(tdir / "good.jsonl", [_user("real session content")])
    store = LoreStore(tmp_path / "repo")
    store.init()

    stats = ingest_transcripts(store, ClaudeCodeAdapter(), tdir)
    assert stats["ingested"] == 1
    assert store.list_sessions() == ["good"]
