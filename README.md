# 🎵 musomatic-client

CLI client for [musomatic-server](https://github.com/9ckobn/musomatic-server) — search, download, and manage your lossless music library from the terminal.

## Install

```bash
# Recommended (Arch Linux, any distro with pipx)
pipx install git+https://github.com/9ckobn/musomatic-client.git

# Or with pip (venv recommended)
pip install git+https://github.com/9ckobn/musomatic-client.git
```

## Setup

```bash
# Interactive setup — server URL + API key
musomatic setup

# Or set directly
musomatic setup server_url http://192.168.88.92:8844
musomatic setup api_key YOUR_KEY
```

Config is stored in `~/.config/musomatic/config.json` (chmod 600).

## Usage

```bash
# Server status
musomatic status

# Search
musomatic search Rammstein - Du Hast

# Download
musomatic download Metallica - Enter Sandman

# Batch from JSON file
musomatic batch tracks.json
musomatic batch tracks.json --scan-only
musomatic batch tracks.json -l 10  # first 10 only

# List library
musomatic ls
musomatic ls rammstein

# Delete by ID or search
musomatic rm 42 53
musomatic rm nickelback -y

# Audit library quality
musomatic audit

# 16→24bit upgrade scan
musomatic upgrade

# 🤖 AI recommendations
musomatic recommend              # generate 30 recommendations
musomatic recommend status       # check status
musomatic recommend cleanup      # delete unrated, keep liked

# List jobs
musomatic jobs

# Version
musomatic --version
```

## Batch JSON Format

```json
[
  {"artist": "Rammstein", "title": "Du Hast"},
  {"artist": "Metallica", "title": "Enter Sandman"}
]
```

Also supports: `{"songs": [{"artist": "...", "title": "..."}]}`

## Connecting from iPhone / Desktop Players

musomatic server includes Navidrome (Subsonic API), so any Subsonic-compatible player works:

- **iPhone**: [Amperfy](https://github.com/BLeeEZ/Amperfy) (free) or play:Sub ($5) — both support offline cache
- **Desktop**: [Feishin](https://github.com/jeffvli/feishin) or Navidrome web UI

## Server

Requires [musomatic-server](https://github.com/9ckobn/musomatic-server) running on your home server.

## License

MIT
