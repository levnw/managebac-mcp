"""
ManageBac MCP CLI
Usage: managebac-mcp <command>
"""
import json
import os
import sys
from pathlib import Path

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="managebac-mcp",
    help="ManageBac MCP server — Claude, ChatGPT, and more.",
    no_args_is_help=True,
)
console = Console()


# ---------------------------------------------------------------------------
# setup — interactive credential setup + install to Claude Desktop
# ---------------------------------------------------------------------------

@app.command()
def setup():
    """Interactive first-time setup — enter credentials and install to Claude Desktop."""
    rprint(Panel.fit(
        "[bold]ManageBac MCP Setup[/bold]\n"
        "This will save your credentials and register the server with Claude Desktop.",
        border_style="blue"
    ))

    config_dir = Path.home() / ".managebac_mcp"
    config_dir.mkdir(exist_ok=True)
    env_file = config_dir / ".env"

    url = typer.prompt("ManageBac URL", default="https://es.managebac.com")
    email = typer.prompt("Email")
    password = typer.prompt("Password", hide_input=True)

    env_file.write_text(
        f"MANAGEBAC_URL={url}\n"
        f"MANAGEBAC_EMAIL={email}\n"
        f"MANAGEBAC_PASSWORD={password}\n"
    )
    rprint(f"[green]✓[/green] Credentials saved to {env_file}")

    rprint("Testing login...")
    try:
        import asyncio
        from .auth import get_client, login
        async def _test():
            async with await get_client() as client:
                await login(client)
        asyncio.run(_test())
        rprint("[green]✓[/green] Login successful")
    except Exception as e:
        rprint(f"[red]✗[/red] Login failed: {e}")
        rprint("Check your credentials and try again.")
        raise typer.Exit(1)

    project_root = Path(__file__).parent.parent
    _install_claude_desktop(project_root)

    rprint(Panel.fit(
        "[green]Setup complete![/green]\n\n"
        "• [bold]Claude Desktop[/bold]: Restart Claude Desktop — tools will appear automatically\n"
        "• [bold]Peek raw data[/bold]: Run [cyan]managebac-mcp peek classes[/cyan]",
        border_style="green"
    ))


def _install_claude_desktop(project_root: Path):
    """Write the Claude Desktop MCP config entry."""
    python = project_root / ".venv" / "bin" / "python3"
    if not python.exists():
        python = project_root / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)

    config_paths = [
        Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        Path.home() / ".config" / "claude" / "claude_desktop_config.json",
        Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json",
    ]

    config_path = next((p for p in config_paths if p.parent.exists()), None)
    if not config_path:
        rprint("[yellow]⚠[/yellow] Claude Desktop config directory not found — skipping auto-install.")
        return

    existing = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except Exception:
            pass

    if "mcpServers" not in existing:
        existing["mcpServers"] = {}

    existing["mcpServers"]["managebac"] = {
        "command": str(python),
        "args": ["-m", "managebac_mcp.server"],
    }

    config_path.write_text(json.dumps(existing, indent=2))
    rprint(f"[green]✓[/green] Registered with Claude Desktop ({config_path.name})")
    rprint("  [dim]Restart Claude Desktop to activate[/dim]")


# ---------------------------------------------------------------------------
# install — re-run just the Claude Desktop registration
# ---------------------------------------------------------------------------

@app.command()
def install():
    """Register this server with Claude Desktop (re-run if it stopped showing up)."""
    project_root = Path(__file__).parent.parent
    _install_claude_desktop(project_root)
    rprint("[dim]Restart Claude Desktop to see the tools.[/dim]")


# ---------------------------------------------------------------------------
# peek — print raw JSON that the AI receives for any tool
# ---------------------------------------------------------------------------

