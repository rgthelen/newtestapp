#!/usr/bin/env bash
# Install Hailo driver, runtime, Python bindings, and GStreamer plugins.
set -euo pipefail

echo "==> [2/6] Hailo stack (hailo-all)"

# `hailo-all` is the meta-package Raspberry Pi maintains. It pulls:
#   - hailo-pci-dkms       (kernel driver)
#   - hailort              (runtime + hailortcli)
#   - python3-hailort      (python bindings)
#   - hailo-tappas-core    (GStreamer plugins)
#   - rpicam-apps Hailo post-processing
sudo apt-get install -y hailo-all

echo "==> [2/6] verifying"
if command -v hailortcli >/dev/null 2>&1; then
    hailortcli --version || true
else
    echo "    hailortcli not found on PATH — install may have failed" >&2
    exit 1
fi

# Probe the device. If this fails the user almost certainly needs to reboot
# for the freshly-built kernel module to load.
if ! hailortcli fw-control identify >/dev/null 2>&1; then
    cat <<'EOF'

    ⚠  Hailo device not yet visible. This usually means the DKMS module was
       just built and needs a reboot. Run:

           sudo reboot

       Then re-run: ./scripts/install-all.sh

       If the device is still missing after reboot see docs/07-troubleshooting.md
EOF
    exit 0
fi

echo "==> [2/6] Hailo device:"
hailortcli fw-control identify | sed 's/^/    /'
