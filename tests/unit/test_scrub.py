"""Secret scrubbing runs at ingest time so secrets never reach the LLM, the
anchors, or the committed store. The cheap half of the C3/C4 leakage gate.
"""

from datetime import datetime, timezone

from lore.schemas import NSFEvent
from lore.scrub import scrub_events, scrub_text


def test_redacts_api_key():
    out, n = scrub_text("export ANTHROPIC_API_KEY=sk-ant-api03-AbCdEf123456_xyz789TOKENvalue")
    assert "sk-ant" not in out
    assert "REDACTED" in out
    assert n >= 1


def test_redacts_aws_access_key():
    out, n = scrub_text("aws key AKIAIOSFODNN7EXAMPLE in the logs")
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert n >= 1


def test_redacts_private_key_block():
    blob = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBA...\n-----END RSA PRIVATE KEY-----"
    out, n = scrub_text(f"here is the key:\n{blob}\ndone")
    assert "PRIVATE KEY" not in out or "REDACTED" in out
    assert "MIIEowIBA" not in out
    assert n >= 1


def test_redacts_inline_secret_assignment():
    out, n = scrub_text("config: password = hunter2supersecret")
    assert "hunter2supersecret" not in out
    assert n >= 1


def test_leaves_ordinary_text_untouched():
    text = "the billing webhook fires twice in staging; dedupe on idempotency key"
    out, n = scrub_text(text)
    assert out == text
    assert n == 0


def test_scrub_events_redacts_content():
    ev = NSFEvent(
        session="s", actor="system", kind="tool_result",
        timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
        content="printed token=sk-ant-api03-LEAKED_secret_value_1234567890",
    )
    scrubbed, n = scrub_events([ev])
    assert "sk-ant" not in scrubbed[0].content
    assert n >= 1
    # other fields preserved
    assert scrubbed[0].kind == "tool_result"


def test_redacts_github_classic_pat():
    out, n = scrub_text("export GH=ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345")
    assert "ghp_aBcDe" not in out
    assert "REDACTED:github-token" in out
    assert n >= 1


def test_redacts_github_fine_grained_pat():
    out, n = scrub_text("token: github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    assert "github_pat_ABC" not in out
    assert "REDACTED:github-token" in out
    assert n >= 1


def test_redacts_google_api_key():
    out, n = scrub_text("KEY = AIzaSyA-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456")
    assert "AIzaSy" not in out
    assert "REDACTED:google-api-key" in out
    assert n >= 1


def test_redacts_slack_token():
    for raw in (
        "xoxb-1234567890-0987654321-AbCdEfGhIjKlMnOpQrStUvWx",
        "xoxp-1234567890-1234567890-1234567890-abcdef",
        "xoxa-2-AbCdEfGhIjKl",
    ):
        out, n = scrub_text(f"slack token: {raw}")
        assert raw[:8] not in out, f"slack prefix survived for {raw!r}"
        assert "REDACTED:slack-token" in out
        assert n >= 1


def test_redacts_huggingface_token():
    out, n = scrub_text("HF=hf_abcdefghijklmnopqrstuvwxyz012345")
    assert "hf_abcdefghij" not in out
    assert "REDACTED:hf-token" in out
    assert n >= 1


def test_redacts_jwt():
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    out, n = scrub_text(f"Authorization: Bearer {jwt}")
    assert "eyJhbGc" not in out
    assert "REDACTED:jwt" in out
    assert n >= 1


def test_redacts_postgres_uri_password_preserving_user_and_host():
    out, n = scrub_text("DATABASE_URL=postgres://app_user:r3al_p4ssw0rd!@db.example.com:5432/mydb")
    # password is gone…
    assert "r3al_p4ssw0rd" not in out
    # …but the surrounding URI structure survives so logs stay diagnostic.
    assert "postgres://app_user:" in out
    assert "@db.example.com:5432/mydb" in out
    assert "REDACTED:uri-password" in out
    assert n >= 1


def test_redacts_mongodb_uri_password():
    out, n = scrub_text("MONGO=mongodb://srv:s3cretP@cluster0.mongodb.net/db")
    assert "s3cretP" not in out
    assert "mongodb://srv:" in out
    assert "REDACTED:uri-password" in out
    assert n >= 1


def test_leaves_non_secret_urls_untouched():
    text = "see https://example.com/path?q=1 and postgres://localhost:5432/db (no auth)"
    out, n = scrub_text(text)
    assert out == text
    assert n == 0


def test_redacts_aws_sts_temporary_key():
    out, n = scrub_text("temp creds ASIAIOSFODNN7EXAMPLE in the env")
    assert "ASIAIOSFODNN7EXAMPLE" not in out
    assert "REDACTED:aws-key" in out
    assert n >= 1


def test_redacts_aws_secret_access_key_assignment():
    out, n = scrub_text("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    assert "wJalrXUtnFEMI" not in out
    assert n >= 1


def test_redacts_slack_config_token_xoxc():
    out, n = scrub_text("token: xoxc-1234567890-abcdefghijklmnop")
    assert "xoxc-1234567890" not in out
    assert "REDACTED:slack-token" in out
    assert n >= 1


def test_redacts_quoted_multiword_passphrase():
    out, n = scrub_text('password = "correct horse battery staple"')
    assert "correct horse battery staple" not in out
    assert n >= 1


def test_scrub_events_redacts_secret_in_tool_call_meta():
    # The high-risk case: a secret passed as a tool-call argument lands in meta,
    # not content. It must be scrubbed before the session is written to disk.
    leaky_cmd = "curl -H 'Authorization: Bearer sk-ant-api03-LEAKED_in_args_123456'"
    ev = NSFEvent(
        session="s", actor="agent", kind="tool_call",
        timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
        content="Bash",
        meta={"input": {"command": leaky_cmd}},
    )
    scrubbed, n = scrub_events([ev])
    assert n >= 1
    assert "sk-ant" not in scrubbed[0].meta["input"]["command"]
    # content (the tool name) is untouched; structure is preserved.
    assert scrubbed[0].content == "Bash"
    assert "command" in scrubbed[0].meta["input"]


def test_scrub_events_leaves_clean_meta_untouched():
    ev = NSFEvent(
        session="s", actor="agent", kind="tool_call",
        timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
        content="Bash", meta={"input": {"command": "grep webhook"}},
    )
    scrubbed, n = scrub_events([ev])
    assert n == 0
    assert scrubbed[0].meta == {"input": {"command": "grep webhook"}}
