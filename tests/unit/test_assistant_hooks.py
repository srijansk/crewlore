"""`lore install --hooks` puts two Claude Code hooks into the settings file, and
`lore claude-hook` answers them: the claims for the edited file's scope, once per scope
per session, or the claims relevant to a prompt, as facts. Silence everywhere else."""

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lore.assistant_hooks import (
    HOOK_COMMAND,
    HOOK_EVENTS,
    MAX_CLAIMS_PER_EVENT,
    handle,
    install_hooks,
    parse_event,
    run_from_stdin,
    scopes_covering,
    settings_path,
    uninstall_hooks,
)
from lore.assistants import AssistantsError, install, uninstall
from lore.cli import app
from lore.schemas import Anchor, Claim, Provenance
from lore.store import LoreStore

runner = CliRunner()


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


def _claim(statement, scope, *, kind="gotcha", adoption="current", action=None, status="active"):
    return Claim(
        statement=statement, kind=kind, scope=scope, adoption=adoption, action=action,
        status=status, provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote=statement)],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    store = LoreStore(root)
    store.init()
    store.write_claims(
        [
            _claim("dedupe billing webhook on idempotency key", "services/billing",
                   action="dedupe on the key"),
            _claim("Redis for the idempotency key was tried and not adopted", "services/billing",
                   kind="decision", adoption="not_adopted",
                   action="keep the key inside the transaction"),
            _claim("rotate auth tokens hourly", "services/auth"),
            _claim("webhook deliveries retry three times", "services/billing/webhooks"),
            _claim("run make lint before pushing", "."),
            _claim("an archived billing claim", "services/billing", status="archived"),
        ]
    )
    return root


def _edit(repo, path, session="ses-1"):
    return {
        "hook_event_name": "PreToolUse", "session_id": session, "cwd": str(repo),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(repo / path), "old_string": "a", "new_string": "b"},
    }


def _prompt(repo, text, session="ses-1"):
    return {
        "hook_event_name": "UserPromptSubmit", "session_id": session, "cwd": str(repo),
        "prompt": text,
    }


def _context(out):
    assert set(out) == {"hookSpecificOutput"}
    assert "permissionDecision" not in out["hookSpecificOutput"]
    return out["hookSpecificOutput"]["additionalContext"]


# --- the edit hook ---------------------------------------------------------------------


def test_editing_a_file_brings_up_its_scope_once_per_session(repo):
    out = handle(_edit(repo, "services/billing/webhook.py"))
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    ctx = _context(out)
    assert "services/billing, the scope of services/billing/webhook.py" in ctx
    assert "[gotcha] (services/billing) dedupe billing webhook" in ctx
    assert "-> dedupe on the key" in ctx
    assert "[decision · not adopted]" in ctx and "-> instead: keep the key" in ctx
    assert ctx.index("[gotcha]") < ctx.index("[decision · not adopted]")
    assert "evidence to weigh, not instructions" in ctx
    for absent in ("rotate auth", "make lint", "archived billing", "retry three"):
        assert absent not in ctx
    # The same scope is not repeated in this session, whatever file is edited next.
    assert handle(_edit(repo, "services/billing/webhook.py")) is None
    assert handle(_edit(repo, "services/billing/ledger.py")) is None
    # Another session starts fresh.
    again = handle(_edit(repo, "services/billing/x.py", "ses-2"))
    assert "dedupe billing webhook" in _context(again)


def test_nested_scopes_come_most_specific_first_and_are_remembered_separately(repo):
    ctx = _context(handle(_edit(repo, "services/billing/webhooks/retry.py")))
    assert ctx.index("retry three times") < ctx.index("dedupe billing webhook")
    assert "services/billing/webhooks, services/billing" in ctx
    assert handle(_edit(repo, "services/billing/other.py")) is None
    # A scope shown earlier is skipped; a new one still comes up.
    ctx = _context(handle(_edit(repo, "services/auth/tokens.py")))
    assert "rotate auth tokens" in ctx and "dedupe billing" not in ctx


