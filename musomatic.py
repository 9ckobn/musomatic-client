#!/usr/bin/env python3
"""
musomatic — lossless music CLI client.

Thin client for the musomatic API server.
"""
import json
import os
import sys
import time
from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

CONFIG_DIR = Path.home() / ".config" / "musomatic"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load_config() -> dict:
    """Load config from ~/.config/musomatic/config.json"""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_config(cfg: dict):
    """Save config to ~/.config/musomatic/config.json"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


_cfg = _load_config()
API_URL = os.getenv("MUSIC_API_URL") or _cfg.get("server_url") or "http://localhost:8844"
API_KEY = os.getenv("MUSIC_API_KEY") or _cfg.get("api_key") or ""


def _headers() -> dict:
    if API_KEY:
        return {"x-api-key": API_KEY}
    return {}


def api(method: str, path: str, **kwargs) -> dict:
    try:
        with httpx.Client(base_url=API_URL, timeout=600, headers=_headers()) as c:
            r = getattr(c, method)(path, **kwargs)
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        console.print(f"[red]❌ Сервер недоступен:[/] {API_URL}")
        console.print("[dim]Проверь: контейнер запущен? URL правильный?[/]")
        raise SystemExit(1)
    except httpx.TimeoutException:
        console.print(f"[red]❌ Таймаут подключения к[/] {API_URL}")
        raise SystemExit(1)


def api_poll(path: str, retries: int = 20) -> dict | None:
    for attempt in range(retries):
        try:
            return api("get", path)
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ReadError,
                httpx.ConnectError, httpx.RemoteProtocolError) as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                console.print(f"[red]Server unreachable after {retries} retries: {e}[/]")
                return None


def cancel_job(job_id: str):
    try:
        api("post", f"/jobs/{job_id}/cancel")
        console.print(f"\n[yellow]⏹ Cancel sent — already-downloaded files are kept[/]")
    except Exception:
        pass


def quality_badge(result: dict) -> str:
    if not result:
        return "[red]NOT FOUND[/]"
    bd = result.get("bit_depth", 0)
    sr = result.get("sample_rate", 0)
    src = result.get("source", "")
    rate = f"{sr / 1000:.1f}kHz" if sr else ""
    if bd >= 24:
        return f"[green]🟢 Hi-Res {bd}bit/{rate}[/] [{src}]"
    elif bd >= 16:
        return f"[yellow]🟡 CD {bd}bit/{rate}[/] [{src}]"
    return f"[dim]{result.get('quality_label', '?')}[/] [{src}]"


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """🎵 musomatic — lossless music search & download"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(status)


@cli.command()
def status():
    """Server status and library stats."""
    try:
        h = api("get", "/health")
        lib = api("get", "/library/stats")
        console.print(Panel(
            f"[green]●[/] Server: {API_URL}\n"
            f"   Music dir: {h['music_dir']}\n"
            f"   Library: [bold]{lib['total_tracks']}[/] tracks, "
            f"{lib['total_size_gb']} GB, {lib['albums']} albums",
            title="🎵 Musomatic",
        ))
    except Exception as e:
        console.print(f"[red]✗ Server unreachable:[/] {e}")
        if API_URL == "http://localhost:8844":
            console.print("[dim]Запусти [bold]musomatic setup[/bold] для настройки адреса сервера[/]")


@cli.command()
@click.argument("key", required=False)
@click.argument("value", required=False)
def setup(key, value):
    """Configure server connection.

    \b
    musomatic setup              — interactive setup
    musomatic setup server_url   — show current server URL
    musomatic setup server_url http://192.168.88.92:8844
    """
    global API_URL, API_KEY
    cfg = _load_config()

    if key and value:
        cfg[key] = value
        _save_config(cfg)
        console.print(f"[green]✓[/] {key} = {value}")
        if key == "server_url":
            API_URL = value
        return

    if key:
        console.print(f"{key} = {cfg.get(key, '[dim]not set[/]')}")
        return

    # Interactive setup
    console.print("[bold]🎵 Musomatic Setup[/]\n")

    current_url = cfg.get("server_url", "")
    prompt_default = current_url or "http://192.168.88.92:8844"
    url = console.input(f"  Server URL [{prompt_default}]: ").strip() or prompt_default

    # Auto-add http:// if no protocol
    if url and not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
        console.print(f"  [dim]→ Добавлен протокол: {url}[/]")

    # Test connection (follow redirects)
    console.print(f"  [dim]Проверяю {url}...[/]")
    try:
        with httpx.Client(base_url=url, timeout=10, follow_redirects=True) as c:
            r = c.get("/health")
            r.raise_for_status()
            h = r.json()
            console.print(f"  [green]✓[/] Подключено! {h.get('tracks_on_disk', '?')} треков на сервере")
    except Exception as e:
        console.print(f"  [red]✗[/] Не удалось подключиться: {e}")
        console.print(f"  [dim]Подсказка: API порт по умолчанию — 8844 (не 4533)[/]")
        if not click.confirm("  Сохранить всё равно?", default=False):
            return

    cfg["server_url"] = url
    API_URL = url

    api_key = console.input("  API Key (Enter = пропустить): ").strip()
    if api_key:
        cfg["api_key"] = api_key
        API_KEY = api_key

    _save_config(cfg)
    console.print(f"\n[green]✓ Сохранено в {CONFIG_FILE}[/]")


