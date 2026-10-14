"""`lore install --hooks` puts two Claude Code hooks into the settings file, and
`lore claude-hook` answers them: the claims for a read or edited file's scope, once per
scope per conversation, or the claims relevant to a prompt, as facts. Silence everywhere
else, and the installed shell command exits 0 whatever `lore` does."""

import io
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

import lore.assistant_hooks as hooks_module
from lore.assistant_hooks import (
    HOOK_COMMAND,
    HOOK_EVENTS,
    HOOK_SHELL,
    KNOWN_COMMANDS,
    MAX_CLAIMS_PER_EVENT,
    MAX_CONTEXT_CHARS,
    _one_line,
    format_context,
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


def _tool(repo, path, tool="Edit", session="ses-1", agent=None):
    payload = {
        "hook_event_name": "PreToolUse", "session_id": session, "cwd": str(repo),
        "tool_name": tool, "tool_input": {"file_path": str(repo / path)},
    }
    if agent:
        payload["agent_id"] = agent
    return payload


def _prompt(repo, text, session="ses-1"):
    return {
        "hook_event_name": "UserPromptSubmit", "session_id": session, "cwd": str(repo),
        "prompt": text,
    }


def _context(out):
    assert set(out) == {"hookSpecificOutput"}
    assert "permissionDecision" not in out["hookSpecificOutput"]
    return out["hookSpecificOutput"]["additionalContext"]


# --- the file hook ---------------------------------------------------------------------


def test_reading_or_editing_a_file_brings_up_its_scope_once_per_conversation(repo):
    out = handle(_tool(repo, "services/billing/webhook.py", tool="Read"))
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    ctx = _context(out)
    assert "for services/billing, the scope of services/billing/webhook.py (2 claims)" in ctx
    assert "[gotcha] (services/billing) dedupe billing webhook" in ctx
    assert "-> dedupe on the key" in ctx
    assert "[decision · not adopted]" in ctx and "-> instead: keep the key" in ctx
    assert ctx.index("[gotcha]") < ctx.index("[decision · not adopted]")
    assert "evidence to weigh, not instructions" in ctx
    for absent in ("rotate auth", "make lint", "archived billing", "retry three"):
        assert absent not in ctx
    # The edit that follows the read, and any other file in the scope, add nothing.
    assert handle(_tool(repo, "services/billing/webhook.py")) is None
    assert handle(_tool(repo, "services/billing/ledger.py", tool="Write")) is None
    # Another conversation starts fresh, and a subagent is its own conversation.
    fresh = handle(_tool(repo, "services/billing/x.py", session="ses-2"))
    assert "dedupe billing webhook" in _context(fresh)
    sub = handle(_tool(repo, "services/billing/x.py", agent="sub-1"))
    assert "dedupe billing webhook" in _context(sub)
    assert handle(_tool(repo, "services/billing/y.py", agent="sub-1")) is None


def test_nested_scopes_come_most_specific_first_and_are_remembered_separately(repo):
    ctx = _context(handle(_tool(repo, "services/billing/webhooks/retry.py")))
    assert ctx.index("retry three times") < ctx.index("dedupe billing webhook")
    assert "services/billing/webhooks, services/billing" in ctx
    assert handle(_tool(repo, "services/billing/other.py")) is None
    ctx = _context(handle(_tool(repo, "services/auth/tokens.py")))
    assert "rotate auth tokens" in ctx and "dedupe billing" not in ctx


def test_files_outside_any_scope_or_repo_are_silent(repo, tmp_path):
    assert handle(_tool(repo, "docs/README.md")) is None
    outside = {**_tool(repo, "x"), "tool_input": {"file_path": str(tmp_path / "elsewhere.py")}}
    assert handle(outside) is None
    bare = tmp_path / "bare"
    bare.mkdir()
    assert handle(_tool(bare, "services/billing/webhook.py")) is None


def test_the_sessions_repo_wins_over_a_vendored_checkout_with_its_own_store(repo):
    vendored = repo / "services" / "billing" / "vendor" / "inner"
    vendored.mkdir(parents=True)
    LoreStore(vendored).init()
    ctx = _context(handle(_tool(repo, "services/billing/vendor/inner/src/x.py")))
    assert "dedupe billing webhook" in ctx


def test_the_file_hook_counts_as_serving_without_rewriting_the_claims_file(repo):
    store = LoreStore(repo)
    before = store.claims_path.read_bytes()
    mtime = store.claims_path.stat().st_mtime_ns
    handle(_tool(repo, "services/billing/webhook.py"))
    served = {c.statement: c.usage.times_served for c in store.load_claims()}
    assert served["dedupe billing webhook on idempotency key"] == 1
    assert served["Redis for the idempotency key was tried and not adopted"] == 1
    assert served["rotate auth tokens hourly"] == 0
    assert store.claims_path.read_bytes() == before
    assert store.claims_path.stat().st_mtime_ns == mtime


def test_many_claims_are_capped_as_whole_claims_with_an_honest_count(tmp_path):
    root = tmp_path / "big"
    root.mkdir()
    store = LoreStore(root)
    store.init()
    store.write_claims([
        _claim(f"claim number {i} about billing " + "detail " * 150, "services/billing",
               kind="decision", adoption="not_adopted", action="do the other thing " * 40)
        for i in range(MAX_CLAIMS_PER_EVENT + 5)
    ])
    ctx = _context(handle(_tool(root, "services/billing/a.py")))
    shown = ctx.count("\n- [")
    assert 0 < shown < MAX_CLAIMS_PER_EVENT and len(ctx) <= MAX_CONTEXT_CHARS
    assert f"({shown} of {MAX_CLAIMS_PER_EVENT + 5} claims)" in ctx
    assert ctx.count("-> instead:") == shown  # never a statement without its action
    assert f"- {MAX_CLAIMS_PER_EVENT + 5 - shown} more not shown" in ctx
    assert "lore explain" not in ctx
    served = sum(c.usage.times_served for c in store.load_claims())
    assert served == shown


def test_format_context_counts_and_footer():
    claims = [_claim(f"c{i}", "s") for i in range(MAX_CLAIMS_PER_EVENT + 2)]
    text, shown = format_context("for s", claims)
    assert len(shown) == MAX_CLAIMS_PER_EVENT
    assert f"({MAX_CLAIMS_PER_EVENT} of {MAX_CLAIMS_PER_EVENT + 2} claims)" in text
    assert "2 more not shown" in text
    text, shown = format_context("for s", claims[:3])
    assert "(3 claims)" in text and "more not shown" not in text


def test_scopes_covering_normalises_spellings_and_orders_by_specificity():
    claims = [
        _claim("a", "./services/billing/"),
        _claim("b", "services\\billing\\webhooks"),
        _claim("c", "services/billing-v2"),
        _claim("d", "/services"),
        _claim("e", "."),
        _claim("f", "services/billing", status="archived"),
    ]
    covering = scopes_covering("services/billing/webhooks/retry.py", claims)
    assert list(covering) == ["services/billing/webhooks", "services/billing", "services"]
    assert [c.statement for c in covering["services/billing"]] == ["a"]
    assert scopes_covering("lib/x.py", claims) == {}


def test_one_line_strips_controls_and_format_characters_but_keeps_joiners():
    noisy = "Dedupe\x1b[31m on\n the key" + chr(0x200B) + chr(0x202E)
    assert _one_line(noisy) == "Dedupe on the key"
    assert _one_line("a\x1b(Bb\x1b7c") == "abc"  # escapes that are not CSI sequences
    assert _one_line("क्" + chr(0x200D) + "ष") == "क्" + chr(0x200D) + "ष"
    assert _one_line(None) == "" and _one_line(42) == "42"


# --- the prompt hook ---------------------------------------------------------------------


def test_a_prompt_brings_up_relevant_claims_when_enough_words_overlap(repo):
    out = handle(_prompt(repo, "fix the billing webhook double charge"))
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    ctx = _context(out)
    assert "dedupe billing webhook" in ctx and "rotate auth" not in ctx
    served = {c.statement: c.usage.times_served for c in LoreStore(repo).load_claims()}
    assert served["dedupe billing webhook on idempotency key"] == 1
    assert handle(_prompt(repo, "billing")) is None  # one shared word is not enough
    assert handle(_prompt(repo, "   ")) is None
    assert handle(_prompt(repo, "write a haiku about the sea")) is None


# --- silence ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [None, "junk", [], {"hook_event_name": "PostToolUse", "cwd": "."},
     {"hook_event_name": "PreToolUse", "cwd": "."},
     {"hook_event_name": "PreToolUse", "tool_input": {"file_path": 7}}],
)
def test_unknown_events_and_malformed_payloads_are_silent(payload):
    assert handle(payload) is None


