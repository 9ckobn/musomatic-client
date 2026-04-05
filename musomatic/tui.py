"""Interactive TUI for musomatic library management."""

import time
import httpx
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Input, Static, Label, Button
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.binding import Binding
from textual import on, work


# ── Shared helpers ──

def _make_client(server_url: str, api_key: str, timeout: float = 120) -> httpx.Client:
    headers = {"x-api-key": api_key} if api_key else {}
    return httpx.Client(base_url=server_url, timeout=timeout, headers=headers)


def _api(server_url: str, api_key: str, method: str, path: str, **kwargs) -> dict:
    with _make_client(server_url, api_key) as c:
        r = getattr(c, method)(path, **kwargs)
        r.raise_for_status()
        return r.json()


def _trunc(text: str, maxlen: int = 22) -> str:
    return text[:maxlen - 1] + "…" if len(text) > maxlen else text


def _fmt_duration(secs: int) -> str:
    return f"{secs // 60}:{secs % 60:02d}"


# ── Confirm dialog ──

class ConfirmDialog(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmDialog { align: center middle; }
    #confirm-box {
        width: 60; height: auto; max-height: 24;
        border: thick $error; background: $surface; padding: 1 2;
    }
    .item { color: $text-muted; }
    #confirm-btns { width: 100%; height: 3; align-horizontal: center; margin-top: 1; }
    #confirm-btns Button { margin: 0 2; }
    """

    def __init__(self, title: str, items: list[str]):
        super().__init__()
        self._title = title
        self._items = items

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self._title)
            for item in self._items[:10]:
                yield Label(f"  {item}", classes="item")
            if len(self._items) > 10:
                yield Label(f"  ... +{len(self._items) - 10} more", classes="item")
            with Horizontal(id="confirm-btns"):
                yield Button("Delete", variant="error", id="yes")
                yield Button("Cancel", variant="default", id="no")

    @on(Button.Pressed, "#yes")
    def yes(self): self.dismiss(True)
    @on(Button.Pressed, "#no")
    def no(self): self.dismiss(False)
    def on_key(self, event):
        if event.key == "escape": self.dismiss(False)


# ── Search & Download screen ──

_STATUS_ICON = {
    "queued": "⏳", "searching": "🔍", "downloading": "⬇️",
    "done": "✅", "exists": "♻️", "failed": "❌", "not_found": "🚫",
    "cancelled": "🚫",
}


class SearchScreen(ModalScreen):
    DEFAULT_CSS = """
    SearchScreen { align: center middle; }
    #ss {
        width: 92%; height: 88%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    #ss-input { margin-bottom: 1; }
    #ss-table { height: 1fr; }
    #ss-bar { height: 1; margin-top: 1; }
    #ss-btns { height: 3; align-horizontal: center; margin-top: 1; }
    #ss-btns Button { margin: 0 1; }
    """

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, server_url: str, api_key: str):
        super().__init__()
        self.server_url = server_url
        self.api_key = api_key
        self.results: list[dict] = []
        self.selected: set[int] = set()
        self.dl_jobs: dict[int, str] = {}      # row_idx → job_id
        self.dl_status: dict[int, str] = {}    # row_idx → status string
        self._polling = False

    def compose(self) -> ComposeResult:
        with Vertical(id="ss"):
            yield Label("🔍 Search Tidal & Download")
            yield Input(placeholder="e.g.  depeche mode  or  Radiohead - Creep", id="ss-input")
            yield DataTable(id="ss-table")
            yield Static("[dim]Type query, press Enter to search[/]", id="ss-bar")
            with Horizontal(id="ss-btns"):
                yield Button("⬇ Download Selected", variant="success", id="ss-dl", disabled=True)
                yield Button("Close", variant="default", id="ss-close")

    def on_mount(self):
        t = self.query_one("#ss-table", DataTable)
        t.cursor_type = "row"
        t.zebra_stripes = True
        t.add_columns("St", "Artist", "Title", "Album", "Qual", "Dur")
        self.query_one("#ss-input", Input).focus()

    @on(Input.Submitted, "#ss-input")
    def do_search(self, event: Input.Submitted):
        q = event.value.strip()
        if q:
            self.query_one("#ss-bar", Static).update("🔍 Searching Tidal...")
            self._run_search(q)

    @work(thread=True)
    def _run_search(self, query: str):
        try:
            data = _api(self.server_url, self.api_key, "get", "/search/browse", params={"q": query})
            self.app.call_from_thread(self._show_results, data.get("results", []))
        except Exception as e:
            self.app.call_from_thread(
                lambda: self.query_one("#ss-bar", Static).update(f"❌ {e}"))

    def _show_results(self, results: list[dict]):
        self.results = results
        self.selected = set()
        self.dl_jobs = {}
        self.dl_status = {}
        self._refresh_table()
        found = len(results)
        self.query_one("#ss-bar", Static).update(
            f"📊 {found} results · Space=select · Enter=download one")
        self.query_one("#ss-dl", Button).disabled = True
        self.query_one("#ss-table", DataTable).focus()

    def _refresh_table(self, keep_cursor: int | None = None):
        t = self.query_one("#ss-table", DataTable)
        t.clear()
        for i, r in enumerate(self.results):
            sel = "✓ " if i in self.selected else ""
            st = self.dl_status.get(i, sel)
            t.add_row(
                st,
                _trunc(r.get("artist", "?"), 20),
                _trunc(r.get("title", "?"), 25),
                _trunc(r.get("album", ""), 22),
                r.get("quality", "?")[:6],
                _fmt_duration(r.get("duration_s", 0)),
            )
        if keep_cursor is not None and keep_cursor < len(self.results):
            t.move_cursor(row=keep_cursor)

    def on_key(self, event):
        if event.key == "space":
            t = self.query_one("#ss-table", DataTable)
            idx = t.cursor_row
            if idx is None or idx >= len(self.results):
                return
            if idx in self.selected:
                self.selected.discard(idx)
            else:
                self.selected.add(idx)
            self._refresh_table(keep_cursor=idx)
            self.query_one("#ss-dl", Button).disabled = len(self.selected) == 0
            n = len(self.selected)
            self.query_one("#ss-bar", Static).update(f"✓ {n} selected")

    @on(DataTable.RowSelected, "#ss-table")
    def on_row_selected(self, event):
        idx = event.cursor_row
        if idx is not None and idx < len(self.results):
            self._start_downloads([idx])

    @on(Button.Pressed, "#ss-dl")
    def dl_selected(self):
        if self.selected:
            self._start_downloads(sorted(self.selected))
            self.selected = set()

    def _start_downloads(self, indices: list[int]):
        for idx in indices:
            if idx in self.dl_jobs:
                continue
            r = self.results[idx]
            self.dl_status[idx] = "🔍"
            self._do_async_dl(idx, r.get("artist", ""), r.get("title", ""))
        self._refresh_table()
        if not self._polling:
            self._polling = True
            self._poll_jobs()

    @work(thread=True)
    def _do_async_dl(self, idx: int, artist: str, title: str):
        try:
            data = _api(self.server_url, self.api_key, "post", "/download",
                        json={"artist": artist, "title": title})
            job_id = data["job_id"]
            self.dl_jobs[idx] = job_id
        except Exception as e:
            self.dl_status[idx] = "❌"
            self.app.call_from_thread(self._refresh_table)

    @work(thread=True)
    def _poll_jobs(self):
        while self._polling and self.dl_jobs:
            time.sleep(2)
            active = False
            for idx, jid in list(self.dl_jobs.items()):
                try:
                    j = _api(self.server_url, self.api_key, "get", f"/jobs/{jid}")
                    st = j.get("status", "?")
                    icon = _STATUS_ICON.get(st, "❓")
                    self.dl_status[idx] = icon
                    if st not in ("done", "failed", "not_found", "exists", "cancelled"):
                        active = True
                except Exception:
                    pass
            self.app.call_from_thread(self._refresh_table)
            if not active:
                break
        self._polling = False
        done_count = sum(1 for s in self.dl_status.values() if s in ("✅", "♻️"))
        fail_count = sum(1 for s in self.dl_status.values() if s in ("❌", "🚫"))
        self.app.call_from_thread(
            lambda: self.query_one("#ss-bar", Static).update(
                f"✅ {done_count} downloaded · ❌ {fail_count} failed"))

    @on(Button.Pressed, "#ss-close")
    def close_btn(self): self.dismiss()
    def action_close(self): self.dismiss()


# ── Downloads screen ──

class DownloadsScreen(ModalScreen):
    DEFAULT_CSS = """
    DownloadsScreen { align: center middle; }
    #ds {
        width: 88%; height: 80%;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    #ds-table { height: 1fr; }
    #ds-bar { height: 1; margin-top: 1; }
    #ds-btns { height: 3; align-horizontal: center; margin-top: 1; }
    #ds-btns Button { margin: 0 1; }
    """

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, server_url: str, api_key: str):
        super().__init__()
        self.server_url = server_url
        self.api_key = api_key
        self._live = True

    def compose(self) -> ComposeResult:
        with Vertical(id="ds"):
            yield Label("📥 Downloads")
            yield DataTable(id="ds-table")
            yield Static("Loading...", id="ds-bar")
            with Horizontal(id="ds-btns"):
                yield Button("🔄 Refresh", variant="primary", id="ds-ref")
                yield Button("Close", variant="default", id="ds-close")

    def on_mount(self):
        t = self.query_one("#ds-table", DataTable)
        t.cursor_type = "row"
        t.zebra_stripes = True
        t.add_columns("Status", "Artist", "Title", "Elapsed")
        self._auto_refresh()

    @work(thread=True)
    def _auto_refresh(self):
        while self._live:
            self._load_jobs()
            time.sleep(3)

    def _load_jobs(self):
        try:
            data = _api(self.server_url, self.api_key, "get", "/jobs")
        except Exception as e:
            self.app.call_from_thread(
                lambda: self.query_one("#ds-bar", Static).update(f"❌ {e}"))
            return

        now = time.time()
        rows = []
        active = 0
        for jid, info in sorted(data.items(), key=lambda x: x[1].get("started", 0), reverse=True):
            st = info.get("status", "?")
            icon = _STATUS_ICON.get(st, "❓")
            artist = _trunc(info.get("artist", "?"), 22)
            title = _trunc(info.get("title", "?"), 28)
            started = info.get("started", 0)
            elapsed = f"{int(now - started)}s" if started else "?"
            rows.append((f"{icon} {st}", artist, title, elapsed))
            if st in ("searching", "downloading", "queued"):
                active += 1

        def _update():
            t = self.query_one("#ds-table", DataTable)
            t.clear()
            for row in rows[:50]:
                t.add_row(*row)
            self.query_one("#ds-bar", Static).update(
                f"📊 {len(rows)} jobs · {active} active")

        self.app.call_from_thread(_update)

    @on(Button.Pressed, "#ds-ref")
    def refresh(self): self._load_jobs_once()

    @work(thread=True)
    def _load_jobs_once(self): self._load_jobs()

    @on(Button.Pressed, "#ds-close")
    def close_btn(self): self._live = False; self.dismiss()
    def action_close(self): self._live = False; self.dismiss()


# ── Recommendations screen ──

class RecommendScreen(ModalScreen):
    DEFAULT_CSS = """
    RecommendScreen { align: center middle; }
    #rs {
        width: 80%; height: 70%;
        border: thick $success; background: $surface; padding: 1 2;
    }
    #rs-progress { height: 3; margin: 1 0; }
    #rs-status { height: 1; }
    #rs-btns { height: 3; align-horizontal: center; margin-top: 1; }
    #rs-btns Button { margin: 0 1; }
    """

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, server_url: str, api_key: str):
        super().__init__()
        self.server_url = server_url
        self.api_key = api_key

    def compose(self) -> ComposeResult:
        with Vertical(id="rs"):
            yield Label("🤖 AI Music Recommendations")
            yield Static("[dim]Generate personalized recommendations based on your library[/]",
                         id="rs-progress")
            yield Static("", id="rs-status")
            with Horizontal(id="rs-btns"):
                yield Button("🎲 Generate (30)", variant="success", id="rs-gen")
                yield Button("🧹 Cleanup unrated", variant="warning", id="rs-clean")
                yield Button("Close", variant="default", id="rs-close")

    def on_mount(self):
        self._load_last()

    @work(thread=True)
    def _load_last(self):
        try:
            data = _api(self.server_url, self.api_key, "get", "/recommend/status")
            lr = data.get("last_result", {})
            if lr:
                msg = (f"Last run: ✅ {lr.get('downloaded', 0)}/{lr.get('recommended', 0)} downloaded\n"
                       f"Provider: {data.get('provider', '?')}")
            else:
                msg = "No previous recommendations — hit Generate!"
            self.app.call_from_thread(
                lambda: self.query_one("#rs-progress", Static).update(msg))
        except Exception as e:
            self.app.call_from_thread(
                lambda: self.query_one("#rs-progress", Static).update(f"❌ {e}"))

    @on(Button.Pressed, "#rs-gen")
    def generate(self):
        self.query_one("#rs-gen", Button).disabled = True
        self._do_generate()

    @work(thread=True)
    def _do_generate(self):
        self.app.call_from_thread(
            lambda: self.query_one("#rs-progress", Static).update("🤖 Starting..."))
        try:
            job = _api(self.server_url, self.api_key, "post",
                       "/recommend/generate", json={"count": 30})
            job_id = job["job_id"]

            while True:
                time.sleep(3)
                j = _api(self.server_url, self.api_key, "get", f"/jobs/{job_id}")
                s = j.get("status", "?")

                if s == "generating":
                    self._set_prog("🤖 AI is analyzing your library...")
                elif s == "downloading":
                    d = j.get("downloaded", 0)
                    t = j.get("recommended", 0)
                    nf = j.get("not_found", 0)
                    self._set_prog(f"⬇️ Downloading {d}/{t}  ·  Not found: {nf}")
                elif s == "done":
                    d = j.get("downloaded", 0)
                    t = j.get("recommended", 0)
                    nf = j.get("not_found", 0)
                    el = j.get("elapsed_s", "?")
                    self._set_prog(f"✅ Done! {d}/{t} downloaded · {nf} not found · {el}s")
                    self._enable_gen()
                    break
                elif s == "failed":
                    self._set_prog(f"❌ {j.get('error', 'Unknown error')}")
                    self._enable_gen()
                    break
        except Exception as e:
            self._set_prog(f"❌ {e}")
            self._enable_gen()

    def _set_prog(self, text: str):
        self.app.call_from_thread(
            lambda: self.query_one("#rs-progress", Static).update(text))

    def _enable_gen(self):
        self.app.call_from_thread(
            lambda: setattr(self.query_one("#rs-gen", Button), "disabled", False))

    @on(Button.Pressed, "#rs-clean")
    def cleanup(self):
        self._do_cleanup()

    @work(thread=True)
    def _do_cleanup(self):
        try:
            data = _api(self.server_url, self.api_key, "post", "/recommend/cleanup")
            if data.get("status") == "no_playlist":
                msg = "No recommendation playlist found"
            else:
                msg = f"✅ Kept {data.get('kept', 0)} rated, deleted {data.get('deleted', 0)} unrated"
            self.app.call_from_thread(
                lambda: self.query_one("#rs-status", Static).update(msg))
        except Exception as e:
            self.app.call_from_thread(
                lambda: self.query_one("#rs-status", Static).update(f"❌ {e}"))

    @on(Button.Pressed, "#rs-close")
    def close_btn(self): self.dismiss()
    def action_close(self): self.dismiss()


# ── Main App ──

class MusomaticApp(App):
    CSS = """
    #search-bar { dock: top; height: 3; padding: 0 1; }
    #search-bar Input { width: 100%; }
    #status {
        dock: bottom; height: 1;
        background: $primary-background; padding: 0 1;
        color: $text-muted;
    }
    DataTable { height: 1fr; }
    """

    TITLE = "🎵 musomatic"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "delete_track", "Delete"),
        Binding("slash", "focus_search", "/Search"),
        Binding("escape", "focus_table", show=False),
        Binding("tab", "switch_focus", show=False),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "server_search", "Search+DL"),
        Binding("g", "recommend", "AI Recs"),
        Binding("j", "show_downloads", "Downloads"),
        Binding("space", "toggle_select", "Select", show=False),
    ]

    def __init__(self, server_url: str, api_key: str):
        super().__init__()
        self.server_url = server_url
        self.api_key = api_key
        self.all_tracks: list[dict] = []
        self.displayed: list[dict] = []
        self.selected_ids: set[int] = set()
        self.filter_text = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="search-bar"):
            yield Input(placeholder="🔍 Filter library (instant)...", id="search-input")
        yield DataTable(id="library")
        yield Static("Loading...", id="status")
        yield Footer()

    def on_mount(self):
        table = self.query_one("#library", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns(" ", "ID", "Artist", "Title", "Album", "Quality", "MB")
        self.load_library()
        table.focus()

    @work(thread=True)
    def load_library(self):
        try:
            data = _api(self.server_url, self.api_key, "get", "/library/tracks")
            stats = _api(self.server_url, self.api_key, "get", "/library/stats")
        except Exception as e:
            self.call_from_thread(self._set_status, f"❌ {e}")
            return
        tracks = sorted(data["tracks"],
                        key=lambda t: (t["artist"].lower(), t["title"].lower()))
        self.call_from_thread(self._on_loaded, tracks, stats)

    def _on_loaded(self, tracks: list[dict], stats: dict):
        self.all_tracks = tracks
        self.sub_title = (f"{stats['total_tracks']} tracks · "
                          f"{stats['total_size_gb']} GB · {stats['albums']} albums")
        self.apply_filter()

    def apply_filter(self):
        if self.filter_text:
            q = self.filter_text.lower()
            self.displayed = [
                t for t in self.all_tracks
                if q in f"{t['artist']} {t['title']} {t['album']}".lower()
            ]
        else:
            self.displayed = list(self.all_tracks)

        table = self.query_one("#library", DataTable)
        table.clear()
        for t in self.displayed:
            tid = t["id"]
            sel = "✓" if tid in self.selected_ids else ""
            bd = t.get("bit_depth", 0)
            sr = t.get("sample_rate", 0)
            if bd >= 24:
                quality = f"24/{sr // 1000}k" if sr else "24bit"
            elif bd >= 16:
                quality = f"16/{sr // 1000}k" if sr else "16bit"
            else:
                quality = "?"
            table.add_row(sel, str(tid), t["artist"], t["title"],
                          t["album"], quality, str(t["size_mb"]))
        self._update_status()

    def _update_status(self):
        parts = [f"📊 {len(self.displayed)}/{len(self.all_tracks)}"]
        if self.filter_text:
            parts.append(f"🔍 \"{self.filter_text}\"")
        if self.selected_ids:
            parts.append(f"✓ {len(self.selected_ids)} selected")
        self._set_status("  │  ".join(parts))

    def _set_status(self, text: str):
        self.query_one("#status", Static).update(text)

    def _current_track(self) -> dict | None:
        table = self.query_one("#library", DataTable)
        if table.row_count == 0:
            return None
        idx = table.cursor_row
        if idx is not None and 0 <= idx < len(self.displayed):
            return self.displayed[idx]
        return None

    # ── Focus ──

    def action_focus_search(self):
        self.query_one("#search-input", Input).focus()

    def action_focus_table(self):
        self.query_one("#library", DataTable).focus()

    def action_switch_focus(self):
        inp = self.query_one("#search-input", Input)
        if inp.has_focus:
            self.query_one("#library", DataTable).focus()
        else:
            inp.focus()

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed):
        self.filter_text = event.value
        self.apply_filter()

    @on(Input.Submitted, "#search-input")
    def on_search_submitted(self, event: Input.Submitted):
        self.query_one("#library", DataTable).focus()

    # ── Select / Delete ──

    def action_toggle_select(self):
        track = self._current_track()
        if not track:
            return
        tid = track["id"]
        self.selected_ids.symmetric_difference_update({tid})
        self.apply_filter()

    def action_delete_track(self):
        if self.selected_ids:
            tracks = [t for t in self.all_tracks if t["id"] in self.selected_ids]
        else:
            track = self._current_track()
            if not track:
                return
            tracks = [track]

        items = [f"{t['artist']} — {t['title']}" for t in tracks]
        self.push_screen(
            ConfirmDialog(f"🗑 Delete {len(tracks)} track(s)?", items),
            lambda ok: self._do_delete(tracks) if ok else None,
        )

    @work(thread=True)
    def _do_delete(self, tracks: list[dict]):
        ids = [t["id"] for t in tracks]
        try:
            _api(self.server_url, self.api_key, "post",
                 "/library/delete", json={"ids": ids})
            self.selected_ids -= set(ids)
            self.call_from_thread(self.notify,
                f"🗑 Deleted {len(ids)} track(s)", severity="warning")
            self.call_from_thread(self._reload)
        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    def _reload(self):
        self.load_library()

    def action_refresh(self):
        self.notify("Refreshing...")
        self.load_library()

    # ── Search & Download (Tidal browse) ──

    def action_server_search(self):
        self.push_screen(
            SearchScreen(self.server_url, self.api_key),
            lambda _=None: self._reload(),
        )

    # ── Downloads ──

    def action_show_downloads(self):
        self.push_screen(DownloadsScreen(self.server_url, self.api_key))

    # ── AI Recommendations ──

    def action_recommend(self):
        self.push_screen(
            RecommendScreen(self.server_url, self.api_key),
            lambda _=None: self._reload(),
        )


def run_tui():
    from .client import API_URL, API_KEY
    app = MusomaticApp(API_URL, API_KEY)
    app.run()
