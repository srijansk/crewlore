"""`lore` — the single user-facing surface.

    lore init        create .lore/ in the repo
    lore compile     ingest new transcripts -> distill -> prune (one pass)
    lore watch       do that automatically on an interval (--once for cron)
    lore import-prs  compile a GitHub repo's pull-request threads
    lore query       task-conditioned retrieval (records usage)
    lore feedback    mark served claims influential or overridden
    lore status      counts + how much of the layer is actually being read
    lore serve       MCP server for query-time retrieval
"""

from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import typer

from lore import __version__
from lore.serve.server import KnowledgeServer, claim_label
from lore.store import LoreStore

app = typer.Typer(
    help=(
        "Compile coding-agent sessions and pull requests into a citable "
        "team-knowledge layer in your repo. Local-first."
    )
)

RepoOpt = typer.Option(Path("."), "--repo", help="Path to the team repo root.")
TranscriptsOpt = typer.Option(
    None,
    "--transcripts",
    help=(
        "Directory of transcripts to read. Default: only this repo's own Claude Code "
        "transcripts (~/.claude/projects/<this repo>)."
    ),
)
RebuildOpt = typer.Option(
    False, "--rebuild", help="Ignore the extraction cache and re-extract all sessions."
)
ClaimIdsArg = typer.Argument(..., help="Claim ids, as shown by `lore query`.")

_INIT_HINT = "No .lore/ here yet — run `lore init` in the repo root first."


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"crewlore {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
        help="Show the crewlore version and exit.",
    ),
) -> None:
    """Compile coding-agent sessions and pull requests into a citable team-knowledge
    layer in your repo. Local-first."""


# --- config-derived settings -------------------------------------------------


def _transcript_dir(store: LoreStore, override: Path | None) -> Path:
    """Where to read transcripts from.

    An explicit `--transcripts` or a directory in `capture.transcripts` is used
    as given. Otherwise ("auto", unset, or the pre-0.3 default of the whole
    `~/.claude/projects` tree) only this repo's own Claude Code transcript
    directory is read, so one repo's knowledge never absorbs every project on
    the machine — or bills the model key for all of them.
    """
    from lore.capture.ingest import CLAUDE_PROJECTS_ROOT, claude_code_project_dir

    if override is not None:
        return override
    cfg = store.load_config().get("capture", {}) or {}
    configured = cfg.get("transcripts")
    whole_tree = CLAUDE_PROJECTS_ROOT.expanduser()
    if configured in (None, "", "auto") or Path(str(configured)).expanduser() == whole_tree:
        scoped = claude_code_project_dir(store.root)
        if not scoped.exists():
            typer.echo(
                f"note: no Claude Code transcripts for this repo yet at {scoped} "
                "(Claude Code creates it when you work in this repo). "
                "To read another directory, pass --transcripts DIR."
            )
        return scoped
    return Path(str(configured)).expanduser()


def _compile_settings(store: LoreStore) -> dict:
    cfg = store.load_config().get("compile", {}) or {}
    return {
        "interval": int(cfg.get("watch_interval_seconds", 300)),
        "max_unused_age": timedelta(days=float(cfg.get("max_unused_days", 30))),
    }


def _require_store(store: LoreStore) -> None:
    """Commands that write need an initialised store; create one with a notice."""
    if not store.is_initialised:
        store.init()
        typer.echo(f"Initialised .lore/ at {store.lore} (no .lore/ existed here yet)")


def _build_extractor(store: LoreStore, *, harness: str):
    """Build the live LLM extractor or exit with a clear credentials error."""
    from lore.compile.extractor import LLMExtractor
    from lore.compile.llm import CredentialsError, build_complete

    try:
        return LLMExtractor(build_complete(store.load_config()), harness=harness)
    except CredentialsError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc


# --- commands -----------------------------------------------------------------


@app.command()
def init(repo: Path = RepoOpt):
    """Create the .lore/ layout in the repo."""
    store = LoreStore(repo)
    if store.is_initialised:
        store.init()  # refresh the layout and .gitignore, keep the config
        typer.echo(f"Already initialised: {store.lore}")
    else:
        store.init()
        typer.echo(f"Initialised .lore/ at {store.lore}")
    typer.echo(
        "Next: `lore watch` to compile this repo's Claude Code sessions, or "
        "`lore import-prs OWNER/REPO` to compile a repo's pull requests. "
        "Both need a model key (ANTHROPIC_API_KEY) or a local model in .lore/config.yaml."
    )