def test_parse_event_reads_the_fields_the_hooks_use(repo):
    event = parse_event(_tool(repo, "services/billing/webhook.py", session="abc", agent="sub"))
    assert (event.name, event.session, event.agent, event.cwd) == ("PreToolUse", "abc", "sub", repo)
    assert event.file_path == repo / "services/billing/webhook.py"
    assert parse_event(_tool(repo, "x")).agent == "main"
    assert parse_event({"hook_event_name": "PostToolUse"}) is None


def test_run_from_stdin_never_fails_and_prints_one_json_line(repo):
    out = io.StringIO()
    assert run_from_stdin(io.StringIO("this is not json"), out) == 0 and out.getvalue() == ""
    out = io.StringIO()
    assert run_from_stdin(io.StringIO(json.dumps(_tool(repo, "services/billing/w.py"))), out) == 0
    lines = out.getvalue().splitlines()
    assert len(lines) == 1
    context = json.loads(lines[0])["hookSpecificOutput"]["additionalContext"]
    assert "dedupe billing webhook" in context


def test_cli_claude_hook_reads_the_event_on_stdin(repo):
    event = json.dumps(_tool(repo, "services/auth/t.py"))
    result = runner.invoke(app, ["claude-hook"], input=event)
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "rotate auth tokens hourly" in payload["hookSpecificOutput"]["additionalContext"]
    result = runner.invoke(app, ["claude-hook"], input=json.dumps(_tool(repo, "docs/x.md")))
    assert result.exit_code == 0 and result.stdout == ""