@app.command()
def peek(
    tool: str = typer.Argument(
        help="Tool to call: classes | timetable | tasks | task | units | files | journal | find | file-content"
    ),
    class_id: str = typer.Option(None, "--class", "-c", help="Class ID (needed for tasks / task / files / journal)"),
    task_id:  str = typer.Option(None, "--task",  "-t", help="Task ID  (needed for task)"),
    query:    str = typer.Option(None, "--query", "-q", help="Search query (needed for find)"),
    url:      str = typer.Option(None, "--url",   "-u", help="File URL (needed for file-content)"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass cache and force a fresh scrape"),
):
    """
    Print the raw JSON that the AI receives when it calls a tool.

    Examples:

    \b
      managebac-mcp peek classes
      managebac-mcp peek timetable
      managebac-mcp peek tasks        --class 12345
      managebac-mcp peek task         --class 12345 --task 67890
      managebac-mcp peek units        --class 12345
      managebac-mcp peek files        --class 12345
      managebac-mcp peek journal      --class 12345
      managebac-mcp peek find         --query "biology essay"
      managebac-mcp peek find         --query "https://es.managebac.com/..."
      managebac-mcp peek file-content --url "https://es.managebac.com/attachments/..."
    """
    import asyncio
    from . import scraper, cache as _cache

    # Optional: wipe the relevant cache key before fetching
    if no_cache:
        key_map = {
            "classes":  "get_classes",
            "timetable":"get_timetable",
            "tasks":    f"get_tasks:{class_id}",
            "task":     f"get_task_detail:{class_id}:{task_id}",
            "units":    f"get_units:{class_id}",
            "files":    f"get_files:{class_id}",
            "journal":  f"get_journal:{class_id}",
        }
        if tool in key_map:
            _cache.invalidate(key_map[tool])

    async def _run():
        if tool == "classes":
            return await scraper.fetch_classes()
        elif tool == "timetable":
            return await scraper.fetch_timetable()
        elif tool == "tasks":
            if not class_id:
                rprint("[red]--class is required for 'tasks'[/red]"); raise typer.Exit(1)
            return await scraper.fetch_tasks(class_id)
        elif tool == "task":
            if not class_id or not task_id:
                rprint("[red]--class and --task are required for 'task'[/red]"); raise typer.Exit(1)
            return await scraper.fetch_task_detail(class_id, task_id)
        elif tool == "units":
            if not class_id:
                rprint("[red]--class is required for 'units'[/red]"); raise typer.Exit(1)
            return await scraper.fetch_units(class_id)
        elif tool == "file-content":
            if not url:
                rprint("[red]--url is required for 'file-content'[/red]"); raise typer.Exit(1)
            file = await scraper.fetch_file_bytes(url)
            # Don't dump raw bytes — show metadata summary
            return {
                "content_type": file["content_type"],
                "size_bytes": file["size_bytes"],
                "size_human": f"{file['size_bytes'] / 1024:.1f} KB",
                "error": file["error"],
                "cached_to_disk": file["error"] is None,
            }
        elif tool == "files":
            if not class_id:
                rprint("[red]--class is required for 'files'[/red]"); raise typer.Exit(1)
            return await scraper.fetch_files(class_id)
        elif tool == "journal":
            if not class_id:
                rprint("[red]--class is required for 'journal'[/red]"); raise typer.Exit(1)
            return await scraper.fetch_journal(class_id)
        elif tool == "find":
            if not query:
                rprint("[red]--query is required for 'find'[/red]"); raise typer.Exit(1)
            result = await scraper.find_task(query)
            return result if result is not None else {"error": "Task not found"}
        else:
            rprint(f"[red]Unknown tool: {tool}[/red]")
            rprint("Choose from: classes | timetable | tasks | task | units | files | journal | find | file-content")
            raise typer.Exit(1)

    result = asyncio.run(_run())
    print(json.dumps(result, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# mcp — run the stdio MCP server (Claude Desktop calls this automatically)
# ---------------------------------------------------------------------------

@app.command()
def submit(
    class_id: str = typer.Option(..., "--class", "-c", help="Class ID"),
    task_id:  str = typer.Option(..., "--task",  "-t", help="Task ID"),
    file:     str = typer.Option(..., "--file",  "-f", help="Path to the file to submit"),
    yes:      bool = typer.Option(False, "--yes", "-y", help="Skip dry-run confirmation and submit immediately"),
):
    """
    Submit a file to a ManageBac task's dropbox.

    \b
    Always does a dry-run first so you can confirm before uploading.
    Use --yes to skip the confirmation prompt.

    \b
      managebac-mcp submit --class 12734244 --task 48220527 --file ~/Documents/essay.pdf
    """
    import asyncio
    from . import scraper

    async def _run(dry: bool):
        return await scraper.submit_task_file(class_id, task_id, file, dry_run=dry)

    # Dry run first
    preview = asyncio.run(_run(dry=True))
    if not preview.get("dry_run"):
        rprint(f"[red]Error:[/red] {preview.get('error', 'Unknown error')}")
        raise typer.Exit(1)

    w = preview["would_submit"]
    rprint(Panel.fit(
        f"[bold]About to submit:[/bold]\n\n"
        f"  File:  [cyan]{w['filename']}[/cyan]  ({w['size_bytes'] / 1024:.1f} KB)\n"
        f"  Type:  {w['mime_type']}\n"
        f"  Task:  [cyan]{w['to_task']}[/cyan]",
        border_style="yellow", title="Confirm Submission"
    ))

    if not yes:
        confirmed = typer.confirm("Submit this file?")
        if not confirmed:
            rprint("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

    result = asyncio.run(_run(dry=False))
    if result.get("success"):
        rprint(f"[green]✓[/green] Submitted [bold]{result['file']}[/bold]")
        rprint(f"  View task: [cyan]{result['task_url']}[/cyan]")
    else:
        rprint(f"[red]✗[/red] Submission failed: {result.get('error')}")
        if result.get("server_response"):
            rprint(f"[dim]{result['server_response'][:200]}[/dim]")
        raise typer.Exit(1)


@app.command(hidden=True)
def mcp_stdio():
    """Run the stdio MCP server (called automatically by Claude Desktop)."""
    import asyncio
    from .server import main
    asyncio.run(main())


# ---------------------------------------------------------------------------
# cache — inspect the local cache from the terminal
# ---------------------------------------------------------------------------

@app.command()
def cache_view():
    """Show all cached data in the terminal."""
    from . import cache as _cache
    entries = _cache.get_cache_entries()
    if not entries:
        rprint("[dim]Cache is empty.[/dim]")
        return

    table = Table(title="ManageBac Cache", show_lines=True)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Expires in", style="green")
    table.add_column("Items", justify="right")

    for e in entries:
        mins = e["expires_in_s"] // 60
        expiry = f"{mins}m" if not e["expired"] else "[red]expired[/red]"
        val = e["data"]
        count = str(len(val)) if isinstance(val, list) else "1"
        table.add_row(e["key"], expiry, count)

    console.print(table)


if __name__ == "__main__":
    app()