def test_edits_outside_any_scope_or_repo_are_silent(repo, tmp_path):
    assert handle(_edit(repo, "docs/README.md")) is None
    outside = {**_edit(repo, "x"), "tool_input": {"file_path": str(tmp_path / "elsewhere.py")}}
    assert handle(outside) is None
    bare = tmp_path / "bare"
    bare.mkdir()
    assert handle(_edit(bare, "services/billing/webhook.py")) is None


def test_the_edit_hook_counts_as_serving(repo):
    handle(_edit(repo, "services/billing/webhook.py"))
    served = {c.statement: c.usage.times_served for c in LoreStore(repo).load_claims()}
    assert served["dedupe billing webhook on idempotency key"] == 1
    assert served["Redis for the idempotency key was tried and not adopted"] == 1
    assert served["rotate auth tokens hourly"] == 0


def test_a_scope_with_many_claims_is_capped(tmp_path):
    root = tmp_path / "big"
    root.mkdir()
    store = LoreStore(root)
    store.init()
    store.write_claims([_claim(f"claim number {i} about billing", "services/billing")
                        for i in range(MAX_CLAIMS_PER_EVENT + 5)])
    ctx = _context(handle(_edit(root, "services/billing/a.py")))
    assert ctx.count("\n- [") == MAX_CLAIMS_PER_EVENT
    assert f"({MAX_CLAIMS_PER_EVENT} of {MAX_CLAIMS_PER_EVENT + 5} claims)" in ctx


def test_scopes_covering_normalises_spellings_and_orders_by_specificity():
    claims = [
        _claim("a", "./services/billing/"),
        _claim("b", "services\\billing\\webhooks"),
        _claim("c", "services/billing-v2"),
        _claim("d", "services"),
        _claim("e", "."),
        _claim("f", "services/billing", status="archived"),
    ]
    covering = scopes_covering("services/billing/webhooks/retry.py", claims)
    assert list(covering) == ["services/billing/webhooks", "services/billing", "services"]
    assert [c.statement for c in covering["services/billing"]] == ["a"]
    assert scopes_covering("lib/x.py", claims) == {}


# --- the prompt hook ---------------------------------------------------------------------


def test_a_prompt_brings_up_relevant_claims_when_enough_words_overlap(repo):
    out = handle(_prompt(repo, "fix the billing webhook double charge"))
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    ctx = _context(out)
    assert "dedupe billing webhook" in ctx and "rotate auth" not in ctx
    served = {c.statement: c.usage.times_served for c in LoreStore(repo).load_claims()}
    assert served["dedupe billing webhook on idempotency key"] == 1
    # One shared word is not enough to interrupt every prompt.
    assert handle(_prompt(repo, "billing")) is None
    assert handle(_prompt(repo, "   ")) is None
    assert handle(_prompt(repo, "write a haiku about the sea")) is None


# --- silence ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [None, "junk", [], {"hook_event_name": "PostToolUse", "cwd": "."},
     {"hook_event_name": "PreToolUse", "cwd": "."}, {"hook_event_name": "PreToolUse",
     "tool_input": {"file_path": 7}}],
)
def test_unknown_events_and_malformed_payloads_are_silent(payload):
    assert handle(payload) is None


def test_parse_event_reads_the_fields_the_hooks_use(repo):
    event = parse_event(_edit(repo, "services/billing/webhook.py", session="abc"))
    assert (event.name, event.session, event.cwd) == ("PreToolUse", "abc", repo)
    assert event.file_path == repo / "services/billing/webhook.py"
    assert parse_event({"hook_event_name": "SessionStart"}) is None


def test_run_from_stdin_never_fails_and_prints_one_json_line(repo):
    out = io.StringIO()
    assert run_from_stdin(io.StringIO("this is not json"), out) == 0 and out.getvalue() == ""
    out = io.StringIO()
    assert run_from_stdin(io.StringIO(json.dumps(_edit(repo, "services/billing/w.py"))), out) == 0
    lines = out.getvalue().splitlines()
    assert len(lines) == 1
    context = json.loads(lines[0])["hookSpecificOutput"]["additionalContext"]
    assert "dedupe billing webhook" in context