@pytest.mark.skipif(os.name == "nt", reason="the installed command is for a POSIX shell")
def test_the_installed_shell_command_exits_0_whatever_lore_does(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()

    def run(fake_lore: str | None):
        if fake_lore is not None:
            (bindir / "lore").write_text("#!/bin/sh\n" + fake_lore)
            (bindir / "lore").chmod(0o755)
        elif (bindir / "lore").exists():
            (bindir / "lore").unlink()
        return subprocess.run(
            ["sh", "-c", HOOK_SHELL], input=b"{}", capture_output=True,
            env={"PATH": f"{bindir}:/usr/bin:/bin"}, timeout=30,
        )

    older = run('echo "Usage: lore [OPTIONS] COMMAND\\nError: No such command" >&2; exit 2')
    assert older.returncode == 0 and older.stdout == b""
    broken = run("exit 1")
    assert broken.returncode == 0
    answer = run("cat >/dev/null; echo '{\"hookSpecificOutput\": {}}'; exit 0")
    assert answer.returncode == 0 and json.loads(answer.stdout) == {"hookSpecificOutput": {}}
    # Some other program called `lore`, or a notice on stdout, is not passed on as context.
    chatter = run("cat >/dev/null; echo 'lore 9.0 is available, run lore upgrade'; exit 0")
    assert chatter.returncode == 0 and chatter.stdout == b""
    absent = run(None)
    assert absent.returncode == 0 and absent.stdout == b""


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
    assert ours["matcher"] == HOOK_EVENTS["PreToolUse"] == "Read|Edit|Write"
    assert ours["hooks"][0]["command"] == HOOK_SHELL and ours["hooks"][0]["timeout"] > 0
    assert "matcher" not in data["hooks"]["UserPromptSubmit"][0]
    assert path.read_text().splitlines()[1].startswith("    ")  # the file's own indent
    assert install_hooks(path, tmp_path) == "already current"
    assert uninstall_hooks(path, tmp_path) == "removed"
    data = json.loads(path.read_text())
    assert data["hooks"] == existing["hooks"] and HOOK_COMMAND not in path.read_text()
    assert uninstall_hooks(path, tmp_path) == "absent"


def test_install_hooks_keeps_line_endings_tabs_and_non_ascii(tmp_path):
    path = tmp_path / "settings.json"
    original = '{\r\n\t"permissions": {"allow": ["Bash(echo ✓ — ready)"]}\r\n}\r\n'
    path.write_bytes(original.encode("utf-8"))
    assert install_hooks(path, tmp_path) == "written"
    text = path.read_bytes().decode("utf-8")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    assert '\t"permissions"' in text and "✓ — ready" in text and "\\u" not in text
    assert uninstall_hooks(path, tmp_path) == "removed"
    after = path.read_bytes().decode("utf-8")
    assert json.loads(after) == json.loads(original)  # the data, in the file's own style
    assert "\r\n" in after and '\t"permissions"' in after and "✓ — ready" in after


def test_install_hooks_creates_and_uninstall_removes_a_file_that_held_only_ours(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    assert install_hooks(path, tmp_path) == "written"
    assert set(json.loads(path.read_text())["hooks"]) == set(HOOK_EVENTS)
    assert uninstall_hooks(path, tmp_path) == "removed file"
    assert not path.exists() and not path.parent.exists()


def test_ownership_is_exact_so_a_users_own_entry_survives(tmp_path):
    path = tmp_path / "settings.json"
    theirs = {"type": "command", "command": f"my-audit-log && {HOOK_COMMAND} | tee -a log"}
    path.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [theirs]}]}}))
    install_hooks(path, tmp_path)
    assert uninstall_hooks(path, tmp_path) == "removed"
    assert json.loads(path.read_text())["hooks"]["UserPromptSubmit"] == [{"hooks": [theirs]}]
    assert HOOK_SHELL in KNOWN_COMMANDS


