#!/usr/bin/env bash
# Diagnostic dump for the Hailo stack. Run any time the device isn't behaving.
#
# Prints everything in one go so you can paste it into an issue / chat:
#   - Pi 5 EEPROM + kernel + config.txt PCIe lines
#   - lspci (link speed, BAR, capabilities)
#   - hailo_pci kernel module + DKMS status
#   - dmesg lines mentioning hailo or PCIe
#   - /dev/hailo0 permissions
#   - hailortcli identify + fw-version
#   - installed package versions
#   - HEFs present in models dir
#
# No sudo prompt for read-only stuff; sudo is used only where strictly required.
set +e

hr() { echo; printf '%.0s─' {1..70}; echo; echo "$1"; printf '%.0s─' {1..70}; echo; }

hr "system"
echo "host:       $(hostname)"
echo "uname:      $(uname -srm)"
echo "model:      $(tr -d '\0' </proc/device-tree/model 2>/dev/null)"
echo "kernel:     $(uname -r)"
if command -v rpi-eeprom-update >/dev/null; then
    echo "eeprom:     $(sudo rpi-eeprom-update 2>/dev/null | awk -F': ' '/CURRENT:/ {print $2}' | head -1)"
fi

hr "config.txt (pcie lines)"
grep -E '^(dtparam|dtoverlay).*(pcie|pciex1)' /boot/firmware/config.txt 2>/dev/null \
    || echo "(no PCIe-related lines in /boot/firmware/config.txt)"

hr "lspci -nn -d 1e60:"
lspci -nn -d 1e60: 2>/dev/null || echo "(no Hailo device on PCIe bus)"

hr "lspci -vv (link speed + state)"
sudo lspci -vv -d 1e60: 2>/dev/null | grep -iE 'lnk(cap|sta|ctl)|hailo|kernel driver' | sed 's/^/  /'

hr "kernel module"
lsmod | grep -E '^hailo' || echo "(hailo_pci not loaded)"
echo
if command -v dkms >/dev/null; then
    dkms status 2>/dev/null | grep -i hailo || echo "(no hailo entries in dkms status)"
fi

hr "dmesg (hailo + PCIe slot)"
sudo dmesg 2>/dev/null | grep -iE 'hailo|brcm-pcie 1000120000' | tail -25 | sed 's/^/  /'

hr "/dev/hailo*"
ls -l /dev/hailo* 2>/dev/null || echo "(no /dev/hailo* device node)"

hr "udev rules"
ls -l /etc/udev/rules.d/*hailo* /lib/udev/rules.d/*hailo* 2>/dev/null \
    || echo "(no hailo udev rules found)"

hr "hailortcli"
if command -v hailortcli >/dev/null; then
    echo "  version: $(hailortcli --version 2>/dev/null)"
    echo
    sudo hailortcli fw-control identify 2>&1 | sed 's/^/  /'
    echo
    sudo hailortcli scan 2>&1 | sed 's/^/  /'
else
    echo "(hailortcli not installed)"
fi

hr "packages"
dpkg -l 'hailo*' 'python3-hailort' 2>/dev/null | awk '/^ii/ {printf "  %-30s %s\n", $2, $3}'

hr "HEFs"
MODELS_DIR="${HOME}/.local/share/pi5-hailo-vision/models"
if [[ -d "$MODELS_DIR" ]]; then
    ls -lh "$MODELS_DIR"/*.hef 2>/dev/null | sed 's/^/  /' \
        || echo "  (no HEFs in $MODELS_DIR)"
else
    echo "  $MODELS_DIR does not exist"
fi

hr "done"
