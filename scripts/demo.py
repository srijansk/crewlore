#!/usr/bin/env python3
"""End-to-end demo of agent-lore on synthetic, public-safe data — no API key.

Runs the whole loop: capture (Claude Code adapter) -> compile -> serve -> the two
success-criteria measurements (fidelity + held-out preventable-rediscovery rate).
The LLM is replaced by a small deterministic demo extractor so the demo is
reproducible offline; a real run swaps in `LLMExtractor` with a BYO key.

    uv run python scripts/demo.py        # recommended (handles env + deps)
    # or: source .venv/bin/activate && python scripts/demo.py
"""
# ruff: noqa: E402  (src-path bootstrap must run before importing `lore`)

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Make `lore` importable even without an editable install (deps still required).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

try:
    from lore.capture.adapters.claude_code import ClaudeCodeAdapter
    from lore.compile.run import run_compile
    from lore.replay import fidelity_report, replay_report
    from lore.schemas import Anchor, Claim, Provenance
    from lore.serve.server import KnowledgeServer
    from lore.store import LoreStore
except ModuleNotFoundError as exc:  # missing third-party deps (pydantic/typer/…)
    sys.exit(
        f"Missing dependency: {exc.name}. Run this demo inside the project env:\n"
        "  uv run python scripts/demo.py\n"
        "  (or: uv venv && source .venv/bin/activate && uv pip install -e '.[dev]')"
    )


class DemoExtractor:
    """Deterministic stand-in for the LLM extractor. Anchors are pulled verbatim
    from event content, so the fidelity gate passes by construction."""

    RULES = [
        ("fires twice", "gotcha",
         "Billing webhook double-fires in staging; dedupe on idempotency key.",
         "webhook-dedupe", "Dedupe on the idempotency key before processing the webhook."),
        ("postgres", "decision", "Use Postgres for the ledger.", "ledger-db",
         "Default new ledger storage to Postgres unless a decision says otherwise."),
        ("dynamo", "decision", "Use DynamoDB for the ledger.", "ledger-db", None),
        ("migration", "procedure",
         "Run migrations before deploy; never edit generated files.",
         "migrations", "Run `make migrate` before deploy; do not hand-edit migration files."),
    ]

    def extract(self, events, session_id, known_topics=None):
        out = []
        for ev in events:
            low = ev.content.lower()
            for needle, kind, statement, topic, action in self.RULES:
                if needle in low:
                    out.append(
                        Claim(
                            statement=statement, kind=kind, scope="services/billing",
                            topic=topic, action=action,
                            provenance=Provenance(
                                session=session_id, author="dev", harness="claude-code"
                            ),
                            anchors=[Anchor(
                                source_kind="transcript", ref=f"{session_id}#1", quote=ev.content
                            )],
                            observed_at=ev.timestamp,
                        )
                    )
        return out


def _raw(session, ts, role, text):
    return {"type": role, "sessionId": session, "timestamp": ts,
            "message": {"role": role, "content": text}}


# Synthetic "prior" sessions (pre-cutoff) from a fictional public web-app repo.
PRIOR_SESSIONS = {
    "ses_1": [
        _raw("ses_1", "2026-05-10T10:00:00Z", "user", "No, that's wrong."),
        _raw("ses_1", "2026-05-10T10:01:00Z", "user",
             "the billing webhook fires twice in staging, charging customers twice"),
        _raw("ses_1", "2026-05-10T10:02:00Z", "assistant",
             "Right. We decided to use Postgres for the ledger for a unique constraint."),
    ],
    "ses_2": [
        _raw("ses_2", "2026-05-11T09:00:00Z", "user",
             "Actually, run the migration before deploy or the new column is missing."),
    ],
    "ses_3": [
        _raw("ses_3", "2026-05-13T09:00:00Z", "user",
             "Actually no — we decided to use DynamoDB for the ledger instead."),
    ],
    # A trivial one-shot session: should be gated out (no claims).
    "ses_trivial": [
        _raw("ses_trivial", "2026-05-12T08:00:00Z", "user", "what does get_user() return?"),
        _raw("ses_trivial", "2026-05-12T08:00:05Z", "assistant", "It returns the user id."),
    ],
}

# Held-out "post" sessions (post-cutoff) — what actually happened next.
POST_SESSIONS = {
    "ses_post_1": [
        _raw("ses_post_1", "2026-05-25T12:00:00Z", "user",
             "why is the billing webhook firing twice again?"),
    ],
    "ses_post_2": [
        _raw("ses_post_2", "2026-05-25T13:00:00Z", "user",
             "deploy failed — a column is missing, do I need a migration?"),
    ],
    "ses_post_3": [
        _raw("ses_post_3", "2026-05-25T14:00:00Z", "user",
             "how do I configure the kubernetes ingress controller?"),  # no prior knowledge
    ],
}


def main() -> None:
    adapter = ClaudeCodeAdapter()
    with tempfile.TemporaryDirectory() as tmp:
        store = LoreStore(Path(tmp))
        store.init()

        for sid, raw in PRIOR_SESSIONS.items():
            store.write_session(sid, adapter.parse_records(raw))

        result = run_compile(store, DemoExtractor())

        print("=" * 70)
        print("COMPILED KNOWLEDGE BOOK")
        print("=" * 70)
        print((Path(tmp) / ".lore" / "knowledge" / "README.md").read_text())

        print("=" * 70)
        print("QUERY: 'billing webhook firing twice'")
        print("=" * 70)
        for c in KnowledgeServer(store).query("billing webhook firing twice"):
            print(f"  [{c.kind}] {c.statement}")
            if c.action:
                print(f"      -> {c.action}")

        transcript = "\n".join(
            e.content for sid in store.list_sessions() for e in store.load_session(sid)
        )
        fid = fidelity_report(result.claims, transcript)
        post = {sid: adapter.parse_records(raw) for sid, raw in POST_SESSIONS.items()}
        rep = replay_report([c for c in result.claims if c.status == "active"], post)

        print("=" * 70)
        print("SUCCESS CRITERIA")
        print("=" * 70)
        clean = fid.total - len(fid.defects)
        print(f"  Fidelity:                  {fid.rate:.0%} "
              f"({clean}/{fid.total} claims have verbatim-resolvable anchors)")
        print(f"  Conflicts surfaced:        {len(result.conflicts)} "
              "(Postgres vs DynamoDB on the ledger — recorded, not merged away)")
        print(f"  Preventable rediscovery:   {rep.rate:.0%} "
              f"({rep.preventable}/{rep.total} post-cutoff sessions re-derived known knowledge)")
        print()
        print("  Read: of the sessions that happened AFTER the knowledge was compiled,")
        print(f"  {rep.preventable} of {rep.total} hit something lore already knew.")


if __name__ == "__main__":
    main()