def test_install_hooks_refuses_what_it_cannot_safely_edit(tmp_path):
    path = tmp_path / "settings.json"
    for bad, message in (
        ("{not json", "not valid JSON"),
        ("[]", "JSON object"),
        ('{"hooks": "nope"}', "'hooks' is not an object"),
        ('{"hooks": {"PreToolUse": {"matcher": "Edit"}}}', "not a list of hook groups"),
        ('{"hooks": {"PreToolUse": ["text"]}}', "not a list of hook groups"),
    ):
        path.write_text(bad)
        with pytest.raises(AssistantsError, match=message):
            install_hooks(path, tmp_path)
        assert path.read_text() == bad
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(AssistantsError, match="symbolic link"):
        install_hooks(link, tmp_path)
    with pytest.raises(AssistantsError, match="symbolic link"):
        uninstall_hooks(link, tmp_path)


def test_a_bad_settings_file_is_refused_before_the_skill_is_written(home, repo):
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {"PreToolUse": {"matcher": "Edit"}}}')
    with pytest.raises(AssistantsError, match="not a list of hook groups"):
        install(["claude"], project=True, repo=repo, hooks=True)
    assert not (repo / ".claude" / "skills").exists()


def test_install_with_hooks_through_the_installer_and_cli(home, repo, monkeypatch):
    monkeypatch.setattr("lore.assistants.shutil.which", lambda name: "/usr/local/bin/lore")
    lines = install(["claude", "codex"], project=True, repo=repo, hooks=True)
    assert any("claude: hooks written" in ln for ln in lines)
    assert any("codex: hooks are available for Claude Code only" in ln for ln in lines)
    assert not any("note:" in ln for ln in lines)
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


def test_hooks_need_claude_and_warn_when_lore_is_off_path(home, repo, monkeypatch):
    with pytest.raises(AssistantsError, match="add claude to --platform"):
        install(["codex"], project=True, repo=repo, hooks=True)
    assert not (repo / ".agents").exists() and not (repo / ".claude").exists()
    monkeypatch.setattr("lore.assistants.shutil.which", lambda name: None)
    lines = install(["claude"], project=True, repo=repo, hooks=True)
    assert any("not on this shell's PATH" in ln for ln in lines)


# --- second-pass findings ----------------------------------------------------------------


def test_parallel_hooks_keep_every_bump_and_every_remembered_scope(tmp_path):
    import concurrent.futures

    root = tmp_path / "par"
    root.mkdir()
    store = LoreStore(root)
    store.init()
    scopes = [f"services/s{i}" for i in range(24)]
    store.write_claims([_claim(f"claim about s{i}", scope) for i, scope in enumerate(scopes)])
    events = [_tool(root, f"{scope}/file.py") for scope in scopes]
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        outputs = list(pool.map(handle, events))
    assert all(out is not None for out in outputs)
    assert all(c.usage.times_served == 1 for c in store.load_claims())
    assert all(handle(_tool(root, f"{scope}/other.py")) is None for scope in scopes)


def test_a_scope_counts_as_shown_only_when_one_of_its_claims_was(tmp_path):
    root = tmp_path / "cap"
    root.mkdir()
    store = LoreStore(root)
    store.init()
    big = [_claim(f"billing claim {i} " + "detail " * 200, "services/billing") for i in range(8)]
    wide = [_claim(f"services-wide rule {i}", "services") for i in range(3)]
    store.write_claims(big + wide)
    ctx = _context(handle(_tool(root, "services/billing/a.py")))
    assert "services-wide rule" not in ctx and "of 11 claims" in ctx
    # The cap pushed the `services` scope out entirely, so it is not remembered as shown.
    ctx = _context(handle(_tool(root, "services/auth/x.py")))
    assert "services-wide rule 0" in ctx
    assert handle(_tool(root, "services/billing/b.py")) is None  # billing was shown


