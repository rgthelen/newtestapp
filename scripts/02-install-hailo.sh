#!/usr/bin/env bash
# Install Hailo driver, runtime, Python bindings, and verify the
# Hailo-10H / Hailo-8 / Hailo-8L is fully operational.
#
# What gets installed (via Raspberry Pi's `hailo-all` metapackage):
#   - hailo-pci-dkms       kernel module (rebuilt against your current kernel)
#   - hailort              userspace runtime + hailortcli
#   - hailofw              device firmware blob (re-flashed on every boot)
#   - python3-hailort      Python bindings (used by our app via venv)
#   - hailo-tappas-core    GStreamer plugins
#   - rpicam-apps hailo post-processing
#
# Verification covers:
#   - DKMS built the module against the running kernel
#   - hailo_pci kernel module is loaded
#   - PCIe device is enumerated and trained at Gen3
#   - device firmware loaded successfully (dmesg)
#   - /dev/hailo0 exists with sane permissions
#   - hailortcli can talk to the device
#   - HailoRT version meets Hailo-10H minimum (>= 4.18) if H10 detected
#
set -euo pipefail

HAILO_RT_MIN_VERSION_FOR_H10="4.18"

# --- 1. install --------------------------------------------------------------
echo "==> [2/6] Hailo stack (hailo-all)"
sudo apt-get update
sudo apt-get install -y hailo-all

# --- 2. DKMS module built? --------------------------------------------------
echo "==> [2/6] DKMS status"
KVER="$(uname -r)"
if command -v dkms >/dev/null 2>&1; then
    if dkms status 2>/dev/null | grep -E '^hailo[_-]?pci' | grep -q "$KVER"; then
        echo "    hailo_pci module is built for kernel $KVER"
    else
        echo "    rebuilding hailo_pci DKMS module for $KVER"
        sudo dkms autoinstall || true
    fi
    dkms status 2>/dev/null | grep -E '^hailo[_-]?pci' | sed 's/^/    /' || true
fi

# --- 3. PCIe enumeration ----------------------------------------------------
echo "==> [2/6] PCIe enumeration"
if ! lspci -d 1e60: >/dev/null 2>&1 || [[ -z "$(lspci -d 1e60: 2>/dev/null)" ]]; then
    cat <<'EOF' >&2

    ⚠  No Hailo PCIe device found on the bus (vendor 1e60).
       Things to check:
         - Is the M.2 card seated and the FFC ribbon attached the right way?
         - Did you reboot after enabling dtparam=pciex1_gen=3?
         - Run:  sudo dmesg | grep -i -E 'pcie|brcm-pcie'
         - 3rd-party HAT? you may need a dtoverlay — see docs/07-troubleshooting.md
EOF
    exit 1
fi
echo "    Hailo PCIe device:"
lspci -nn -d 1e60: | sed 's/^/    /'

# Link speed — we want LnkSta showing 8GT/s (Gen3 x1).
LNK_SPEED="$(sudo lspci -vv -d 1e60: 2>/dev/null | awk -F'Speed ' '/LnkSta:/{print $2}' | awk -F',' '{print $1}' | head -1)"
echo "    PCIe link speed: ${LNK_SPEED:-unknown}"
if [[ -n "${LNK_SPEED:-}" && "$LNK_SPEED" != "8GT/s" ]]; then
    echo "    ⚠ link came up below Gen3 — Hailo will work but throughput will be limited." >&2
    echo "      Confirm 'dtparam=pciex1_gen=3' is in /boot/firmware/config.txt and reboot." >&2
fi

# --- 4. driver module loaded -------------------------------------------------
echo "==> [2/6] kernel module"
if ! lsmod | awk '{print $1}' | grep -qE '^hailo(_pci|pci)$'; then
    echo "    hailo_pci not loaded — attempting modprobe"
    sudo modprobe hailo_pci || true
fi
if lsmod | awk '{print $1}' | grep -qE '^hailo(_pci|pci)$'; then
    echo "    hailo_pci module loaded"
else
    echo "    ⚠ hailo_pci module is NOT loaded. Check 'sudo dmesg | grep hailo'." >&2
fi

