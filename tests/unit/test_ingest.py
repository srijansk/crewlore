"""Capture-from-transcripts: read Claude Code's existing on-disk session
transcripts, scrub, and write them as NSF sessions — incrementally, so this is
safe to run on a schedule. No live hook needed for MVP.
"""

import json
import os
import time
from datetime import timedelta

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


# GUARDS: the default transcript directory is THIS repo's Claude Code directory,
# never the whole ~/.claude/projects tree (which holds every project on the
# machine). Claude Code encodes the cwd by replacing every non-alphanumeric
# character with "-".
def test_claude_code_project_dir_encodes_the_repo_path(tmp_path):
    from lore.capture.ingest import claude_code_project_dir

    repo = tmp_path / "work" / "my_app.v2"
    repo.mkdir(parents=True)
    got = claude_code_project_dir(repo, projects_root=tmp_path / "projects")
    raw = str(repo.resolve()).lstrip("/")
    expected = "-" + raw.replace("/", "-").replace("_", "-").replace(".", "-")
    assert got.parent == tmp_path / "projects"
    assert got.name == expected


def test_claude_code_project_dir_defaults_under_home(tmp_path, monkeypatch):
    from pathlib import Path

    from lore.capture import ingest

    monkeypatch.setattr(ingest, "CLAUDE_PROJECTS_ROOT", tmp_path / "projects")
    got = ingest.claude_code_project_dir(tmp_path / "repo")
    assert got.parent == Path(tmp_path / "projects")


# GUARDS: a session is captured once and for good. A transcript the agent is still
# writing (a post-commit hook fires mid-session) must wait until it has settled, or
# only its first half would ever be extracted; a transcript that has not changed for
# a while is taken.
ONE_HOUR = 3600


def test_a_transcript_still_being_written_is_left_for_a_later_pass(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    _write_transcript(tdir / "settled.jsonl", [_user("No, that's wrong — use the key")])
    _write_transcript(tdir / "live.jsonl", [_user("No, that's wrong — dedupe it")])
    an_hour_ago = time.time() - ONE_HOUR
    os.utime(tdir / "settled.jsonl", (an_hour_ago, an_hour_ago))
    store = LoreStore(tmp_path / "repo")
    store.init()

    first = ingest_transcripts(store, ClaudeCodeAdapter(), tdir, settle=timedelta(minutes=10))
    assert first["ingested"] == 1 and first["settling"] == 1
    assert store.list_sessions() == ["settled"]

    os.utime(tdir / "live.jsonl", (an_hour_ago, an_hour_ago))  # the session has ended
    second = ingest_transcripts(store, ClaudeCodeAdapter(), tdir, settle=timedelta(minutes=10))
    assert second["ingested"] == 1 and second["settling"] == 0
    assert sorted(store.list_sessions()) == ["live", "settled"]


def test_without_a_settle_time_every_transcript_is_captured_at_once(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    _write_transcript(tdir / "s1.jsonl", [_user("No, that's wrong — use the key")])
    _write_transcript(tdir / "s2.jsonl", [_user("No, that's wrong — dedupe it")])
    for settle in (None, timedelta(0)):
        store = LoreStore(tmp_path / f"repo-{settle is None}")
        store.init()
        stats = ingest_transcripts(store, ClaudeCodeAdapter(), tdir, settle=settle)
        assert stats["ingested"] == 2 and stats["settling"] == 0
