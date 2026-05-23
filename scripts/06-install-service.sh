#!/usr/bin/env bash
# Install the systemd service + seed the user config.
set -euo pipefail

echo "==> [6/6] systemd + user config"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="$HOME/.config/pi5-hailo-vision"

mkdir -p "$CONFIG_DIR"

if [[ ! -f "$CONFIG_DIR/cameras.yaml" ]]; then
    cp "$REPO_DIR/config/cameras.example.yaml" "$CONFIG_DIR/cameras.yaml"
    echo "    seeded $CONFIG_DIR/cameras.yaml (edit it to add your cameras)"
fi

if [[ ! -f "$CONFIG_DIR/app.yaml" ]]; then
    cp "$REPO_DIR/config/app.example.yaml" "$CONFIG_DIR/app.yaml"
    echo "    seeded $CONFIG_DIR/app.yaml"
fi

# Render the systemd unit with the right paths/user.
TMP_UNIT="$(mktemp)"
sed -e "s|@USER@|$USER|g" \
    -e "s|@HOME@|$HOME|g" \
    -e "s|@REPO@|$REPO_DIR|g" \
    "$REPO_DIR/systemd/pi5-hailo-vision.service" > "$TMP_UNIT"

sudo install -m 0644 "$TMP_UNIT" /etc/systemd/system/pi5-hailo-vision.service
rm -f "$TMP_UNIT"

sudo systemctl daemon-reload

echo "    service installed. enable with:"
echo "        sudo systemctl enable --now pi5-hailo-vision"