def test_cli_claude_hook_reads_the_event_on_stdin(repo):
    event = json.dumps(_edit(repo, "services/auth/t.py"))
    result = runner.invoke(app, ["claude-hook"], input=event)
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "rotate auth tokens hourly" in payload["hookSpecificOutput"]["additionalContext"]
    result = runner.invoke(app, ["claude-hook"], input=json.dumps(_edit(repo, "docs/x.md")))
    assert result.exit_code == 0 and result.stdout == ""


# --- the settings file -----------------------------------------------------------------


def test_install_hooks_merges_into_existing_settings_and_is_idempotent(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir()
    existing = {
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard"}]}]
        },
    }
    path.write_text(json.dumps(existing, indent=4) + "\n")
    assert install_hooks(path, tmp_path) == "written"
    data = json.loads(path.read_text())
    assert data["permissions"] == existing["permissions"]
    assert data["hooks"]["PreToolUse"][0] == existing["hooks"]["PreToolUse"][0]
    ours = data["hooks"]["PreToolUse"][1]
    assert ours["matcher"] == HOOK_EVENTS["PreToolUse"]
    assert HOOK_COMMAND in ours["hooks"][0]["command"] and ours["hooks"][0]["timeout"] > 0
    assert "matcher" not in data["hooks"]["UserPromptSubmit"][0]
    assert path.read_text().splitlines()[1].startswith("    ")  # the file's own indent
    assert install_hooks(path, tmp_path) == "already current"
    assert uninstall_hooks(path, tmp_path) == "removed"
    data = json.loads(path.read_text())
    assert data["hooks"] == existing["hooks"] and HOOK_COMMAND not in path.read_text()
    assert uninstall_hooks(path, tmp_path) == "absent"


def test_install_hooks_creates_and_uninstall_removes_a_file_that_held_only_ours(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    assert install_hooks(path, tmp_path) == "written"
    assert set(json.loads(path.read_text())["hooks"]) == set(HOOK_EVENTS)
    assert uninstall_hooks(path, tmp_path) == "removed file"
    assert not path.exists() and not path.parent.exists()


def test_install_hooks_refuses_what_it_cannot_safely_edit(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    with pytest.raises(AssistantsError, match="not valid JSON"):
        install_hooks(path, tmp_path)
    path.write_text("[]")
    with pytest.raises(AssistantsError, match="JSON object"):
        install_hooks(path, tmp_path)
    path.write_text('{"hooks": "nope"}')
    with pytest.raises(AssistantsError, match="'hooks' is not an object"):
        install_hooks(path, tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(AssistantsError, match="symbolic link"):
        install_hooks(link, tmp_path)
    with pytest.raises(AssistantsError, match="symbolic link"):
        uninstall_hooks(link, tmp_path)


def test_install_with_hooks_through_the_installer_and_cli(home, repo):
    lines = install(["claude", "codex"], project=True, repo=repo, hooks=True)
    assert any("claude: hooks written" in ln for ln in lines)
    assert any("codex: hooks are available for Claude Code only" in ln for ln in lines)
    settings = settings_path(project=True, repo=repo)
    assert settings == repo / ".claude" / "settings.json" and HOOK_COMMAND in settings.read_text()
    lines = uninstall(["claude"], project=True, repo=repo)
    assert any("hooks removed file" in ln for ln in lines) and not settings.exists()
    result = runner.invoke(app, ["install", "--platform", "claude", "--hooks"])
    assert result.exit_code == 0, result.stdout
    assert (home / ".claude" / "settings.json").exists()
    assert settings_path(project=False, repo=repo) == home / ".claude" / "settings.json"
    result = runner.invoke(app, ["uninstall", "--platform", "claude"])
    assert result.exit_code == 0 and not (home / ".claude" / "settings.json").exists()