@cli.command()
@click.argument("query", nargs=-1, required=True)
def search(query):
    """Search for tracks. Usage: musomatic search Artist - Title"""
    q = " ".join(query)
    for sep in [" - ", " — ", " – "]:
        if sep in q:
            artist, title = q.split(sep, 1)
            break
    else:
        artist, title = "", q

    console.print(f"[dim]Searching: {artist} — {title}[/]")
    data = api("post", "/search", json={"tracks": [{"artist": artist.strip(), "title": title.strip()}]})
    r = data["results"][0]
    best = r["best"]
    if best:
        console.print(f"  {quality_badge(best)}  {best['artist']} — {best['title']}")
    else:
        console.print(f"  [red]✗ Not found[/] (searched {r['source_count']} sources)")


@cli.command()
@click.argument("query", nargs=-1, required=True)
def download(query):
    """Search + download single track to server."""
    q = " ".join(query)
    for sep in [" - ", " — ", " – "]:
        if sep in q:
            artist, title = q.split(sep, 1)
            break
    else:
        artist, title = "", q

    console.print(f"[dim]Downloading: {artist.strip()} — {title.strip()}[/]")
    job = api("post", "/download", json={"artist": artist.strip(), "title": title.strip()})
    job_id = job["job_id"]

    try:
        with console.status("[bold green]Searching & downloading...") as st:
            while True:
                time.sleep(2)
                j = api_poll(f"/jobs/{job_id}")
                if j is None:
                    console.print("[yellow]⚠ Lost connection, job continues on server[/]")
                    return
                s = j["status"]
                st.update(f"[bold green]{s}...")
                if s in ("done", "failed", "not_found", "cancelled"):
                    break
    except KeyboardInterrupt:
        cancel_job(job_id)
        return

    if j["status"] == "done":
        r = j["result"]
        console.print(f"[green]✅[/] {r['quality_tag']}  ({r['size_mb']} MB)")
        console.print(f"   [dim]{r['path']}[/]")
    elif j["status"] == "not_found":
        console.print(f"[red]✗ Not found on any source[/]")
    else:
        console.print(f"[red]✗ Failed:[/] {j.get('error', '?')}")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--scan-only", is_flag=True, help="Search only, don't download")
