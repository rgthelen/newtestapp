#!/usr/bin/env bash
# Base system setup: packages, PCIe Gen3, dirs.
set -euo pipefail

echo "==> [1/6] base system packages"

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    build-essential \
    git curl ca-certificates \
    python3 python3-venv python3-pip python3-dev \
    python3-opencv \
    ffmpeg \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    libgl1 libglib2.0-0 \
    sqlite3 \
    jq

echo "==> [1/6] config dirs"
mkdir -p "$HOME/.config/pi5-hailo-vision"
mkdir -p "$HOME/.local/share/pi5-hailo-vision/models"
mkdir -p "$HOME/.local/share/pi5-hailo-vision/snapshots"
mkdir -p "$HOME/.local/state/pi5-hailo-vision/logs"

echo "==> [1/6] PCIe Gen3 check"
CONFIG_TXT="/boot/firmware/config.txt"
if ! grep -q "^dtparam=pciex1_gen=3" "$CONFIG_TXT"; then
    echo "    enabling PCIe Gen3 (requires reboot to take effect)"
    echo "dtparam=pciex1_gen=3" | sudo tee -a "$CONFIG_TXT" > /dev/null
    PCIE_REBOOT_NEEDED=1
else
    echo "    PCIe Gen3 already enabled"
fi

if [[ "${PCIE_REBOOT_NEEDED:-0}" == "1" ]]; then
    cat <<'EOF'

    ⚠  PCIe Gen3 was just enabled. You MUST reboot before Hailo install
       will succeed. Run:

           sudo reboot

       Then re-run: ./scripts/install-all.sh
EOF
    exit 0
fi
