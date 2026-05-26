"""auto_compile is the unit of automation: ingest new transcripts -> compile ->
prune (actuation lifecycle) -> re-render the book. `lore watch` just calls this
on an interval, so the human never has to remember to compile.
"""

import json
from datetime import datetime, timezone

from lore.capture.adapters.claude_code import ClaudeCodeAdapter
from lore.compile.run import auto_compile
from lore.schemas import Anchor, Claim, Provenance
from lore.store import LoreStore


class DemoExtractor:
    def extract(self, events, session_id, known_topics=None):
        out = []
        for ev in events:
            if "fires twice" in ev.content.lower():
                out.append(
                    Claim(
                        statement="Billing webhook double-fires; dedupe on idempotency key.",
                        kind="gotcha", scope="services/billing", topic="webhook-dedupe",
                        action="Dedupe on idempotency key before processing.",
                        provenance=Provenance(
                            session=session_id, author="dev", harness="claude-code"
                        ),
                        anchors=[
                            Anchor(
                                source_kind="transcript",
                                ref=f"{session_id}#1",
                                quote=ev.content,
                            )
                        ],
                        observed_at=ev.timestamp,
                    )
                )
        return out


def _transcript(tdir, name, text):
    rec = {"type": "user", "timestamp": "2026-05-19T10:00:00Z",
           "message": {"role": "user", "content": text}}
    (tdir / f"{name}.jsonl").write_text(json.dumps(rec))


def test_auto_compile_ingests_compiles_prunes_and_writes_book(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    _transcript(tdir, "s1", "No, that's wrong — the billing webhook fires twice in staging")
    store = LoreStore(tmp_path / "repo")
    store.init()

    stats = auto_compile(store, DemoExtractor(), ClaudeCodeAdapter(), tdir)

    assert stats["ingested"] == 1
    assert stats["claims"] == 1
    assert len(store.load_claims()) == 1
    book = (tmp_path / "repo" / ".lore" / "knowledge" / "README.md").read_text()
    assert "double-fires" in book


def test_auto_compile_is_idempotent_across_runs(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    _transcript(tdir, "s1", "No — the billing webhook fires twice")
    store = LoreStore(tmp_path / "repo")
    store.init()

    first = auto_compile(store, DemoExtractor(), ClaudeCodeAdapter(), tdir)
    second = auto_compile(store, DemoExtractor(), ClaudeCodeAdapter(), tdir)
    assert first["claims"] == 1
    assert second["claims"] == 1  # no duplication
    assert second["ingested"] == 0  # nothing new to ingest


def test_auto_compile_does_not_grow_active_set_when_idle(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    _transcript(tdir, "s1", "No — the billing webhook fires twice")
    store = LoreStore(tmp_path / "repo")
    store.init()
    auto_compile(store, DemoExtractor(), ClaudeCodeAdapter(), tdir)
    active_after_1 = sum(c.status == "active" for c in store.load_claims())
    auto_compile(store, DemoExtractor(), ClaudeCodeAdapter(), tdir)
    active_after_2 = sum(c.status == "active" for c in store.load_claims())
    assert active_after_2 <= active_after_1


def test_auto_compile_stats_shape(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    store = LoreStore(tmp_path / "repo")
    store.init()
    stats = auto_compile(store, DemoExtractor(), ClaudeCodeAdapter(), tdir)
    assert set(stats) >= {"discovered", "ingested", "redactions", "claims", "active", "conflicts"}
    assert stats["ingested"] == 0  # empty transcript dir
    assert isinstance(datetime.now(timezone.utc), datetime)  # sanity
