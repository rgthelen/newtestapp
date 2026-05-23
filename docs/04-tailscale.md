# 04 — Tailscale (remote access)

Tailscale gives you a private mesh: your Pi gets a stable hostname (`vision`)
reachable from your phone/laptop anywhere, without opening ports.

## Install

`scripts/03-install-tailscale.sh` runs the official installer:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh --hostname vision --accept-routes
```

Flags explained:
- `--ssh` — Tailscale handles SSH auth with your tailnet ACL (you can disable
  the OS-level sshd password auth once this works).
- `--hostname vision` — sets the magic DNS name. UI will be at
  `http://vision:8080`.
- `--accept-routes` — lets you reach your RTSP cameras even if they're on a
  subnet you've advertised from another node (optional).

## Lock down

After confirming Tailscale SSH works:

```bash
sudo nano /etc/ssh/sshd_config.d/90-pi5-vision.conf
```
```
PasswordAuthentication no
PubkeyAuthentication no
```
Tailscale's `--ssh` flag handles auth via your tailnet — the OS sshd then
only accepts connections from inside the tailnet over key-based auth that
Tailscale brokers.

```bash
sudo systemctl restart ssh
```

## Subnet routes (optional)

If your IP cameras live on a separate VLAN that your laptop can't reach:

```bash
sudo tailscale up --advertise-routes=192.168.50.0/24 --ssh --hostname vision
```

Approve the route in the Tailscale admin console → Machines → vision → Edit
route settings.

## Access the UI

From any tailnet device:

- Web UI: `http://vision:8080`
- API docs (FastAPI swagger): `http://vision:8080/docs`
- WebSocket live feed: `ws://vision:8080/ws/cameras/<id>`

Next: [05 — Add cameras](05-cameras.md).
