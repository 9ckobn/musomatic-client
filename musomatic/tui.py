"""Interactive TUI for musomatic library management."""

import httpx
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Input, Static, Label, Button
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.binding import Binding
from textual import on, work


class ConfirmDelete(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmDelete { align: center middle; }
    #dialog {
        width: 60; height: auto; max-height: 24;
        border: thick $error; background: $surface; padding: 1 2;
    }
    #dialog Label { width: 100%; }
    .track-item { color: $text-muted; }
    #buttons { width: 100%; height: 3; align-horizontal: center; margin-top: 1; }
    #buttons Button { margin: 0 2; }
    """

    def __init__(self, tracks: list[dict]):
        super().__init__()
        self.tracks = tracks

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"🗑  Delete {len(self.tracks)} track(s)?")
            for t in self.tracks[:10]:
                yield Label(f"  {t['artist']} — {t['title']}", classes="track-item")
            if len(self.tracks) > 10:
                yield Label(f"  ... and {len(self.tracks) - 10} more", classes="track-item")
            with Horizontal(id="buttons"):
                yield Button("Delete", variant="error", id="confirm")
                yield Button("Cancel", variant="default", id="cancel")

    @on(Button.Pressed, "#confirm")
    def confirm(self): self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(False)

    def on_key(self, event):
        if event.key == "escape":
            self.dismiss(False)


class DownloadDialog(ModalScreen[str | None]):
    DEFAULT_CSS = """
    DownloadDialog { align: center middle; }
    #dl-dialog {
        width: 70; height: auto;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    #dl-dialog Label { margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dl-dialog"):
            yield Label("⬇️  Download New Track")
            yield Label("[dim]Format: artist - title  (or just keywords)[/]")
            yield Input(placeholder="e.g. Radiohead - Creep", id="dl-input")

    def on_mount(self):
        self.query_one("#dl-input", Input).focus()

    @on(Input.Submitted, "#dl-input")
    def on_submit(self, event: Input.Submitted):
        q = event.value.strip()
        self.dismiss(q if q else None)

    def on_key(self, event):
        if event.key == "escape":
            self.dismiss(None)


class MusomaticApp(App):
    CSS = """
    #search-bar {
        dock: top; height: 3; padding: 0 1;
    }
    #search-bar Input {
        width: 100%;
    }
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
        Binding("slash", "focus_search", "Search"),
        Binding("r", "refresh", "Refresh"),
        Binding("n", "new_download", "Download"),
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
            yield Input(placeholder="🔍 Search by artist, title, album...", id="search-input")
        yield DataTable(id="library")
        yield Static("Loading...", id="status")
        yield Footer()

    def on_mount(self):
        table = self.query_one("#library", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns(" ", "ID", "Artist", "Title", "Album", "Quality", "MB")
        self.load_library()

    def _api(self, method: str, path: str, **kwargs) -> dict:
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        with httpx.Client(base_url=self.server_url, timeout=120, headers=headers) as c:
            r = getattr(c, method)(path, **kwargs)
            r.raise_for_status()
            return r.json()

    @work(thread=True)
    def load_library(self):
        try:
            data = self._api("get", "/library/tracks")
            stats = self._api("get", "/library/stats")
        except Exception as e:
            self.call_from_thread(self._set_status, f"❌ Error: {e}")
            return
        tracks = sorted(data["tracks"], key=lambda t: (t["artist"].lower(), t["title"].lower()))
        self.call_from_thread(self._on_tracks_loaded, tracks, stats)

    def _on_tracks_loaded(self, tracks: list[dict], stats: dict):
        self.all_tracks = tracks
        self.sub_title = f"{stats['total_tracks']} tracks · {stats['total_size_gb']} GB · {stats['albums']} albums"
        self.apply_filter()

    def apply_filter(self):
        if self.filter_text:
            q = self.filter_text.lower()
            self.displayed = [t for t in self.all_tracks if q in f"{t['artist']} {t['title']} {t['album']}".lower()]
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
            table.add_row(sel, str(tid), t["artist"], t["title"], t["album"], quality, str(t["size_mb"]))

        self._update_status()

    def _update_status(self):
        parts = [f"📊 {len(self.displayed)}/{len(self.all_tracks)} tracks"]
        if self.filter_text:
            parts.append(f"🔍 \"{self.filter_text}\"")
        if self.selected_ids:
            parts.append(f"✓ {len(self.selected_ids)} selected")
        parts.append("/ filter · d delete · space select · n download · r refresh · q quit")
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

    # ── Actions ──

    def action_toggle_select(self):
        track = self._current_track()
        if not track:
            return
        tid = track["id"]
        if tid in self.selected_ids:
            self.selected_ids.discard(tid)
        else:
            self.selected_ids.add(tid)
        self.apply_filter()

    def action_delete_track(self):
        if self.selected_ids:
            tracks = [t for t in self.all_tracks if t["id"] in self.selected_ids]
        else:
            track = self._current_track()
            if not track:
                return
            tracks = [track]

        def on_confirm(confirmed: bool):
            if confirmed:
                self._do_delete(tracks)

        self.push_screen(ConfirmDelete(tracks), on_confirm)

    @work(thread=True)
    def _do_delete(self, tracks: list[dict]):
        ids = [t["id"] for t in tracks]
        try:
            self._api("post", "/library/delete", json={"ids": ids})
            self.selected_ids -= set(ids)
            self.call_from_thread(self.notify, f"🗑  Deleted {len(ids)} track(s)", severity="warning")
            self.call_from_thread(self._reload_after_change)
        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    def _reload_after_change(self):
        self.load_library()

    def action_focus_search(self):
        self.query_one("#search-input", Input).focus()

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed):
        self.filter_text = event.value
        self.apply_filter()

    @on(Input.Submitted, "#search-input")
    def on_search_submitted(self, event: Input.Submitted):
        self.query_one("#library", DataTable).focus()

    def action_refresh(self):
        self.notify("Refreshing...")
        self.load_library()

    def action_new_download(self):
        def on_result(query: str | None):
            if query:
                self._do_download(query)
        self.push_screen(DownloadDialog(), on_result)

    @work(thread=True)
    def _do_download(self, query: str):
        self.call_from_thread(self.notify, f"⬇️  Downloading: {query}...")
        try:
            result = self._api("post", "/quick", json={"query": query})
            if result.get("status") == "done":
                msg = result.get("quality", "Done")
                self.call_from_thread(self.notify, f"✅ {query} — {msg}")
                self.call_from_thread(self._reload_after_change)
            else:
                self.call_from_thread(self.notify, f"❌ {result.get('message', 'Failed')}", severity="error")
        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")


def run_tui():
    from .client import API_URL, API_KEY
    app = MusomaticApp(API_URL, API_KEY)
    app.run()
