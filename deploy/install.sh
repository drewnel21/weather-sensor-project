#!/usr/bin/env bash
#
# Install (or update) the weather-server systemd unit on the Pi.
#
# Detects the repo location and the current user, fills those into the unit
# template, installs it to /etc/systemd/system/, and enables it. Safe to re-run
# after a `git pull` to pick up template changes.
#
# Usage:  bash deploy/install.sh
#
set -euo pipefail

# Repo root = parent of this script's directory.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(whoami)"
UNIT_SRC="$APP_DIR/deploy/systemd/weather-server.service"
UNIT_DST="/etc/systemd/system/weather-server.service"

echo "Repo dir : $APP_DIR"
echo "Run user : $RUN_USER"

if [[ ! -x "$APP_DIR/server/.venv/bin/python" ]]; then
  echo "ERROR: $APP_DIR/server/.venv/bin/python not found." >&2
  echo "Create the venv and install deps first (see deploy/README.md)." >&2
  exit 1
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "WARNING: $APP_DIR/.env not found — the service will fail to read its"
  echo "         config. Create it before starting (see deploy/README.md)."
fi

echo "Installing unit -> $UNIT_DST"
sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__RUN_USER__|$RUN_USER|g" \
  "$UNIT_SRC" | sudo tee "$UNIT_DST" >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable weather-server.service

echo
echo "Done. weather-server is enabled (starts on boot)."
echo "Start it now with:   sudo systemctl start weather-server"
echo "Check status with:   systemctl status weather-server"
echo "Follow logs with:    journalctl -u weather-server -f"
