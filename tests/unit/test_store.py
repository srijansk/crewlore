from datetime import datetime, timezone

from lore.schemas import Anchor, Claim, Conflict, NSFEvent, Provenance
from lore.store import LoreStore


def _claim(statement, kind="gotcha", scope="services/billing"):
    return Claim(
        statement=statement,
        kind=kind,
        scope=scope,
        provenance=Provenance(session="ses_1", author="alice", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="ses_1#turn-42", quote="it fires twice")],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


def test_init_creates_layout_and_gitignores_raw_sessions(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    assert (tmp_path / ".lore" / "claims").is_dir()
    assert (tmp_path / ".lore" / "knowledge").is_dir()
    assert (tmp_path / ".lore" / "sessions").is_dir()
    assert (tmp_path / ".lore" / "config.yaml").is_file()
    # Raw sessions must never be committed.
    gitignore = (tmp_path / ".lore" / ".gitignore").read_text()
    assert "sessions/" in gitignore


def test_load_claims_is_empty_before_any_write(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    assert store.load_claims() == []


def test_write_and_load_claims_round_trip(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    claims = [_claim("dedupe on idempotency key"), _claim("staging double-fires")]
    store.write_claims(claims)
    loaded = store.load_claims()
    assert sorted(c.id for c in loaded) == sorted(c.id for c in claims)
    assert {c.statement for c in loaded} == {c.statement for c in claims}


def test_claims_persist_one_json_object_per_line(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    claims = [_claim("a"), _claim("b"), _claim("c")]
    store.write_claims(claims)
    lines = (tmp_path / ".lore" / "claims" / "claims.jsonl").read_text().splitlines()
    assert len([ln for ln in lines if ln.strip()]) == 3


def test_write_is_idempotent_and_order_stable(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    claims = [_claim("c"), _claim("a"), _claim("b")]
    store.write_claims(claims)
    first = (tmp_path / ".lore" / "claims" / "claims.jsonl").read_text()
    store.write_claims(list(reversed(claims)))  # different input order
    second = (tmp_path / ".lore" / "claims" / "claims.jsonl").read_text()
    assert first == second  # stable, sorted output -> clean git diffs/merges


def test_conflicts_round_trip(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    conflicts = [
        Conflict(
            scope="services/billing",
            claim_ids=["clm_aaa", "clm_bbb"],
            reason="disagree on dedupe key",
            detected_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )
    ]
    store.write_conflicts(conflicts)
    loaded = store.load_conflicts()
    assert [c.id for c in loaded] == [c.id for c in conflicts]


def test_list_sessions_returns_captured_ids(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    ev = NSFEvent(
        session="x", actor="user", kind="user_message",
        timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc), content="hi",
    )
    store.write_session("ses_a", [ev])
    store.write_session("ses_b", [ev])
    assert sorted(store.list_sessions()) == ["ses_a", "ses_b"]


def test_session_capture_round_trips_as_nsf(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    events = [
        NSFEvent(
            session="ses_7",
            actor="user",
            kind="user_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content="why does it fire twice?",
        )
    ]
    store.write_session("ses_7", events)
    loaded = store.load_session("ses_7")
    assert loaded == events
    assert (tmp_path / ".lore" / "sessions" / "ses_7.jsonl").is_file()
