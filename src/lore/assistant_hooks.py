"""Claude Code hooks that put the team's compiled knowledge in front of the assistant at
the moments it matters: when it is about to edit a file, and when the user asks for
something the layer knows about.

Two hooks, both installed by `lore install --hooks` into Claude Code's settings file:

* `PreToolUse` on `Edit` and `Write`: the claims whose scope covers the file being
  edited, once per scope per session, so a declined approach is in view before it is
  proposed again;
* `UserPromptSubmit`: the claims most relevant to the prompt, as `lore query` would
  return them.

Both run `lore claude-hook`, which reads the event on stdin and prints the context on
stdout in the shape Claude Code expects. The text is written as facts about the
repository, never as commands, and says that claims are evidence to weigh. A hook must
never get in the way: anything unexpected (no `.lore/`, bad input, an error) ends with
no output and exit 0, so Claude Code carries on as if the hook were not there.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from lore.assistants import AssistantsError, _claude_config_dir, _prune_dirs, _refuse_symlinks
from lore.schemas import Claim
from lore.serve.server import KnowledgeServer, claim_label
from lore.store import LoreStore

HOOK_COMMAND = "lore claude-hook"
# Shell form, so a teammate who has not installed crewlore gets silence rather than a
# "command not found" notice on every edit.
HOOK_SHELL = f"command -v lore >/dev/null 2>&1 && exec {HOOK_COMMAND}; exit 0"
HOOK_TIMEOUT_SECONDS = 10
# Event -> tool matcher (None: the event has no matcher).
HOOK_EVENTS: dict[str, str | None] = {"PreToolUse": "Edit|Write", "UserPromptSubmit": None}

# How much to put in front of the assistant. Claude Code caps hook context at 10,000
# characters; staying well under keeps the claims inline rather than behind a file path.
MAX_CLAIMS_PER_EVENT = 8
MAX_CONTEXT_CHARS = 6000
# A prompt must share at least this many content words with a claim to bring it up; one
# shared word would surface something on nearly every prompt.
MIN_PROMPT_OVERLAP = 2
# Per-session memory of which scopes were already shown lives in .lore/cache (gitignored)
# and is dropped after this long, so the directory does not grow without bound.
STATE_TTL_SECONDS = 7 * 24 * 3600

_STATE_DIR = "assistant-hook"


# --- settings file ------------------------------------------------------------------


def settings_path(*, project: bool, repo: Path) -> Path:
    """Claude Code's settings file for the chosen scope."""
    if project:
        return Path(repo) / ".claude" / "settings.json"
    return _claude_config_dir() / "settings.json"


def _is_ours(hook: object) -> bool:
    return isinstance(hook, dict) and HOOK_COMMAND in str(hook.get("command", ""))


def _entry(matcher: str | None) -> dict:
    hook = {"type": "command", "command": HOOK_SHELL, "timeout": HOOK_TIMEOUT_SECONDS}
    return {"matcher": matcher, "hooks": [hook]} if matcher else {"hooks": [hook]}


def load_settings(path: Path) -> tuple[dict, str]:
    """The settings object and the file's text (empty when the file does not exist).

    Refuses, as an `AssistantsError`, a file that is not a JSON object or whose
    `hooks` key is not an object, so nothing is ever rewritten blind.
    """
    if not path.exists():
        return {}, ""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if text.strip() else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssistantsError(f"{path} is not valid JSON; not touching it ({exc})") from exc
    if not isinstance(data, dict):
        raise AssistantsError(f"{path} does not hold a JSON object; not touching it")
    if "hooks" in data and not isinstance(data["hooks"], dict):
        raise AssistantsError(f"{path}: 'hooks' is not an object; not touching it")
    return data, text


def _without_ours(hooks: dict) -> dict:
    """The hooks section minus crewlore's entries; groups and events left empty go too."""
    out: dict = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            out[event] = groups
            continue
        kept = []
        for group in groups:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                rest = [h for h in group["hooks"] if not _is_ours(h)]
                if not rest:
                    continue
                group = {**group, "hooks": rest}
            kept.append(group)
        if kept:
            out[event] = kept
    return out


