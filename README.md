# 🎵 musomatic-client

CLI client for [musomatic-server](https://github.com/9ckobn/musomatic-server) — search, download, and manage your lossless music library from the terminal.

## Install

```bash
git clone https://github.com/9ckobn/musomatic-client.git
cd musomatic-client
bash install.sh
```

Or manually:
```bash
pip install click httpx rich
export MUSIC_API_URL=http://your-server:8844
python musomatic.py status
```

## Configuration

```bash
# Server URL (required)
export MUSIC_API_URL=http://your-server:8844

# API key for external access (optional)
export MUSIC_API_KEY=your-key

# Add to ~/.bashrc for persistence
```

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

# Audit library
musomatic audit

# 16→24bit upgrade scan
musomatic upgrade

# 🤖 AI recommendations
musomatic recommend              # generate
musomatic recommend status       # check status
musomatic recommend cleanup      # delete unrated, keep liked

musomatic recommend -p deepseek -k sk-xxx -n 20  # custom

# List jobs
musomatic jobs
```

## Batch JSON Format

```json
[
  {"artist": "Rammstein", "title": "Du Hast"},
  {"artist": "Metallica", "title": "Enter Sandman"}
]
```

Also supports: `{"songs": [{"artist": "...", "title": "..."}]}`

## Server

Requires [musomatic-server](https://github.com/9ckobn/musomatic-server) running on your home server.

## License

MIT
