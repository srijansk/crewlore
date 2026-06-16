"""`lore` — the single user-facing surface.

    lore init       create .lore/ and detect the harness
    lore compile    ingest new transcripts -> distill -> prune (one pass)
    lore watch      do that automatically on an interval (--once for cron)
    lore query      task-conditioned retrieval (instruments usage)
    lore status     counts + actuation health (so you can see the dumpyard early)
    lore serve      MCP server for query-time retrieval
"""

from __future__ import annotations

import time
from pathlib import Path

import typer

from lore import __version__
from lore.serve.server import KnowledgeServer
from lore.store import LoreStore

app = typer.Typer(help="Compile coding-agent sessions into team tribal knowledge, locally.")

RepoOpt = typer.Option(Path("."), "--repo", help="Path to the team repo root.")
TranscriptsOpt = typer.Option(None, "--transcripts", help="Override the transcripts dir.")


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
    """Compile coding-agent sessions into team tribal knowledge, locally."""


def _transcript_dir(store: LoreStore, override: Path | None) -> Path:
    if override is not None:
        return override
    cfg = store.load_config().get("capture", {}) or {}
    return Path(cfg.get("transcripts", "~/.claude/projects")).expanduser()


def _build_extractor(store: LoreStore):
    """Build the live LLM extractor or exit with a clear credentials error."""
    from lore.compile.extractor import LLMExtractor
    from lore.compile.llm import CredentialsError, build_complete

    try:
        return LLMExtractor(build_complete(store.load_config()))
    except CredentialsError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc


@app.command()
def init(repo: Path = RepoOpt):
    """Create the .lore/ layout in the repo."""
    store = LoreStore(repo)
    store.init()
    typer.echo(f"Initialised .lore/ at {store.lore}")


@app.command()
def status(repo: Path = RepoOpt):
    """Show claim/conflict/session counts and actuation health."""
    store = LoreStore(repo)
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
            "  ! nothing served yet — a growing, unused store is the dumpyard signal"
        )


@app.command()
def query(text: str, repo: Path = RepoOpt, limit: int = 5):
    """Retrieve the claims most relevant to a task (records usage)."""
    store = LoreStore(repo)
    results = KnowledgeServer(store).query(text, limit=limit)
    if not results:
        typer.echo("(no relevant claims)")
        return
    for c in results:
        typer.echo(f"[{c.kind}] ({c.scope}) {c.statement}")
        if c.action:
            typer.echo(f"    -> {c.action}")


def _compile_once(store: LoreStore, transcript_dir: Path, *, rebuild: bool = False) -> dict:
    from lore.capture.adapters.claude_code import ClaudeCodeAdapter
    from lore.compile.run import auto_compile

    extractor = _build_extractor(store)
    return auto_compile(store, extractor, ClaudeCodeAdapter(), transcript_dir, rebuild=rebuild)


@app.command()
def compile(  # noqa: A001
    repo: Path = RepoOpt,
    transcripts: Path = TranscriptsOpt,
    rebuild: bool = typer.Option(
        False, "--rebuild", help="Ignore the extraction cache and re-extract all sessions."
    ),
):
    """Ingest new transcripts, distill to claims + book, and prune (one pass)."""
    store = LoreStore(repo)
    stats = _compile_once(store, _transcript_dir(store, transcripts), rebuild=rebuild)
    typer.echo(
        f"ingested {stats['ingested']} new sessions "
        f"({stats['redactions']} redactions); "
        f"{stats['active']} active claims, {stats['conflicts']} conflicts"
    )


@app.command()
def watch(
    repo: Path = RepoOpt,
    transcripts: Path = TranscriptsOpt,
    interval: int = typer.Option(300, "--interval", help="Seconds between passes."),
    once: bool = typer.Option(False, "--once", help="Run a single pass and exit (cron mode)."),
    rebuild: bool = typer.Option(
        False, "--rebuild", help="Ignore the extraction cache and re-extract all sessions."
    ),
):
    """Automatically compile on an interval — so nobody has to remember to.

    Extraction is cached per session, so each pass only sends newly-ingested
    sessions to the model; cost is incremental, not per-corpus-per-interval.
    """
    store = LoreStore(repo)
    tdir = _transcript_dir(store, transcripts)
    while True:
        stats = _compile_once(store, tdir, rebuild=rebuild)
        typer.echo(
            f"[watch] +{stats['ingested']} sessions, "
            f"{stats['active']} active claims, {stats['conflicts']} conflicts"
        )
        if once:
            break
        try:
            time.sleep(interval)
        except KeyboardInterrupt:  # pragma: no cover
            typer.echo("stopped.")
            break


@app.command()
def serve(
    repo: Path = RepoOpt,
    mcp: bool = typer.Option(
        True, "--mcp", help="Run as an MCP server over stdio (the only mode today)."
    ),
):
    """Start the MCP server exposing query-time retrieval to any MCP client."""
    if not mcp:  # reserved for future non-MCP serve modes
        typer.echo("Only MCP serving is supported today; run without --no-mcp.")
        raise typer.Exit(1)
    try:
        from lore.serve.mcp_server import run_mcp
    except ImportError:
        typer.echo("MCP extra not installed. Install with: pipx install 'crewlore[serve]'")
        raise typer.Exit(1) from None
    run_mcp(LoreStore(repo))


if __name__ == "__main__":
    app()
