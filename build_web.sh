#!/usr/bin/env bash
# Build the browser (WebAssembly) version with pygbag.
# Output goes to ./build/web — upload its CONTENTS to itch.io (HTML5) or
# GitHub Pages to get a shareable link anyone can play, no install.
#
# One-time setup:  pip install pygbag   (or it's already in .venv)
set -euo pipefail
cd "$(dirname "$0")"

PY="./.venv/bin/python"
[ -x "$PY" ] || PY="python3"

STAGE_PARENT="$(mktemp -d)"
trap 'rm -rf "$STAGE_PARENT"' EXIT
STAGE="$STAGE_PARENT/swarmada"           # folder name -> apk name
mkdir -p "$STAGE"

# Stage ONLY the game files (never the virtualenv, or the build balloons to 100s of MB)
cp main.py swarmada.py make_assets.py "$STAGE"/
cp -r assets "$STAGE"/assets

# Bake the global leaderboard URL into the web build (browsers have no env vars).
# Usage:  SWARMADA_SERVER=https://your.vps ./build_web.sh
if [ -n "${SWARMADA_SERVER:-}" ]; then
  printf 'SERVER_URL = "%s"\n' "$SWARMADA_SERVER" > "$STAGE/server_config.py"
  echo "Baked global leaderboard URL: $SWARMADA_SERVER"
fi

"$PY" -m pygbag --build --title "Swarmada" "$STAGE/main.py"

rm -rf build
mkdir -p build
cp -r "$STAGE/build/web" build/web
cp assets/icon.png build/web/favicon.png 2>/dev/null || true   # our icon, not pygbag's

echo
echo "Web build ready: build/web/"
echo "  - Test locally:   $PY -m pygbag $STAGE/main.py   (then open http://localhost:8000)"
echo "  - Share a link:   zip the CONTENTS of build/web/ and upload to itch.io as an HTML5 game,"
echo "                    or push build/web/ to GitHub Pages."
