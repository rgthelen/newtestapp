#!/usr/bin/env bash
# Base system setup: packages, EEPROM, PCIe Gen3, dirs.
set -euo pipefail

echo "==> [1/6] base system packages"

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    build-essential \
    dkms \
    git curl ca-certificates \
    python3 python3-venv python3-pip python3-dev \
    python3-opencv \
    ffmpeg \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    libgl1 libglib2.0-0 \
    pciutils usbutils \
    sqlite3 \
    jq

echo "==> [1/6] config dirs"
mkdir -p "$HOME/.config/pi5-hailo-vision"
mkdir -p "$HOME/.local/share/pi5-hailo-vision/models"
mkdir -p "$HOME/.local/share/pi5-hailo-vision/snapshots"
mkdir -p "$HOME/.local/state/pi5-hailo-vision/logs"

echo "==> [1/6] Pi 5 EEPROM (PCIe stability fixes)"
# Older Pi 5 EEPROM revisions had PCIe Gen3 quirks under sustained Hailo
# load. Pull the latest stable firmware.
if command -v rpi-eeprom-update >/dev/null 2>&1; then
    sudo rpi-eeprom-update -a || true
    BOOTLOADER_VER="$(sudo rpi-eeprom-update 2>/dev/null | awk -F': ' '/CURRENT:/ {print $2}' | head -1)"
    echo "    EEPROM: ${BOOTLOADER_VER:-unknown}"
else
    echo "    rpi-eeprom-update not available — skipping (non-Pi host?)"
fi

echo "==> [1/6] kernel version"
KVER="$(uname -r)"
echo "    running kernel: $KVER"
# Hailo-10H driver builds against modern kernels. Pi OS Bookworm ships
# 6.6+; warn if we're somehow on an older one.
KMAJ="$(echo "$KVER" | cut -d. -f1)"
KMIN="$(echo "$KVER" | cut -d. -f2)"
if (( KMAJ < 6 || (KMAJ == 6 && KMIN < 6) )); then
    echo "    ⚠ kernel < 6.6 — strongly recommend 'sudo apt full-upgrade -y && sudo reboot' before continuing." >&2
fi

echo "==> [1/6] PCIe Gen3 check"
CONFIG_TXT="/boot/firmware/config.txt"
PCIE_REBOOT_NEEDED=0
if ! grep -q "^dtparam=pciex1_gen=3" "$CONFIG_TXT"; then
    echo "    enabling PCIe Gen3 (requires reboot to take effect)"
    echo "dtparam=pciex1_gen=3" | sudo tee -a "$CONFIG_TXT" > /dev/null
    PCIE_REBOOT_NEEDED=1
else
    echo "    PCIe Gen3 already enabled"
fi

# Some Pi 5 HATs (e.g. Pineboards) also need an explicit external PCIe
# enable. The official Pi M.2 HAT+ does not. If the user has a 3rd-party
# carrier and the device isn't enumerated after reboot, see
# docs/07-troubleshooting.md.

if [[ "$PCIE_REBOOT_NEEDED" == "1" ]]; then
    cat <<'EOF'

    ⚠  PCIe Gen3 was just enabled (and possibly EEPROM was updated).
       You MUST reboot before the Hailo install will succeed:

           sudo reboot

       Then re-run: ./scripts/install-all.sh
EOF
    exit 0
fi