@click.option("-l", "--limit", default=0, help="Limit tracks (0=all)")
def batch(file, scan_only, limit):
    """Batch search + download from JSON file.

    JSON format: [{"artist": "...", "title": "..."}]
    or: {"songs": [{"artist": "...", "title": "..."}]}
    """
    data = json.loads(Path(file).read_text())
    if isinstance(data, list):
        tracks = data
    elif "songs" in data:
        tracks = [{"artist": s.get("artist", ""), "title": s.get("title", "")}
                  for s in data["songs"]]
    else:
        tracks = data.get("tracks", data.get("items", []))

    if limit > 0:
        tracks = tracks[:limit]

    console.print(f"📋 Loaded {len(tracks)} tracks from {file}")

    if scan_only:
        t0 = time.time()
        with console.status("[bold]Scanning..."):
            with httpx.Client(base_url=API_URL, timeout=900, headers=_headers()) as c:
                r = c.post("/search", json={"tracks": tracks})
                r.raise_for_status()
                data = r.json()
        stats = data["stats"]
        console.print(f"  ✓ Scan complete in {time.time() - t0:.1f}s\n")
        console.print(f"📊 [bold]Scan Results:[/]")
        console.print(f"  🟢 Hi-Res 24bit:  {stats['hires']}")
        console.print(f"  🟡 FLAC CD:       {stats['cd']}")
        console.print(f"  🔴 Not found:     {stats['not_found']}")
        console.print(f"  ✅ Total lossless: {stats['hires'] + stats['cd']}/{stats['total']} ({stats['lossless_pct']}%)")
        missing = [r for r in data["results"] if not r["best"]]
        if missing:
            console.print(f"\n[red]Missing ({len(missing)}):[/]")
            for r in missing:
                console.print(f"  ✗ {r['artist']} — {r['title']}")
    else:
        console.print(f"  Starting batch scan + download...")
        job = api("post", "/batch/download",
                  json={"tracks": [{"artist": t.get("artist", ""), "title": t.get("title", "")}
                                   for t in tracks]})
        job_id = job["job_id"]
        j = {"status": "scanning"}

        try:
            with console.status("") as st:
                while True:
                    time.sleep(3)
                    j = api_poll(f"/jobs/{job_id}")
                    if j is None:
                        console.print("[yellow]⚠ Lost connection, job continues on server[/]")
                        return
                    s = j["status"]
                    if s == "scanning":
                        st.update(f"[bold]Scanning... {j.get('done', 0)}/{j['total']} ({j.get('scan_phase', '')})")
                    elif s == "downloading":
                        st.update(
                            f"[bold]Downloading... {j.get('downloaded', 0)} done, "
                            f"{j.get('failed', 0)} failed "
                            f"(Hi-Res: {j.get('hires', 0)}, CD: {j.get('cd', 0)})"
                        )
                    elif s in ("done", "cancelled"):
                        break
                    else:
                        break
        except KeyboardInterrupt:
            cancel_job(job_id)
            time.sleep(2)
            try:
                j = api_poll(f"/jobs/{job_id}")
            except Exception:
                pass

        if j.get("status") not in ("done", "cancelled", "failed"):
            final = api_poll(f"/jobs/{job_id}")
            if final:
                j = final

        if j["status"] in ("done", "cancelled"):
            label = "[bold green]Batch complete!" if j["status"] == "done" else "[bold yellow]Batch cancelled (files kept)"
            console.print(f"\n{'✅' if j['status'] == 'done' else '⏹'} {label}[/]")
            console.print(f"  Downloaded: {j.get('downloaded', 0)}")
            console.print(f"  Failed: {j.get('failed', 0)}")
            console.print(f"  Hi-Res: {j.get('hires', 0)} | CD: {j.get('cd', 0)} | Not found: {j.get('not_found', 0)}")
            console.print(f"  Time: {j.get('elapsed_s', '?')}s")
        else:
            console.print(f"[red]Batch failed: {j.get('error', j.get('status', '?'))}[/]")


@cli.command()
def jobs():
    """List active/recent jobs."""
    data = api("get", "/jobs")
    if not data:
        console.print("[dim]No jobs[/]")
        return
    for jid, info in data.items():
        color = {"done": "green", "failed": "red", "downloading": "yellow"}.get(info["status"], "white")
        console.print(f"  [{color}]{info['status']:12}[/] {jid}")


@cli.command()
def audit():
    """Audit library for non-original tracks (live, remix, etc.)."""
    with console.status("Scanning library..."):
        data = api("get", "/library/audit")
    total = data["total_tracks"]
    q = data["quality"]
    issues = data["issues"]
    console.print(f"\n📊 Library: {total} tracks  |  Hi-Res: {q['hires']}  CD: {q['cd']}")
    if not issues:
        console.print("[green]✅ No issues found[/]")
        return
    console.print(f"\n[yellow]⚠ {len(issues)} non-original tracks:[/]")
    table = Table(show_lines=False)
    table.add_column("Artist", style="cyan")
    table.add_column("Title")
    table.add_column("Album", style="dim")
    for i in issues:
        table.add_row(i["artist"], i["title"], i["album"])
    console.print(table)


