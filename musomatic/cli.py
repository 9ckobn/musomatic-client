"""CLI commands for musomatic."""

import json
import sys
import time

import click
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from . import __version__
from .client import (
    api, api_poll, cancel_job, quality_badge, quality_short,
    API_URL, API_KEY, CONFIG_FILE,
    load_config, save_config, ensure_protocol, ApiError,
)

console = Console()

RECOMMEND_PLAYLIST = "AI Recommendations"
RECOMMEND_CLEANUP_HOURS = 24


def _handle_api_error(e: ApiError):
    console.print(f"[red]❌ {e}[/]")
    if e.status_code == 401:
        console.print("[dim]Run: musomatic setup[/]")
    raise SystemExit(1)


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="musomatic")
@click.pass_context
def cli(ctx):
    """🎵 musomatic — lossless music search & download"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(status)


@cli.command()
def status():
    """Server status and library stats."""
    try:
        api("get", "/health")
        lib = api("get", "/library/stats")
        console.print(Panel(
            f"[green]●[/] Server: {API_URL}\n"
            f"   Library: [bold]{lib['total_tracks']}[/] tracks, "
            f"{lib['total_size_gb']} GB, {lib['albums']} albums",
            title="🎵 Musomatic",
        ))
    except ApiError as e:
        _handle_api_error(e)
    except Exception as e:
        console.print(f"[red]✗ Error:[/] {e}")


@cli.command()
@click.argument("key", required=False)
@click.argument("value", required=False)
def setup(key, value):
    """Configure server connection.

    \b
    musomatic setup                    — interactive setup
    musomatic setup server_url         — show current server URL
    musomatic setup server_url https://api.example.com
    """
    import musomatic.client as client_mod
    cfg = load_config()

    if key and value:
        if key == "server_url":
            value = ensure_protocol(value)
        cfg[key] = value
        save_config(cfg)
        console.print(f"[green]✓[/] {key} = {value}")
        if key == "server_url":
            client_mod.API_URL = value
        elif key == "api_key":
            client_mod.API_KEY = value
        return

    if key:
        val = cfg.get(key, "")
        if key == "api_key" and val:
            console.print(f"{key} = {val[:8]}...")
        else:
            console.print(f"{key} = {val or '[dim]not set[/]'}")
        return

    console.print("[bold]🎵 Musomatic Setup[/]\n")

    current_url = cfg.get("server_url", "")
    prompt_default = current_url or "http://192.168.88.92:8844"
    url = console.input(f"  Server URL [{prompt_default}]: ").strip() or prompt_default
    url = ensure_protocol(url)

    console.print(f"  [dim]Checking {url}...[/]")
    try:
        with httpx.Client(base_url=url, timeout=10, follow_redirects=True) as c:
            r = c.get("/health")
            r.raise_for_status()
            h = r.json()
            console.print(f"  [green]✓[/] Connected! {h.get('tracks', '?')} tracks on server")
    except Exception as e:
        console.print(f"  [red]✗[/] Cannot connect: {e}")
        console.print(f"  [dim]Hint: API port is 8844 (not 4533, that's Navidrome)[/]")
        if not click.confirm("  Save anyway?", default=False):
            return

    cfg["server_url"] = url
    client_mod.API_URL = url

    api_key = click.prompt("  API Key", default=cfg.get("api_key", ""), show_default=False,
                           prompt_suffix=" (Enter to skip): ")
    if api_key:
        cfg["api_key"] = api_key
        client_mod.API_KEY = api_key

    save_config(cfg)
    console.print(f"\n[green]✓ Saved to {CONFIG_FILE}[/]")


@cli.command()
@click.argument("query", nargs=-1, required=True)
def search(query):
    """Search tracks. Example: musomatic search Rammstein Du Hast"""
    q = " ".join(query)
    parts = q.replace(" - ", " – ").split(" – ", 1)
    artist = parts[0].strip() if len(parts) > 1 else ""
    title = parts[1].strip() if len(parts) > 1 else parts[0].strip()

    with console.status(f"[bold]Searching: {q}"):
        try:
            data = api("post", "/search", json={
                "tracks": [{"artist": artist, "title": title}]
            })
        except ApiError as e:
            _handle_api_error(e)

    for r in data.get("results", []):
        b = r.get("best")
        console.print(f"\n  [bold]{r['artist']} — {r['title']}[/]")
        if b:
            bd = b.get("bit_depth", 0)
            sr = b.get("sample_rate", 0)
            src = b.get("source", "")
            rate = f"{sr / 1000:.1f}kHz" if sr else ""
            if bd >= 24:
                console.print(f"  [green]🟢 Hi-Res {bd}bit/{rate}[/] [{src}]")
            elif bd >= 16:
                console.print(f"  [yellow]🟡 CD {bd}bit/{rate}[/] [{src}]")
            console.print(f"  📦 {b.get('size_mb', '?')} MB  📁 {b.get('filename', '')}")
        else:
            console.print(f"  [red]❌ Not found[/]")


@cli.command()
@click.argument("query", nargs=-1, required=True)
def download(query):
    """Download a track. Example: musomatic download Metallica - Enter Sandman"""
    q = " ".join(query)
    parts = q.replace(" - ", " – ").split(" – ", 1)
    artist = parts[0].strip() if len(parts) > 1 else ""
    title = parts[1].strip() if len(parts) > 1 else parts[0].strip()

    try:
        job = api("post", "/download", json={"artist": artist, "title": title})
    except ApiError as e:
        _handle_api_error(e)

    job_id = job["job_id"]
    console.print(f"[cyan]⬇️  Downloading: {artist} — {title} ({job_id})[/]")

    j = {}
    try:
        with console.status("[bold]Searching sources...") as st:
            while True:
                time.sleep(2)
                j = api_poll(f"/jobs/{job_id}")
                if j is None:
                    console.print("[yellow]⚠ Lost connection, job continues on server[/]")
                    return
                s = j["status"]
                if s == "searching":
                    st.update(f"[bold]🔍 Searching...")
                elif s == "downloading":
                    st.update(f"[bold]⬇️  Downloading from {j.get('source', '?')}...")
                elif s in ("done", "failed"):
                    break
    except KeyboardInterrupt:
        cancel_job(job_id)
        console.print("\n[yellow]⏹ Cancelled[/]")
        return

    if j.get("status") == "done":
        r = j.get("result", {})
        console.print(f"\n[green]✅ {r.get('artist', artist)} — {r.get('title', title)}[/]")
        console.print(f"  {quality_badge(r)}")
        console.print(f"  📦 {r.get('size_mb', '?')} MB  ⏱ {j.get('elapsed_s', '?')}s")
    elif j.get("status") == "failed":
        console.print(f"[red]✗ {j.get('error', 'Unknown error')}[/]")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--limit", "-l", type=int, help="Download first N tracks only")
@click.option("--scan-only", is_flag=True, help="Only scan, don't download")
def batch(file, limit, scan_only):
    """Batch download from JSON file."""
    with open(file) as f:
        raw = json.load(f)

    if isinstance(raw, list):
        tracks = raw
    elif isinstance(raw, dict):
        tracks = raw.get("songs") or raw.get("tracks") or []
    else:
        console.print("[red]Invalid JSON format[/]")
        return

    if limit:
        tracks = tracks[:limit]

    console.print(f"[bold]📋 {len(tracks)} tracks to {'scan' if scan_only else 'download'}[/]")

    try:
        job = api("post", "/batch", json={
            "tracks": [{"artist": t.get("artist", ""), "title": t.get("title", "")} for t in tracks],
            "scan_only": scan_only,
        })
    except ApiError as e:
        _handle_api_error(e)

    job_id = job["job_id"]
    j = {}
    try:
        with console.status("[bold]Processing...") as st:
            while True:
                time.sleep(3)
                j = api_poll(f"/jobs/{job_id}")
                if j is None:
                    console.print("[yellow]⚠ Lost connection, job continues on server[/]")
                    return
                s = j["status"]
                done = j.get("done", 0)
                total = j.get("total", len(tracks))
                pct = int(done / total * 100) if total else 0
                if s == "scanning":
                    st.update(f"[bold]🔍 Scanning {done}/{total} ({pct}%)...")
                elif s == "downloading":
                    st.update(f"[bold]⬇️  Downloading {done}/{total} ({pct}%)...")
                elif s in ("done", "failed"):
                    break
    except KeyboardInterrupt:
        cancel_job(job_id)
        console.print("\n[yellow]⏹ Cancelled[/]")
        return

    if j.get("status") == "done":
        console.print(f"\n[green]✅ Batch complete[/]")
        console.print(f"  🎵 Downloaded: {j.get('downloaded', 0)}/{j.get('total', 0)}")
        console.print(f"  🔴 Not found: {j.get('not_found', 0)}")
        console.print(f"  ⏱ Time: {j.get('elapsed_s', '?')}s")
    elif j.get("status") == "failed":
        console.print(f"[red]✗ {j.get('error', '?')}[/]")


@cli.command()
def jobs():
    """List active jobs."""
    try:
        data = api("get", "/jobs")
    except ApiError as e:
        _handle_api_error(e)

    active = data.get("jobs", [])
    if not active:
        console.print("[dim]No active jobs[/]")
        return
    table = Table()
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("Progress")
    for j in active:
        prog = ""
        if "done" in j and "total" in j:
            prog = f"{j['done']}/{j['total']}"
        table.add_row(j["id"], j["status"], prog)
    console.print(table)


@cli.command()
@click.argument("query", nargs=-1)
def audit(query):
    """Audit library quality. Optional filter: musomatic audit rammstein"""
    q = " ".join(query) if query else ""
    with console.status("[bold]Auditing library quality..."):
        try:
            data = api("get", "/library/audit", timeout=300)
        except ApiError as e:
            _handle_api_error(e)

    stats = data.get("quality_stats", {})
    console.print(Panel(
        f"🟢 Hi-Res (24bit): {stats.get('hires', 0)}\n"
        f"🟡 CD (16bit): {stats.get('cd', 0)}\n"
        f"🔴 Other: {stats.get('other', 0)}",
        title="Library Quality",
    ))

    issues = data.get("issues", [])
    if q:
        q_lower = q.lower()
        issues = [i for i in issues if q_lower in f"{i['artist']} {i['title']} {i['album']}".lower()]

    if not issues:
        console.print("[green]✅ No issues found[/]")
        return

    table = Table(title=f"Issues ({len(issues)})")
    table.add_column("Artist", style="cyan")
    table.add_column("Title")
    table.add_column("Album", style="dim")
    for i in issues:
        table.add_row(i["artist"], i["title"], i["album"])
    console.print(table)


@cli.command()
def upgrade():
    """Trigger manual 16→24bit upgrade scan."""
    try:
        data = api("post", "/upgrade/trigger")
    except ApiError as e:
        _handle_api_error(e)

    job_id = data["job_id"]
    console.print(f"[cyan]Upgrade scan started: {job_id}[/]")
    j = {}
    with console.status("Scanning..."):
        while True:
            j = api_poll(f"/jobs/{job_id}")
            if not j or j["status"] in ("done", "failed"):
                break
            time.sleep(5)
    if j and j["status"] == "done":
        console.print(f"[green]✅ Upgraded {j.get('upgraded', 0)}/{j.get('candidates', 0)} tracks[/]")
    elif j:
        console.print(f"[red]Failed: {j.get('error', '?')}[/]")


@cli.command()
@click.argument("action", required=False, default="generate",
                type=click.Choice(["generate", "status", "cleanup"]))
@click.option("--provider", "-p", help="LLM provider (openai, deepseek, claude, openrouter)")
@click.option("--model", "-m", help="Override model name")
@click.option("--count", "-n", default=30, help="Number of recommendations (max 50)")
def recommend(action, provider, model, count):
    """AI music recommendations.

    \b
    musomatic recommend              # generate 30 AI recommendations
    musomatic recommend status       # check status
    musomatic recommend cleanup      # delete unrated, keep liked
    """
    if action == "status":
        try:
            data = api("get", "/recommend/status")
        except ApiError as e:
            _handle_api_error(e)
        enabled = "🟢 Enabled" if data.get("enabled") else "🔴 Disabled (manual only)"
        console.print(Panel(
            f"Status: {enabled}\n"
            f"Provider: {data.get('provider') or 'not set'}\n"
            f"Auto interval: {data.get('interval_s', 0)}s\n"
            f"Cleanup after: {data.get('cleanup_hours', 24)}h\n"
            f"Last run: {time.strftime('%H:%M:%S', time.localtime(data['last_run'])) if data.get('last_run') else 'never'}\n"
            f"Supported: {', '.join(data.get('supported_providers', []))}",
            title="🤖 AI Recommendations",
        ))
        if data.get("last_result"):
            lr = data["last_result"]
            console.print(f"  Last: {lr.get('downloaded', 0)}/{lr.get('recommended', 0)} downloaded")
        return

    if action == "cleanup":
        with console.status("Cleaning up recommendations..."):
            try:
                data = api("post", "/recommend/cleanup")
            except ApiError as e:
                _handle_api_error(e)
        if data.get("status") == "no_playlist":
            console.print("[dim]No recommendation playlist found[/]")
        else:
            console.print(f"[green]✅ Cleanup: kept {data.get('kept', 0)} rated, deleted {data.get('deleted', 0)}[/]")
        return

    body = {"count": min(count, 50)}
    if provider:
        body["provider"] = provider
    if model:
        body["model"] = model

    try:
        job = api("post", "/recommend/generate", json=body)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            console.print(f"[red]✗ {e.response.json().get('detail', str(e))}[/]")
            console.print("[dim]Set LLM_PROVIDER + LLM_API_KEY in server .env[/]")
            return
        raise
    except ApiError as e:
        _handle_api_error(e)

    job_id = job["job_id"]
    console.print(f"[cyan]🤖 Generating AI recommendations...[/]")

    j = {}
    try:
        with console.status("[bold]Analyzing library...") as st:
            while True:
                time.sleep(3)
                j = api_poll(f"/jobs/{job_id}")
                if j is None:
                    console.print("[yellow]⚠ Lost connection, job continues on server[/]")
                    return
                s = j["status"]
                if s == "generating":
                    st.update("[bold]🤖 AI is analyzing...")
                elif s == "downloading":
                    st.update(f"[bold]⬇️ Downloading {j.get('downloaded', 0)}/{j.get('recommended', 0)}")
                elif s in ("done", "failed"):
                    break
    except KeyboardInterrupt:
        cancel_job(job_id)
        return

    if j.get("status") == "done":
        console.print(f"\n[green]✅ Recommendations ready![/]")
        console.print(f"  🎵 Downloaded: {j.get('downloaded', 0)}/{j.get('recommended', 0)}")
        console.print(f"  🔴 Not found: {j.get('not_found', 0)}")
        if j.get("playlist_id"):
            console.print(f"  📋 Playlist: '{RECOMMEND_PLAYLIST}' in Navidrome")
        console.print(f"  ⏱ Time: {j.get('elapsed_s', '?')}s")
        console.print(f"\n[dim]Rate tracks in Navidrome/Amperfy to keep them.[/]")
        console.print(f"[dim]Unrated auto-delete after {RECOMMEND_CLEANUP_HOURS}h[/]")
    elif j.get("status") == "failed":
        console.print(f"[red]✗ {j.get('error', '?')}[/]")


@cli.command("ls")
@click.argument("query", nargs=-1)
def list_tracks(query):
    """List library tracks. Optional search: musomatic ls rammstein"""
    q = " ".join(query) if query else ""
    try:
        data = api("get", "/library/tracks", params={"q": q} if q else {})
    except ApiError as e:
        _handle_api_error(e)

    tracks = data["tracks"]
    if not tracks:
        console.print("[dim]Nothing found[/]")
        return
    table = Table(show_lines=False)
    table.add_column("ID", style="bold", width=4)
    table.add_column("Artist", style="cyan")
    table.add_column("Title")
    table.add_column("Album", style="dim")
    table.add_column("Quality", style="green")
    table.add_column("MB", style="dim", justify="right")
    for t in tracks:
        q_str = quality_short(t.get("bit_depth", 0), t.get("sample_rate", 0))
        table.add_row(str(t["id"]), t["artist"], t["title"], t["album"], q_str, str(t["size_mb"]))
    console.print(table)
    console.print(f"[dim]Total: {data['total']}[/]")


@cli.command("rm")
@click.argument("query", nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation")
def delete_tracks(query, yes):
    """Delete tracks by ID or search.

    \b
    musomatic rm 5 12 23       # delete by IDs
    musomatic rm rammstein     # delete by search
    musomatic rm rammstein -y  # skip confirmation
    """
    ids = []
    try:
        ids = [int(x) for x in query]
    except ValueError:
        pass

    try:
        if ids:
            all_data = api("get", "/library/tracks")
            id_set = set(ids)
            tracks = [t for t in all_data["tracks"] if t["id"] in id_set]
        else:
            q = " ".join(query)
            data = api("get", "/library/tracks", params={"q": q})
            tracks = data["tracks"]
    except ApiError as e:
        _handle_api_error(e)

    if not tracks:
        console.print("[dim]Nothing found[/]")
        return

    console.print(f"[yellow]Will delete {len(tracks)} track(s):[/]")
    for t in tracks:
        console.print(f"  🗑 [bold]{t['id']}[/]  {t['artist']} — {t['title']}  [dim]({t['size_mb']} MB)[/]")

    if not yes:
        if not click.confirm("\nConfirm delete?"):
            console.print("[dim]Cancelled[/]")
            return

    try:
        if ids:
            result = api("post", "/library/delete", json={"ids": ids})
        else:
            result = api("post", "/library/delete", json={"query": " ".join(query)})
    except ApiError as e:
        _handle_api_error(e)

    console.print(f"[green]{result['message']}[/]")


@cli.command()
def tui():
    """Open interactive TUI for library management."""
    try:
        from .tui import run_tui
    except ImportError:
        console.print("[red]TUI requires textual: pip install textual[/]")
        return
    run_tui()


if __name__ == "__main__":
    cli()
