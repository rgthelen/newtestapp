#!/usr/bin/env bash
# Tailscale install + bring-up (idempotent).
set -euo pipefail

echo "==> [3/6] Tailscale"

if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi

# Already authenticated? skip the interactive login.
if sudo tailscale status >/dev/null 2>&1; then
    echo "    tailscale already up:"
    sudo tailscale status | head -3 | sed 's/^/    /'
    exit 0
fi

HOSTNAME_TS="${PI5_TS_HOSTNAME:-vision}"
cat <<EOF

    Bringing up Tailscale with hostname "${HOSTNAME_TS}".
    A browser URL will be printed below — open it on your laptop/phone to
    authenticate this node into your tailnet.

EOF

sudo tailscale up \
    --ssh \
    --hostname "${HOSTNAME_TS}" \
    --accept-routes