@app.command()
def status(repo: Path = RepoOpt):
    """Show claim/conflict/session counts and how much of the layer is being read."""
    store = LoreStore(repo)
    if not store.is_initialised:
        typer.echo(_INIT_HINT)
        return
    claims = store.load_claims()
    conflicts = store.load_conflicts()
    sessions = store.list_sessions()
    active = [c for c in claims if c.status == "active"]
    served = [c for c in active if c.usage.times_served > 0]
    utilization = (len(served) / len(active)) if active else 0.0

    typer.echo(f"claims:    {len(claims)} ({len(active)} active)")
    typer.echo(f"conflicts: {len(conflicts)}")
    typer.echo(f"sessions:  {len(sessions)} captured")
    typer.echo(f"utilization: {utilization:.0%} of active claims have ever been served")
    if active and utilization == 0.0:
        typer.echo(
            "  ! nothing has read these claims yet — wire `lore query` or the MCP server "
            "into your agent, or unused claims will simply age out"
        )


@app.command()
def query(
    text: str,
    repo: Path = RepoOpt,
    limit: int = typer.Option(5, "--limit", help="Maximum number of claims to return."),
):
    """Retrieve the claims most relevant to a task (records usage)."""
    store = LoreStore(repo)
    if not store.is_initialised:
        typer.echo(_INIT_HINT)
        return
    results = KnowledgeServer(store).query(text, limit=limit)
    if not results:
        typer.echo("(no relevant claims)")
        return
    for c in results:
        typer.echo(f"[{claim_label(c)}] ({c.scope}) {c.statement}  [{c.id}]")
        if c.action:
            verb = "" if c.adoption == "current" else "instead: "
            typer.echo(f"    -> {verb}{c.action}")


@app.command()
def feedback(
    claim_ids: list[str] = ClaimIdsArg,
    repo: Path = RepoOpt,
    influential: bool = typer.Option(
        False, "--influential", help="The claims shaped what you did; reinforce them."
    ),
    overridden: bool = typer.Option(
        False, "--overridden", help="The claims were wrong for this task; retire them over time."
    ),
):
    """Tell the layer whether served claims helped.

    Feedback drives the lifecycle: influential claims are reinforced, repeatedly
    overridden ones are retired.
    """
    if influential == overridden:
        typer.echo("error: pass exactly one of --influential or --overridden")
        raise typer.Exit(2)
    store = LoreStore(repo)
    if not store.is_initialised:
        typer.echo(_INIT_HINT)
        raise typer.Exit(1)
    known = {c.id for c in store.load_claims()}
    unknown = [cid for cid in claim_ids if cid not in known]
    if unknown:
        typer.echo(f"error: unknown claim id(s): {', '.join(unknown)}")
        raise typer.Exit(1)
    server = KnowledgeServer(store)
    if influential:
        server.mark_influential(claim_ids)
        typer.echo(f"marked {len(claim_ids)} claim(s) influential")
    else:
        server.mark_overridden(claim_ids)
        typer.echo(f"marked {len(claim_ids)} claim(s) overridden")


def _compile_once(
    store: LoreStore, transcript_dir: Path, *, rebuild: bool = False, adapter=None
) -> dict:
    from lore.capture.adapters.claude_code import ClaudeCodeAdapter
    from lore.compile.extractor import FatalExtractionError
    from lore.compile.run import auto_compile

    adapter = adapter or ClaudeCodeAdapter()
    extractor = _build_extractor(store, harness=adapter.name)
    settings = _compile_settings(store)
    try:
        stats = auto_compile(
            store,
            extractor,
            adapter,
            transcript_dir,
            rebuild=rebuild,
            max_unused_age=settings["max_unused_age"],
        )
    except FatalExtractionError as exc:
        # Without this the run would report success having compiled nothing.
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    stats["gate"] = dict(extractor.stats)
    return stats


def _report(stats: dict) -> None:
    gate = stats.get("gate") or {}
    if gate.get("claims_emitted"):
        typer.echo(
            f"  fidelity gate: dropped {gate['anchors_rejected']} of "
            f"{gate['anchors_emitted']} anchors and {gate['claims_rejected']} of "
            f"{gate['claims_emitted']} claims the model proposed this pass"
        )
    if failed := stats.get("failed"):
        typer.echo(
            f"  ! {failed} session(s) failed to extract and were skipped; "
            "they will be retried on the next pass"
        )