@cli.command()
def upgrade():
    """Trigger manual 16→24bit upgrade scan on Soulseek."""
    data = api("post", "/upgrade/trigger")
    job_id = data["job_id"]
    console.print(f"[cyan]Upgrade scan started: {job_id}[/]")
    with console.status("Scanning..."):
        while True:
            j = api_poll(f"/jobs/{job_id}")
            if not j:
                break
            if j["status"] in ("done", "failed"):
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
@click.option("--api-key", "-k", help="LLM API key")
@click.option("--model", "-m", help="Override model name")
@click.option("--count", "-n", default=30, help="Number of recommendations")
def recommend(action, provider, api_key, model, count):
    """AI music recommendations. Generate, check status, or cleanup.

    \b
    musomatic recommend              # generate 30 AI recommendations
    musomatic recommend status       # check recommendation status
    musomatic recommend cleanup      # delete unrated, keep rated tracks
    musomatic recommend -p deepseek -k sk-xxx -n 20  # custom provider
    """
    if action == "status":
        data = api("get", "/recommend/status")
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
            data = api("post", "/recommend/cleanup")
        if data.get("status") == "no_playlist":
            console.print("[dim]No recommendation playlist found[/]")
        else:
            console.print(f"[green]✅ Cleanup done: kept {data.get('kept', 0)} rated, deleted {data.get('deleted', 0)}[/]")
        return

    # Generate
    body = {"count": count}
    if provider:
        body["provider"] = provider
    if api_key:
        body["api_key"] = api_key
    if model:
        body["model"] = model

    try:
        job = api("post", "/recommend/generate", json=body)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            console.print(f"[red]✗ {e.response.json().get('detail', str(e))}[/]")
            console.print("[dim]Set LLM_PROVIDER + LLM_API_KEY in .env, or pass --provider and --api-key[/]")
            return
        raise

    job_id = job["job_id"]
    console.print(f"[cyan]🤖 Generating AI recommendations... ({job_id})[/]")

    j = {}
    try:
        with console.status("[bold]Analyzing library and generating...") as st:
            while True:
                time.sleep(3)
                j = api_poll(f"/jobs/{job_id}")
                if j is None:
                    console.print("[yellow]⚠ Lost connection, job continues on server[/]")
                    return
                s = j["status"]
                if s == "generating":
                    st.update("[bold]🤖 AI is analyzing your library...")
                elif s == "downloading":
                    st.update(f"[bold]⬇️  Downloading... {j.get('downloaded', 0)}/{j.get('recommended', 0)}")
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
        console.print(f"\n[dim]Rate/star tracks you like in Navidrome/Amperfy to keep them.[/]")
        console.print(f"[dim]Unrated tracks auto-delete after {RECOMMEND_CLEANUP_HOURS}h (or run: musomatic recommend cleanup)[/]")
    elif j.get("status") == "failed":
        console.print(f"[red]✗ Failed: {j.get('error', '?')}[/]")


RECOMMEND_PLAYLIST = "AI Recommendations"
RECOMMEND_CLEANUP_HOURS = 24


@cli.command("ls")
@click.argument("query", nargs=-1)
def list_tracks(query):
    """List library tracks. Optional search: musomatic ls rammstein"""
    q = " ".join(query) if query else ""
    data = api("get", "/library/tracks", params={"q": q} if q else {})
    tracks = data["tracks"]
    if not tracks:
        console.print("[dim]Nothing found[/]")
        return
    table = Table(show_lines=False)
    table.add_column("ID", style="bold", width=4)
    table.add_column("Artist", style="cyan")
    table.add_column("Title")
    table.add_column("Album", style="dim")
    table.add_column("MB", style="dim", justify="right")
    for t in tracks:
        table.add_row(str(t["id"]), t["artist"], t["title"], t["album"], str(t["size_mb"]))
    console.print(table)
    console.print(f"[dim]Total: {data['total']}[/]")


@cli.command("rm")
@click.argument("query", nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation")
def delete_tracks(query, yes):
    """Delete tracks by ID or search. By ID: musomatic rm 5 12 23. By name: musomatic rm rammstein"""
    ids = []
    try:
        ids = [int(x) for x in query]
    except ValueError:
        pass

    if ids:
        all_data = api("get", "/library/tracks")
        id_set = set(ids)
        tracks = [t for t in all_data["tracks"] if t["id"] in id_set]
    else:
        q = " ".join(query)
        data = api("get", "/library/tracks", params={"q": q})
        tracks = data["tracks"]

    if not tracks:
        console.print(f"[dim]Nothing found[/]")
        return

    console.print(f"[yellow]Will delete {len(tracks)} track(s):[/]")
    for t in tracks:
        console.print(f"  🗑 [bold]{t['id']}[/]  {t['artist']} — {t['title']}  [dim]({t['size_mb']} MB)[/]")

    if not yes:
        if not click.confirm("\nConfirm delete?"):
            console.print("[dim]Cancelled[/]")
            return

    if ids:
        result = api("post", "/library/delete", json={"ids": ids})
    else:
        result = api("post", "/library/delete", json={"query": " ".join(query)})
    console.print(f"[green]{result['message']}[/]")


if __name__ == "__main__":
    cli()
