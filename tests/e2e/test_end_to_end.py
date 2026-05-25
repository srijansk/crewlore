"""End-to-end: capture (Claude Code adapter) -> compile -> serve (instrumented
query) -> actuation lifecycle -> held-out replay metric. Real components
throughout; only the LLM is replaced by a deterministic demo extractor so the
whole loop runs offline and produces real numbers.
"""

from datetime import datetime, timedelta, timezone

from lore.actuation import apply_lifecycle
from lore.capture.adapters.claude_code import ClaudeCodeAdapter
from lore.compile.run import run_compile
from lore.replay import fidelity_report, replay_report
from lore.schemas import Anchor, Claim, Provenance
from lore.serve.server import KnowledgeServer
from lore.store import LoreStore


class DemoExtractor:
    """Deterministic stand-in for the LLM. Emits claims with verbatim anchors
    pulled straight from event content, so fidelity holds by construction."""

    RULES = [
        ("fires twice", "gotcha", "Billing webhook double-fires; dedupe on idempotency key.",
         "webhook-dedupe", "Dedupe on the idempotency key before processing."),
        ("postgres", "decision", "Use Postgres for the ledger.", "ledger-db", None),
        ("dynamo", "decision", "Use DynamoDB for the ledger.", "ledger-db", None),
    ]

    def extract(self, events, session_id):
        claims = []
        for ev in events:
            low = ev.content.lower()
            for needle, kind, statement, topic, action in self.RULES:
                if needle in low:
                    claims.append(
                        Claim(
                            statement=statement, kind=kind, scope="services/billing",
                            topic=topic, action=action,
                            provenance=Provenance(
                                session=session_id, author="dev", harness="claude-code"
                            ),
                            anchors=[Anchor(
                                source_kind="transcript",
                                ref=f"{session_id}#1",
                                quote=ev.content,
                            )],
                            observed_at=ev.timestamp,
                        )
                    )
        return claims


def _raw(session, ts, role, text):
    return {
        "type": role,
        "sessionId": session,
        "timestamp": ts,
        "message": {"role": role, "content": text},
    }


def test_full_loop_capture_compile_serve_actuate_replay(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    adapter = ClaudeCodeAdapter()

    # --- capture two prior sessions with friction signals ---
    s1 = [
        _raw("ses_1", "2026-05-10T10:00:00Z", "user", "No, that's wrong."),
        _raw("ses_1", "2026-05-10T10:01:00Z", "user", "the billing webhook fires twice in staging"),
        _raw("ses_1", "2026-05-10T10:02:00Z", "assistant", "Right — we decided to use Postgres."),
    ]
    s2 = [
        _raw("ses_2", "2026-05-11T09:00:00Z", "user", "No, use Dynamo instead — we decided that."),
    ]
    store.write_session("ses_1", adapter.parse_records(s1))
    store.write_session("ses_2", adapter.parse_records(s2))

    # --- compile ---
    result = run_compile(store, DemoExtractor())
    assert len(result.claims) >= 2
    # Postgres vs Dynamo on the same topic -> a recorded conflict, not a silent merge.
    assert len(result.conflicts) == 1
    book = (tmp_path / ".lore" / "knowledge" / "README.md").read_text()
    assert "Conflicts" in book

    # --- serve: query instruments usage; influence feedback ---
    server = KnowledgeServer(store)
    hits = server.query("billing webhook firing twice")
    assert hits and any("double-fires" in c.statement for c in hits)
    served = store.load_claims()
    assert any(c.usage.times_served > 0 for c in served)
    server.mark_influential([hits[0].id])

    # --- fidelity: every anchor resolves verbatim against the captured transcript ---
    transcript = "\n".join(
        e.content for sid in store.list_sessions() for e in store.load_session(sid)
    )
    fid = fidelity_report(store.load_claims(), transcript)
    assert fid.rate == 1.0 and fid.defects == []

    # --- actuation: lifecycle keeps the active set from growing ---
    before_active = sum(c.status == "active" for c in store.load_claims())
    after = apply_lifecycle(
        store.load_claims(), now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        max_unused_age=timedelta(days=30),
    )
    store.write_claims(after)
    assert sum(c.status == "active" for c in after) <= before_active

    # --- held-out replay: a later session re-derives known knowledge -> preventable ---
    post = {"ses_post": adapter.parse_records([
        _raw("ses_post", "2026-05-25T12:00:00Z", "user",
             "why does the billing webhook fire twice again?"),
    ])}
    active_prior = [c for c in store.load_claims() if c.status == "active"]
    rep = replay_report(active_prior, post)
    assert rep.preventable == 1
    assert rep.rate == 1.0