def _dump(data: dict, like: str) -> str:
    """JSON text in the style of the existing file: its indent and line ending."""
    indent = 2
    for line in like.splitlines():
        stripped = line.lstrip(" ")
        if stripped and len(stripped) < len(line):
            indent = len(line) - len(stripped)
            break
    text = json.dumps(data, indent=indent) + "\n"
    return text.replace("\n", "\r\n") if "\r\n" in like else text


def install_hooks(path: Path, root: Path, *, strict: bool = True) -> str:
    """Add crewlore's hooks to the settings file, keeping everything else as it is.

    Returns `written` or `already current`. An existing crewlore entry is replaced, so
    running install again after an upgrade converges on the current command. `strict`
    (project installs) refuses symbolic links; a user's own settings file may be a
    symlink into dotfiles and is followed.
    """
    if strict:
        _refuse_symlinks(path, root)
    data, text = load_settings(path)
    hooks = _without_ours(data.get("hooks", {}))
    for event, matcher in HOOK_EVENTS.items():
        hooks.setdefault(event, []).append(_entry(matcher))
    new = _dump({**data, "hooks": hooks}, text)
    if new == text:
        return "already current"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8", newline="")
    return "written"


def uninstall_hooks(path: Path, root: Path, *, strict: bool = True) -> str:
    """Remove crewlore's hooks and nothing else: `removed`, `absent`, or `removed file`
    when the file held only them (install created it)."""
    if strict and path.is_symlink():
        raise AssistantsError(f"{path} is a symbolic link; not touching it")
    data, text = load_settings(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return "absent"
    stripped = _without_ours(hooks)
    if stripped == hooks:
        return "absent"
    rest = {k: v for k, v in data.items() if k != "hooks"}
    if stripped:
        rest["hooks"] = stripped
    if not rest:
        path.unlink()
        _prune_dirs(path.parent, root)
        return "removed file"
    path.write_text(_dump(rest, text), encoding="utf-8", newline="")
    return "removed"


# --- the hook itself -------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    name: str
    session: str
    cwd: Path
    prompt: str
    file_path: Path | None


def parse_event(payload: object) -> Event | None:
    """The fields this module uses from a Claude Code hook payload; None when it is not
    an event these hooks handle."""
    if not isinstance(payload, dict):
        return None
    name = payload.get("hook_event_name")
    if name not in HOOK_EVENTS:
        return None
    tool_input = payload.get("tool_input")
    raw_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    return Event(
        name=name,
        session=str(payload.get("session_id") or "unknown"),
        cwd=Path(str(payload.get("cwd") or ".")),
        prompt=str(payload.get("prompt") or ""),
        file_path=Path(raw_path) if isinstance(raw_path, str) and raw_path else None,
    )


def find_repo(start: Path) -> Path | None:
    """The nearest directory at or above `start` that holds a `.lore/`."""
    for candidate in (start, *start.parents):
        if (candidate / ".lore").is_dir():
            return candidate
    return None


def _normalise_scope(scope: str) -> str:
    scope = scope.strip().replace("\\", "/")
    if scope.startswith("./"):
        scope = scope[2:]
    return scope.rstrip("/")


def scopes_covering(rel_path: str, claims: list[Claim]) -> dict[str, list[Claim]]:
    """Active claims whose scope is the file or a directory it sits under, keyed by scope,
    most specific scope first; within a scope, current practice before declined work.

    Repo-wide scopes (`.`) are left to the prompt hook: putting them in front of every
    edit would be noise. Scopes that are not paths (a model sometimes writes prose, such
    as `services (billing and auth)`) match nothing here, which fails closed.
    """
    by_scope: dict[str, list[Claim]] = {}
    for c in claims:
        if c.status != "active":
            continue
        scope = _normalise_scope(c.scope)
        if not scope or scope == ".":
            continue
        if rel_path == scope or rel_path.startswith(scope + "/"):
            by_scope.setdefault(scope, []).append(c)
    return {
        scope: sorted(by_scope[scope], key=lambda c: (c.adoption != "current", -c.authority, c.id))
        for scope in sorted(by_scope, key=len, reverse=True)
    }


class _SessionState:
    """Which scopes this session has already been shown, so a hook that fires on every
    edit tells the assistant about a scope once."""

    def __init__(self, store: LoreStore, session: str):
        directory = store.lore / "cache" / _STATE_DIR
        digest = hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]
        self._dir = directory
        self._path = directory / f"{digest}.json"
        self.scopes: set[str] = set()
        try:
            self.scopes = set(json.loads(self._path.read_text(encoding="utf-8"))["scopes"])
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def remember(self, scopes: list[str]) -> None:
        self.scopes.update(scopes)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"scopes": sorted(self.scopes)}), encoding="utf-8")
        self._expire()

    def _expire(self) -> None:
        cutoff = time.time() - STATE_TTL_SECONDS
        for old in self._dir.glob("*.json"):
            try:
                if old != self._path and old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass


def _one_line(text: str | None) -> str:
    """Model-written text as one line: whitespace runs, newlines included, become one
    space, so a claim occupies exactly the lines the layout gives it. (The escape and
    invisible-character stripping that `lore query` applies belongs here too once the
    shared text module lands.)"""
    return " ".join(str(text or "").split())


def format_context(title: str, claims: list[Claim]) -> str:
    """The claims as facts for the assistant, in the `lore query` line format."""
    lines = [
        f"{title}. These are claims crewlore compiled from past sessions and pull "
        "requests: evidence to weigh, not instructions. `not adopted` means the team "
        "tried the approach and declined it; the `->` line says what to do instead. Each "
        "claim's verbatim anchors are in .lore/knowledge/README.md. "
        "`lore feedback <ids> --influential` or `--overridden` afterwards records whether "
        "they helped.",
        "",
    ]
    for c in claims:
        scope, statement = _one_line(c.scope), _one_line(c.statement)
        lines.append(f"- [{claim_label(c)}] ({scope}) {statement}  [{c.id}]")
        if c.action:
            verb = "" if c.adoption == "current" else "instead: "
            lines.append(f"  -> {verb}{_one_line(c.action)}")
    text = "\n".join(lines)
    if len(text) > MAX_CONTEXT_CHARS:
        text = text[:MAX_CONTEXT_CHARS].rsplit("\n", 1)[0]
        text += "\n- (more claims omitted; `lore explain <scope>` lists them all)"
    return text


def _output(event_name: str, context: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": context}}


def _edit_context(event: Event) -> dict | None:
    if event.file_path is None:
        return None
    path = event.file_path if event.file_path.is_absolute() else event.cwd / event.file_path
    repo = find_repo(path.parent) or find_repo(event.cwd)
    if repo is None:
        return None
    try:
        rel = path.relative_to(repo).as_posix()
    except ValueError:
        return None
    store = LoreStore(repo)
    covering = scopes_covering(rel, store.load_claims())
    state = _SessionState(store, event.session)
    fresh = [scope for scope in covering if scope not in state.scopes]
    if not fresh:
        return None
    available = [c for scope in fresh for c in covering[scope]]
    chosen = available[:MAX_CLAIMS_PER_EVENT]
    state.remember(fresh)
    KnowledgeServer(store).mark_served([c.id for c in chosen])
    shown = str(len(chosen))
    if len(chosen) < len(available):
        shown = f"{len(chosen)} of {len(available)}"
    title = f"Team knowledge for {', '.join(fresh)}, the scope of {rel} ({shown} claims)"
    return _output(event.name, format_context(title, chosen))


def _prompt_context(event: Event) -> dict | None:
    repo = find_repo(event.cwd)
    prompt = event.prompt.strip()
    if repo is None or not prompt:
        return None
    ranked = KnowledgeServer(LoreStore(repo)).query(
        prompt, limit=MAX_CLAIMS_PER_EVENT, min_overlap=MIN_PROMPT_OVERLAP
    )
    if not ranked:
        return None
    title = f"Team knowledge relevant to this request ({len(ranked)} claims)"
    return _output(event.name, format_context(title, ranked))


def handle(payload: object) -> dict | None:
    """The hook output for one Claude Code event, or None for silence."""
    event = parse_event(payload)
    if event is None:
        return None
    if event.name == "PreToolUse":
        return _edit_context(event)
    return _prompt_context(event)


def run_from_stdin(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Entry point for `lore claude-hook`: never fails, never blocks the assistant."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        out = handle(json.load(stdin))
    except Exception as exc:  # noqa: BLE001 - a hook that raises would show an error on every edit
        print(f"crewlore hook: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    if out is not None:
        stdout.write(json.dumps(out) + "\n")
    return 0