@app.command()
def compile(  # noqa: A001
    repo: Path = RepoOpt,
    transcripts: Path = TranscriptsOpt,
    rebuild: bool = RebuildOpt,
):
    """Ingest new transcripts, distill to claims + book, and prune (one pass)."""
    store = LoreStore(repo)
    _require_store(store)
    stats = _compile_once(store, _transcript_dir(store, transcripts), rebuild=rebuild)
    typer.echo(
        f"ingested {stats['ingested']} new sessions "
        f"({stats['redactions']} redactions); "
        f"{stats['active']} active claims, {stats['conflicts']} conflicts"
    )
    _report(stats)


@app.command("import-prs")
def import_prs(
    source_repo: str = typer.Argument(..., metavar="OWNER/REPO", help="GitHub repo to import."),
    repo: Path = RepoOpt,
    limit: int = typer.Option(
        50, "--limit", help="How many pull requests to scan, most recently updated first."
    ),
    state: str = typer.Option(
        "closed",
        "--state",
        help="Which pull requests to scan: closed (merged or not), open, or all.",
    ),
    all_authors: bool = typer.Option(
        False, "--all-authors", help="Import human-authored PRs too, not just agent-authored ones."
    ),
    rebuild: bool = RebuildOpt,
):
    """Compile a GitHub repo's pull-request threads into knowledge.

    Agent-authored PR threads state the intent, the alternatives weighed and the
    constraint hit, so a repo you have never run an agent in still has a usable
    knowledge layer — no local transcripts, no waiting for sessions to pile up.
    Needs the GitHub CLI (`gh auth login`); crewlore stores no token.
    """
    from lore.capture.adapters.github_pr import GitHubPRAdapter
    from lore.capture.sources.github import GitHubError, GitHubPRSource

    if state not in ("closed", "open", "all"):
        typer.echo("error: --state must be closed, open, or all")
        raise typer.Exit(2)
    store = LoreStore(repo)
    _require_store(store)
    store.ensure_gitignore()  # raw exports under .lore/sources/ are never committed
    out_dir = store.lore / "sources" / "github"
    try:
        stats = GitHubPRSource().export(
            source_repo, out_dir, limit=limit, agents_only=not all_authors, state=state
        )
    except GitHubError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc

    typer.echo(f"exported {stats['written']} PR threads from {source_repo}")
    if stats["skipped_non_agent"]:
        typer.echo(
            f"  skipped {stats['skipped_non_agent']} with no agent authorship detected "
            "(use --all-authors to include them)"
        )
    if not stats["written"]:
        return

    result = _compile_once(store, out_dir, rebuild=rebuild, adapter=GitHubPRAdapter())
    typer.echo(
        f"ingested {result['ingested']} new sessions; "
        f"{result['active']} active claims, {result['conflicts']} conflicts"
    )
    _report(result)


@app.command()
def watch(
    repo: Path = RepoOpt,
    transcripts: Path = TranscriptsOpt,
    interval: int = typer.Option(
        None,
        "--interval",
        help="Seconds between passes (default: compile.watch_interval_seconds, 300).",
    ),
    once: bool = typer.Option(False, "--once", help="Run a single pass and exit (cron mode)."),
    rebuild: bool = RebuildOpt,
):
    """Automatically compile on an interval — so nobody has to remember to.

    Extraction is cached per session, so each pass only sends newly-ingested
    sessions to the model; cost is incremental, not per-corpus-per-interval.
    """
    store = LoreStore(repo)
    _require_store(store)
    tdir = _transcript_dir(store, transcripts)
    sleep_for = interval if interval is not None else _compile_settings(store)["interval"]
    while True:
        stats = _compile_once(store, tdir, rebuild=rebuild)
        typer.echo(
            f"[watch] +{stats['ingested']} sessions, "
            f"{stats['active']} active claims, {stats['conflicts']} conflicts"
        )
        _report(stats)
        if once:
            break
        try:
            time.sleep(sleep_for)
        except KeyboardInterrupt:  # pragma: no cover
            typer.echo("stopped.")
            break


@app.command()
def serve(
    repo: Path = RepoOpt,
    mcp: bool = typer.Option(True, "--mcp", hidden=True),  # accepted for compatibility
):
    """Start the MCP server (stdio) exposing query-time retrieval to any MCP client."""
    store = LoreStore(repo)
    if not store.is_initialised:
        typer.echo(_INIT_HINT)
        raise typer.Exit(1)
    try:
        from lore.serve.mcp_server import run_mcp
    except ImportError:
        typer.echo(
            "MCP extra not installed. Fresh install: pipx install 'crewlore[serve]'  ·  "
            "existing pipx install: pipx inject crewlore mcp"
        )
        raise typer.Exit(1) from None
    run_mcp(store)


if __name__ == "__main__":
    app()
