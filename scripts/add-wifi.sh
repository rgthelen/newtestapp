#!/usr/bin/env bash
# Add a WiFi network on Raspberry Pi OS Bookworm (NetworkManager-based).
#
# Usage:
#   ./scripts/add-wifi.sh "MySSID" "myPassword"
#   ./scripts/add-wifi.sh "MySSID" "myPassword" hidden
#
# - Does not remove existing connections (your current WiFi still works).
# - Sets the regulatory country if it wasn't already configured.
# - Works for both 2.4 GHz and 5 GHz networks.
#
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    cat <<EOF >&2
usage: $0 <ssid> <password> [hidden]

  <ssid>       network name (case-sensitive)
  <password>   WPA/WPA2/WPA3 PSK
  hidden       optional, pass literal "hidden" if the SSID is hidden
EOF
    exit 2
fi

SSID="$1"
PSK="$2"
HIDDEN="${3:-}"

if ! command -v nmcli >/dev/null 2>&1; then
    echo "nmcli not found. This script requires NetworkManager (Pi OS Bookworm or newer)." >&2
    exit 1
fi

# 1. Make sure a country code is configured. Without it the wifi chip may
#    refuse to associate with 5 GHz networks.
COUNTRY="$(sudo iw reg get 2>/dev/null | awk '/^country/ {print $2}' | tr -d ':' | head -1)"
if [[ -z "$COUNTRY" || "$COUNTRY" == "00" ]]; then
    echo "==> WiFi regulatory country is not set."
    read -rp "    Enter your ISO country code (e.g. US, GB, DE): " CC
    CC="$(echo "$CC" | tr '[:lower:]' '[:upper:]')"
    sudo raspi-config nonint do_wifi_country "$CC"
    sudo iw reg set "$CC"
    echo "    set to $CC"
fi

# 2. Add (or update) the connection.
CON_NAME="$SSID"
if nmcli -t -f NAME con show | grep -Fxq "$CON_NAME"; then
    echo "==> Updating existing connection '$CON_NAME'"
    sudo nmcli con modify "$CON_NAME" \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$PSK"
    if [[ "$HIDDEN" == "hidden" ]]; then
        sudo nmcli con modify "$CON_NAME" 802-11-wireless.hidden yes
    fi
else
    echo "==> Adding connection '$CON_NAME'"
    EXTRA=()
    if [[ "$HIDDEN" == "hidden" ]]; then
        EXTRA+=(hidden yes)
    fi
    sudo nmcli device wifi connect "$SSID" password "$PSK" \
        ifname wlan0 name "$CON_NAME" "${EXTRA[@]}" || {
        # `wifi connect` fails if the network isn't currently visible (hidden
        # / out of range). Fall back to creating it as a saved connection.
        echo "    direct connect failed — creating saved connection instead."
        sudo nmcli con add type wifi ifname wlan0 con-name "$CON_NAME" ssid "$SSID"
        sudo nmcli con modify "$CON_NAME" \
            wifi-sec.key-mgmt wpa-psk \
            wifi-sec.psk "$PSK"
        if [[ "$HIDDEN" == "hidden" ]]; then
            sudo nmcli con modify "$CON_NAME" 802-11-wireless.hidden yes
        fi
        sudo nmcli con up "$CON_NAME" || true
    }
fi

# 3. Make sure it auto-connects on boot and has a sensible priority.
sudo nmcli con modify "$CON_NAME" connection.autoconnect yes

echo
echo "==> Current WiFi state:"
nmcli -t -f NAME,TYPE,DEVICE con show --active | grep -i wifi || echo "    (not yet associated)"
echo
echo "Done. List all saved networks: nmcli con show"
echo "      Remove a network:        sudo nmcli con delete \"<name>\""
