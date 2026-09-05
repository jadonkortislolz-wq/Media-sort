"""Command-line interface for Media Sorter.

Provides intuitive commands for scanning, dry-run simulation, live atomic organization,
transactional rollback, quarantine resolution, and web dashboard hosting.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from .config import ActionType, Settings
from .db import get_db_session, init_db
from .models import BatchRecord, Operation, QuarantineRecord, QuarantineStatus
from .quarantine import QuarantineManager
from .sorter import MediaSorterApp

app = typer.Typer(
    name="media-sorter",
    help="Reliable, high-performance media sorter with atomic moves, dry-runs, and rollback.",
    add_completion=False,
)
quarantine_app = typer.Typer(help="Manage quarantined or low-confidence review files.")
config_app = typer.Typer(help="Inspect or initialize configuration.")

app.add_typer(quarantine_app, name="quarantine")
app.add_typer(config_app, name="config")

console = Console()


def load_settings_or_default(config_path: Optional[Path] = None) -> Settings:
    if config_path and config_path.is_file():
        if config_path.suffix in (".env", "") and "env" in config_path.name:
            return Settings.load_from_env_file(config_path)
        return Settings.load_from_file(config_path)

    # Check if .env exists in current working directory
    env_file = Path(".env")
    if env_file.is_file():
        return Settings.load_from_env_file(env_file)

    # Search standard configuration paths
    for cand in ("config.yaml", "config.yml", "config.toml", "media-sorter.yaml"):
        p = Path(cand)
        if p.is_file():
            return Settings.load_from_file(p)

    return Settings()


@app.command()
def scan(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file"),
    source: Optional[Path] = typer.Option(None, "--source", "-s", help="Override source directory"),
):
    """Scan source directories and display media classification preview without moving any files."""
    settings = load_settings_or_default(config)
    if source:
        settings.storage.source_dirs = [str(source)]

    engine = init_db(db_path=settings.get_database_path())
    sorter = MediaSorterApp(settings, engine)

    console.print(Panel(f"[bold cyan]Scanning sources:[/bold cyan] {', '.join(settings.storage.source_dirs)}", title="Media Sorter Discovery"))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("[green]Analyzing media...", total=None)

        def on_prog(curr, total, name):
            progress.update(task, total=total, completed=curr, description=f"[cyan]Probing: {name[:30]}")

        results = sorter.scan_and_analyze(progress_callback=on_prog)

    if not results:
        console.print("[yellow]No qualifying files found in source directories.[/yellow]")
        return

    table = Table(title=f"Discovered Media Items ({len(results)} total)")
    table.add_column("Filename", style="bold", overflow="fold")
    table.add_column("Category", style="cyan")
    table.add_column("Confidence", justify="right")
    table.add_column("Status", justify="center")

    for scanned, cls_res in results[:50]:
        conf_pct = f"{int(cls_res.confidence * 100)}%"
        if cls_res.needs_quarantine:
            status_style = "[red]QUARANTINE[/red]"
        elif cls_res.confidence >= 0.85:
            status_style = "[green]HIGH CONF[/green]"
        else:
            status_style = "[yellow]MEDIUM[/yellow]"

        table.add_row(scanned.path.name, cls_res.category, conf_pct, status_style)

    console.print(table)
    if len(results) > 50:
        console.print(f"[dim]... and {len(results) - 50} more items.[/dim]")


@app.command()
def organize(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file"),
    dry_run: bool = typer.Option(True, "--dry-run/--live", help="Safety preview mode (default: True)"),
    source: Optional[Path] = typer.Option(None, "--source", "-s", help="Override source directory"),
    dest: Optional[Path] = typer.Option(None, "--dest", "-d", help="Override destination directory"),
    action: Optional[ActionType] = typer.Option(None, "--action", "-a", help="Action (move, copy, link, hardlink)"),
    threshold: Optional[float] = typer.Option(None, "--threshold", "-t", help="Confidence threshold (0.0-1.0)"),
    interval: Optional[int] = typer.Option(None, "--interval", "-i", help="Continuous scan interval in seconds"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Run continuously in watch/daemon mode"),
):
    """Execute media organization or generate a dry-run preview."""
    import time
    settings = load_settings_or_default(config)
    if source:
        settings.storage.source_dirs = [str(source)]
    if dest:
        settings.storage.destination_base = str(dest)
    if action:
        settings.general.action = action
    if threshold:
        settings.general.confidence_threshold = threshold

    loop_interval = interval or (settings.general.scan_interval_seconds if settings.general.scan_interval_seconds > 0 else (60 if watch else 0))

    engine = init_db(db_path=settings.get_database_path())
    sorter = MediaSorterApp(settings, engine)

    mode_label = "[bold yellow]DRY-RUN PREVIEW[/bold yellow]" if dry_run else "[bold red]LIVE EXECUTION[/bold red]"

    while True:
        console.print(Panel(f"Mode: {mode_label} | Action: {settings.general.action.value.upper()}", title="Media Sorter"))
        start_t = time.time()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[green]Processing...", total=None)

            def on_prog(curr, total, name):
                progress.update(task, total=total, completed=curr, description=f"Processing: {name[:30]}")

            report = sorter.run(dry_run=dry_run, progress_callback=on_prog)

        elapsed = max(time.time() - start_t, 0.001)
        throughput = round(report.total_files / elapsed, 1)

        # Print summary table
        summary_table = Table(title=f"Batch Summary [{report.batch_id[:8]}]")
        summary_table.add_column("Metric", style="bold")
        summary_table.add_column("Count", justify="right")

        summary_table.add_row("Total Processed", str(report.total_files))
        summary_table.add_row("Moved / Organized", f"[green]{report.moved_files}[/green]")
        summary_table.add_row("Copied", f"[blue]{report.copied_files}[/blue]")
        summary_table.add_row("Linked", f"[cyan]{report.linked_files}[/cyan]")
        summary_table.add_row("Skipped (Conflicts / Existing)", f"[dim]{report.skipped_files}[/dim]")
        summary_table.add_row("Quarantined (Review Queue)", f"[yellow]{report.quarantined_files}[/yellow]")
        summary_table.add_row("Failures", f"[red]{report.failed_files}[/red]")
        summary_table.add_row("Throughput", f"{throughput} files/sec ({round(elapsed, 2)}s)")

        console.print(summary_table)

        if dry_run:
            console.print("\n[bold cyan]Safe dry-run complete. No files were modified on disk.[/bold cyan]")
            console.print("[dim]To apply these changes live, rerun with --live.[/dim]")

        if loop_interval <= 0:
            break

        console.print(f"\n[cyan]Sleeping for {loop_interval}s until next scan cycle (press Ctrl+C to stop)...[/cyan]")
        try:
            time.sleep(loop_interval)
        except KeyboardInterrupt:
            console.print("\n[yellow]Daemon watch loop stopped by user.[/yellow]")
            break


@app.command()
def rollback(
    batch_id: Optional[str] = typer.Option(None, "--batch-id", "-b", help="Specific batch ID to roll back"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file"),
):
    """Roll back a previous organization batch, restoring moved files to original sources."""
    settings = load_settings_or_default(config)
    engine = init_db(db_path=settings.get_database_path())
    sorter = MediaSorterApp(settings, engine)

    with console.status("[bold yellow]Executing transactional rollback...[/bold yellow]"):
        reverted = sorter.rollback(batch_id)

    if reverted > 0:
        console.print(f"[bold green]Successfully rolled back {reverted} file operations.[/bold green]")
    else:
        console.print("[yellow]No operations were reverted (batch already rolled back or not found).[/yellow]")


@app.command()
def history(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of past batches to display"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file"),
):
    """Display history of past organization batches and execution logs."""
    settings = load_settings_or_default(config)
    engine = init_db(db_path=settings.get_database_path())

    with get_db_session(engine) as session:
        batches = session.query(BatchRecord).order_by(BatchRecord.created_at.desc()).limit(limit).all()
        if not batches:
            console.print("[dim]No batch records found.[/dim]")
            return

        table = Table(title=f"Execution History (Last {len(batches)})")
        table.add_column("Batch ID", style="bold")
        table.add_column("Date", style="dim")
        table.add_column("Mode")
        table.add_column("Status")
        table.add_column("Total", justify="right")
        table.add_column("Moved", justify="right")
        table.add_column("Quarantined", justify="right")

        for b in batches:
            mode = "[dim]Dry-Run[/dim]" if b.dry_run else "[bold]Live[/bold]"
            status = f"[green]{b.status}[/green]" if b.status == "COMPLETED" else f"[yellow]{b.status}[/yellow]"
            date_str = b.created_at.strftime("%Y-%m-%d %H:%M") if b.created_at else "-"
            table.add_row(b.id[:8], date_str, mode, status, str(b.total_files), str(b.moved_files), str(b.quarantined_files))

        console.print(table)


@quarantine_app.command("list")
def quarantine_list(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file"),
):
    """List pending items requiring manual review."""
    settings = load_settings_or_default(config)
    engine = init_db(db_path=settings.get_database_path())

    with get_db_session(engine) as session:
        qm = QuarantineManager(session)
        items = qm.list_pending()
        if not items:
            console.print("[green]Quarantine queue is empty. All media classified cleanly![/green]")
            return

        table = Table(title=f"Quarantine Review Queue ({len(items)} items)")
        table.add_column("ID", justify="right")
        table.add_column("File Path", overflow="fold")
        table.add_column("Suggested", style="cyan")
        table.add_column("Confidence", justify="right")
        table.add_column("Reason", style="yellow")

        for q in items:
            conf = f"{int((q.confidence or 0) * 100)}%"
            table.add_row(str(q.id), q.src, q.suggested_category or "unknown", conf, q.reason)

        console.print(table)


@quarantine_app.command("resolve")
def quarantine_resolve(
    item_id: int = typer.Argument(..., help="Quarantine record ID to resolve"),
    category: str = typer.Option(..., "--category", "-cat", help="Target category (movie, tv, music, etc.)"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file"),
):
    """Manually classify and resolve a quarantined item."""
    settings = load_settings_or_default(config)
    engine = init_db(db_path=settings.get_database_path())

    with get_db_session(engine) as session:
        qm = QuarantineManager(session)
        success = qm.resolve_item(item_id, category)
        if success:
            console.print(f"[green]Successfully resolved item #{item_id} as {category}.[/green]")
        else:
            console.print(f"[red]Quarantine item #{item_id} not found.[/red]")


@app.command()
def server(
    host: Optional[str] = typer.Option(None, "--host", "-h", help="Bind host (default from .env or 0.0.0.0)"),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Bind port (default from .env or 8080)"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file"),
):
    """Launch web dashboard and management server."""
    settings = load_settings_or_default(config)
    from .server import create_app
    bind_host = host or settings.server.host or "0.0.0.0"
    bind_port = port or settings.server.port or 8080
    web_app = create_app(settings)
    console.print(f"[bold green]Starting Media Sorter Dashboard on http://{bind_host}:{bind_port}[/bold green]")
    uvicorn.run(web_app, host=bind_host, port=bind_port)


@config_app.command("show")
def config_show(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file"),
):
    """Print effective configuration settings."""
    settings = load_settings_or_default(config)
    import yaml
    console.print(yaml.dump(settings.model_dump(mode="json"), default_flow_style=False, sort_keys=False))


@config_app.command("init")
def config_init(
    output: Path = typer.Option(Path("media-sorter.yaml"), "--output", "-o", help="Target config file path"),
):
    """Create a safe starter configuration file."""
    if output.exists():
        console.print(f"[yellow]Configuration file already exists at {output}. Aborting.[/yellow]")
        return
    settings = Settings()
    settings.dump_yaml(output)
    console.print(f"[green]Created default configuration file at {output}.[/green]")


if __name__ == "__main__":
    app()
