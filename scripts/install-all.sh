#!/usr/bin/env bash
# pi5-hailo-vision — one-shot installer
# Runs every step in order. Idempotent — safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> pi5-hailo-vision install"
echo "    repo:   $REPO_DIR"
echo "    user:   $USER"
echo "    home:   $HOME"
echo

cd "$REPO_DIR"

bash scripts/01-system-setup.sh
bash scripts/02-install-hailo.sh
bash scripts/03-install-tailscale.sh
bash scripts/04-download-models.sh
bash scripts/05-python-env.sh
bash scripts/06-install-service.sh

cat <<'EOF'

============================================================
 install complete.

 Next steps:
   1. Edit ~/.config/pi5-hailo-vision/cameras.yaml
   2. sudo systemctl enable --now pi5-hailo-vision
   3. Open http://$(hostname):8080  (or http://vision:8080 over Tailscale)

 Logs:    journalctl -u pi5-hailo-vision -f
 Stop:    sudo systemctl stop pi5-hailo-vision
 Status:  systemctl status pi5-hailo-vision
============================================================
EOF
