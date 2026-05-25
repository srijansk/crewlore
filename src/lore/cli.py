"""`lore` — the single user-facing surface.

    lore init       create .lore/ and detect the harness
    lore compile    distill captured sessions -> claims + knowledge book
    lore query      task-conditioned retrieval (instruments usage)
    lore status     counts + actuation health (so you can see the dumpyard early)
    lore serve      MCP server for query-time retrieval
"""

from __future__ import annotations

from pathlib import Path

import typer

from lore.serve.server import KnowledgeServer
from lore.store import LoreStore

app = typer.Typer(help="Compile coding-agent sessions into team tribal knowledge, locally.")

RepoOpt = typer.Option(Path("."), "--repo", help="Path to the team repo root.")


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


@app.command()
def compile(repo: Path = RepoOpt):  # noqa: A001 - matches the user-facing verb
    """Distill captured sessions into claims and the knowledge book."""
    from lore.compile.extractor import LLMExtractor
    from lore.compile.llm import CredentialsError, build_complete
    from lore.compile.run import run_compile

    store = LoreStore(repo)
    try:
        complete = build_complete(store.load_config())
    except CredentialsError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc

    result = run_compile(store, LLMExtractor(complete))
    typer.echo(f"compiled {len(result.claims)} claims, {len(result.conflicts)} conflicts")


@app.command()
def serve(repo: Path = RepoOpt):
    """Start the MCP server exposing query-time retrieval."""
    try:
        from lore.serve.mcp_server import run_mcp
    except ImportError:
        typer.echo("MCP extra not installed. Install with: pipx install 'agent-lore[serve]'")
        raise typer.Exit(1) from None
    run_mcp(LoreStore(repo))


if __name__ == "__main__":
    app()
