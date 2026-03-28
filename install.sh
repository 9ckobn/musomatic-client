#!/bin/bash
set -e

echo "📦 Installing musomatic CLI..."

pip3 install --user click httpx rich 2>/dev/null || pip install click httpx rich

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/bin/musomatic"

mkdir -p "$HOME/.local/bin"
cat > "$DEST" << EOF
#!/bin/bash
exec python3 "$SCRIPT_DIR/musomatic.py" "\$@"
EOF
chmod +x "$DEST"

echo "✅ Installed! Run: musomatic status"
echo ""
echo "Set your server URL:"
echo "  export MUSIC_API_URL=http://your-server:8844"
echo "  # Add to ~/.bashrc for persistence"