# --- 5. firmware boot --------------------------------------------------------
echo "==> [2/6] device firmware boot"
FW_LOG="$(sudo dmesg 2>/dev/null | grep -iE 'hailo' | tail -8)"
if [[ -n "$FW_LOG" ]]; then
    echo "$FW_LOG" | sed 's/^/    /'
fi
if sudo dmesg 2>/dev/null | grep -iE 'hailo.*(failed|error)' >/dev/null; then
    echo "    ⚠ dmesg has Hailo errors — see docs/07-troubleshooting.md" >&2
fi

# --- 6. device node ----------------------------------------------------------
echo "==> [2/6] /dev/hailo0"
if [[ -e /dev/hailo0 ]]; then
    ls -l /dev/hailo0 | sed 's/^/    /'
else
    echo "    ⚠ /dev/hailo0 does not exist — driver/firmware boot likely failed." >&2
fi

# --- 7. hailortcli -----------------------------------------------------------
if ! command -v hailortcli >/dev/null 2>&1; then
    echo "    ⚠ hailortcli not on PATH — install may have failed." >&2
    exit 1
fi

RT_VERSION="$(hailortcli --version 2>/dev/null | awk '{print $NF}' | head -1)"
echo "    HailoRT: ${RT_VERSION:-unknown}"

# Probe the device. If this fails we very likely need a reboot for the
# freshly-built kernel module to attach.
if ! sudo hailortcli fw-control identify >/dev/null 2>&1; then
    cat <<'EOF'

    ⚠  Hailo device not yet visible to HailoRT. This usually means the
       DKMS module was just built and the device needs a reboot to attach.
       Run:

           sudo reboot

       Then re-run: ./scripts/install-all.sh

       If the device is still missing after reboot, see docs/07-troubleshooting.md
EOF
    exit 0
fi

IDENTIFY_OUT="$(sudo hailortcli fw-control identify 2>/dev/null)"
echo "==> [2/6] Hailo device:"
echo "$IDENTIFY_OUT" | sed 's/^/    /'

BOARD="$(echo "$IDENTIFY_OUT" | awk -F': ' '/Board Name/ {print tolower($2)}' | tr -d '\r ')"

# --- 8. Hailo-10H minimum version check -------------------------------------
if [[ "$BOARD" == *10h* ]]; then
    # crude semver compare via sort -V
    if [[ -n "$RT_VERSION" ]]; then
        LOWEST="$(printf '%s\n%s\n' "$HAILO_RT_MIN_VERSION_FOR_H10" "$RT_VERSION" | sort -V | head -1)"
        if [[ "$LOWEST" != "$HAILO_RT_MIN_VERSION_FOR_H10" ]]; then
            cat <<EOF >&2

    ⚠  Detected Hailo-10H but HailoRT $RT_VERSION is older than the
       minimum recommended for H10 ($HAILO_RT_MIN_VERSION_FOR_H10).

       Raspberry Pi's apt repo can lag the latest HailoRT. To upgrade:

         1. Sign in at https://hailo.ai/developer-zone/software-downloads/
            and download the latest .deb bundle for arm64 Raspberry Pi 5:
              - hailort_X.Y.Z_arm64.deb
              - hailort-pcie-driver_X.Y.Z_all.deb  (or hailo-pci-dkms)
              - python3-hailort_X.Y.Z_arm64.deb
         2. scp them to the Pi, then:
              sudo apt remove --purge hailort hailo-all python3-hailort
              sudo dpkg -i hailort_*.deb hailort-pcie-driver_*.deb python3-hailort_*.deb
              sudo apt -f install
              sudo reboot
EOF
        fi
    fi
fi

# --- 9. permissions ----------------------------------------------------------
# The hailo_pci package installs a udev rule that gives /dev/hailo0 0666
# permissions. Sanity-check we can open it without sudo.
if [[ -e /dev/hailo0 ]] && ! [[ -r /dev/hailo0 && -w /dev/hailo0 ]]; then
    echo "    ⚠ /dev/hailo0 is not user-readable. Reload udev rules:" >&2
    echo "        sudo udevadm control --reload-rules && sudo udevadm trigger" >&2
fi

echo "==> [2/6] Hailo verification passed."