def test_one_claim_too_large_for_the_cap_is_shown_cut_not_dropped():
    huge = _claim("x" * (MAX_CONTEXT_CHARS + 500), "services/billing", action="do it")
    text, shown = format_context("for services/billing", [huge, _claim("small", "s")])
    assert shown == [huge] and text.endswith("…") is False or "…" in text
    assert "(1 of 2 claims)" in text and len(text) <= MAX_CONTEXT_CHARS
    assert "1 more not shown" in text


def test_compaction_resets_what_the_conversation_was_shown(repo):
    assert handle(_tool(repo, "services/billing/webhook.py")) is not None
    assert handle(_tool(repo, "services/billing/ledger.py")) is None
    compact = {
        "hook_event_name": "SessionStart", "session_id": "ses-1", "cwd": str(repo),
        "source": "compact",
    }
    assert handle(compact) is None
    assert handle(_tool(repo, "services/billing/ledger.py")) is not None
    assert HOOK_EVENTS["SessionStart"] == "compact"


def test_bookkeeping_failures_never_cost_the_assistant_its_context(repo, monkeypatch):
    def failing(self, ids):
        raise OSError("disk full")

    monkeypatch.setattr("lore.serve.server.KnowledgeServer.mark_served", failing)
    out = handle(_tool(repo, "services/billing/webhook.py"))
    assert "dedupe billing webhook" in _context(out)


def test_uninstall_keeps_a_symlinked_settings_file_and_empties_its_target(tmp_path):
    target = tmp_path / "dotfiles" / "claude-settings.json"
    target.parent.mkdir()
    target.write_text("{}\n")
    link = tmp_path / "settings.json"
    link.symlink_to(target)
    assert install_hooks(link, tmp_path, strict=False) == "written"
    assert HOOK_COMMAND in target.read_text()
    assert uninstall_hooks(link, tmp_path, strict=False) == "removed"
    assert link.is_symlink() and json.loads(target.read_text()) == {}


def test_an_older_installed_command_is_replaced_on_reinstall(tmp_path):
    path = tmp_path / "settings.json"
    older = KNOWN_COMMANDS[1]
    path.write_text(json.dumps({"hooks": {"UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": older, "timeout": 10}]}
    ]}}))
    assert install_hooks(path, tmp_path) == "written"
    commands = [
        h["command"]
        for groups in json.loads(path.read_text())["hooks"].values()
        for group in groups
        for h in group["hooks"]
    ]
    assert older not in commands and commands.count(HOOK_SHELL) == len(HOOK_EVENTS)


def test_paths_with_dot_segments_still_match_their_scope(repo):
    event = _tool(repo, "services/../services/billing/webhook.py")
    assert "dedupe billing webhook" in _context(handle(event))


def test_a_bad_settings_file_stops_uninstall_before_any_skill_is_removed(home, repo):
    install(["claude"], project=True, repo=repo)
    settings = repo / ".claude" / "settings.json"
    settings.write_text("{not json")
    with pytest.raises(AssistantsError, match="not valid JSON"):
        uninstall(["claude"], project=True, repo=repo)
    assert (repo / ".claude" / "skills" / "lore" / "SKILL.md").exists()


def test_install_warns_when_no_posix_shell_runs_the_hooks(home, repo, monkeypatch):
    monkeypatch.setattr("lore.assistants.shutil.which", lambda name: "/usr/bin/lore")
    monkeypatch.setattr(hooks_module, "posix_shell_available", lambda: False)
    lines = install(["claude"], project=True, repo=repo, hooks=True)
    assert any("Git Bash" in ln for ln in lines)


def test_usage_sidecar_is_replaced_atomically_and_ignored_by_git(repo):
    store = LoreStore(repo)
    handle(_tool(repo, "services/billing/webhook.py"))
    assert not list((store.lore / "claims").glob(".*.tmp"))
    ignore = (store.lore / ".gitignore").read_text().splitlines()
    assert "claims/usage.jsonl" in ignore and ".*.tmp" in ignore and "cache/" in ignore
