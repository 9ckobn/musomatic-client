# 🎵 musomatic-client

CLI & TUI client for [musomatic-server](https://github.com/9ckobn/musomatic-server) — search, download, and manage your lossless music library from the terminal.

## Install

```bash
# Recommended (Arch Linux, any distro with pipx)
pipx install git+https://github.com/9ckobn/musomatic-client.git

# Or with pip (venv recommended)
pip install git+https://github.com/9ckobn/musomatic-client.git
```

## Setup

```bash
musomatic setup                    # interactive setup
musomatic setup server_url http://192.168.88.92:8844
musomatic setup api_key YOUR_KEY
```

Config: `~/.config/musomatic/config.json` (chmod 600).

## Interactive TUI

```bash
musomatic tui
```

Full-screen terminal interface for library management:
- **Arrow keys** — navigate tracks (sorted by artist)
- **`/`** — filter by artist, title, album
- **`Space`** — select/deselect tracks
- **`d`** — delete selected (with confirmation)
- **`n`** — download new track
- **`r`** — refresh library
- **`q`** — quit

## CLI Commands

```bash
musomatic status                   # server status
musomatic search Rammstein - Du Hast
musomatic download Metallica - Enter Sandman
musomatic batch tracks.json        # batch download from JSON
musomatic batch tracks.json -l 10  # first 10 only
musomatic ls                       # list all tracks (with quality)
musomatic ls rammstein             # search tracks
musomatic rm 42 53 60              # delete by IDs (batch)
musomatic rm nickelback -y         # delete by search
musomatic audit                    # audit library quality
musomatic upgrade                  # 16→24bit upgrade scan
musomatic recommend                # AI recommendations
musomatic recommend status
musomatic recommend cleanup
musomatic jobs                     # list active jobs
musomatic --version
```

## Batch JSON Format

```json
[
  {"artist": "Rammstein", "title": "Du Hast"},
  {"artist": "Metallica", "title": "Enter Sandman"}
]
```

## Connecting from iPhone / Desktop Players

musomatic server includes Navidrome (Subsonic API):

- **iPhone**: [Amperfy](https://github.com/BLeeEZ/Amperfy) — free, offline cache
- **Desktop**: [Feishin](https://github.com/jeffvli/feishin) or Navidrome web UI

## License

MIT
